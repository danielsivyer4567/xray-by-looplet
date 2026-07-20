"""
reassemble.py — Stage 2 of the X-Ray by Looplet engine.

Recovers whole tokens from PDF text layers where dimension strings arrive
fragmented. Two fragmentation modes were observed empirically (2026-07-21,
fixtures/warehouse-design21.pdf sheet 04):

1. OCR "junk runs": Adobe Paper Capture merges a whole dimension line —
   leader dashes, tick marks and the number — into ONE word, e.g.
   ``-+----------29995----------#-``. The number is a substring of a single
   word, so it must be *split out* (digit runs inside dash-leader words).

2. True glyph splits: separate adjacent words that belong to one token,
   e.g. ``150`` + ``0`` -> ``1500`` (observed gap 1.05pt, ~35% of char
   width). These are *merged* when they share a baseline and the gap is
   far below a space width. A vertical analogue handles rotated text
   (tall-narrow boxes stacked in the same x-band).

Conservatism rules (all verified against fixtures/shed-manners-aline.pdf
page 0, a clean Skia/Chromium print where reassemble must be a no-op):
- only numeric fragments are ever merged (digits plus ``.``/``,``) — a
  non-numeric context change always blocks a merge;
- never merge across a gap larger than one char width;
- never merge across a gap that looks like a rendered space: real spaces
  measure ~0.25 em, so gaps above SPACE_GUARD_EM * font-size are refused
  (the shed fixture's phone number "03 5452 2255" sits at 0.25 em and must
  NOT merge; the warehouse glyph split sits at 0.12 em and must).
"""
from dataclasses import dataclass, replace
import re

import pypdfium2 as pdfium


@dataclass
class Word:  # PDF points, origin top-left (flipped from PDFium's y-up)
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int
    source: str  # "text" | "reassembled"


# --- tuning (empirical, see module docstring) -------------------------------
GAP_MEDIAN_FRACTION = 0.6    # gap must be below 60% of pooled median char width
SPACE_GUARD_EM = 0.18        # gap must be below 18% of font size (spaces ~25%)
OVERLAP_TOL = 1.0            # allow up to 1pt overlap between fragments
BASELINE_CLUSTER_TOL = 3.0   # pt, coarse baseline grouping
HEIGHT_COMPAT = 0.55         # min(h)/max(h) of merge candidates
ROTATED_ASPECT = 1.4         # multi-char word is "rotated" when h > 1.4*w

# junk word = OCR'd dimension leader line: >=3 consecutive dashes AND an
# embedded digit run of plausible mm-dimension length (3..6 digits)
RE_DASH_RUN = re.compile(r"-{3,}")
RE_DIGIT_RUN = re.compile(r"\d+")
JUNK_MIN_DIGITS = 3
JUNK_MAX_DIGITS = 6

RE_NUMERIC = re.compile(r"[0-9.,]+")


def extract_words(doc, page_no: int) -> list[Word]:
    """Raw text-layer words of page `page_no` (0-based), source='text'.

    Backed by pypdfium2 (PDFium, permissive licence). PDFium delivers per-
    character boxes in a bottom-left / y-up space; we group characters into
    whitespace-delimited tokens (matching PyMuPDF's word segmentation) and
    flip y to the top-left / y-down convention the Word contract and the rest
    of the pipeline expect.
    """
    page = doc[page_no]
    _w, page_h = page.get_size()
    tp = page.get_textpage()
    try:
        n = tp.count_chars()
        out = []
        buf = []  # (char_str, (left, bottom, right, top))

        def flush():
            if not buf:
                return
            text = "".join(c for c, _ in buf).strip()
            if text:
                x0 = min(b[0] for _, b in buf)
                x1 = max(b[2] for _, b in buf)
                y0 = min(page_h - b[3] for _, b in buf)  # top edge (flip)
                y1 = max(page_h - b[1] for _, b in buf)  # bottom edge (flip)
                out.append(Word(text=text, x0=float(x0), y0=float(y0),
                                x1=float(x1), y1=float(y1),
                                page=page_no, source="text"))
            buf.clear()

        for i in range(n):
            ch = tp.get_text_range(i, 1)
            if ch == "" or ch.isspace():
                flush()
                continue
            buf.append((ch, tp.get_charbox(i)))
        flush()
        return out
    finally:
        tp.close()


def reassemble(words: list[Word]) -> list[Word]:
    """Merged runs + passthrough. Untouched words keep source='text'."""
    out = []
    for page_words in _by_page(words):
        ws = _split_junk_runs(page_words)
        ws = _merge_axis(ws, horizontal=True)
        ws = _merge_axis(ws, horizontal=False)
        out.extend(ws)
    return out


# --- helpers -----------------------------------------------------------------

def _by_page(words):
    pages = {}
    order = []
    for w in words:
        if w.page not in pages:
            pages[w.page] = []
            order.append(w.page)
        pages[w.page].append(w)
    return [pages[p] for p in order]


def _is_numeric(text):
    return bool(RE_NUMERIC.fullmatch(text)) and any(c.isdigit() for c in text)


def _is_junk_run(text):
    if not RE_DASH_RUN.search(text):
        return False
    return any(JUNK_MIN_DIGITS <= len(m.group()) <= JUNK_MAX_DIGITS
               for m in RE_DIGIT_RUN.finditer(text))


