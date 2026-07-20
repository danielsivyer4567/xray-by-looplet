"""tables.py — Stage 2.5 of the X-Ray by Looplet engine: table reconstruction.

Turns a schedule DRAWING into CSV-like rows. Clusters a page's words into rows
by shared baseline and into columns by recurring left-edges, drops preamble
(titles/notes that don't align to the columns), detects the header, and splits
multiple tables on a page by large vertical gaps. Feeds schedule-based trade
packs (electrical schedule of loads, door/window/fixture/equipment schedules).

Pure-Python; consumes reassemble.Word objects (bboxes top-left, y-down, points).
"""
from __future__ import annotations

from dataclasses import dataclass
import statistics

# --- tuning (empirical) ------------------------------------------------------
ROW_TOL_FRAC = 0.6     # words whose y-centres differ by < this * median height share a row
TABLE_GAP_FRAC = 2.2   # a vertical gap > this * median row pitch splits tables
COL_GAP_MIN = 4.0      # pt: min x-gap that can separate two column left-edges
COL_RECUR_MIN = 3      # a real column's left-edge recurs in at least this many rows
ASSIGN_TOL = 2.0       # pt slack when left-binding a word to a column


@dataclass
class Cell:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    row: int
    col: int


@dataclass
class Table:
    headers: list          # list[str] per column
    rows: list             # list[list[Cell]]
    bbox: tuple            # (x0, y0, x1, y1)

    def as_dicts(self) -> list:
        """One dict per data row: header -> joined cell text (left-to-right)."""
        out = []
        for r in self.rows:
            d = {}
            for c in sorted(r, key=lambda c: c.x0):
                h = self.headers[c.col] if 0 <= c.col < len(self.headers) else f"col{c.col}"
                h = h or f"col{c.col}"
                d[h] = (d[h] + " " + c.text).strip() if h in d else c.text
            out.append(d)
        return out


def _median_height(words):
    hs = [w.y1 - w.y0 for w in words if w.y1 > w.y0]
    return statistics.median(hs) if hs else 8.0


def _median_char_w(words):
    ws = [(w.x1 - w.x0) / max(1, len(w.text)) for w in words if w.x1 > w.x0 and w.text]
    return statistics.median(ws) if ws else 4.0


def _cluster_rows(words, tol):
    ws = sorted(words, key=lambda w: (w.y0 + w.y1) / 2.0)
    rows, cur, cy = [], [], None
    for w in ws:
        c = (w.y0 + w.y1) / 2.0
        if cy is None or abs(c - cy) <= tol:
            cur.append(w)
            cy = c if cy is None else (cy * (len(cur) - 1) + c) / len(cur)
        else:
            rows.append(cur)
            cur, cy = [w], c
    if cur:
        rows.append(cur)
    for r in rows:
        r.sort(key=lambda w: w.x0)
    return rows


def _row_yc(r):
    return (min(w.y0 for w in r) + max(w.y1 for w in r)) / 2.0


def _assign(x0, cols):
    """Left-bounded: the column whose left-edge is the largest <= x0 (+tol)."""
    k = 0
    for i, c in enumerate(cols):
        if x0 >= c - ASSIGN_TOL:
            k = i
        else:
            break
    return k


def _columns(block):
    """Recurring left-edges across the block's rows -> column anchors."""
    xs = []
    for ri, r in enumerate(block):
        for w in r:
            xs.append((w.x0, ri))
    xs.sort()
    allw = [w for r in block for w in r]
    gap = max(COL_GAP_MIN, _median_char_w(allw) * 0.8)
    clusters, cur = [], [xs[0]]
    for x in xs[1:]:
        if x[0] - cur[-1][0] <= gap:
            cur.append(x)
        else:
            clusters.append(cur)
            cur = [x]
    clusters.append(cur)
    cols = []
    for c in clusters:
        rowset = {ri for _, ri in c}
        if len(rowset) >= min(COL_RECUR_MIN, max(2, len(block) - 1)):
            cols.append(sum(x for x, _ in c) / len(c))
    cols.sort()
    return cols


def _table_from_block(block):
    allw = [w for r in block for w in r]
    if len(allw) < 6:
        return None
    cols = _columns(block)
    if len(cols) < 2:
        return None
    need = max(2, len(cols) // 2)

    def pop(r):
        return len({_assign(w.x0, cols) for w in r})

    hidx = next((i for i, r in enumerate(block) if pop(r) >= need), None)
    if hidx is None:
        return None
    headers = [""] * len(cols)
    for w in sorted(block[hidx], key=lambda w: w.x0):
        k = _assign(w.x0, cols)
        headers[k] = (headers[k] + " " + w.text).strip()
    drows = []
    for r in block[hidx + 1:]:
        if pop(r) < need:
            continue
        cells = [Cell(w.text, w.x0, w.y0, w.x1, w.y1, len(drows), _assign(w.x0, cols))
                 for w in sorted(r, key=lambda w: w.x0)]
        drows.append(cells)
    if not drows:
        return None
    bbox = (min(w.x0 for w in allw), min(w.y0 for w in allw),
            max(w.x1 for w in allw), max(w.y1 for w in allw))
    return Table(headers=headers, rows=drows, bbox=bbox)


def extract_tables(words, page_rect=None) -> list:
    """All tables on a page. words: list[Word] (top-left y-down)."""
    words = [w for w in words if str(getattr(w, "text", "")).strip()]
    if len(words) < 6:
        return []
    rows = _cluster_rows(words, ROW_TOL_FRAC * _median_height(words))
    if len(rows) < 2:
        return []
    yc = [_row_yc(r) for r in rows]
    pitches = sorted(yc[i + 1] - yc[i] for i in range(len(yc) - 1))
    med_pitch = pitches[len(pitches) // 2] if pitches else _median_height(words) * 1.6
    blocks, cur = [], [0]
    for i in range(1, len(rows)):
        if yc[i] - yc[i - 1] > TABLE_GAP_FRAC * max(med_pitch, 1.0):
            blocks.append(cur)
            cur = [i]
        else:
            cur.append(i)
    blocks.append(cur)
    out = []
    for b in blocks:
        t = _table_from_block([rows[i] for i in b])
        if t:
            out.append(t)
    return out
