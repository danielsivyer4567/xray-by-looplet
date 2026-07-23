"""OCR stage — render, recognise (pluggable backend), convert to pipeline Words.

The recognition backend is not shipped, so these tests prove the parts that are
this module's responsibility: rendering a page, converting a backend's pixel
boxes into PDF-point Words tagged source="ocr", the stub round-trip, and that the
Tesseract backend refuses clearly when the engine isn't installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytest.importorskip("PIL", reason="Pillow needed to render pages")

from xray.ocr import (   # noqa: E402
    OcrWord, StubBackend, TesseractBackend, available_backend,
    render_page, ocr_words, recognize_page,
)

SHED = REPO / "fixtures" / "shed-manners-aline.pdf"


# ------------------------------------------------------------------- render

def test_render_page_produces_an_image_at_the_right_scale():
    img, scale = render_page(SHED, 0, dpi=144)
    assert scale == 2.0                      # 144 / 72
    assert img.width > 200 and img.height > 200


# ----------------------------------------------------- box -> point conversion

def test_boxes_convert_to_points_and_tag_source_ocr():
    words = ocr_words([OcrWord("16000", 100.0, 100.0, 260.0, 140.0, 0.98)],
                      page_index=3, scale=2.0)
    assert len(words) == 1
    w = words[0]
    assert w.text == "16000" and w.source == "ocr" and w.page == 3
    # point = pixel / scale
    assert (w.x0, w.y0, w.x1, w.y1) == (50.0, 50.0, 130.0, 70.0)


def test_blank_recognitions_are_dropped():
    assert ocr_words([OcrWord("   ", 0, 0, 10, 10)], 0, 1.0) == []


# --------------------------------------------------------- stub round-trip

def test_stub_backend_round_trips_through_the_stage():
    words = recognize_page(SHED, StubBackend(), page_index=0, dpi=144)  # scale 2
    assert {w.text for w in words} == {"16000", "9000"}
    assert all(w.source == "ocr" for w in words)
    # the "16000" box (px 100..260) maps to 50..130 pt at scale 2
    w = next(w for w in words if w.text == "16000")
    assert (w.x0, w.x1) == (50.0, 130.0)


def test_stub_is_deterministic():
    a = StubBackend().recognize(None)
    b = StubBackend().recognize(None)
    assert a == b


# --------------------------------------------------- backend availability

def test_tesseract_backend_errors_clearly_when_absent():
    try:
        import pytesseract  # noqa: F401
        pytest.skip("pytesseract is installed; the absent path can't be tested")
    except ImportError:
        pass
    with pytest.raises(RuntimeError) as ei:
        TesseractBackend()
    assert "pytesseract" in str(ei.value)


def test_available_backend_reflects_the_environment():
    try:
        import pytesseract  # noqa: F401
        assert available_backend() is not None
    except ImportError:
        assert available_backend() is None
