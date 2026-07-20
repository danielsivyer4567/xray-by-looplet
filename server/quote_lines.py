"""quote_lines.py — deterministic mapping: X-Ray TakeoffResult -> draft quote lines.

Pure and dependency-free. Built against the ACTUAL emitted contract
(schema/takeoff.schema.json, verified against out/*.xray.json), NOT an assumed
shape. Pass in the dict that engine.run() returns (or a loaded <plan>.xray.json).

The `QuoteLine` record below is engine-derived and stable. Mapping these fields
onto Looplet's own quote-line columns is the ONE step the integrator owns — this
module deliberately does not invent Looplet's schema.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class QuoteLine:
    source_quantity_id: str   # quantities[].id     (traceability back to the takeoff)
    trade: str                # quantities[].trade
    description: str          # quantities[].item
    quantity: float           # quantities[].qty
    unit: str                 # quantities[].unit   (ea|lm|m2|m3|kg|t)
    basis: str                # quantities[].formula (how the number was derived)
    confidence_tier: str      # reconciled | single-source | needs-human
    review_required: bool     # True when tier == needs-human
    evidence_refs: list       # quantities[].evidence (entity / check ids)
    notes: str                # quantities[].notes
    rate: float | None = None    # unit rate — filled by pricing, never the engine
    amount: float | None = None  # rate * quantity — filled by pricing


def quantity_to_line(q: dict) -> QuoteLine:
    """One takeoff quantity -> one draft quote line."""
    return QuoteLine(
        source_quantity_id=q["id"],
        trade=q["trade"],
        description=q["item"],
        quantity=q["qty"],
        unit=q["unit"],
        basis=q["formula"],
        confidence_tier=q["tier"],
        review_required=q["tier"] == "needs-human",
        evidence_refs=list(q.get("evidence", [])),
        notes=q.get("notes", ""),
    )


def build_quote_draft(result: dict) -> dict:
    """TakeoffResult dict -> quote-draft envelope (JSON-serialisable).

    Never raises on a well-formed result; a takeoff with 0 quantities yields an
    empty `quote_lines` list plus any `flags` (this is the normal outcome for a
    plan with no matching rule pack — see 'trade coverage' in the README).
    """
    quantities = result.get("quantities", [])
    checks = result.get("checks", [])
    review = result.get("review", [])
    lines = [asdict(quantity_to_line(q)) for q in quantities]
    n_pass = sum(1 for c in checks if c.get("status") == "pass")
    n_flag = len(checks) - n_pass
    doc = result.get("document", {})
    coverage = doc.get("coverage", {}) or {}
    return {
        "engine": result.get("engine", {}),
        "document": {
            "path": doc.get("path"),
            "sha256": doc.get("sha256"),
            "pages": len(doc.get("pages", [])),
            "coverage": coverage,  # how much of the readable text became structured
        },
        "quote_lines": lines,
        "flags": list(review),  # items a human must confirm before the quote is sent
        "summary": {
            "lines": len(lines),
            "needs_human": sum(1 for ln in lines if ln["review_required"]),
            "reconciled": sum(1 for ln in lines if ln["confidence_tier"] == "reconciled"),
            "single_source": sum(1 for ln in lines if ln["confidence_tier"] == "single-source"),
            "checks_pass": n_pass,
            "checks_flag": n_flag,
            "coverage_ratio": coverage.get("overallRatio"),
            "low_coverage_pages": list(coverage.get("lowPages", [])),
        },
    }
