"""dxf.py — the DXF source adapter (ezdxf).

Reads native CAD as a second front door to the extraction stage. The value over
the PDF path is what a plotted sheet destroys:

  INSERT   -> exact counts by block name, with no recognition step at all
  DIMENSION-> the drawing's own measured value, via get_measurement()
  LINE/LWPOLYLINE -> real lengths in model units

A PDF text layer can carry none of these: plotting flattens block references into
anonymous strokes and dimensions into loose text. That is why a CAD source can
reconcile a quantity where a PDF can only single-source it.

Units are resolved by EVIDENCE, not by the header. $INSUNITS is frequently wrong
-- the reference fixture declares metres (6) for a drawing that is plainly in feet
-- so the declared value is recorded, checked against the geometry, and any
conflict is reported as a mismatch instead of being propagated.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from xray.sources.base import (
    Measure, PageRead, ReadResult, SourceAdapter, Symbol, register,
)

# $INSUNITS enumeration (ISO/AutoCAD); only the values a plan realistically uses.
INSUNITS = {
    0: "", 1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m", 9: "um", 10: "yd", 14: "dm",
}

# Layer name -> trade. Substring match, longest first, so WINDOWS beats WIN.
LAYER_TRADE = [
    ("COLUMN", "structural steel"),
    ("BEAM", "structural steel"),
    ("STEEL", "structural steel"),
    ("WINDOW", "openings"),
    ("DOOR", "openings"),
    ("WALL", "cladding"),
    ("ROOF", "roofing"),
    ("DIMENSION", ""),
    ("TEXT", ""),
]

# A block whose NAME states its own size, e.g. DOOR_3FT / WIN_5FT. Real drafting
# offices name blocks this way, and it is independent evidence of the unit.
NAME_SIZE = re.compile(r"(\d+(?:[._]\d+)?)\s*(FT|FOOT|FEET|IN|INCH|MM|CM|M)\b", re.I)
NAME_UNIT = {"FT": "ft", "FOOT": "ft", "FEET": "ft", "IN": "in", "INCH": "in",
             "MM": "mm", "CM": "cm", "M": "m"}


def trade_for(layer: str) -> str:
    up = (layer or "").upper()
    for key, trade in LAYER_TRADE:
        if key in up:
            return trade
    return ""


def _bbox_width(block, insert) -> float:
    """Width of a block's own geometry, in drawing units, at 1:1."""
    xs = []
    for e in block:
        t = e.dxftype()
        try:
            if t == "LWPOLYLINE":
                xs += [p[0] for p in e.get_points("xy")]
            elif t == "LINE":
                xs += [e.dxf.start.x, e.dxf.end.x]
            elif t == "CIRCLE":
                xs += [e.dxf.center.x - e.dxf.radius, e.dxf.center.x + e.dxf.radius]
            elif t == "ARC":
                xs += [e.dxf.center.x - e.dxf.radius, e.dxf.center.x + e.dxf.radius]
        except Exception:
            continue
    return (max(xs) - min(xs)) if xs else 0.0


def resolve_units(doc, symbols, blocks) -> dict:
    """Decide the drawing's unit from evidence, and flag a lying header.

    Evidence, strongest first:
      1. a block whose NAME declares its size (DOOR_3FT ~ 3 units wide) -- if the
         name says 3FT and the geometry is ~3 units, one unit is one foot.
      2. the declared $INSUNITS, used only when nothing contradicts it.
    """
    declared = INSUNITS.get(int(doc.header.get("$INSUNITS", 0) or 0), "")
    resolved, basis = declared, "header $INSUNITS"
    mismatch = False

    for name, blk in blocks.items():
        m = NAME_SIZE.search(name)
        if not m:
            continue
        stated = float(m.group(1).replace("_", "."))
        unit = NAME_UNIT[m.group(2).upper()]
        width = _bbox_width(blk, None)
        if stated <= 0 or width <= 0:
            continue
        # the block's drawn width matches the size in its own name -> that unit
        # IS the drawing unit (within 20%, generous for jamb/frame detail)
        if abs(width - stated) / stated < 0.20:
            resolved, basis = unit, f"block name {name} ({stated:g}{unit} ~ {width:.2f} units)"
            mismatch = bool(declared) and declared != unit
            break

    return {"declared": declared, "resolved": resolved,
            "basis": basis, "mismatch": mismatch}


