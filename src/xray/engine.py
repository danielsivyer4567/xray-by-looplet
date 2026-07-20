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

import fitz  # pymupdf

from xray import ENGINE_NAME, __version__
from xray.chains import Check, find_chain_checks, trig_check
from xray.grammar import classify
from xray.quantify import shed_pack
from xray.reassemble import extract_words, reassemble
from xray.scale import vote_scale

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


def _page_kind(page: fitz.Page, n_words: int) -> str:
    """vector | raster | sparse (see CONTEXT.md; Paper Capture scans keep an
    invisible OCR text layer, so image coverage decides raster, not words)."""
    page_area = abs(page.rect) or 1.0
    imgs = []
    try:
        imgs = page.get_images(full=True)
        for img in imgs:
            for r in page.get_image_rects(img[0]):
                if abs(r) >= RASTER_COVER_FRACTION * page_area:
                    return "raster"
    except Exception:
        pass
    # Paper Capture scans report unreliable placement rects; a big embedded
    # bitmap on a page with only OCR-level text is a scanned sheet
    if n_words < RASTER_MAX_WORDS and any(
            img[2] * img[3] >= RASTER_MIN_PIXELS for img in imgs):
        return "raster"
    return "vector" if n_words >= SPARSE_WORD_COUNT else "sparse"


def _find_spec(entities) -> dict | None:
    for e in entities:
        if e.type == "SPEC" and isinstance(e.value, dict):
            return e.value
    return None


RE_FRAME_LABEL = re.compile(r"PORTAL\s+RAFTER", re.I)


def _count_checks(spec: dict, entities) -> list[Check]:
    """Label-count evidence: 'PORTAL RAFTER' should appear frames = bays+1
    times (each frame is labelled once on the plan)."""
    frames = int(spec["bays"]) + 1
    hits = [e for e in entities
            if e.type == "LABEL" and RE_FRAME_LABEL.search(str(e.raw))]
    if not hits:
        return []
    n = len(hits)
    status = "pass" if n == frames else "flag"
    return [Check(
        id=f"chk-count-portal-rafter-p{hits[0].page}",
        kind="count",
        status=status,
        detail=(f"'PORTAL RAFTER' label appears {n}x; "
                f"expected frames = bays + 1 = {frames}"),
        delta=float(n - frames),
        evidence=[e.id for e in hits],
    )]


def run(pdf_path: str) -> dict:
    """Full pipeline. Returns a TakeoffResult dict (see schema)."""
    p = Path(pdf_path)
    doc = fitz.open(p)
    try:
        pages_meta = []
        all_entities = []
        all_checks: list[Check] = []
        for i in range(doc.page_count):
            page = doc[i]
            raw = extract_words(doc, i)
            words = reassemble(raw)
            rect = (page.rect.width, page.rect.height)
            entities = classify(words, rect)
            scale = vote_scale(entities, rect, None)
            checks = find_chain_checks(entities, rect)
            all_entities.extend(entities)
            all_checks.extend(checks)
            pages_meta.append({
                "n": i + 1,
                "widthPt": float(page.rect.width),
                "heightPt": float(page.rect.height),
                "kind": _page_kind(page, len(raw)),
                "scale": scale,
            })
        producer = (doc.metadata or {}).get("producer") or ""
    finally:
        doc.close()

    spec = _find_spec(all_entities)
    quantities = []
    if spec:
        tc = trig_check(spec, all_entities)
        if tc is not None:
            all_checks.append(tc)
        all_checks.extend(_count_checks(spec, all_entities))
        quantities = shed_pack(spec, all_entities, all_checks)

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
