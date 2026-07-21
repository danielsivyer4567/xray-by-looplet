"""pdf.py — the PDF source adapter (pypdfium2).

Holds everything that knows a plan is a PDF: the pdfium document lifecycle, the
text-layer extraction, page geometry, the vector/raster/sparse classification,
and the Producer string. Moved here verbatim from engine.run() — behaviour is
unchanged.

The document is fully drained into a ReadResult and closed before `read()`
returns, so no live pdfium handle ever escapes this module.
"""
from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from xray.reassemble import extract_words, reassemble
from xray.sources.base import (
    SPARSE_WORD_COUNT, PageRead, ReadResult, SourceAdapter, register,
)

# a page whose largest placed image covers >= this fraction of the page area
# is a scanned sheet (raster), regardless of any invisible OCR text layer
RASTER_COVER_FRACTION = 0.5
# fallback for scans whose placement rects are unreliable: an embedded bitmap
# of at least this many pixels on a page with only OCR-level text marks it
# raster (warehouse scans: 9-29 words; doc pages with photos: 170+ words)
RASTER_MIN_PIXELS = 300_000
RASTER_MAX_WORDS = 50


def _page_kind(page, n_words: int) -> str:
    """vector | raster | sparse (see CONTEXT.md; Paper Capture scans keep an
    invisible OCR text layer, so image coverage decides raster, not words)."""
    w, h = page.get_size()
    page_area = (w * h) or 1.0
    max_cover = 0.0
    max_px = 0
    try:
        for obj in page.get_objects(max_depth=8):
            if obj.type != pdfium_c.FPDF_PAGEOBJ_IMAGE:
                continue
            # placed coverage on the page (if this build exposes it)
            try:
                l, b, r, t = obj.get_pos()
                max_cover = max(max_cover, abs((r - l) * (t - b)) / page_area)
            except Exception:
                pass
            # raw pixel dimensions (reliable across builds)
            try:
                pw, ph = obj.get_px_size()
                max_px = max(max_px, int(pw) * int(ph))
            except Exception:
                pass
    except Exception:
        pass
    if max_cover >= RASTER_COVER_FRACTION:
        return "raster"
    # Paper Capture scans report unreliable placement rects; a big embedded
    # bitmap on a page with only OCR-level text is a scanned sheet
    if n_words < RASTER_MAX_WORDS and max_px >= RASTER_MIN_PIXELS:
        return "raster"
    return "vector" if n_words >= SPARSE_WORD_COUNT else "sparse"


class PdfAdapter(SourceAdapter):
    name = "pdf"

    def can_read(self, path: str | Path) -> bool:
        return str(path).lower().endswith(".pdf")

    def read(self, path: str | Path) -> ReadResult:
        doc = pdfium.PdfDocument(str(path))
        try:
            pages: list[PageRead] = []
            for i in range(len(doc)):
                page = doc[i]
                raw = extract_words(doc, i)
                words = reassemble(raw)
                w, h = page.get_size()
                pages.append(PageRead(
                    words=words,
                    raw_word_count=len(raw),
                    width_pt=float(w),
                    height_pt=float(h),
                    kind=_page_kind(page, len(raw)),
                ))
            try:
                producer = doc.get_metadata_value("Producer") or ""
            except Exception:
                producer = ""
        finally:
            doc.close()
        # symbols/geometry stay empty: a PDF text layer has neither.
        return ReadResult(pages=pages, producer=producer)


register(PdfAdapter())
