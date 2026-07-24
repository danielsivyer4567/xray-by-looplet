"""Project rollup — building-wide totals from a floor plan + floor count.

The floor count and storey height aren't on the drawing, so every derived total
is needs-human. Proven against the structural fixture's per-floor takeoff.
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

from xray.engine import run                    # noqa: E402
from xray.rollup import project_rollup          # noqa: E402

FIXTURE = REPO / "fixtures" / "cad" / "structural-columns.dxf"


@pytest.fixture(scope="module")
def takeoff():
    return run(str(FIXTURE))


def _t(rollup, item):
    return next((t for t in rollup["totals"] if t["item"] == item), None)


def test_building_height_and_column_line(takeoff):
    """16 columns/floor (12 + 4), 10 floors, 3.5 m storey."""
    r = project_rollup(takeoff, floors=10, floor_height_m=3.5)
    assert r["perFloorColumns"] == 16
    assert _t(r, "building height")["qty"] == 35.0        # 10 x 3.5
    assert _t(r, "column-line length")["qty"] == 560.0    # 16 x 35


def test_total_built_area_multiplies_per_floor(takeoff):
    r = project_rollup(takeoff, floors=10, floor_height_m=3.5)
    built = _t(r, "total built area")
    assert built["qty"] == 96000.0                         # 9600 m2 x 10


def test_every_derived_total_is_needs_human(takeoff):
    """Floors/height are inputs, not measured — so nothing is asserted as fact."""
    r = project_rollup(takeoff, floors=10, floor_height_m=3.5)
    assert all(t["tier"] == "needs-human" for t in r["totals"])


def test_a_flagged_per_floor_area_is_carried_forward(takeoff):
    """The fixture's area is itself flagged (unverified unit); the rollup's total
    built area must SAY so, never launder it into a clean number."""
    r = project_rollup(takeoff, floors=10, floor_height_m=3.5)
    built = _t(r, "total built area")
    assert "needs-human" in built["notes"] or "carries forward" in built["notes"]
