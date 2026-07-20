"""Tests for server/quote_lines.py — asserts on REAL engine output, not stubs.

Runs the engine on the shed fixture and checks the draft-quote mapping against
the ground truths proven in this session (frames=5 reconciled, wall cladding
needs-human, 8 lines total).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray import engine  # noqa: E402
from server.quote_lines import build_quote_draft, quantity_to_line  # noqa: E402

SHED = REPO / "fixtures" / "shed-manners-aline.pdf"
WAREHOUSE = REPO / "fixtures" / "warehouse-design21.pdf"
ALLOWED_UNITS = {"ea", "lm", "m2", "m3", "kg", "t"}
ALLOWED_TIERS = {"reconciled", "single-source", "needs-human"}


@pytest.fixture(scope="module")
def shed_draft():
    return build_quote_draft(engine.run(str(SHED)))


def test_shed_line_count(shed_draft):
    assert shed_draft["summary"]["lines"] == 8
    assert len(shed_draft["quote_lines"]) == 8


def test_every_line_has_a_basis_and_valid_enums(shed_draft):
    for ln in shed_draft["quote_lines"]:
        assert ln["basis"].strip(), f"empty basis on {ln['source_quantity_id']}"
        assert ln["unit"] in ALLOWED_UNITS
        assert ln["confidence_tier"] in ALLOWED_TIERS
        assert isinstance(ln["evidence_refs"], list) and ln["evidence_refs"]


def test_frames_line_is_reconciled(shed_draft):
    frames = [ln for ln in shed_draft["quote_lines"]
              if ln["source_quantity_id"] == "qty-frames"]
    assert len(frames) == 1
    ln = frames[0]
    assert ln["quantity"] == 5.0
    assert ln["unit"] == "ea"
    assert ln["confidence_tier"] == "reconciled"
    assert ln["review_required"] is False
    assert ln["rate"] is None and ln["amount"] is None


def test_needs_human_line_flags_review(shed_draft):
    nh = [ln for ln in shed_draft["quote_lines"] if ln["review_required"]]
    assert nh, "expected at least one needs-human line (wall cladding)"
    assert all(ln["confidence_tier"] == "needs-human" for ln in nh)
    # and it must be surfaced as a flag for the human
    refs = {f["ref"] for f in shed_draft["flags"]}
    assert any(ln["source_quantity_id"] in refs for ln in nh)


def test_summary_tallies_match_lines(shed_draft):
    s = shed_draft["summary"]
    lines = shed_draft["quote_lines"]
    assert s["needs_human"] == sum(1 for ln in lines if ln["review_required"])
    assert s["reconciled"] + s["single_source"] + s["needs_human"] == s["lines"]
    assert s["checks_pass"] >= 3  # the three exact 16000 chains at minimum


def test_warehouse_yields_zero_lines_but_still_valid():
    """No warehouse rule pack yet -> 0 quote lines, empty (not error), with flags."""
    draft = build_quote_draft(engine.run(str(WAREHOUSE)))
    assert draft["quote_lines"] == []
    assert draft["summary"]["lines"] == 0
    assert draft["document"]["pages"] == 50
    assert isinstance(draft["flags"], list)


def test_mapping_is_pure_over_a_minimal_dict():
    """quantity_to_line only depends on documented fields."""
    q = {"id": "q1", "trade": "t", "item": "widget", "qty": 3.0, "unit": "ea",
         "formula": "1+2", "tier": "single-source", "evidence": ["e1"], "notes": ""}
    ln = quantity_to_line(q)
    assert ln.review_required is False
    assert ln.description == "widget" and ln.quantity == 3.0
