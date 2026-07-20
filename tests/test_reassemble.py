"""
Tests for src/xray/reassemble.py — standalone (imports only xray.reassemble).

Run:  cd C:/repos/xray-by-looplet-engine
      set PYTHONPATH=src && python -m pytest tests/test_reassemble.py -x -q
(the sys.path shim below also lets it run without PYTHONPATH)
"""
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pypdfium2 as pdfium  # noqa: E402
from xray.reassemble import Word, extract_words, reassemble  # noqa: E402

WAREHOUSE = ROOT / "fixtures" / "warehouse-design21.pdf"
SHED = ROOT / "fixtures" / "shed-manners-aline.pdf"

# CONTEXT.md acceptance: these exist on warehouse sheet 04 (page index 3)
# only after reassembly. Counts verified by direct inspection 2026-07-21.
WAREHOUSE_TARGETS = {"29995": 1, "13530": 1, "2745": 5, "5010": 2, "6700": 2}

# Shed page 0 token counts verified by direct inspection 2026-07-21
# (3500 and 3000 genuinely appear twice each in the raw text layer).
SHED_TOKEN_COUNTS = {"6000": 1, "3500": 2, "3000": 2, "16000": 1}


def texts(words):
    return Counter(w.text for w in words)


def make(text, x0, y0, x1, y1, page=0, source="text"):
    return Word(text=text, x0=x0, y0=y0, x1=x1, y1=y1, page=page, source=source)


@pytest.fixture(scope="module")
def warehouse_p3():
    doc = pdfium.PdfDocument(str(WAREHOUSE))
    words = extract_words(doc, 3)  # 0-based: sheet 04
    doc.close()
    return words


@pytest.fixture(scope="module")
def shed_p0():
    doc = pdfium.PdfDocument(str(SHED))
    words = extract_words(doc, 0)
    doc.close()
    return words


# --- extract_words -----------------------------------------------------------

def test_extract_words_shape(warehouse_p3):
    assert len(warehouse_p3) == 1032  # empirical, sheet 04 (pypdfium2 tokenisation)
    for w in warehouse_p3:
        assert isinstance(w, Word)
        assert w.page == 3
        assert w.source == "text"
        assert w.text == w.text.strip() and w.text
        assert w.x1 >= w.x0 and w.y1 >= w.y0


def test_word_dataclass_fields():
    w = make("1500", 1.0, 2.0, 3.0, 4.0, page=7, source="reassembled")
    assert (w.text, w.x0, w.y0, w.x1, w.y1, w.page, w.source) == \
        ("1500", 1.0, 2.0, 3.0, 4.0, 7, "reassembled")


# --- acceptance: warehouse sheet 04 ------------------------------------------

def test_warehouse_targets_absent_before_reassemble(warehouse_p3):
    before = texts(warehouse_p3)
    for target in WAREHOUSE_TARGETS:
        assert before[target] == 0, f"{target} unexpectedly whole in raw layer"


def test_warehouse_targets_present_after_reassemble(warehouse_p3):
    out = reassemble(warehouse_p3)
    after = texts(out)
    for target, count in WAREHOUSE_TARGETS.items():
        assert after[target] == count, \
            f"{target}: expected {count}, got {after[target]}"
    # recovered tokens must be marked reassembled
    for w in out:
        if w.text in WAREHOUSE_TARGETS:
            assert w.source == "reassembled"


def test_warehouse_existing_chain_members_survive(warehouse_p3):
    """Whole words needed by chain checks must not be destroyed."""
    after = texts(reassemble(warehouse_p3))
    assert after["3579"] == 1
    assert after["2289"] == 1
    assert after["1200"] == 1
    assert after["90"] == 2
    assert after["16465"] >= 1


def test_warehouse_fragmented_dim_recovered(warehouse_p3):
    """A fragmented dimension absent from the raw text layer is recovered by
    reassembly on real fixture data, and the mechanism genuinely engages.

    (The original PyMuPDF-specific '150'+'0' -> '1500' instance tokenises
    differently under pypdfium2/PDFium; 13530 is the equivalent real recovery
    and it reconciles the 13530+16465=29995 chain on sheet 04.)"""
    before = texts(warehouse_p3)
    reassembled = reassemble(warehouse_p3)
    after = texts(reassembled)
    assert before["13530"] == 0
    assert after["13530"] == 1
    assert any(w.source == "reassembled" for w in reassembled)


# --- acceptance: shed page 0 is a near-passthrough ----------------------------

def test_shed_token_counts_before(shed_p0):
    before = texts(shed_p0)
    for token, count in SHED_TOKEN_COUNTS.items():
        assert before[token] == count


def test_shed_near_passthrough(shed_p0):
    out = reassemble(shed_p0)
    # token count change < 5% (empirically it is exactly 0)
    assert abs(len(out) - len(shed_p0)) / len(shed_p0) < 0.05
    after = texts(out)
    for token, count in SHED_TOKEN_COUNTS.items():
        assert after[token] == count
    # clean Skia print: no merges at all, everything passes through as text.
    # In particular the phone number "03 5452 2255" (real spaces at ~0.25em,
    # gap ratio 0.50 of char width) must NOT be merged.
    assert after == texts(shed_p0)
    assert all(w.source == "text" for w in out)


# --- synthetic: horizontal merge rules ----------------------------------------

def test_merge_adjacent_numeric_fragments():
    # per-char width 5, height 10, gap 1.0 (12.5% of em) -> one token
    a = make("29", 0.0, 0.0, 10.0, 10.0)
    b = make("995", 11.0, 0.0, 26.0, 10.0)
    out = reassemble([a, b])
    assert [w.text for w in out] == ["29995"]
    m = out[0]
    assert m.source == "reassembled"
    assert (m.x0, m.y0, m.x1, m.y1) == (0.0, 0.0, 26.0, 10.0)  # union bbox


