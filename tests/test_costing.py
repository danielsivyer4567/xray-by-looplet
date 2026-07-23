"""Costing — a takeoff priced against a CSV price list, with NO language model.

Every number here is hand-computed from the sample price fixture, so the test is
the proof that the join-and-multiply is right and that the guards (unit gate,
freshness, unmatched, ambiguous, POA) flag rather than fabricate.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from pricing.costing import (   # noqa: E402
    load_price_list, cost_takeoff, to_csv, quote_html, PriceRow,
)

PRICES = REPO / "fixtures" / "pricing" / "sample-fence-prices.csv"

# a synthetic fence takeoff — item/unit/qty is all costing needs
QUANTITIES = [
    {"id": "q-fence-length", "item": "fence line", "unit": "lm", "qty": 48.0},
    {"id": "q-fence-posts", "item": "fence posts", "unit": "ea", "qty": 21.0},
    {"id": "q-fence-gates", "item": "gates", "unit": "ea", "qty": 1.0},
    {"id": "q-rail", "item": "top rail steel", "unit": "lm", "qty": 100.0},
    {"id": "q-bollard", "item": "bollard", "unit": "lm", "qty": 5.0},
]


def _line(result, qid):
    return next(ln for ln in result["lines"] if ln["quantity_id"] == qid)


def test_prices_multiply_qty_by_rate():
    rows = load_price_list(PRICES)
    r = cost_takeoff(QUANTITIES, rows)
    assert _line(r, "q-fence-length")["amount"] == 3456.00      # 48 x 72.00
    assert _line(r, "q-fence-posts")["amount"] == 388.50        # 21 x 18.50
    assert _line(r, "q-fence-gates")["amount"] == 240.00        # 1 x 240.00


def test_total_and_counts():
    r = cost_takeoff(load_price_list(PRICES), [], )  # empty is a valid no-op
    assert r["summary"]["total"] == 0.0 and r["summary"]["priced"] == 0
    r = cost_takeoff(QUANTITIES, load_price_list(PRICES))
    assert r["summary"]["total"] == 4084.50            # 3456 + 388.5 + 240
    assert r["summary"]["priced"] == 3
    assert r["summary"]["needsHuman"] == 2             # rail (unmatched) + bollard (unit)


def test_priced_line_stamps_provenance():
    r = cost_takeoff(QUANTITIES, load_price_list(PRICES))
    ln = _line(r, "q-fence-length")
    assert ln["status"] == "priced"
    assert "SAMPLE-FenceCo" in ln["provenance"] and "2026-07-15" in ln["provenance"]


def test_unmatched_item_flags_not_prices():
    r = cost_takeoff(QUANTITIES, load_price_list(PRICES))
    ln = _line(r, "q-rail")
    assert ln["status"] == "needs-human"
    assert ln["rate"] is None and ln["amount"] is None
    assert "no price row" in ln["reason"]


def test_unit_gate_blocks_a_wrong_unit_match():
    """'bollard' is priced per ea; the quantity is lm. The name matches but the
    unit cannot fulfil it — flagged, and the reason names the unit clash."""
    r = cost_takeoff(QUANTITIES, load_price_list(PRICES))
    ln = _line(r, "q-bollard")
    assert ln["status"] == "needs-human" and ln["amount"] is None
    assert "'ea'" in ln["reason"] and "'lm'" in ln["reason"]


def test_stale_price_does_not_cost_the_job():
    """As of 2026-09-01 with a 30-day window, the 2026-07-15 list is 48 days old
    -> every line flags stale, no amount, rate stays null."""
    r = cost_takeoff(QUANTITIES, load_price_list(PRICES),
                     as_of="2026-09-01", freshness_days=30)
    ln = _line(r, "q-fence-length")
    assert ln["status"] == "needs-human" and ln["amount"] is None
    assert "older than the 30-day window" in ln["reason"]
    assert r["summary"]["total"] == 0.0


def test_fresh_price_inside_window_is_costed():
    r = cost_takeoff(QUANTITIES, load_price_list(PRICES),
                     as_of="2026-07-20", freshness_days=30)   # 5 days old
    assert _line(r, "q-fence-length")["status"] == "priced"


def test_ambiguous_match_flags_rather_than_guessing():
    """Two equally-specific rows for the same item+unit must not be silently
    averaged or first-wins — the operator chooses."""
    rows = [
        PriceRow("fence line", [], "lm", 60.0, "2026-07-15", "QLD-SE", "A"),
        PriceRow("fence line", [], "lm", 80.0, "2026-07-15", "QLD-SE", "B"),
    ]
    r = cost_takeoff([{"id": "x", "item": "fence line", "unit": "lm", "qty": 10}], rows)
    ln = _line(r, "x")
    assert ln["status"] == "needs-human"
    assert "match equally" in ln["reason"]


def test_poa_row_flags_never_prices_zero():
    rows = [PriceRow("gates", [], "ea", None, "2026-07-15", "QLD-SE", "S")]
    r = cost_takeoff([{"id": "g", "item": "gates", "unit": "ea", "qty": 2}], rows)
    ln = _line(r, "g")
    assert ln["status"] == "needs-human" and ln["amount"] is None
    assert "POA" in ln["reason"] or "no price" in ln["reason"]


def test_region_filter_excludes_other_regions():
    rows = [
        PriceRow("gates", [], "ea", 200.0, "2026-07-15", "NSW", "S"),
        PriceRow("gates", [], "ea", 240.0, "2026-07-15", "QLD-SE", "S"),
    ]
    r = cost_takeoff([{"id": "g", "item": "gates", "unit": "ea", "qty": 1}],
                     rows, region="QLD-SE")
    assert _line(r, "g")["amount"] == 240.0


def test_determinism():
    rows = load_price_list(PRICES)
    import json
    a = json.dumps(cost_takeoff(QUANTITIES, rows), sort_keys=True)
    b = json.dumps(cost_takeoff(QUANTITIES, rows), sort_keys=True)
    assert a == b


def test_exports_are_self_contained():
    r = cost_takeoff(QUANTITIES, load_price_list(PRICES))
    csv_text = to_csv(r)
    assert "TOTAL (priced)" in csv_text and "4084.5" in csv_text
    html = quote_html(r)
    assert html.startswith("<!doctype html>")
    assert "$4,084.50" in html
    assert "<script" not in html and "src=" not in html    # offline, no deps
