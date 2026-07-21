"""Symbols reach takeoff.json: block counts as real quantities, per-placement
handle-chain ids, parent chains, and the override dimension flagged to review.

Gate numbers are RE-DERIVED from fixtures/cad/architectural_test_fixtures_v2.dxf
with ezdxf (never taken from prose): 3 assemblies / 6 brackets / 25 bolts
(24 nested + 1 free-standing) / 2 dimensions, both measuring 500, one claiming
650.0 mm (FIELD VERIFY).
"""
import json

import pytest

ezdxf = pytest.importorskip("ezdxf")

from xray import engine

FIX = "fixtures/cad/architectural_test_fixtures_v2.dxf"
PDF = "fixtures/electrical-schedule.pdf"


@pytest.fixture(scope="module")
def result():
    return engine.run(FIX)


def _q(result, item):
    return next(q for q in result["quantities"] if q["item"] == item)


def test_block_counts_are_real_quantities(result):
    """The recursive totals land in quantities[] as reconciled ea rows."""
    assert _q(result, "BOLT_M16")["qty"] == 25.0
    assert _q(result, "STRUCTURAL_BRACKET")["qty"] == 6.0
    assert _q(result, "ASSEMBLY_GIRDER_JOINT")["qty"] == 3.0
    assert _q(result, "*U1")["qty"] == 3.0
    q = _q(result, "BOLT_M16")
    assert q["unit"] == "ea"
    assert q["tier"] == "reconciled"
    assert q["formula"] == "count(INSERT BOLT_M16, recursive)"
    # evidence lists EVERY counted placement, so 25 is re-derivable
    assert len(q["evidence"]) == 25
    assert len(set(q["evidence"])) == 25


def test_attrib_override_stays_auditable(result):
    """The instance override (GRADE 10.9 / TORQUE 290) is never dropped."""
    notes = _q(result, "BOLT_M16")["notes"]
    assert "GRADE=10.9" in notes
    assert "TORQUE_NM=290" in notes


def test_ids_unique_and_parent_chains_resolve(result):
    """Handle-chain ids: unique per placement, parentId = chain minus last."""
    syms = result["symbols"]
    ids = [s["id"] for s in syms]
    assert len(ids) == len(set(ids))            # unique per placement
    by_id = {s["id"]: s for s in syms}
    bolts = [s for s in syms if s["blockName"] == "BOLT_M16"]
    assert len(bolts) == 25
    free = [s for s in bolts if s["parentId"] is None]
    assert len(free) == 1                       # the free-standing bolt
    assert "/" not in free[0]["id"]             # root placement: single handle
    for s in syms:
        if s["parentId"] is not None:
            assert s["parentId"] in by_id       # every parent resolves
            assert s["id"].startswith(s["parentId"] + "/")


def test_units_resolved_not_echoed(result):
    """$INSUNITS lies (metres); the M16 bolt geometry says mm."""
    units = result["document"]["units"]
    assert units["declared"] == "m"
    assert units["resolved"] == "mm"
    assert units["mismatch"] is True


def test_override_dimension_reaches_review(result):
    """Both dims survive; the conflicting one is flagged carrying BOTH values."""
    dims = [g for g in result["geometry"] if g["kind"] == "dimension"]
    assert len(dims) == 2                       # dropping one is the failure
    bad = [g for g in dims if g["conflict"]]
    assert len(bad) == 1
    assert bad[0]["value"] == 500.0
    assert bad[0]["text_value"] == 650.0
    flags = [c for c in result["checks"] if c["kind"] == "dim-override"]
    assert len(flags) == 1
    assert flags[0]["status"] == "flag"
    assert flags[0]["delta"] == 150.0
    # a flagged check lands in review[] — the field-verify trap reaches a human
    assert any(r["ref"] == flags[0]["id"] for r in result["review"])


def test_deterministic_across_runs(result):
    assert json.dumps(result, sort_keys=True) == json.dumps(
        engine.run(FIX), sort_keys=True)


def test_pdf_output_untouched():
    """A PDF read yields no symbols/geometry/units keys at all."""
    r = engine.run(PDF)
    assert "symbols" not in r
    assert "geometry" not in r
    assert "units" not in r["document"]
