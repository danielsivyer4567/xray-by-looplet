"""ocr.py — the OCR stage: recognise text on raster (scanned/photographed) sheets.

A vector PDF carries its dimension text in a text layer the engine reads directly.
A **scan or a photo** carries pixels only, so its text must be recognised first.
This module renders a page to an image and hands it to a **pluggable OCR
backend**, converting the backend's word boxes into the same `reassemble.Word`
objects the rest of the pipeline consumes — tagged `source="ocr"`, so a
recognised number is always distinguishable from one read losslessly from a
vector layer (and carries lower confidence accordingly).

Design boundary, stated honestly:
  * Rendering (pdfium -> PIL) and the box→Word conversion are deterministic and
    fully tested here (incl. via a stub backend).
  * The **recognition** is the backend's job. No OCR engine ships in this repo or
    is assumed installed — `TesseractBackend` activates only when `pytesseract` +
    the tesseract binary are present; otherwise it raises a clear error. Wiring
    OCR into `engine.run` is a separate, opt-in step (it would change raster-page
    output, so it must never be on by default — the byte-identity gate depends on
    that).
  * Accuracy on real construction plans (rotated/dense/glyph-split dimension text,
    and far harder, a glare-y phone photo) is an engine-and-fixture problem, not a
    plumbing one. Clean scans are achievable; a paper photo is much harder.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from xray.reassemble import Word


@dataclass
class OcrWord:
    """One recognised word in IMAGE pixel coordinates (top-left origin)."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float = 0.0     # 0..1 recogniser confidence


class OcrBackend(Protocol):
    """Any text recogniser. Implement `recognize` and you plug into the stage."""
    name: str

    def recognize(self, image) -> list[OcrWord]:
        """Recognise words in a PIL image -> boxes in image pixels."""
        ...


def render_page(pdf_path: str | Path, page_index: int = 0, dpi: int = 200):
    """Render one PDF page to a PIL image at `dpi`. Returns (image, scale) where
    scale = pixels-per-point (dpi/72), needed to map boxes back to PDF points."""
    import pypdfium2 as pdfium

    scale = dpi / 72.0
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        image = doc[page_index].render(scale=scale).to_pil()
    finally:
        doc.close()
    return image, scale


def ocr_words(ocr_out: list[OcrWord], page_index: int, scale: float) -> list[Word]:
    """Convert a backend's pixel-space boxes into pipeline `Word`s in PDF points.

    The pipeline works in PDF points (top-left origin); a render at `scale`
    pixels-per-point means point = pixel / scale. Every word is tagged
    `source="ocr"` so downstream can weight it as recognised, not read."""
    out = []
    for w in ocr_out:
        if not (w.text or "").strip():
            continue
        out.append(Word(
            text=w.text, x0=w.x0 / scale, y0=w.y0 / scale,
            x1=w.x1 / scale, y1=w.y1 / scale,
            page=page_index, source="ocr"))
    return out


def recognize_page(pdf_path, backend: OcrBackend, page_index: int = 0,
                   dpi: int = 200) -> list[Word]:
    """Full stage for one page: render -> recognise -> pipeline Words (points)."""
    image, scale = render_page(pdf_path, page_index, dpi)
    return ocr_words(backend.recognize(image), page_index, scale)


# --------------------------------------------------------------- backends

class StubBackend:
    """A deterministic, engine-free backend for testing the plumbing and demos:
    returns a fixed set of word boxes regardless of the image. NOT recognition —
    it exists so the render→convert→pipeline path is provable without installing
    an OCR engine."""
    name = "stub"

    def __init__(self, words: list[OcrWord] | None = None):
        self._words = words or [
            OcrWord("16000", 100.0, 100.0, 260.0, 140.0, 0.98),
            OcrWord("9000", 100.0, 200.0, 220.0, 240.0, 0.97),
        ]

    def recognize(self, image) -> list[OcrWord]:
        return list(self._words)


class TesseractBackend:
    """Tesseract via pytesseract. Activates ONLY when pytesseract and the
    tesseract binary are installed; otherwise construction raises a clear error
    naming what to install. Recognition quality is Tesseract's — for dense/rotated
    plan text, PaddleOCR is usually stronger; both fit this same interface."""
    name = "tesseract"

    def __init__(self, lang: str = "eng", min_conf: float = 0.3):
        try:
            import pytesseract  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "OCR backend 'tesseract' needs pytesseract: pip install "
                "pytesseract, and install the tesseract binary "
                "(https://github.com/tesseract-ocr/tesseract)") from e
        self.lang = lang
        self.min_conf = min_conf

    def recognize(self, image) -> list[OcrWord]:
        import pytesseract
        from pytesseract import Output
        data = pytesseract.image_to_data(image, lang=self.lang,
                                         output_type=Output.DICT)
        out = []
        for i, txt in enumerate(data["text"]):
            try:
                conf = float(data["conf"][i]) / 100.0
            except (ValueError, TypeError):
                conf = 0.0
            if not (txt or "").strip() or conf < self.min_conf:
                continue
            x, y = float(data["left"][i]), float(data["top"][i])
            out.append(OcrWord(txt, x, y, x + float(data["width"][i]),
                               y + float(data["height"][i]), conf))
        return out


def available_backend():
    """Return a ready-to-use recognition backend, or None if none is installed.
    (StubBackend is never returned — it does not recognise anything.)"""
    try:
        return TesseractBackend()
    except RuntimeError:
        return None
