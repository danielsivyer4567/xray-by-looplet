"""Tests for xray.grammar + xray.scale.

Standalone by design: no imports of sibling modules under construction
(reassemble/chains/quantify). Real-page tests use fitz raw words directly;
unit tests use a local Word-alike dataclass.

Run:  PYTHONPATH=src python -m pytest tests/test_grammar.py -x -q
(cwd = repo root; a sys.path shim below makes it work either way)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from xray import grammar, scale  # noqa: E402
from xray.grammar import classify, parse_spec_token, normalize_tag  # noqa: E402
from xray.scale import vote_scale  # noqa: E402
from xray.reassemble import extract_words  # noqa: E402

SHED_PDF = REPO / "fixtures" / "shed-manners-aline.pdf"


@dataclass
class FakeWord:
    """Mirrors reassemble.Word's fields without importing it."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int = 0
    source: str = "text"


def _word(text, x0=100.0, y0=100.0, w=30.0, h=8.0, page=0, source="text"):
    return FakeWord(text, x0, y0, x0 + w, y0 + h, page, source)


@pytest.fixture(scope="module")
def shed_page0():
    doc = pdfium.PdfDocument(str(SHED_PDF))
    words = extract_words(doc, 0)  # 0-based: sheet 1 (raw text-layer words)
    w, h = doc[0].get_size()
    rect = (w, h)
    ents = classify(words, rect)
    yield ents, rect
    doc.close()


# ------------------------------------------------------------------ SPEC

def test_spec_token_found_and_parsed_on_shed_page0(shed_page0):
    ents, _ = shed_page0
    specs = [e for e in ents if e.type == "SPEC"]
    assert specs, "SPEC entity not found on shed page 0"
    assert specs[0].value == {"L": 16.0, "W": 9.0, "eave": 4.2, "pitch": 10.0, "bays": 4}
    # title-block token arrives with a 'Shed.' prefix in this fixture
    assert "bays" in specs[0].raw


def test_parse_spec_token_degree_variants():
    expected = {"L": 16.0, "W": 9.0, "eave": 4.2, "pitch": 10.0, "bays": 4}
    assert parse_spec_token("16Lx9Wx4.2H|10°|4bays") == expected  # °
    assert parse_spec_token("16Lx9Wx4.2H|10o|4bays") == expected       # letter o
    assert parse_spec_token("Shed.16Lx9Wx4.2H|10°|4bays") == expected  # embedded
    assert parse_spec_token("no spec here") is None
    assert parse_spec_token("16Lx9W") is None  # partial must not parse


# ------------------------------------------------------------------ DIM

def test_dims_on_shed_page0(shed_page0):
    ents, _ = shed_page0
    dims = [e for e in ents if e.type == "DIM"]
    assert len(dims) >= 15, f"expected >=15 DIM entities, got {len(dims)}"
    values = {e.value for e in dims}
    for must in (6000, 3500, 3000, 16000):
        assert must in values, f"DIM {must} missing from shed page 0"
    # all plausibility-bounded, ints, mm
    assert all(isinstance(v, int) and 40 <= v <= 99999 for v in values)


def test_dim_comma_strip_and_plausibility():
    ents = classify([_word("16,465"), _word("39", x0=200), _word("100000", x0=300),
                     _word("450", x0=400)], (842.0, 595.0))
    dims = {e.value for e in ents if e.type == "DIM"}
    assert dims == {16465, 450}  # 39 below floor, 100000 above ceiling


# ------------------------------------------------------------------ TAG

def test_tag_normalization_w0l_to_w01():
    assert normalize_tag("W0l") == "W01"
    ents = classify([_word("W0l")], (842.0, 595.0))
    tags = [e for e in ents if e.type == "TAG"]
    assert len(tags) == 1
    assert tags[0].value == "W01"
    assert tags[0].raw == "W0l"


def test_tag_variants_and_rejections():
    assert normalize_tag("D04") == "D04"
    assert normalize_tag("WT02") == "WT02"
    assert normalize_tag("DP1") == "DP1"
    assert normalize_tag("PF3") == "PF3"
    assert normalize_tag("WD-12") == "WD12"
    assert normalize_tag("W1O") == "W10"       # trailing capital O in tail -> 0
    assert normalize_tag("DOOR") is None       # no digit in tail: not a tag
    assert normalize_tag("Do") is None
    assert normalize_tag("W") is None
    assert normalize_tag("16000") is None