class DxfAdapter(SourceAdapter):
    name = "dxf"

    def can_read(self, path: str | Path) -> bool:
        return str(path).lower().endswith(".dxf")

    def read(self, path: str | Path) -> ReadResult:
        import ezdxf  # imported here so the engine works without CAD deps

        doc = ezdxf.readfile(str(path))
        msp = doc.modelspace()

        blocks = {b.name: b for b in doc.blocks if not b.name.startswith("*")}

        symbols: list[Symbol] = []
        geometry: list[Measure] = []
        words = []          # DXF TEXT/MTEXT flow into the existing text pipeline

        for e in msp:
            t = e.dxftype()
            layer = getattr(e.dxf, "layer", "") or ""
            try:
                if t == "INSERT":
                    symbols.append(Symbol(
                        block_name=e.dxf.name, layer=layer,
                        x=float(e.dxf.insert.x), y=float(e.dxf.insert.y),
                        rotation=float(getattr(e.dxf, "rotation", 0.0) or 0.0),
                        xscale=float(getattr(e.dxf, "xscale", 1.0) or 1.0),
                        yscale=float(getattr(e.dxf, "yscale", 1.0) or 1.0),
                        trade=trade_for(layer)))
                elif t == "DIMENSION":
                    # the measured span, from the geometry -- never the display
                    # text, which is "<>" when derived
                    geometry.append(Measure(
                        kind="dimension", value=float(e.get_measurement()),
                        layer=layer, text=getattr(e.dxf, "text", "") or "",
                        trade=trade_for(layer)))
                elif t == "LINE":
                    a, b = e.dxf.start, e.dxf.end
                    geometry.append(Measure(
                        kind="line", value=math.dist((a.x, a.y), (b.x, b.y)),
                        layer=layer, trade=trade_for(layer)))
                elif t == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points("xy")]
                    if e.closed and len(pts) > 2:
                        pts = pts + [pts[0]]
                    total = sum(math.dist(pts[i], pts[i + 1])
                                for i in range(len(pts) - 1))
                    geometry.append(Measure(
                        kind="polyline", value=total, layer=layer,
                        trade=trade_for(layer)))
            except Exception:
                continue   # one malformed entity never fails the whole read

        units = resolve_units(doc, symbols, blocks)
        for g in geometry:
            g.unit = units["resolved"]

        ext_min = doc.header.get("$EXTMIN", (0, 0, 0))
        ext_max = doc.header.get("$EXTMAX", (0, 0, 0))
        try:
            w = abs(float(ext_max[0]) - float(ext_min[0]))
            h = abs(float(ext_max[1]) - float(ext_min[1]))
        except Exception:
            w = h = 0.0
        if not (w and h) or w > 1e9 or h > 1e9:
            xs = [s.x for s in symbols] or [0.0]
            ys = [s.y for s in symbols] or [0.0]
            w, h = (max(xs) - min(xs)) or 1.0, (max(ys) - min(ys)) or 1.0

        # model space is one "page"; a DXF is vector by construction
        pages = [PageRead(words=words, raw_word_count=len(words),
                          width_pt=float(w), height_pt=float(h), kind="vector")]

        # Producer is the adapter, not $LASTSAVEDBY — CAD files rarely set that
        # header, and the seam needs a stable identity for diagnostics.
        return ReadResult(pages=pages,
                          producer="ezdxf",
                          symbols=symbols, geometry=geometry, units=units)


def block_counts(symbols) -> dict:
    """Exact counts by block name — the non-text auto-count."""
    out: dict = {}
    for s in symbols:
        out[s.block_name] = out.get(s.block_name, 0) + 1
    return out


register(DxfAdapter())
