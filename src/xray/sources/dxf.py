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
# ISO metric thread designation: M16 means a 16 mm nominal diameter. Anchored on
# a non-letter (underscore counts as a word char, so \b fails on BOLT_M16).
NAME_METRIC = re.compile(r"(?:^|[^A-Za-z])M(\d{1,3})(?![0-9A-Za-z])")
# leading number in an override dimension text, e.g. "650.0 mm (FIELD VERIFY)"
TEXT_NUM = re.compile(r"-?\d+(?:\.\d+)?")
# a block DAG deeper than this is malformed or self-referential
MAX_BLOCK_DEPTH = 12


def trade_for(layer: str) -> str:
    up = (layer or "").upper()
    for key, trade in LAYER_TRADE:
        if key in up:
            return trade
    return ""


def _attrs_for(insert, blocks) -> tuple[dict, tuple]:
    """Instance ATTRIBs merged over the block's ATTDEF defaults.

    An ATTDEF is the block's default ("every M16 is grade 8.8"); an ATTRIB on the
    placement is this instance's own statement ("this one is 10.9"). The instance
    wins, and the overridden tags are recorded so the override stays auditable.
    """
    defaults, out, over = {}, {}, []
    blk = blocks.get(insert.dxf.name)
    if blk is not None:
        for e in blk:
            if e.dxftype() == "ATTDEF":
                defaults[e.dxf.tag] = e.dxf.text
    out.update(defaults)
    for a in getattr(insert, "attribs", []) or []:
        tag, val = a.dxf.tag, a.dxf.text
        if tag in defaults and defaults[tag] != val:
            over.append(tag)
        out[tag] = val
    return out, tuple(over)


