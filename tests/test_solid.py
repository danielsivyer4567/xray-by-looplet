"""Solid glTF export (visualization Phase 3 on-ramp).

The glTF is a solid reconstruction of the takeoff, so its truths are the
takeoff's: one box per placed component at its measured (x,y), node names that
are graph ids, counts that round-trip, and a buffer whose bytes are the actual
coordinates. Proven against the fence fixture, and the buffer is decoded and
checked — no glTF validator dependency needed.
"""
from __future__ import annotations

import base64
import json
import struct
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytest.importorskip("ezdxf", reason="CAD deps not installed")

from xray.engine import run                                   # noqa: E402
from xray.solid import build_solids, to_gltf, roundtrip_check  # noqa: E402

FENCE = REPO / "fixtures" / "cad" / "fencing-boundary.dxf"
HEIGHTS = {"POST": 1800.0, "GATE": 1800.0}


@pytest.fixture(scope="module")
def takeoff():
    return run(str(FENCE))


# ------------------------------------------------------------------ solids

def test_one_box_per_component(takeoff):
    solids = build_solids(takeoff, heights=HEIGHTS)
    assert len(solids["meshes"]) == 22
    assert {m["type"] for m in solids["meshes"]} == {"POST", "GATE"}


def test_boxes_are_extruded_from_ground_to_height(takeoff):
    solids = build_solids(takeoff, heights=HEIGHTS)
    for m in solids["meshes"]:
        x0, y0, z0, x1, y1, z1 = m["box"]
        assert z0 == 0.0 and z1 == 1800.0       # extruded up to the given height
        assert x1 > x0 and y1 > y0              # a real footprint, not degenerate


def test_height_tier_tracks_given_vs_assumed(takeoff):
    given = build_solids(takeoff, heights=HEIGHTS)
    assert all(m["heightTier"] == "given" for m in given["meshes"])
    assert given["meta"]["heightBasis"] == "given"
    assumed = build_solids(takeoff)              # no heights supplied
    assert all(m["heightTier"] == "needs-human" for m in assumed["meshes"])


# -------------------------------------------------------------------- glTF

def test_gltf_structure_is_valid(takeoff):
    g = to_gltf(build_solids(takeoff, heights=HEIGHTS))
    assert g["asset"]["version"] == "2.0"
    assert len(g["nodes"]) == 22 and len(g["meshes"]) == 22
    assert len(g["accessors"]) == 44           # a POSITION + an index per mesh
    assert len(g["bufferViews"]) == 44
    # one self-contained embedded buffer
    assert len(g["buffers"]) == 1
    assert g["buffers"][0]["uri"].startswith("data:application/octet-stream;base64,")


def test_every_node_is_named_by_its_graph_id(takeoff):
    tk = takeoff
    ids = {s["id"] for s in tk["symbols"]}
    g = to_gltf(build_solids(tk, heights=HEIGHTS))
    assert all(n["name"] in ids for n in g["nodes"])
    # the tag rides into the renderer via extras
    n0 = g["nodes"][0]
    assert n0["extras"]["xrayNodeId"] == n0["name"]
    assert n0["extras"]["xrayType"] in ("POST", "GATE")


def test_position_accessors_carry_min_max(takeoff):
    g = to_gltf(build_solids(takeoff, heights=HEIGHTS))
    pos = [a for a in g["accessors"] if a["type"] == "VEC3"]
    assert len(pos) == 22
    assert all("min" in a and "max" in a and a["componentType"] == 5126 for a in pos)


def test_buffer_bytes_are_the_real_coordinates(takeoff):
    """Decode the embedded buffer and confirm the first box's vertices are the
    actual post footprint — the geometry is really in there, not a stub."""
    solids = build_solids(takeoff, heights=HEIGHTS)
    g = to_gltf(solids)
    raw = base64.b64decode(g["buffers"][0]["uri"].split(",", 1)[1])
    assert len(raw) == g["buffers"][0]["byteLength"] == 22 * (96 + 72)
    # first mesh = POST at (0,0); footprint half = 0.05*1800/2 = 45
    first = struct.unpack("<3f", raw[0:12])
    assert first == (-45.0, -45.0, 0.0)
    # its index block starts right after all positions (22*96 = 2112)
    idx0 = struct.unpack("<3H", raw[2112:2118])
    assert idx0 == (0, 2, 1)                    # first triangle of the box


def test_gltf_is_byte_deterministic(takeoff):
    a = json.dumps(to_gltf(build_solids(takeoff, heights=HEIGHTS)), sort_keys=True)
    b = json.dumps(to_gltf(build_solids(takeoff, heights=HEIGHTS)), sort_keys=True)
    assert a == b


# ------------------------------------------------------------- round-trip

def test_roundtrip_counts_match(takeoff):
    solids = build_solids(takeoff, heights=HEIGHTS)
    check = roundtrip_check(solids, takeoff)
    assert check["ok"] is True
    assert check["byType"] == {"POST": 21, "GATE": 1}


def test_roundtrip_detects_a_dropped_solid(takeoff):
    solids = build_solids(takeoff, heights=HEIGHTS)
    solids["meshes"] = [m for m in solids["meshes"] if m["type"] != "GATE"]
    check = roundtrip_check(solids, takeoff)
    assert check["ok"] is False and "GATE" in check["mismatches"]
