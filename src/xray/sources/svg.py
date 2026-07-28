"""svg.py — the SVG source adapter (stdlib xml only).

The third vector format: an SVG exported from CAD carries the geometry losslessly
as paths + text, and — via <use> — the block-instance equivalent of a DXF INSERT.
So SVG slots into the same model the DXF adapter produces:

  <use href="#col" x= y=>        -> Symbol   (a placement, counted exactly)
  <rect>/<polygon>/closed <path> -> Measure  (polyline, with length + area)
  <line>/<polyline>/open <path>  -> Measure  (line / polyline, length)
  <text>                         -> Word     (into the text pipeline)

Layer semantics come from the enclosing <g id="…">, so the same trade packs that
key on a layer name (structural columns, fencing) work on an SVG whose groups are
named like CAD layers.

Units: taken from the root <svg width="…mm">, marked `verified: False` — a
declared unit with no geometric corroboration, exactly like a DXF header (so an
area from an SVG is flagged needs-human, per the unit-verification rule).
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from xray.reassemble import Word
from xray.sources.base import (
    Measure, PageRead, ReadResult, SourceAdapter, Symbol, register,
)

_UNIT_RE = re.compile(r"([-\d.]+)\s*(mm|cm|m|in|px|pt)?", re.I)
_NUM = re.compile(r"-?\d*\.?\d+")


def _tag(el) -> str:
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _len(v):
    """A length attr like '100mm' -> (value, unit)."""
    m = _UNIT_RE.match((v or "").strip())
    if not m:
        return None, ""
    return _f(m.group(1)), (m.group(2) or "").lower()


def _points(s):
    nums = [float(x) for x in _NUM.findall(s or "")]
    return list(zip(nums[0::2], nums[1::2]))


def _polyline_len(pts, closed):
    ring = pts + [pts[0]] if (closed and len(pts) > 2) else pts
    return sum(math.dist(ring[i], ring[i + 1]) for i in range(len(ring) - 1))


def _shoelace(pts):
    n = len(pts)
    if n < 3:
        return None
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
                   for i in range(n))) / 2.0


def _path_points(d):
    """Anchor points of a path's straight commands (M/L/H/V), plus a closed flag.
    Curves (C/Q/A/S/T) contribute their end anchor only — length is then a
    straight-segment approximation, which is fine for the orthogonal linework
    plans are made of; a closing Z marks the ring closed."""
    pts, cur, closed = [], [0.0, 0.0], False
    toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:e-?\d+)?", d or "")
    i, cmd = 0, ""
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            if cmd in "Zz":
                closed = True
            i += 1
            continue
        rel = cmd.islower()
        c = cmd.upper()
        def nxt():
            nonlocal i
            v = _f(toks[i]); i += 1; return v
        if c == "M" or c == "L":
            x, y = nxt(), nxt()
            cur = [cur[0] + x, cur[1] + y] if rel else [x, y]
        elif c == "H":
            x = nxt(); cur = [cur[0] + x if rel else x, cur[1]]
        elif c == "V":
            y = nxt(); cur = [cur[0], cur[1] + y if rel else y]
        elif c in "CSQTA":
            # consume this command's numbers, keep only the final (end) point
            n = {"C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}[c]
            vals = [nxt() for _ in range(n)]
            ex, ey = vals[-2], vals[-1]
            cur = [cur[0] + ex, cur[1] + ey] if rel else [ex, ey]
        else:
            i += 1
            continue
        pts.append((cur[0], cur[1]))
    return pts, closed


class SvgAdapter(SourceAdapter):
    name = "svg"

    def can_read(self, path: str | Path) -> bool:
        return str(path).lower().endswith(".svg")

    def read(self, path: str | Path) -> ReadResult:
        root = ET.fromstring(Path(path).read_bytes())

        # units from the root width (declared, not corroborated -> unverified)
        _, unit = _len(root.get("width"))
        resolved = unit if unit in ("mm", "cm", "m", "in") else ""
        units = {"declared": resolved, "resolved": resolved,
                 "basis": "svg width attribute" if resolved else "none",
                 "mismatch": False, "verified": False}

        symbols: list[Symbol] = []
        geometry: list[Measure] = []
        words: list[Word] = []
        counter = [0]

        def gid():
            counter[0] += 1
            return f"s{counter[0]}"

        def walk(el, layer):
            name = _tag(el)
            if name == "g":
                layer = el.get("id") or layer
            eid = el.get("id") or gid()

            if name == "use":
                href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or ""
                block = href.lstrip("#") or "use"
                symbols.append(Symbol(
                    block_name=block, layer=layer, x=_f(el.get("x")), y=_f(el.get("y")),
                    trade="", id=eid, parent_id=None))
            elif name == "line":
                a = (_f(el.get("x1")), _f(el.get("y1")))
                b = (_f(el.get("x2")), _f(el.get("y2")))
                geometry.append(Measure(kind="line", value=math.dist(a, b),
                                        layer=layer, id=eid))
            elif name in ("polyline", "polygon"):
                pts = _points(el.get("points"))
                if len(pts) >= 2:
                    closed = name == "polygon"
                    geometry.append(Measure(
                        kind="polyline", value=_polyline_len(pts, closed),
                        layer=layer, id=eid,
                        area=_shoelace(pts) if closed else None))
            elif name == "rect":
                w, h = _f(el.get("width")), _f(el.get("height"))
                if w > 0 and h > 0:
                    geometry.append(Measure(kind="polyline", value=2 * (w + h),
                                            layer=layer, id=eid, area=w * h))
            elif name == "path":
                pts, closed = _path_points(el.get("d"))
                if len(pts) >= 2:
                    geometry.append(Measure(
                        kind="polyline", value=_polyline_len(pts, closed),
                        layer=layer, id=eid,
                        area=_shoelace(pts) if closed else None))
            elif name == "text":
                txt = "".join(el.itertext()).strip()
                if txt:
                    x, y = _f(el.get("x")), _f(el.get("y"))
                    fs, _u = _len(el.get("font-size") or "10")
                    fs = fs or 10.0
                    words.append(Word(text=txt, x0=x, y0=y - fs,
                                      x1=x + len(txt) * fs * 0.6, y1=y,
                                      page=0, source="text"))

            for child in el:
                walk(child, layer)

        walk(root, "")

        # the resolved unit travels with every measurement (as the DXF adapter
        # does), so lengths/areas convert to metres downstream.
        for g in geometry:
            g.unit = resolved

        # page size from viewBox or width/height (in user units)
        vb = (root.get("viewBox") or "").split()
        if len(vb) == 4:
            w, h = _f(vb[2]), _f(vb[3])
        else:
            w = _len(root.get("width"))[0] or 0.0
            h = _len(root.get("height"))[0] or 0.0

        pages = [PageRead(words=words, raw_word_count=len(words),
                          width_pt=float(w or 1.0), height_pt=float(h or 1.0),
                          kind="vector")]
        return ReadResult(pages=pages, producer="svg",
                          symbols=symbols, geometry=geometry, units=units)


register(SvgAdapter())
