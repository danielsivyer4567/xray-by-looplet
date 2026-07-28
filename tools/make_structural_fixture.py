"""Render a small structural floor plan to fixtures/cad/structural-columns.dxf —
the permanent fixture for the structural-count pack.

Exact by construction, so the ground truths the tests assert are provable:
  * 12 column footprints (closed polylines) on layer PERIMETER_COLUMNS
  *  4 column footprints on layer CORE_COLUMNS
  *  1 building outline on layer FOOTPRINT   (a boundary — must NOT be counted)
  *  1 core outline on layer CORE_WALLS      (a boundary — must NOT be counted)

Mirrors the shape of a real column plan (e.g. the WTC DXF): components drawn as
polylines, not blocks, on named trade layers. Deterministic — no timestamps.
"""
from __future__ import annotations

import os

COL = 500.0  # column footprint side (mm-ish; units are cm here, values are illustrative)


def _sq(msp, cx, cy, s, layer):
    h = s / 2.0
    msp.add_lwpolyline(
        [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)],
        close=True, dxfattribs={"layer": layer})


def build(path: str) -> str:
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 5  # cm
    for name, colour in [("FOOTPRINT", 1), ("CORE_WALLS", 4),
                         ("PERIMETER_COLUMNS", 2), ("CORE_COLUMNS", 3)]:
        doc.layers.add(name, color=colour)
    msp = doc.modelspace()

    W, H = 12000.0, 8000.0
    msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True,
                       dxfattribs={"layer": "FOOTPRINT"})           # boundary, not counted

    # 12 perimeter columns: 4 along each long wall, 2 more on each short wall
    xs_top = [W * i / 4 for i in range(5)]          # 5 points, but corners shared
    perim = []
    for x in [0, W / 4, W / 2, 3 * W / 4, W]:
        perim += [(x, 0), (x, H)]                    # bottom + top rows (10)
    perim += [(0, H / 2), (W, H / 2)]                # mid side columns (2) -> 12
    for (x, y) in perim:
        _sq(msp, x, y, COL, "PERIMETER_COLUMNS")

    # a core: an outline (not counted) + 4 core columns at its corners
    cx0, cy0, cx1, cy1 = W * 0.38, H * 0.38, W * 0.62, H * 0.62
    msp.add_lwpolyline([(cx0, cy0), (cx1, cy0), (cx1, cy1), (cx0, cy1)],
                       close=True, dxfattribs={"layer": "CORE_WALLS"})  # boundary
    for (x, y) in [(cx0, cy0), (cx1, cy0), (cx1, cy1), (cx0, cy1)]:
        _sq(msp, x, y, COL * 0.6, "CORE_COLUMNS")

    doc.header["$EXTMIN"] = (-COL, -COL, 0.0)
    doc.header["$EXTMAX"] = (W + COL, H + COL, 0.0)
    doc.saveas(path)
    return path


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "fixtures", "cad", "structural-columns.dxf")
    print(build(out))
