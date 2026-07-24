"""Structural-count pack — count members drawn as polylines, not blocks.

The fix for "the engine read the file but counted nothing" (a real WTC column
plan hit this). Proven against fixtures/cad/structural-columns.dxf: 12 perimeter
+ 4 core column footprints on named layers, with boundary layers deliberately not
counted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytest.importorskip("ezdxf", reason="CAD deps not installed")

from xray.engine import run                                   # noqa: E402
from xray.packs_structural import StructuralCountPack, _column_layers  # noqa: E402
from xray.packs import PackContext                             # noqa: E402
from xray.sources.base import Measure                          # noqa: E402

FIXTURE = REPO / "fixtures" / "cad" / "structural-columns.dxf"


def _q(result, qid):
    return next((q for q in result["quantities"] if q["id"] == qid), None)


@pytest.fixture(scope="module")
def result():
    return run(str(FIXTURE))


def test_columns_are_counted_per_layer(result):
    per = _q(result, "q-struct-perimeter-columns")
    core = _q(result, "q-struct-core-columns")
    assert per is not None and per["qty"] == 12.0 and per["unit"] == "ea"
    assert core is not None and core["qty"] == 4.0
    assert per["tier"] == "reconciled" and core["tier"] == "reconciled"


def test_each_column_carries_its_own_evidence(result):
    per = _q(result, "q-struct-perimeter-columns")
    assert len(per["evidence"]) == 12          # one polyline id per column


def test_boundary_layers_are_not_counted(result):
    """FOOTPRINT and CORE_WALLS are outlines, not members — they must not become
    a count. Only the two column layers produce quantities."""
    struct = [q for q in result["quantities"] if q["id"].startswith("q-struct-")]
    assert len(struct) == 2
    items = {q["item"] for q in struct}
    assert items == {"Perimeter Columns", "Core Columns"}


def test_pack_does_not_fire_without_a_column_layer():
    pack = StructuralCountPack()
    # a fence run on a FENCE layer is not a column layer
    ctx = PackContext([], [], [], [], symbols=[],
                      geometry=[Measure(kind="polyline", value=10, layer="FENCE")])
    assert pack.detect(ctx) is False
    # a wall polyline is a boundary, not a countable member
    ctx2 = PackContext([], [], [], [], symbols=[],
                       geometry=[Measure(kind="polyline", value=10, layer="CORE_WALLS")])
    assert pack.detect(ctx2) is False


def test_column_layer_matching():
    assert set(_column_layers([
        Measure(kind="polyline", value=1, layer="PERIMETER_COLUMNS"),
        Measure(kind="polyline", value=1, layer="CORE_COLUMNS"),
        Measure(kind="polyline", value=1, layer="FOOTPRINT"),
        Measure(kind="line", value=1, layer="COLUMNS"),   # a line is not a footprint
    ])) == {"PERIMETER_COLUMNS", "CORE_COLUMNS"}
