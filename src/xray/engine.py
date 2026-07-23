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
from xray.packs import PackContext, iter_packs, run_packs
from xray.quantify import Quantity
from xray.sources import find_adapter
from xray.sources.base import SPARSE_WORD_COUNT
from xray.preflight import check_input, InputError
import xray.packs_shed  # noqa: F401  (registers ShedPack)
import xray.packs_electrical  # noqa: F401  (registers ElectricalPack)
import xray.packs_fencing  # noqa: F401  (registers FencingPack)

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

    Order conversion (measured -> orderable stock) is applied downstream by the
    hardening pass, whose purchase optimiser is xray.orders (one tested kernel).
    """
    p = Path(pdf_path)
    # Bad input is stopped at the door with a clear, typed error rather than a
    # raw parser traceback (empty / oversized / encrypted / corrupt / wrong
    # format). check_input returns the adapter it validated.
    adapter = check_input(p)
    # The adapter owns everything format-specific and returns pure data — it
    # closes its own document, so nothing below holds a live handle. A parser
    # failure on a file that passed preflight is still surfaced as InputError,
    # never a stack trace.
    try:
        read = adapter.read(p)
    except InputError:
        raise
    except Exception as e:
        raise InputError(
            "unreadable",
            f"{p.name} could not be parsed as {adapter.name} "
            f"({type(e).__name__}: {e})") from e
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
                      tables=all_tables, pages=pages_meta,
                      symbols=read.symbols, geometry=read.geometry)
    quantities, pack_checks = run_packs(ctx)
    all_checks.extend(pack_checks)

    # CAD symbols -> real quantities. A block placement is an exact count with
    # no recognition step; the recursive total (all depths) is the true number,
    # and every counted placement's id rides along as evidence, so the count is
    # re-derivable from the output alone. Attribute overrides stay auditable in
    # the notes — an instance override is the drawing's statement about THAT
    # placement and must never be silently dropped.
    if read.symbols:
        by_name: dict[str, list] = {}
        for s in read.symbols:
            by_name.setdefault(s.block_name, []).append(s)
        for name in sorted(by_name):
            group = by_name[name]
            trade = next((s.trade for s in group if s.trade), "")
            over = [s for s in group if s.overridden]
            notes = ""
            if over:
                notes = "attribute override on " + "; ".join(
                    f"{s.id}: " + ", ".join(
                        f"{t}={s.attribs.get(t)}" for t in s.overridden)
                    for s in over)
            quantities.append(Quantity(
                id="q-sym-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
                trade=trade, item=name, qty=float(len(group)), unit="ea",
                formula=f"count(INSERT {name}, recursive)", tier="reconciled",
                evidence=[s.id for s in group], notes=notes))

    # A dimension whose text states a number its geometry does not support is
    # the drawing contradicting itself. Flag it carrying BOTH numbers — flagged
    # checks reach review[], which is exactly where a field-verify note belongs.
    # Silently trusting either value is how a wrong number reaches a quote.
    for gi, g in enumerate(read.geometry):
        if getattr(g, "conflict", False):
            all_checks.append(Check(
                id=f"dim-override-{gi}",
                kind="dim-override", status="flag",
                detail=(f"dimension measures {g.value:g} {g.unit or 'units'} "
                        f"but its text claims {g.text_value:g} ({g.text!r})"),
                delta=(g.text_value - g.value) if g.text_value is not None
                      else None,
                evidence=[]))

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

    # An empty takeoff is not self-explanatory. "No trade pack recognised this
    # drawing" and "the pack that recognised it broke" produce the identical
    # empty table, and they mean opposite things to whoever opens it. Neither
    # should be inferred from silence, so the result says which one happened.
    if not quantities:
        broken = [c for c in all_checks if c.kind == "pack-error"]
        if broken:
            detail = ("no quantities were produced because every trade pack that "
                      "applied to this drawing failed — see the pack-error checks "
                      "for which, and why")
        else:
            trades = sorted({pack.trade for pack in iter_packs()})
            detail = ("no trade pack recognised this drawing, so nothing was "
                      "quantified. X-Ray measures: "
                      f"{', '.join(trades) if trades else 'no trades (none registered)'}. "
                      "The entities and dimension checks in this takeoff are still "
                      "valid evidence — only the quantity step was skipped.")
        all_checks.append(Check(id="chk-pack-coverage", kind="pack-coverage",
                                status="flag", detail=detail))

    # A file that looks like a flattened plot rather than native CAD is flagged
    # loudly: it has no blocks to count and no dimensions it measured, so any
    # number derived from it would be confident nonsense. Flag, never silently
    # ingest (see fixtures/negative/README.md).
    prov = getattr(read, "provenance", None) or {}
    if prov.get("suspect"):
        all_checks.append(Check(
            id="chk-provenance", kind="provenance", status="flag",
            detail=("this file looks like a flattened plot, not native CAD ("
                    + "; ".join(prov.get("reasons", []))
                    + ") — counts and lengths from it may be unfounded; verify "
                    "against a file saved by a CAD application")))

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

    # Non-text content, present ONLY when the source produced it — a PDF read
    # yields neither, and its output must stay byte-identical to before these
    # keys existed. Symbols serialize with the contract's camelCase identity
    # fields (id / parentId) so a consumer can rebuild the placement DAG.
    if read.symbols:
        result["symbols"] = [{
            "id": s.id, "parentId": s.parent_id, "blockName": s.block_name,
            "layer": s.layer, "x": s.x, "y": s.y, "rotation": s.rotation,
            "xscale": s.xscale, "yscale": s.yscale, "trade": s.trade,
            "depth": s.depth, "path": list(s.path),
            "attribs": dict(s.attribs), "overridden": list(s.overridden),
            "anonymous": s.anonymous,
        } for s in read.symbols]
    if read.geometry:
        result["geometry"] = [asdict(g) for g in read.geometry]
    if read.units:
        result["document"]["units"] = dict(read.units)

    # json round-trip: tuples -> lists, exotic scalars -> json types, so the
    # dict is exactly what a takeoff.json consumer (or jsonschema) would see
    return json.loads(json.dumps(result, default=str))
