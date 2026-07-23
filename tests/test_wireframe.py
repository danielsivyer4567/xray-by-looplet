"""Wireframe (visualization roadmap, Phase 2).

The scene is a reconstruction of the takeoff, so its truths are the takeoff's:
one vertical element per placed component at its measured (x, y), counts that
round-trip exactly, heights flagged as assumed unless supplied, and a
self-contained offline viewer. Proven against the CAD fixtures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytest.importorskip("ezdxf", reason="CAD deps not installed")

from xray.engine import run                                      # noqa: E402
from xray.wireframe import build_scene, roundtrip_check, render_html  # noqa: E402

CAD2 = REPO / "fixtures" / "cad" / "architectural_test_fixtures_v2.dxf"
FENCE = REPO / "fixtures" / "cad" / "fencing-boundary.dxf"


@pytest.fixture(scope="module")
def fence_takeoff():
    return run(str(FENCE))


@pytest.fixture(scope="module")
def arch_takeoff():
    return run(str(CAD2))


# ---------------------------------------------------------- one element per part

def test_one_element_per_placed_component(fence_takeoff):
    """22 placements (21 posts + 1 gate) -> 22 vertical elements."""
    scene = build_scene(fence_takeoff)
    assert len(scene["elements"]) == 22
    kinds = {e["type"] for e in scene["elements"]}
    assert kinds == {"POST", "GATE"}


def test_elements_sit_at_measured_xy(fence_takeoff):
    """A post's element base must be exactly the symbol's measured (x, y) — the
    faithful part of the model."""
    posts = [s for s in fence_takeoff["symbols"] if s["blockName"] == "POST"]
    by_id = {s["id"]: s for s in posts}
    scene = build_scene(fence_takeoff)
    checked = 0
    for e in scene["elements"]:
        if e["nodeId"] in by_id:
            s = by_id[e["nodeId"]]
            assert e["a"][0] == s["x"] and e["a"][1] == s["y"]
            assert e["a"][2] == 0.0 and e["b"][2] > 0.0    # extruded upward
            checked += 1
    assert checked == 21


def test_element_carries_its_graph_node_id(arch_takeoff):
    """Every element's nodeId is a real symbol id, so the wireframe and the graph
    are the same object viewed two ways."""
    ids = {s["id"] for s in arch_takeoff["symbols"]}
    scene = build_scene(arch_takeoff)
    assert scene["elements"]
    assert all(e["nodeId"] in ids for e in scene["elements"])


# ------------------------------------------------------------- height discipline

def test_height_is_flagged_assumed_by_default(fence_takeoff):
    scene = build_scene(fence_takeoff)
    assert scene["meta"]["heightBasis"] == "assumed"
    assert all(e["heightTier"] == "needs-human" for e in scene["elements"])


def test_supplied_height_is_marked_given(fence_takeoff):
    scene = build_scene(fence_takeoff, heights={"POST": 1800.0, "GATE": 1800.0})
    assert scene["meta"]["heightBasis"] == "given"
    assert all(e["heightTier"] == "given" for e in scene["elements"])
    post = next(e for e in scene["elements"] if e["type"] == "POST")
    assert post["b"][2] == 1800.0


def test_mixed_heights_flag_only_the_assumed_type(fence_takeoff):
    scene = build_scene(fence_takeoff, heights={"POST": 1800.0})  # gate assumed
    posts = [e for e in scene["elements"] if e["type"] == "POST"]
    gates = [e for e in scene["elements"] if e["type"] == "GATE"]
    assert all(e["heightTier"] == "given" for e in posts)
    assert all(e["heightTier"] == "needs-human" for e in gates)


# ------------------------------------------------------------- the round-trip gate

def test_roundtrip_counts_match_the_takeoff(arch_takeoff):
    scene = build_scene(arch_takeoff)
    check = roundtrip_check(scene, arch_takeoff)
    assert check["ok"] is True
    assert check["byType"]["BOLT_M16"] == 25       # matches the adapter's count

    scene = build_scene(FENCE and run(str(FENCE)))
    assert roundtrip_check(scene, run(str(FENCE)))["ok"] is True


def test_roundtrip_detects_a_dropped_component(arch_takeoff):
    """If the scene loses an element, the gate must catch it — the model is
    then not faithful to the drawing."""
    scene = build_scene(arch_takeoff)
    scene["elements"] = [e for e in scene["elements"] if e["type"] != "BOLT_M16"]
    check = roundtrip_check(scene, arch_takeoff)
    assert check["ok"] is False
    assert "BOLT_M16" in check["mismatches"]


# ------------------------------------------------------------- determinism + html

def test_scene_is_byte_deterministic(arch_takeoff):
    a = json.dumps(build_scene(arch_takeoff), sort_keys=True)
    b = json.dumps(build_scene(arch_takeoff), sort_keys=True)
    assert a == b


def test_viewer_is_self_contained(fence_takeoff):
    html = render_html(build_scene(fence_takeoff))
    assert html.startswith("<!doctype html>")
    assert "getContext('webgl'" in html
    # offline: no external scripts, styles, or fetches
    assert "src=" not in html and "http://" not in html and "https://" not in html
    # the scene is embedded, so it renders with no companion file
    assert '"nodeId"' in html
