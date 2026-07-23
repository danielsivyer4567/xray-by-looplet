"""OCR wired into engine.run — as an OPT-IN path that never disturbs the default.

The byte-identity gate depends on OCR being off unless asked for, and on it never
touching a page that already has a text layer. These tests pin both, plus the
fail-fast when OCR is requested with no engine installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray.engine import run                       # noqa: E402
from xray.ocr import StubBackend, OcrWord         # noqa: E402

SHED = REPO / "fixtures" / "shed-manners-aline.pdf"

STUB = StubBackend([
    OcrWord("16000", 100.0, 100.0, 260.0, 140.0, 0.98),
    OcrWord("9000", 100.0, 200.0, 220.0, 240.0, 0.97),
])


def _sparse_pdf(path):
    """A 1-page PDF with only a couple of words -> classified 'sparse', so the
    OCR path fires on it."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=(400, 400))
    c.setFont("Helvetica", 12)
    c.drawString(50, 300, "SITE")
    c.drawString(50, 280, "PLAN")
    c.save()
    return path


def test_default_run_does_no_ocr():
    """No ocr argument -> not a single source='ocr' entity, so output is exactly
    what it was before OCR existed (parity safe)."""
    r = run(str(SHED))
    assert not [e for e in r["entities"] if e["source"] == "ocr"]


def test_ocr_true_without_an_engine_fails_clearly():
    with pytest.raises(RuntimeError) as ei:
        run(str(SHED), ocr=True)
    assert "no engine is installed" in str(ei.value)


def test_ocr_does_not_touch_a_vector_page():
    """Even with a backend supplied, a page that already has a text layer is
    skipped — OCR only runs where there's nothing else to read."""
    r = run(str(SHED), ocr=STUB)
    assert not [e for e in r["entities"] if e["source"] == "ocr"]


def test_ocr_recovers_text_on_a_sparse_page(tmp_path):
    pytest.importorskip("reportlab")
    pdf = _sparse_pdf(tmp_path / "sparse.pdf")
    r = run(str(pdf), ocr=STUB)
    assert r["document"]["pages"][0]["kind"] == "sparse"
    ocr_e = [e for e in r["entities"] if e["source"] == "ocr"]
    raws = {str(e["raw"]) for e in ocr_e}
    assert "16000" in raws and "9000" in raws


def test_sparse_page_without_ocr_stays_empty(tmp_path):
    pytest.importorskip("reportlab")
    pdf = _sparse_pdf(tmp_path / "sparse.pdf")
    r = run(str(pdf))                              # no ocr -> nothing recovered
    assert not [e for e in r["entities"] if e["source"] == "ocr"]