def _split_junk_runs(words):
    """Replace OCR leader-line words by their embedded digit-run tokens.

    Token bboxes are interpolated by character position along the word's
    major axis — approximate, but preserves band membership for chains.
    """
    out = []
    for w in words:
        if not _is_junk_run(w.text):
            out.append(w)
            continue
        n = len(w.text)
        wide = (w.x1 - w.x0) >= (w.y1 - w.y0)
        for m in RE_DIGIT_RUN.finditer(w.text):
            if not (JUNK_MIN_DIGITS <= len(m.group()) <= JUNK_MAX_DIGITS):
                continue
            f0, f1 = m.start() / n, m.end() / n
            if wide:
                bbox = (w.x0 + f0 * (w.x1 - w.x0), w.y0,
                        w.x0 + f1 * (w.x1 - w.x0), w.y1)
            else:
                bbox = (w.x0, w.y0 + f0 * (w.y1 - w.y0),
                        w.x1, w.y0 + f1 * (w.y1 - w.y0))
            out.append(Word(text=m.group(), x0=bbox[0], y0=bbox[1],
                            x1=bbox[2], y1=bbox[3],
                            page=w.page, source="reassembled"))
    return out


def _em_size(w, horizontal):
    """Approximate font size: box height for horizontal text, width rotated."""
    return (w.y1 - w.y0) if horizontal else (w.x1 - w.x0)


def _char_advance(w, horizontal):
    """Mean per-character advance along the reading axis."""
    span = (w.x1 - w.x0) if horizontal else (w.y1 - w.y0)
    return span / max(1, len(w.text))


def _is_rotated(w):
    """Multi-char word drawn vertically -> tall, narrow box."""
    return len(w.text) >= 2 and (w.y1 - w.y0) > ROTATED_ASPECT * (w.x1 - w.x0)


def _pair_mergeable(a, b, horizontal):
    """a precedes b along the reading axis. All rules must hold."""
    if not (_is_numeric(a.text) and _is_numeric(b.text)):
        return False  # non-numeric context change: never merge

    if horizontal:
        if _is_rotated(a) or _is_rotated(b):
            return False
        base_delta = abs(a.y1 - b.y1)
        gap = b.x0 - a.x1
    else:
        # rotated text only: both fragments must be tall-narrow
        # (single chars are naturally narrow, so only test len>=2)
        if (len(a.text) >= 2 and not _is_rotated(a)) or \
           (len(b.text) >= 2 and not _is_rotated(b)):
            return False
        base_delta = abs(((a.x0 + a.x1) - (b.x0 + b.x1)) / 2.0)
        gap = b.y0 - a.y1

    ha, hb = _em_size(a, horizontal), _em_size(b, horizontal)
    if min(ha, hb) < HEIGHT_COMPAT * max(ha, hb):
        return False
    if base_delta > max(1.5, 0.2 * max(ha, hb)):
        return False

    if gap < -OVERLAP_TOL:
        return False
    ca, cb = _char_advance(a, horizontal), _char_advance(b, horizontal)
    pooled = (abs((a.x1 - a.x0) if horizontal else (a.y1 - a.y0)) +
              abs((b.x1 - b.x0) if horizontal else (b.y1 - b.y0))) / \
             max(1, len(a.text) + len(b.text))
    if gap > GAP_MEDIAN_FRACTION * pooled:
        return False
    if gap > min(ca, cb):
        return False  # never merge across more than one char width
    if gap > SPACE_GUARD_EM * max(ha, hb):
        return False  # gap is a rendered space, not a glyph split
    return True


def _merge_axis(words, horizontal):
    """Cluster words by shared baseline (or x-band) and merge tight runs.

    Output preserves input order: a merged word replaces its first fragment.
    """
    if len(words) < 2:
        return list(words)

    idx = list(range(len(words)))
    if horizontal:
        idx.sort(key=lambda i: words[i].y1)
        line_of = lambda i: words[i].y1
    else:
        idx.sort(key=lambda i: (words[i].x0 + words[i].x1) / 2.0)
        line_of = lambda i: (words[i].x0 + words[i].x1) / 2.0

    # coarse baseline clusters
    clusters, cur = [], [idx[0]]
    for i in idx[1:]:
        if line_of(i) - line_of(cur[-1]) <= BASELINE_CLUSTER_TOL:
            cur.append(i)
        else:
            clusters.append(cur)
            cur = [i]
    clusters.append(cur)

    merged_into = {}   # member index -> anchor index
    accum = {}         # anchor index -> Word being accumulated
    for cluster in clusters:
        if horizontal:
            cluster.sort(key=lambda i: words[i].x0)
        else:
            cluster.sort(key=lambda i: words[i].y0)
        anchor = None
        for prev, nxt in zip(cluster, cluster[1:]):
            a = accum[anchor] if anchor is not None else words[prev]
            b = words[nxt]
            if _pair_mergeable(a, b, horizontal):
                if anchor is None:
                    anchor = prev
                accum[anchor] = Word(
                    text=a.text + b.text,
                    x0=min(a.x0, b.x0), y0=min(a.y0, b.y0),
                    x1=max(a.x1, b.x1), y1=max(a.y1, b.y1),
                    page=a.page, source="reassembled")
                merged_into[nxt] = anchor
            else:
                anchor = None

    out = []
    for i, w in enumerate(words):
        if i in merged_into:
            continue
        out.append(accum.get(i, w))
    return out
