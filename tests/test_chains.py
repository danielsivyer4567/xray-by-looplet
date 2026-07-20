"""Standalone tests for xray.chains + xray.quantify.

Does NOT import grammar (built in parallel) — uses a local Entity stub whose
shape matches CONTEXT.md exactly. Run:
    PYTHONPATH=src python -m pytest tests/test_chains.py -x -q
"""
import math
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest

from xray.chains import Check, find_chain_checks, titleblock_mask, trig_check
from xray.quantify import Quantity, shed_pack


# --- local Entity stub (shape per CONTEXT.md grammar.Entity) -----------------
@dataclass
class Entity:
    id: str
    page: int
    type: str            # DIM|TAG|SCALE|SPEC|LABEL|LEVEL|STD|NOTEKEY
    value: object
    raw: str
    bbox: tuple
    confidence: float = 0.9
    source: str = "text"


PAGE = (1190.55, 841.89)  # A3 landscape, pts
SPEC = {"L": 16.0, "W": 9.0, "eave": 4.2, "pitch": 10.0, "bays": 4}

_n = [0]


def dim(value, x, y, page=1, w=40.0, h=10.0):
    _n[0] += 1
    return Entity(id=f"e{_n[0]}", page=page, type="DIM", value=value,
                  raw=str(value), bbox=(x, y, x + w, y + h))


def ent(etype, raw, x, y, page=1, value=None, w=40.0, h=10.0):
    _n[0] += 1
    return Entity(id=f"e{_n[0]}", page=page, type=etype, value=value,
                  raw=raw, bbox=(x, y, x + w, y + h))


# --- titleblock mask ----------------------------------------------------------

def test_titleblock_mask_is_bottom_22_percent():
    x0, y0, x1, y1 = titleblock_mask(PAGE)
    assert x0 == 0.0 and x1 == pytest.approx(1190.55)
    assert y0 == pytest.approx(841.89 * 0.78)
    assert y1 == pytest.approx(841.89)


# --- chain sums -----------------------------------------------------------------

def test_shed_chain_passes():
    # 6000+3500+3500+3000 = 16000, all on one horizontal dimension line
    ents = [
        dim(6000, 100, 300), dim(3500, 200, 300), dim(3500, 300, 300),
        dim(3000, 400, 300), dim(16000, 500, 302),
    ]
    checks = find_chain_checks(ents, PAGE)
    assert len(checks) == 1
    c = checks[0]
    assert c.kind == "chain-sum" and c.status == "pass"
    assert "16000" in c.detail
    assert set(c.evidence) == {e.id for e in ents}


def test_dims_inside_titleblock_band_are_ignored():
    # same chain but sitting in the bottom 22% band -> masked out entirely
    y = 841.89 * 0.85
    ents = [
        dim(6000, 100, y), dim(3500, 200, y), dim(3500, 300, y),
        dim(3000, 400, y), dim(16000, 500, y),
    ]
    assert find_chain_checks(ents, PAGE) == []


def test_vertical_band_cross_matches_overall_stated_elsewhere():
    # vertical chain (shared x, ordered by y) sums to 16000; the overall is
    # stated separately elsewhere on the page -> cross-sheet pass
    parts = [200, 5775, 350, 2850, 650, 2850, 3325]
    ents = [dim(v, 100, 150 + i * 50) for i, v in enumerate(parts)]
    overall = dim(16000, 600, 100)
    checks = find_chain_checks(ents + [overall], PAGE)
    assert len(checks) == 1
    c = checks[0]
    assert c.kind == "cross-sheet" and c.status == "pass"
    assert set(c.evidence) == {e.id for e in ents} | {overall.id}


# --- near-miss flag ----------------------------------------------------------------

def test_near_miss_panel_chain_flags_with_delta_2():
    # warehouse concrete-panel chain: 2745*5 + 2742 = 16467 vs stated 16465
    parts = [2745, 2745, 2745, 2745, 2745, 2742]
    ents = [dim(v, 100 + i * 60, 400) for i, v in enumerate(parts)]
    ents.append(dim(16465, 100 + 6 * 60, 400))
    checks = find_chain_checks(ents, PAGE)
    assert len(checks) == 1
    c = checks[0]
    assert c.kind == "chain-sum" and c.status == "flag"
    assert c.delta == 2
    assert "16465" in c.detail


# --- false-positive guards -----------------------------------------------------------

