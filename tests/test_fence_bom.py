"""Full fencing BOM — a measured run expanded into an orderable material list.

The run length is measured; the rest follows from the length + the chosen fence
system. Proven against the fence fixture (48 lm), across all three systems, with
the honest tiers (measured-derived = single-source, concrete = needs-human).
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

from xray.engine import run                     # noqa: E402
from xray.fence_bom import fence_bom            # noqa: E402

FIXTURE = REPO / "fixtures" / "cad" / "fencing-boundary.dxf"


@pytest.fixture(scope="module")
def takeoff():
    return run(str(FIXTURE))


def _line(bom, item):
    return next((ln for ln in bom["lines"] if ln["item"] == item), None)


def test_colorbond_bill(takeoff):
    b = fence_bom(takeoff, system="colorbond", height_m=1.8)
    assert b["runLength_m"] == 48.0
    assert _line(b, "Colorbond steel rails")["qty"] == 96.0      # 2 x 48
    assert _line(b, "Colorbond sheets")["qty"] == 20.0           # ceil(48/2.4)
    assert _line(b, "Footings")["qty"] == 21.0
    assert _line(b, "Post caps")["qty"] == 21.0


def test_paling_bill(takeoff):
    b = fence_bom(takeoff, system="paling", height_m=1.8)
    assert _line(b, "Palings")["qty"] == 534.0                   # ceil(48/0.09)
    assert _line(b, "Post caps") is None                          # paling has no caps


def test_chainmesh_bill(takeoff):
    b = fence_bom(takeoff, system="chainmesh", height_m=1.8)
    assert _line(b, "Chainmesh")["qty"] == 86.4                  # 48 x 1.8
    assert _line(b, "Top rail")["qty"] == 48.0


def test_taller_fence_adds_a_mid_rail(takeoff):
    b = fence_bom(takeoff, system="colorbond", height_m=2.1)     # > 1.8
    assert _line(b, "Colorbond steel rails")["qty"] == 144.0     # 3 x 48


def test_concrete_is_needs_human_and_names_the_assumption(takeoff):
    b = fence_bom(takeoff, system="colorbond", height_m=1.8)
    c = _line(b, "Concrete (footings)")
    assert c["tier"] == "needs-human" and c["unit"] == "m3"
    assert "footing" in c["notes"].lower() and "confirm" in c["notes"].lower()


def test_measured_lines_carry_the_run_evidence(takeoff):
    b = fence_bom(takeoff, system="colorbond", height_m=1.8)
    assert _line(b, "Colorbond steel rails")["evidence"]         # cites the run
    assert _line(b, "Footings")["evidence"]                       # cites the posts


def test_overrides_change_the_bill(takeoff):
    b = fence_bom(takeoff, system="colorbond", height_m=1.8,
                  overrides={"panel_width_m": 3.0})
    assert _line(b, "Colorbond sheets")["qty"] == 16.0          # ceil(48/3.0)


def test_bom_includes_the_posts_and_gates_themselves(takeoff):
    """The physical posts + gates are orderable lines — the bill is incomplete
    without them (caught while wiring costing)."""
    b = fence_bom(takeoff, system="colorbond", height_m=1.8)
    assert _line(b, "Fence posts")["qty"] == 21.0
    assert _line(b, "Gates")["qty"] == 1.0


def test_bom_prices_end_to_end(takeoff):
    """BOM lines are quantity-shaped, so they feed the costing engine straight
    through: drawing -> bill -> priced quote, no LLM. $3,045.08 on the sample
    list, every line matched."""
    from pricing.costing import load_price_list, cost_takeoff
    b = fence_bom(takeoff, system="colorbond", height_m=1.8)
    prices = load_price_list(REPO / "fixtures" / "pricing" / "sample-fence-bom-prices.csv")
    costed = cost_takeoff(b["lines"], prices)
    assert costed["summary"]["needsHuman"] == 0
    assert costed["summary"]["total"] == 3045.08


def test_unknown_system_errors():
    with pytest.raises(ValueError):
        fence_bom({"quantities": []}, system="brick")
