"""Render a small, internally-consistent boundary-fence DXF to
fixtures/cad/fencing-boundary.dxf — the permanent fixture for the fencing pack.

Everything is exact by construction, so the ground truths the tests assert are
provable from these numbers alone:

  * units: $INSUNITS = 4 (mm), no block contradicts it -> resolves to mm
  * one straight fence run: (0,0) -> (48000,0)  = 48000 mm = 48.0 lm
  * 21 POST blocks at 2400 mm centres (x = 0, 2400, ... , 48000) on layer FENCE
      -> equals the spacing estimate floor(48.0/2.4)+1 = 21, so posts RECONCILE
  * 1 GATE block on layer FENCE
      -> gates = 1

Deterministic: no timestamps or random ids are written by this script.
"""
from __future__ import annotations

import os


RUN_MM = 48000.0
SPACING_MM = 2400.0


def build(path: str) -> str:
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # millimetres — the resolved unit, uncontested
    msp = doc.modelspace()
    doc.layers.add("FENCE")

    # POST block: a small square marker centred on its insert point.
    post = doc.blocks.new(name="POST")
    post.add_lwpolyline([(-40, -40), (40, -40), (40, 40), (-40, 40)], close=True)

    # GATE block: a simple leaf rectangle.
    gate = doc.blocks.new(name="GATE")
    gate.add_lwpolyline([(0, 0), (900, 0), (900, 60), (0, 60)], close=True)

    # the fence line — one straight run along the boundary
    msp.add_lwpolyline([(0.0, 0.0), (RUN_MM, 0.0)], dxfattribs={"layer": "FENCE"})

    # posts at 2400 mm centres, both ends inclusive -> 21 posts
    n = int(round(RUN_MM / SPACING_MM)) + 1
    for i in range(n):
        msp.add_blockref("POST", (i * SPACING_MM, 0.0),
                         dxfattribs={"layer": "FENCE"})

    # one gate, set a little off the line so it doesn't sit on a post
    msp.add_blockref("GATE", (12000.0, 500.0), dxfattribs={"layer": "FENCE"})

    doc.header["$EXTMIN"] = (-100.0, -100.0, 0.0)
    doc.header["$EXTMAX"] = (RUN_MM + 100.0, 1000.0, 0.0)

    doc.saveas(path)
    return path


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "fixtures", "cad", "fencing-boundary.dxf")
    print(build(out))
