"""Tests for the coverage/confidence report (engine.run -> document.coverage).

Coverage is a diagnostic, not a gate: it reports how much of a page's readable
text turned into structured output (entities + table cells) and flags text-heavy
pages that fell below COVERAGE_MIN. It must never drop a quantity or change a
tier — only surface "here's the bit I couldn't parse".

Run:  python -m pytest tests/test_coverage.py -x -q   (cwd = repo root)
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray import engine  # noqa: E402

SHED = REPO / "fixtures" / "shed-manners-aline.pdf"
ELEC = REPO / "fixtures" / "electrical-schedule.pdf"


def test_every_page_has_coverage_block():
    result = engine.run(str(SHED))
    for pm in result["document"]["pages"]:
        cov = pm["coverage"]
        assert set(cov) >= {"words", "entities", "tableCells", "structuredRatio"}
        assert cov["words"] >= 0
        assert cov["entities"] >= 0
        assert cov["tableCells"] >= 0
        assert 0.0 <= cov["structuredRatio"] <= 1.0


def test_document_coverage_summary_present():
    result = engine.run(str(SHED))
    cov = result["document"]["coverage"]
    assert 0.0 <= cov["overallRatio"] <= 1.0
    assert isinstance(cov["lowPages"], list)
    assert all(isinstance(n, int) for n in cov["lowPages"])


def test_overall_ratio_matches_page_totals():
    result = engine.run(str(SHED))
    pages = result["document"]["pages"]
    tot_words = sum(pm["coverage"]["words"] for pm in pages)
    tot_struct = sum(pm["coverage"]["entities"] + pm["coverage"]["tableCells"]
                     for pm in pages)
    expected = round(min(1.0, tot_struct / max(1, tot_words)), 3)
    assert result["document"]["coverage"]["overallRatio"] == expected


def test_low_pages_only_lists_text_heavy_pages():
    """A page can only be 'low' if it has real text (>= SPARSE_WORD_COUNT).
    Sparse/blank pages are not coverage failures — nothing to read there."""
    result = engine.run(str(SHED))
    low = set(result["document"]["coverage"]["lowPages"])
    for pm in result["document"]["pages"]:
        if pm["coverage"]["words"] < engine.SPARSE_WORD_COUNT:
            assert pm["n"] not in low
        if pm["n"] in low:
            assert pm["coverage"]["structuredRatio"] < engine.COVERAGE_MIN


def test_schedule_page_has_table_cells():
    """The electrical schedule is a table -> its cells should be counted,
    proving tableCells feeds coverage (not just entities)."""
    result = engine.run(str(ELEC))
    assert sum(pm["coverage"]["tableCells"]
               for pm in result["document"]["pages"]) > 0


def test_coverage_does_not_alter_quantities():
    """Coverage is a report only: the shed's quantity count is unchanged."""
    result = engine.run(str(SHED))
    # shed pack: 8 core + 5 hardening accessories = 13 (see test_quote_lines)
    assert len(result["quantities"]) == 13
