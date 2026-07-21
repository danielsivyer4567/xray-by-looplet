"""engine.py — pipeline orchestrator for X-Ray by Looplet.

run(path) executes the full pipeline (read -> grammar -> scale -> checks ->
tables -> quantify) and returns a dict conforming to
schema/takeoff.schema.json. File output (takeoff json + marked pdf) is the
CLI's job (cli.py), not this module's.

The **read** stage is delegated to a source adapter (`xray.sources`), so this
module holds nothing format-specific: it never imports pdfium and never touches
an open document. Adding an input format is a new adapter module plus a
`register()` call — `run()` does not change.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

from xray import ENGINE_NAME, __version__
from xray.chains import Check, find_chain_checks
from xray.grammar import classify
from xray.scale import vote_scale
from xray.tables import extract_tables
from xray.packs import PackContext, run_packs
from xray.sources import find_adapter
from xray.sources.base import SPARSE_WORD_COUNT
import xray.packs_shed  # noqa: F401  (registers ShedPack)
import xray.packs_electrical  # noqa: F401  (registers ElectricalPack)

# a text-heavy page whose structured-output ratio is below this warrants a
# human look ("read 94%, here's the 6% I couldn't") — a diagnostic, not a gate.
COVERAGE_MIN = 0.15


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(pdf_path: str, calibrations: dict | None = None) -> dict:
    """Full pipeline. Returns a TakeoffResult dict (see schema).

    `calibrations`: optional {page_index (0-based): calibration} where a
    calibration is {"p0":[x,y], "p1":[x,y], "known_mm": float} or
    {"mmPerPt": float}. A calibrated page's scale wins over auto-voting.
    """
    p = Path(pdf_path)
    # The adapter owns everything format-specific and returns pure data — it
    # closes its own document, so nothing below holds a live handle.
    read = find_adapter(p).read(p)
    producer = read.producer

    pages_meta = []
    all_entities = []
    all_checks: list[Check] = []
    all_tables = []
    for i, pr in enumerate(read.pages):
        words = pr.words
        n_raw = pr.raw_word_count
        rect = (pr.width_pt, pr.height_pt)
        entities = classify(words, rect)
        scale = vote_scale(entities, rect, None, (calibrations or {}).get(i))
        checks = find_chain_checks(entities, rect)
        tbls = extract_tables(words, rect)
        all_entities.extend(entities)
        all_checks.extend(checks)
        all_tables.extend(tbls)
        n_cells = sum(len(r) for t in tbls for r in t.rows)
        ratio = round(min(1.0, (len(entities) + n_cells) / max(1, n_raw)), 3)
        pages_meta.append({
            "n": i + 1,
            "widthPt": float(pr.width_pt),
            "heightPt": float(pr.height_pt),
            "kind": pr.kind,
            "scale": scale,
            "coverage": {
                "words": n_raw,
                "entities": len(entities),
                "tableCells": n_cells,
                "structuredRatio": ratio,
            },
        })

    ctx = PackContext(entities=all_entities, checks=all_checks,
                      tables=all_tables, pages=pages_meta)
    quantities, pack_checks = run_packs(ctx)
    all_checks.extend(pack_checks)

    # document-level coverage: how much of the readable text turned into
    # structured output, and which text-heavy pages fell below the bar.
    tot_words = sum(pm["coverage"]["words"] for pm in pages_meta)
    tot_struct = sum(pm["coverage"]["entities"] + pm["coverage"]["tableCells"]
                     for pm in pages_meta)
    low_pages = [pm["n"] for pm in pages_meta
                 if pm["coverage"]["words"] >= SPARSE_WORD_COUNT
                 and pm["coverage"]["structuredRatio"] < COVERAGE_MIN]
    doc_coverage = {
        "overallRatio": round(min(1.0, tot_struct / max(1, tot_words)), 3),
        "lowPages": low_pages,
    }

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
            "coverage": doc_coverage,
        },
        "entities": [asdict(e) for e in all_entities],
        "checks": [asdict(c) for c in all_checks],
        "quantities": [asdict(q) for q in quantities],
        "review": review,
    }
    # json round-trip: tuples -> lists, exotic scalars -> json types, so the
    # dict is exactly what a takeoff.json consumer (or jsonschema) would see
    return json.loads(json.dumps(result, default=str))
