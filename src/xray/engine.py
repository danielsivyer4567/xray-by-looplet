"""engine.py — pipeline orchestrator for X-Ray by Looplet.

run(pdf_path) executes the full pipeline (extract -> reassemble -> grammar ->
scale -> checks -> quantify) and returns a dict conforming to
schema/takeoff.schema.json. File output (takeoff json + marked pdf) is the
CLI's job (cli.py), not this module's.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from xray import ENGINE_NAME, __version__
from xray.chains import Check, find_chain_checks
from xray.grammar import classify
from xray.reassemble import extract_words, reassemble
from xray.scale import vote_scale
from xray.tables import extract_tables
from xray.packs import PackContext, run_packs
import xray.packs_shed  # noqa: F401  (registers ShedPack)
import xray.packs_electrical  # noqa: F401  (registers ElectricalPack)

# a page whose largest placed image covers >= this fraction of the page area
# is a scanned sheet (raster), regardless of any invisible OCR text layer
RASTER_COVER_FRACTION = 0.5
# fewer text words than this (and no dominant image) => "sparse"
SPARSE_WORD_COUNT = 15
# fallback for scans whose placement rects are unreliable: an embedded bitmap
# of at least this many pixels on a page with only OCR-level text marks it
# raster (warehouse scans: 9-29 words; doc pages with photos: 170+ words)
RASTER_MIN_PIXELS = 300_000
RASTER_MAX_WORDS = 50


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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


def run(pdf_path: str, calibrations: dict | None = None) -> dict:
    """Full pipeline. Returns a TakeoffResult dict (see schema).

    `calibrations`: optional {page_index (0-based): calibration} where a
    calibration is {"p0":[x,y], "p1":[x,y], "known_mm": float} or
    {"mmPerPt": float}. A calibrated page's scale wins over auto-voting.
    """
    p = Path(pdf_path)
    doc = pdfium.PdfDocument(str(p))
    try:
        pages_meta = []
        all_entities = []
        all_checks: list[Check] = []
        all_tables = []
        for i in range(len(doc)):
            page = doc[i]
            raw = extract_words(doc, i)
            words = reassemble(raw)
            w, h = page.get_size()
            rect = (w, h)
            entities = classify(words, rect)
            scale = vote_scale(entities, rect, None, (calibrations or {}).get(i))
            checks = find_chain_checks(entities, rect)
            all_entities.extend(entities)
            all_checks.extend(checks)
            all_tables.extend(extract_tables(words, rect))
            pages_meta.append({
                "n": i + 1,
                "widthPt": float(w),
                "heightPt": float(h),
                "kind": _page_kind(page, len(raw)),
                "scale": scale,
            })
        try:
            producer = doc.get_metadata_value("Producer") or ""
        except Exception:
            producer = ""
    finally:
        doc.close()

    ctx = PackContext(entities=all_entities, checks=all_checks,
                      tables=all_tables, pages=pages_meta)
    quantities, pack_checks = run_packs(ctx)
    all_checks.extend(pack_checks)

    review = []
    for q in quantities:
        if q.tier == "needs-human":
            review.append({"ref": q.id, "reason": q.notes or "needs human review"})
    for c in all_checks:
        if c.status == "flag":
            review.append({"ref": c.id, "reason": c.detail})

    result = {
        "engine": {"name": ENGINE_NAME, "version": __version__},
        "document": {
            "path": str(p),
            "sha256": _sha256(p),
            "producer": producer,
            "pages": pages_meta,
        },
        "entities": [asdict(e) for e in all_entities],
        "checks": [asdict(c) for c in all_checks],
        "quantities": [asdict(q) for q in quantities],
        "review": review,
    }
    # json round-trip: tuples -> lists, exotic scalars -> json types, so the
    # dict is exactly what a takeoff.json consumer (or jsonschema) would see
    return json.loads(json.dumps(result, default=str))
