"""Tests for hardening: wastage/laps -> order_qty, purchase units, accessories."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray import engine  # noqa: E402
from xray.hardening import harden  # noqa: E402
from xray.quantify import Quantity  # noqa: E402

SHED = REPO / "fixtures" / "shed-manners-aline.pdf"
SPEC = {"L": 16, "W": 9, "pitch": 10, "eave": 4.2, "bays": 4}


@pytest.fixture(scope="module")
def shed():
    return engine.run(str(SHED))


def _q(res, frag):
    return next((q for q in res["quantities"] if frag in q["item"]), None)


def test_roof_gets_wastage_and_lap_order_qty(shed):
    roof = _q(shed, "roof sheeting")
    assert roof["order_qty"] is not None and roof["order_qty"] > roof["qty"]
    assert {a["name"] for a in roof["allowances"]} == {"laps", "wastage"}
    assert abs(roof["order_qty"] - round(roof["qty"] * 1.05 * 1.10, 1)) < 0.2


def test_steel_gets_purchase_units(shed):
    steel = _q(shed, "portal frame steel")
    assert steel["purchase"], "steel should carry a purchase breakdown"
    p = steel["purchase"][0]
    assert p["stock_length_m"] == 12.0 and p["count"] >= 1 and p["offcut_m"] >= 0


def test_accessories_generated_with_evidence(shed):
    for frag in ("ridge capping", "barge", "gutter", "downpipes", "roof screws"):
        a = _q(shed, frag)
        assert a is not None, f"accessory '{frag}' missing"
        assert a["formula"].strip() and a["evidence"]
    assert _q(shed, "gutter")["unit"] == "lm"
    assert _q(shed, "downpipes")["unit"] == "ea"


def test_harden_is_pure():
    q = Quantity(id="x", trade="roofing", item="roof sheeting", qty=100.0,
                 unit="m2", formula="f", tier="single-source", evidence=["e1"])
    out = harden([q], spec=SPEC, base_evidence=["e1"])
    assert q.order_qty is None and q.allowances == []       # input untouched
    hardened = next(x for x in out if x.item == "roof sheeting")
    assert hardened.order_qty is not None                   # copy enriched
    assert any(x.id.startswith("qty-acc-") for x in out)    # accessories added