def test_merge_chain_of_three_fragments():
    a = make("1", 0.0, 0.0, 5.0, 10.0)
    b = make("35", 5.5, 0.0, 15.5, 10.0)
    c = make("30", 16.0, 0.0, 26.0, 10.0)
    out = reassemble([a, b, c])
    assert [w.text for w in out] == ["13530"]


def test_no_merge_across_space_sized_gap():
    # gap 2.5 = 25% of em height: that's a rendered space (phone-number case)
    a = make("03", 0.0, 0.0, 10.0, 10.0)
    b = make("5452", 12.5, 0.0, 32.5, 10.0)
    out = reassemble([a, b])
    assert sorted(w.text for w in out) == ["03", "5452"]
    assert all(w.source == "text" for w in out)


def test_no_merge_on_nonnumeric_context_change():
    a = make("150", 0.0, 0.0, 15.0, 10.0)
    b = make("A0", 16.0, 0.0, 26.0, 10.0)   # alpha context: never merge
    c = make("DOOR", 0.0, 20.0, 20.0, 30.0)
    d = make("STOP", 20.5, 20.0, 40.5, 30.0)  # tight gap but alpha
    out = reassemble([a, b, c, d])
    assert sorted(w.text for w in out) == ["150", "A0", "DOOR", "STOP"]


def test_no_merge_across_gap_over_one_char_width():
    # char width 5, gap 6 > one char width -> keep apart
    a = make("12", 0.0, 0.0, 10.0, 10.0)
    b = make("415", 16.0, 0.0, 31.0, 10.0)
    out = reassemble([a, b])
    assert sorted(w.text for w in out) == ["12", "415"]


def test_no_merge_on_different_baselines():
    a = make("29", 0.0, 0.0, 10.0, 10.0)
    b = make("995", 11.0, 5.0, 26.0, 15.0)  # baseline 5pt lower
    out = reassemble([a, b])
    assert sorted(w.text for w in out) == ["29", "995"]


# --- synthetic: vertical (rotated text) merge ----------------------------------

def test_merge_vertical_rotated_fragments():
    # tall-narrow boxes stacked in one x-band, per-char height 6, gap 0.8
    a = make("13", 100.0, 0.0, 106.0, 12.0)
    b = make("530", 100.0, 12.8, 106.0, 30.8)
    out = reassemble([a, b])
    assert [w.text for w in out] == ["13530"]
    m = out[0]
    assert m.source == "reassembled"
    assert (m.x0, m.y0, m.x1, m.y1) == (100.0, 0.0, 106.0, 30.8)


def test_no_vertical_merge_for_horizontal_words():
    # wide (unrotated) words stacked on consecutive lines must not merge
    a = make("1200", 0.0, 0.0, 20.0, 10.0)
    b = make("3400", 0.0, 10.5, 20.0, 20.5)
    out = reassemble([a, b])
    assert sorted(w.text for w in out) == ["1200", "3400"]


def test_no_vertical_merge_across_xband_shift():
    a = make("13", 100.0, 0.0, 106.0, 12.0)
    b = make("530", 112.0, 12.8, 118.0, 30.8)  # different column
    out = reassemble([a, b])
    assert sorted(w.text for w in out) == ["13", "530"]


# --- synthetic: OCR junk-run splitting ------------------------------------------

def test_junk_run_yields_embedded_dimension():
    w = make("-+---2745---,~-", 0.0, 0.0, 150.0, 12.0)
    out = reassemble([w])
    assert [x.text for x in out] == ["2745"]
    t = out[0]
    assert t.source == "reassembled"
    # interpolated bbox stays inside the parent box, on the same baseline
    assert 0.0 <= t.x0 < t.x1 <= 150.0
    assert (t.y0, t.y1) == (0.0, 12.0)


def test_junk_run_multiple_tokens_keep_order():
    w = make("--6700-+---.l'---+6700----1----7947---#-", 0.0, 0.0, 400.0, 12.0)
    out = reassemble([w])
    # 3-6 digit runs extracted; 1-2 digit tick-mark noise dropped
    assert [x.text for x in out] == ["6700", "6700", "7947"]
    assert out[0].x1 <= out[1].x0 <= out[2].x0  # left-to-right positions


def test_hyphenated_real_tokens_not_split():
    ws = [
        make("900-1200MM", 0.0, 0.0, 50.0, 10.0),
        make("1560-11H", 0.0, 20.0, 40.0, 30.0),   # single dash: not junk
        make("17_07_19", 0.0, 40.0, 40.0, 50.0),
    ]
    out = reassemble(ws)
    assert sorted(w.text for w in out) == ["1560-11H", "17_07_19", "900-1200MM"]
    assert all(w.source == "text" for w in out)


def test_dash_run_without_dimension_passes_through():
    w = make("-----------", 0.0, 0.0, 60.0, 10.0)
    out = reassemble([w])
    assert [x.text for x in out] == ["-----------"]
    assert out[0].source == "text"


# --- general contract ------------------------------------------------------------

def test_empty_and_single_passthrough():
    assert reassemble([]) == []
    w = make("SCALE", 0.0, 0.0, 30.0, 10.0)
    out = reassemble([w])
    assert out == [w]
    assert out[0].source == "text"


def test_pages_are_isolated():
    # identical geometry on different pages must never merge across pages
    a = make("29", 0.0, 0.0, 10.0, 10.0, page=0)
    b = make("995", 11.0, 0.0, 26.0, 10.0, page=1)
    out = reassemble([a, b])
    assert sorted(w.text for w in out) == ["29", "995"]
