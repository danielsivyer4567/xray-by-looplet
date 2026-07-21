"""Tests for the source-adapter seam (xray.sources).

Guards the contract the CAD adapter will plug into: dispatch by format, pure
data out, no leaked document handle, and the two reserved slots staying empty
for PDF.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray.sources import ReadResult, adapters, find_adapter  # noqa: E402
from xray.sources.pdf import PdfAdapter  # noqa: E402

SHED = REPO / "fixtures" / "shed-manners-aline.pdf"


def test_pdf_adapter_is_registered():
    assert "pdf" in [a.name for a in adapters()]


def test_dispatch_picks_the_pdf_adapter():
    assert find_adapter(SHED).name == "pdf"
    assert find_adapter("PLAN.PDF").name == "pdf"  # case-insensitive


def test_unsupported_format_names_what_is_registered():
    with pytest.raises(ValueError) as e:
        find_adapter("plan.dxf")
    msg = str(e.value)
    assert "plan.dxf" in msg and "pdf" in msg


def test_read_returns_pure_data():
    r = find_adapter(SHED).read(SHED)
    assert isinstance(r, ReadResult)
    assert len(r.pages) == 5
    assert r.producer  # Skia/PDF (Chromium print)
    p1 = r.pages[0]
    assert p1.words and p1.raw_word_count == len(p1.words)  # shed: no glyph split
    assert p1.width_pt > 0 and p1.height_pt > 0
    assert p1.kind in ("vector", "raster", "sparse")


def test_reserved_slots_are_empty_for_pdf():
    """symbols/geometry exist so the CAD adapter can fill them later. A PDF
    text layer has neither; nothing downstream reads them yet."""
    r = find_adapter(SHED).read(SHED)
    assert r.symbols == []
    assert r.geometry == []


def test_read_leaks_no_open_document():
    """The adapter must drain and close its own document. If a handle escaped,
    the file would still be locked; on Windows an exclusive re-open proves it
    was released."""
    find_adapter(SHED).read(SHED)
    with open(SHED, "rb") as fh:      # would raise if pdfium still held it
        assert fh.read(5) == b"%PDF-"


def test_adapter_can_read_rejects_other_extensions():
    a = PdfAdapter()
    assert a.can_read("x.pdf") and not a.can_read("x.dxf") and not a.can_read("x")
