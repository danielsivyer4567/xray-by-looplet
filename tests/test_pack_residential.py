"""Tests for xray.packs_residential (ResidentialPack).

Synthetic units follow the local-stub convention from test_chains.py, plus a
real-fixture smoke on fixtures/residential-ruffles-seeka.pdf (the SEEKA
renovation set that motivated the pack — it used to yield 0 quantities).
Run:  PYTHONPATH=src python -m pytest tests/test_pack_residential.py -x -q
"""
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest

from xray.chains import Check
from xray.packs import PackContext
from xray.packs_residential import ResidentialPack

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "residential-ruffles-seeka.pdf")


@dataclass
class Entity:
    id: str
    page: int
    type: str
    value: object
    raw: str
    bbox: tuple = (0, 0, 10, 10)
    confidence: float = 1.0
    source: str = "text"


def ctx(entities=(), checks=()):
    return PackContext(entities=list(entities), checks=list(checks),
                       tables=[], pages=[])


def lbl(i, raw, page=1):
    return Entity(id=f"e{page}-{i}", page=page, type="LABEL", value=None, raw=raw)


def chain_check(cid, detail, evidence=(), status="pass", kind="cross-sheet"):
    return Check(id=cid, kind=kind, status=status, detail=detail,
                 evidence=list(evidence))


P = ResidentialPack()


# ---------------- detect ----------------

def test_detects_renovation_label():
    assert P.detect(ctx(entities=[lbl(0, "PROPOSED RENOVATION")]))


def test_detects_bedroom_vocab():
    assert P.detect(ctx(entities=[lbl(0, "BED 2"), lbl(1, "ENSUITE")]))


def test_standards_citation_never_detects():
    # the warehouse fixture cites "RESIDENTIAL SLABS AND FOOTINGS" (AS 2870) in
    # general notes — a standards line must not make a warehouse read as a house
    assert not P.detect(ctx(entities=[
        lbl(0, "RESIDENTIAL SLABS AND FOOTINGS"),
        lbl(1, "AS 2870 RESIDENTIAL"),
    ]))


def test_shed_spec_owns_the_document():
    spec = Entity(id="e1-9", page=1, type="SPEC",
                  value={"L": 16.0, "W": 9.0}, raw="16Lx9Wx4.2H|10o|4bays")
    assert not P.detect(ctx(entities=[spec, lbl(0, "PROPOSED RENOVATION")]))


# ---------------- envelope ----------------

def env_checks():
    return [
        chain_check("chk-cross-p4-1",
                    "230+4680+90+1100+90+2955+90+2955+250 = 12,440 matches overall "
                    "12,440 stated separately (H band, page 4)",
                    evidence=["e4-1", "e4-2"]),
        chain_check("chk-cross-p4-2",
                    "90+5000+90+5238+90 = 10,508 matches overall 10,508 stated "
                    "separately (V band, page 4)",
                    evidence=["e4-3"]),
    ]


def test_envelope_quantities():
    q, c = P.quantify(ctx(entities=[lbl(0, "PROPOSED RENOVATION")],
                          checks=env_checks()))
    gfa = next(x for x in q if x.id == "qty-res-gfa")
    per = next(x for x in q if x.id == "qty-res-ext-wall")
    assert gfa.unit == "m2" and gfa.qty == pytest.approx(12.440 * 10.508, abs=0.1)
    assert per.unit == "lm" and per.qty == pytest.approx(2 * (12.440 + 10.508), abs=0.1)
    assert gfa.tier == per.tier == "needs-human"       # envelope = assumption
    assert "e4-1" in gfa.evidence and "e4-3" in gfa.evidence
    assert not any(x.id == "chk-res-envelope" for x in c)


def test_no_envelope_flags_instead_of_inventing():
    # only a tiny V chain — nothing house-sized reconciles
    q, c = P.quantify(ctx(
        entities=[lbl(0, "PROPOSED RENOVATION")],
        checks=[chain_check("chk-cross-p2-1",
                            "1300+750 = 2,050 matches overall 2,050 stated "
                            "separately (V band, page 2)")]))
    assert not any(x.id.startswith("qty-res-gfa") for x in q)
    flag = next(x for x in c if x.id == "chk-res-envelope")
    assert flag.status == "flag"


def test_flagged_chains_never_feed_the_envelope():
    bad = chain_check("chk-chain-p4-1",
                      "6000+6440 = 12,440 vs stated 12,410 (H chain, page 4)",
                      status="flag", kind="chain-sum")
    q, _ = P.quantify(ctx(entities=[lbl(0, "PROPOSED RENOVATION")],
                          checks=[bad, env_checks()[1]]))
    assert not any(x.id == "qty-res-gfa" for x in q)


# ---------------- construction signature ----------------

def test_construction_census():
    _, c = P.quantify(ctx(entities=[lbl(0, "PROPOSED RENOVATION")],
                          checks=env_checks()))
    sig = next(x for x in c if x.id == "chk-res-construction")
    # H chain: 90x3 + 230 + 250 ; V chain: 90x3  -> 6 stud, 2 masonry
    assert "6 stud" in sig.detail and "2 masonry" in sig.detail
    walls = next(x for x in c if x.id == "chk-res-internal-walls")
    assert walls.status == "flag"


# ---------------- scope items ----------------

def test_scope_items_exclude_sheet_titles():
    q, _ = P.quantify(ctx(entities=[
        lbl(0, "PROPOSED RENOVATION"),
        lbl(1, "PROPOSED CARPORT EXTENSION"),
        lbl(2, "PROPOSED CARPORT EXTENSION", page=2),
        lbl(3, "PROPOSED GROUND FLOOR PLAN"),      # sheet title — excluded
        lbl(4, "PROPOSED FLOOR AREAS"),            # sheet title — excluded
    ]))
    items = {x.item for x in q if x.id.startswith("qty-res-scope")}
    assert "scope: proposed carport extension" in items
    assert not any("floor plan" in i or "floor areas" in i for i in items)
    carport = next(x for x in q if "carport" in x.item)
    assert carport.qty == 1 and carport.unit == "ea" and len(carport.evidence) == 2


# ---------------- real fixture ----------------

@pytest.mark.skipif(not os.path.exists(FIXTURE), reason="fixture missing")
def test_ruffles_end_to_end():
    from xray.engine import run
    result = run(FIXTURE)
    quants = result["quantities"]
    trades = {q["trade"] for q in quants}
    assert "residential" in trades                       # pack fired
    items = {q["item"] for q in quants}
    assert "scope: proposed carport extension" in items  # real scope found
    assert not any("floor plan" in i for i in items)     # titles filtered
    # honesty: envelope did not reconcile on this set -> flagged, not invented
    ids = {c["id"] for c in result["checks"]}
    assert "chk-res-envelope" in ids
    assert "chk-res-construction" in ids
    # pack-coverage flag must be GONE now that a pack recognised the drawing
    assert not any(c["kind"] == "pack-coverage" for c in result["checks"])