def expand_inserts(container, blocks, depth=0, path=(), origin=(0.0, 0.0),
                   rot=0.0, scale=(1.0, 1.0), chain=()):
    """Yield a Symbol for EVERY block placement, at any nesting depth.

    A component's real count only appears after recursion: one modelspace INSERT
    of an assembly can stand for dozens of parts (here, 3 assemblies carry 24 of
    the 25 bolts). A top-level-only scan silently undercounts — the single most
    consequential mistake this adapter could make, because the number still looks
    plausible.

    Positions carry through the cumulative transform, so a nested part reports
    where it actually sits in model space.
    """
    if depth > MAX_BLOCK_DEPTH:
        return
    ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    for i, e in enumerate(container):
        if e.dxftype() != "INSERT":
            continue
        name = e.dxf.name
        # Identity: the chain of INSERT handles from the modelspace root down
        # to this placement (see Symbol.id). The chain — not any single handle —
        # is what stays unique when one definition is placed many times.
        h = str(getattr(e.dxf, "handle", "") or f"i{i}")
        sid = "/".join(chain + (h,))
        pid = "/".join(chain) or None
        # local placement -> parent space: scale, then rotate, then translate
        lx = float(e.dxf.insert.x) * scale[0]
        ly = float(e.dxf.insert.y) * scale[1]
        wx = origin[0] + lx * ca - ly * sa
        wy = origin[1] + lx * sa + ly * ca
        wrot = rot + float(getattr(e.dxf, "rotation", 0.0) or 0.0)
        wsx = scale[0] * float(getattr(e.dxf, "xscale", 1.0) or 1.0)
        wsy = scale[1] * float(getattr(e.dxf, "yscale", 1.0) or 1.0)
        layer = getattr(e.dxf, "layer", "") or ""
        attribs, over = _attrs_for(e, blocks)
        yield Symbol(block_name=name, layer=layer, x=wx, y=wy,
                     rotation=wrot, xscale=wsx, yscale=wsy,
                     trade=trade_for(layer), depth=depth, path=path,
                     attribs=attribs, overridden=over,
                     id=sid, parent_id=pid)
        blk = blocks.get(name)
        if blk is not None:
            yield from expand_inserts(blk, blocks, depth + 1, path + (name,),
                                      (wx, wy), wrot, (wsx, wsy),
                                      chain + (h,))


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
            return {"declared": declared, "resolved": resolved,
                    "basis": basis, "mismatch": mismatch}

    # ISO metric thread: a BOLT_M16 drawn 16 units across is a 16 mm bolt, so
    # the drawing unit is the millimetre.
    for name, blk in blocks.items():
        m = NAME_METRIC.search(name)
        if not m:
            continue
        stated = float(m.group(1))
        width = _bbox_width(blk, None)
        if stated > 0 and width > 0 and abs(width - stated) / stated < 0.20:
            resolved = "mm"
            basis = f"metric thread {name} (M{stated:g} ~ {width:.2f} units)"
            mismatch = bool(declared) and declared != "mm"
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

        # recursion needs the anonymous blocks too (*U1 groups hold real
        # placements); unit evidence only looks at named ones
        all_blocks = {b.name: b for b in doc.blocks}
        blocks = {n: b for n, b in all_blocks.items() if not n.startswith("*")}

        symbols: list[Symbol] = []
        geometry: list[Measure] = []
        words = []          # DXF TEXT/MTEXT flow into the existing text pipeline

        # every placement at every depth — see expand_inserts
        symbols.extend(expand_inserts(msp, all_blocks))

        for gi, e in enumerate(msp):
            t = e.dxftype()
            layer = getattr(e.dxf, "layer", "") or ""
            # the entity handle is a stable per-file id; fall back to the read
            # ordinal so every run is still citable as evidence.
            mid = str(getattr(e.dxf, "handle", "") or "") or f"g{gi}"
            try:
                if t == "DIMENSION":
                    # the measured span comes from the geometry, never from the
                    # display text ("<>" means derived). An override text stating
                    # a DIFFERENT number is kept alongside, never resolved away.
                    measured = float(e.get_measurement())
                    text = getattr(e.dxf, "text", "") or ""
                    tv = None
                    if text and text != "<>":
                        m = TEXT_NUM.search(text)
                        if m:
                            tv = float(m.group())
                    geometry.append(Measure(
                        kind="dimension", value=measured, layer=layer, text=text,
                        text_value=tv,
                        conflict=(tv is not None and
                                  abs(tv - measured) > max(1e-6, abs(measured) * 1e-6)),
                        trade=trade_for(layer), id=mid))
                elif t == "LINE":
                    a, b = e.dxf.start, e.dxf.end
                    geometry.append(Measure(
                        kind="line", value=math.dist((a.x, a.y), (b.x, b.y)),
                        layer=layer, trade=trade_for(layer), id=mid))
                elif t == "LWPOLYLINE":
                    raw = [(p[0], p[1]) for p in e.get_points("xy")]
                    ring = raw + [raw[0]] if (e.closed and len(raw) > 2) else raw
                    total = sum(math.dist(ring[i], ring[i + 1])
                                for i in range(len(ring) - 1))
                    # shoelace area for a closed ring (0 for open/degenerate)
                    area = None
                    if e.closed and len(raw) >= 3:
                        n = len(raw)
                        area = abs(sum(raw[i][0] * raw[(i + 1) % n][1]
                                       - raw[(i + 1) % n][0] * raw[i][1]
                                       for i in range(n))) / 2.0
                    geometry.append(Measure(
                        kind="polyline", value=total, layer=layer,
                        trade=trade_for(layer), id=mid, area=area))
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

        # Provenance: is this a native CAD drawing, or a plot flattened into a
        # DXF container (see fixtures/negative/README.md)? A flattened plot has
        # no blocks to count and no DIMENSION entities it measured — every tell
        # below is sufficient on its own, so any one flags the file.
        # A flattened plot has no blocks to count, no DIMENSION entities, AND no
        # trade semantics — just loose strokes on generic buckets (0/GEOMETRY/
        # TEXT). A real drawing can also lack blocks and dimensions (components
        # drawn as polylines), so the deciding tell is the LAYERS: if any
        # geometry sits on a recognised trade layer (PERIMETER_COLUMNS, WALL,
        # ROOF…), it is a real drawing, not a flatten. $LASTSAVEDBY == ezdxf only
        # corroborates — legitimate CAD is routinely exported through ezdxf.
        reasons = []
        n_dims = sum(1 for g in geometry if g.kind == "dimension")
        has_trade_layer = any(getattr(g, "trade", "") for g in geometry)
        if not symbols and n_dims == 0 and geometry and not has_trade_layer:
            reasons.append("no blocks (INSERTs), no DIMENSION entities, and no "
                           f"trade-semantic layers, yet {len(geometry)} loose "
                           "line/polyline(s) — the signature of a flattened plot")
            if str(doc.header.get("$LASTSAVEDBY", "") or "").strip().lower() == "ezdxf":
                reasons.append("and $LASTSAVEDBY is 'ezdxf' (machine-written, not "
                               "saved by a CAD application)")
        provenance = {"suspect": bool(reasons), "reasons": reasons}

        # Producer is the adapter, not $LASTSAVEDBY — CAD files rarely set that
        # header, and the seam needs a stable identity for diagnostics.
        return ReadResult(pages=pages,
                          producer="ezdxf",
                          symbols=symbols, geometry=geometry, units=units,
                          provenance=provenance)


def block_counts(symbols) -> dict:
    """Exact counts by block name — the non-text auto-count."""
    out: dict = {}
    for s in symbols:
        out[s.block_name] = out.get(s.block_name, 0) + 1
    return out


register(DxfAdapter())