# ------------------------------------------------------------------ ids / confidence / sources

def test_entity_ids_and_confidence():
    ents = classify([_word("6000"), _word("3500", x0=200),
                     _word("1:100", x0=300, source="reassembled")], (842.0, 595.0))
    assert [e.id for e in ents] == ["e0-0", "e0-1", "e0-2"]
    assert ents[0].confidence == 1.0
    assert ents[2].confidence == 0.9
    assert ents[2].source == "reassembled"
    assert ents[2].type == "SCALE" and ents[2].value == "1:100"


def test_classify_accepts_word_objects_and_fitz_tuples():
    tup = (100.0, 100.0, 130.0, 108.0, "6000", 0, 0, 0)
    obj = _word("6000")
    e_tup = classify([tup], (842.0, 595.0))
    e_obj = classify([obj], (842.0, 595.0))
    assert e_tup[0].type == e_obj[0].type == "DIM"
    assert e_tup[0].value == e_obj[0].value == 6000


# ------------------------------------------------------------------ LABEL / LEVEL / STD / NOTEKEY

def test_portal_rafter_labels_on_shed_page0(shed_page0):
    ents, _ = shed_page0
    labels = [e for e in ents if e.type == "LABEL"]
    portal = [e for e in labels if "PORTAL RAFTER" in e.value]
    assert len(portal) == 5, f"expected 5 PORTAL RAFTER labels, got {len(portal)}"


def test_level_std_notekey():
    ents = classify([
        _word("RL", x0=100, w=12), _word("12.500", x0=115),
        _word("FFL100.000", x0=300),
        _word("AS/NZS", x0=100, y0=200, w=30), _word("4600", x0=133, y0=200),
        _word("AS1684.2", x0=300, y0=200),
        _word("MIN.", x0=100, y0=300), _word("CH", x0=200, y0=300),
    ], (842.0, 595.0))
    by_type = {}
    for e in ents:
        by_type.setdefault(e.type, []).append(e)
    levels = by_type.get("LEVEL", [])
    assert {(l.value["kind"], l.value["value"]) for l in levels} == {
        ("RL", 12.5), ("FFL", 100.0)}
    stds = by_type.get("STD", [])
    assert len(stds) == 2
    notekeys = {e.value for e in by_type.get("NOTEKEY", [])}
    assert notekeys == {"MIN", "CH"}
    # the paired "4600" must NOT also appear as a DIM
    assert 4600 not in {e.value for e in by_type.get("DIM", [])}


# ------------------------------------------------------------------ scale voting

def test_vote_scale_shed_page0_is_1_to_100(shed_page0):
    ents, rect = shed_page0
    result = vote_scale(ents, rect, None)
    assert result["value"] == "1:100"
    assert result["mmPerPt"] == pytest.approx(25.4 / 72.0 * 100, rel=1e-9)
    assert 0.0 < result["confidence"] <= 1.0
    assert "onpage-scale" in result["methods"]


def test_vote_scale_declared_and_titleblock_weighting():
    # declared alone
    r = vote_scale([], (1684.0, 1191.0), "SCALE @A2 1:100")
    assert r["value"] == "1:100" and "declared" in r["methods"]
    assert r["mmPerPt"] == pytest.approx(35.2777, rel=1e-4)

    # a title-block SCALE token (weight 2) beats two stray on-page tokens (1+1)... tie
    # broken deterministically; make title-block strictly heavier: 2.0 vs 1.0
    W, H = 1684.0, 1191.0

    class E:
        def __init__(self, ratio, x0, y0):
            self.type = "SCALE"
            self.raw = f"1:{ratio}"
            self.value = self.raw
            self.bbox = (x0, y0, x0 + 30, y0 + 8)

    tb = E(50, W * 0.9, H * 0.95)     # title-block: 1:50
    stray = E(200, W * 0.2, H * 0.3)  # mid-page: 1:200
    r = vote_scale([tb, stray], (W, H), None)
    assert r["value"] == "1:50"
    assert "titleblock-scale" in r["methods"]


def test_vote_scale_no_evidence():
    # page size not A-series, nothing declared, no entities
    r = vote_scale([], (500.0, 500.0), None)
    assert r["value"] is None
    assert r["mmPerPt"] is None
    assert r["confidence"] == 0.0
    assert r["methods"] == []