def test_phone_number_band_with_P_neighbor_is_masked():
    # a band that WOULD pass as a chain (1500+2500 = 4000), but a "P:" label
    # sits within 30pt -> phone number furniture, must be dropped
    band = [dim(1500, 100, 300), dim(2500, 200, 300), dim(4000, 300, 300)]
    phone_label = ent("LABEL", "P:", 70, 300)  # 20pt gap to first token
    assert find_chain_checks(band + [phone_label], PAGE) == []
    # control: identical band without the neighbor DOES produce a pass
    ctrl = [dim(1500, 100, 300), dim(2500, 200, 300), dim(4000, 300, 300)]
    checks = find_chain_checks(ctrl, PAGE)
    assert len(checks) == 1 and checks[0].status == "pass"


def test_copyright_neighbor_masks_band():
    band = [dim(1500, 100, 300), dim(2500, 200, 300), dim(4000, 300, 300)]
    note = ent("LABEL", "Copyright 2019", 340, 302)
    assert find_chain_checks(band + [note], PAGE) == []


def test_state_plus_postcode_neighbor_masks_band():
    # VIC + 4-digit-token pattern near a band of 4-digit dims -> address line
    band = [dim(1000, 100, 300), dim(3000, 200, 300), dim(4000, 300, 300)]
    state = ent("LABEL", "VIC", 345, 300)
    assert find_chain_checks(band + [state], PAGE) == []


# --- trig check --------------------------------------------------------------------

def test_trig_check_finds_793_rise():
    rise = math.tan(math.radians(10.0)) * 4.5 * 1000.0  # 793.38 mm
    ents = [dim(793, 500, 200), dim(4570, 560, 200, w=30)]
    c = trig_check(SPEC, ents)
    assert c is not None
    assert c.kind == "trig" and c.status == "pass"
    assert c.evidence == [ents[0].id]
    assert abs(c.delta - (793 - rise)) < 0.01


def test_trig_check_none_when_no_matching_dim():
    ents = [dim(780, 500, 200), dim(4570, 560, 200)]
    assert trig_check(SPEC, ents) is None


# --- shed quantity pack -----------------------------------------------------------

def _shed_inputs(with_count_check=True):
    spec_ent = ent("SPEC", "16Lx9Wx4.2H|10°|4bays", 900, 100,
                   value={"L": 16.0, "W": 9.0, "eave": 4.2, "pitch": 10.0, "bays": 4})
    tags = [
        ent("TAG", "D0-1", 150, 500, value="D0-1"),
        ent("TAG", "D2", 250, 500, value="D2"),
        ent("TAG", "D3", 350, 500, value="D3"),
    ]
    open_lbl = ent("LABEL", "OPEN", 120, 450)
    checks = []
    if with_count_check:
        checks.append(Check(id="chk-count-1", kind="count", status="pass",
                            detail="PORTAL RAFTER label appears 5x = 5 frames",
                            delta=None, evidence=[]))
    return [spec_ent] + tags + [open_lbl], checks


def _by_id(qtys, qid):
    m = {q.id: q for q in qtys}
    assert qid in m, f"{qid} missing from {sorted(m)}"
    return m[qid]


def test_shed_pack_core_quantities():
    entities, checks = _shed_inputs()
    qtys = shed_pack(SPEC, entities, checks)

    frames = _by_id(qtys, "qty-frames")
    assert frames.qty == 5 and frames.unit == "ea"
    assert frames.tier == "reconciled"  # count check confirms bays+1

    portal = _by_id(qtys, "qty-portal-steel")
    assert portal.unit == "lm"
    assert abs(portal.qty - 87.7) <= 0.5
    assert "cos" in portal.formula  # human-readable formula

    roof = _by_id(qtys, "qty-roof-sheeting")
    assert roof.unit == "m2"
    assert abs(roof.qty - 146.2) <= 0.5


def test_shed_pack_openings_and_cladding():
    entities, checks = _shed_inputs()
    qtys = shed_pack(SPEC, entities, checks)

    openings = [q for q in qtys if q.trade == "openings"]
    assert len(openings) == 3
    assert all(q.unit == "ea" and q.qty == 1 and q.tier == "single-source"
               for q in openings)

    clad = _by_id(qtys, "qty-wall-cladding")
    assert clad.tier == "needs-human"
    assert "OPEN" in clad.notes.upper()


def test_shed_pack_frames_single_source_without_count_check():
    entities, checks = _shed_inputs(with_count_check=False)
    qtys = shed_pack(SPEC, entities, checks)
    frames = _by_id(qtys, "qty-frames")
    assert frames.qty == 5 and frames.tier == "single-source"


def test_quantities_rounded_to_one_decimal():
    entities, checks = _shed_inputs()
    for q in shed_pack(SPEC, entities, checks):
        assert q.qty == round(q.qty, 1)
