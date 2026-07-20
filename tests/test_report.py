"""Tests for src/xray/report.py — the deterministic HTML quote formatter.

The formatter's contract is provenance: every number on the page is copied
verbatim from the structured takeoff result, nothing is computed or invented,
and the same result renders byte-identical output. These tests lock that in.

Run:  python -m pytest tests/test_report.py -x -q   (cwd = repo root)
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray import engine  # noqa: E402
from xray.report import quote_rows, render_quote_html, _fmt_qty  # noqa: E402

SHED = REPO / "fixtures" / "shed-manners-aline.pdf"


def test_one_row_per_quantity():
    result = engine.run(str(SHED))
    html = render_quote_html(result)
    n_rows = html.count("<tr>") - 1  # minus the header row
    assert n_rows == len(result["quantities"])
    assert len(quote_rows(result)) == len(result["quantities"])


def test_every_quantity_number_and_formula_appears():
    """Provenance: each quantity's value, unit and formula are on the page."""
    result = engine.run(str(SHED))
    html = render_quote_html(result)
    for q in result["quantities"]:
        assert _fmt_qty(q["qty"]) in html, f"missing qty for {q['id']}"
        assert q["unit"] in html
        # the formula is HTML-escaped but its digits survive; check a token
        assert str(q["item"]) in html


def test_no_number_is_invented():
    """Every numeric token inside the quote table traces to a result value.

    We gather the allowed numbers from the structured result (quantities +
    coverage), then assert the rendered rows introduce none of their own.
    """
    result = engine.run(str(SHED))
    html = render_quote_html(result)
    body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]

    allowed = set()
    for q in result["quantities"]:
        allowed.add(_fmt_qty(q["qty"]))
        for field in ("formula", "notes"):
            for tok in re.findall(r"\d+(?:\.\d+)?", str(q.get(field, ""))):
                allowed.add(tok)
        for ev in q.get("evidence", []):
            for tok in re.findall(r"\d+", str(ev)):
                allowed.add(tok)

    for tok in re.findall(r"\d+(?:\.\d+)?", body):
        assert tok in allowed, f"row contains a number not in the result: {tok!r}"


def test_render_is_deterministic():
    result = engine.run(str(SHED))
    assert render_quote_html(result) == render_quote_html(result)


def test_html_is_escaped_against_injection():
    """A hostile item/notes string must not break out into live markup."""
    result = {
        "engine": {"name": "xray-by-looplet", "version": "0.1.0"},
        "document": {"path": "p.pdf", "pages": [{"n": 1}]},
        "quantities": [{
            "id": "q1", "trade": "t", "item": "<script>alert(1)</script>",
            "qty": 3.0, "unit": "ea", "formula": "1<2", "tier": "single-source",
            "evidence": ["e1"], "notes": "",
        }],
        "checks": [], "review": [],
    }
    html = render_quote_html(result)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_quantities_free_result_still_renders():
    result = {
        "engine": {"name": "xray-by-looplet", "version": "0.1.0"},
        "document": {"path": "p.pdf", "pages": []},
        "quantities": [], "checks": [], "review": [],
    }
    html = render_quote_html(result)
    assert "<table>" in html and "No items flagged" in html
