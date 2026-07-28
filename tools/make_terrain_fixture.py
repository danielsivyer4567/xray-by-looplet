"""Render a site survey / terrain model to fixtures/cad/terrain-survey.dxf —
the permanent fixture for the survey pack.

Exact by construction, so the ground truths the tests assert are provable by
opening this .dxf in ANY CAD viewer and reading the numbers yourself:

  *   5 survey spot levels (POINT entities on layer SURVEY_POINTS), z = RL:
        lowest  RL -40.91   (the shot at 48.20, 827.65)
        highest RL 283.42   (the shot at 594.80, 481.67)
        site fall = 283.42 - (-40.91) = 324.33
  *  121 terrain-mesh vertices (an 11 x 11 polygon mesh on TERRAIN_MESH)
  *   3 contour lines (single-RL 3D polylines on CONTOURS_MAJOR at RL 100/150/200)
  *   1 breakline (a variable-z 3D polyline on BREAKLINES)

Old-style R12 heavy POLYLINE + POINT entities on purpose — a real surveyor's
export is exactly this, and it is the case the DXF adapter had to learn to read.
Deterministic: no timestamps, no randomness. The five spot levels below are the
literal coordinates from the survey DXF this fixture stands in for.
"""
from __future__ import annotations

import os

# The five field shots (x, y, RL) — the survey's raw evidence. Do not reorder:
# the tests derive lowest/highest RL and the fall directly from these numbers.
SPOT_LEVELS = [
    (504.33, 468.12, 267.82),
    (594.80, 481.67, 283.42),   # highest RL
    (713.54, 356.92, 194.71),
    (48.20, 827.65, -40.91),    # lowest RL
    (1186.78, 1181.55, 252.40),
]

CONTOUR_RLS = (100.0, 150.0, 200.0)   # three contours, each at ONE level


def build(path: str) -> str:
    import ezdxf

    doc = ezdxf.new("R12")             # old CAD: heavy POLYLINE + POINT, not LWPOLYLINE
    doc.header["$INSUNITS"] = 6         # metres
    for name, colour in [("TERRAIN_MESH", 3), ("CONTOURS_MAJOR", 1),
                         ("CONTOURS_MINOR", 8), ("SURVEY_POINTS", 2),
                         ("BREAKLINES", 5)]:
        if name not in doc.layers:
            doc.layers.add(name, color=colour)
    msp = doc.modelspace()

    # 11 x 11 polygon mesh (121 vertices) — a smooth hump. The mesh's own z is
    # illustrative; it is the COUNT of vertices (11*11) the survey pack reports.
    m, n = 11, 11
    mesh = msp.add_polymesh(size=(m, n), dxfattribs={"layer": "TERRAIN_MESH"})
    for i in range(m):
        for j in range(n):
            x, y = i * 120.0, j * 120.0
            z = 100.0 * (1 - ((i - 5) ** 2 + (j - 5) ** 2) / 50.0)
            mesh.set_mesh_vertex((i, j), (x, y, z))

    # three contour lines, each a 3D polyline at a CONSTANT z (its RL)
    for rl in CONTOUR_RLS:
        msp.add_polyline3d(
            [(200 + rl, 100, rl), (400, 300 + rl / 2, rl), (700, 800, rl)],
            dxfattribs={"layer": "CONTOURS_MAJOR"})

    # one breakline: a 3D polyline whose z VARIES along its length
    msp.add_polyline3d(
        [(0, 515, -21), (300, 475, 58), (600, 330, 248), (1200, 205, 213)],
        dxfattribs={"layer": "BREAKLINES"})

    # the five survey spot levels (POINT entities carrying x, y, RL)
    for (x, y, z) in SPOT_LEVELS:
        msp.add_point((x, y, z), dxfattribs={"layer": "SURVEY_POINTS"})

    doc.header["$EXTMIN"] = (0.0, 0.0, -42.0)
    doc.header["$EXTMAX"] = (1200.0, 1200.0, 286.0)
    doc.saveas(path)
    return path


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "fixtures", "cad", "terrain-survey.dxf")
    print(build(out))
