"""mapping.py — match a measured takeoff line to a supplier SKU.

THE RULE
--------
This module PROPOSES. It never decides. A takeoff line is only ever bound to a
SKU because a human confirmed it once, and that confirmation is remembered so
nobody is asked twice. Everything else comes back as ranked candidates or as
`needs-human` — the same tier the engine uses when the drawing will not tell it
something.

That restraint is the point. "146.2 m2 of roof sheeting" could plausibly match
a dozen products at different prices, and picking one on token overlap would
produce a confident, orderable, wrong quote. Guessing is the one thing an
ordering system must not do, because the mistake arrives as delivered steel.

DETERMINISTIC, LIKE THE ENGINE
------------------------------
Scoring is plain token and dimension arithmetic — no LLM, no network, no
randomness. The same takeoff and catalogue always produce the same candidate
order, so a review is reproducible and a disagreement is debuggable.

UNITS ARE A GATE, NOT A SCORE
-----------------------------
A product priced per metre cannot fulfil a line measured in square metres. Unit
mismatch disqualifies a candidate outright rather than costing it points,
because no amount of description similarity makes $232/m the right answer for
an area. Importing this catalogue mistyped ~1,900 per-metre rows as "each"
before it was caught; a scorer that treats units as a soft signal would have
buried that instead of surfacing it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Words that carry no discriminating power in a fencing/steel catalogue.
STOPWORDS = {
    "the", "and", "for", "with", "per", "to", "of", "a", "x", "mm", "std",
    "standard", "colour", "color", "each", "only", "high", "wide",
}

# Units that can substitute for each other. Deliberately empty of anything
# lossy: "ea" is NOT interchangeable with "lm" even when a product happens to
# come in fixed lengths, because that conversion needs a stated length.
UNIT_EQUIVALENTS = {
    "lm": {"lm", "m"},
    "m2": {"m2", "sqm"},
    "ea": {"ea", "each"},
    "pack": {"pack"},
}

TOKEN_RE = re.compile(r"[a-z0-9.]+")

# Millimetre sizes, however the line phrases them: "1800mm", "1800H", "1800 High",
# "65 x 16". Takeoff lines say "1800 high" where the catalogue says "1800H", and
# missing that left every gate height scoring identically — the mismatch that
# matters most to rank is exactly the one a builder is choosing between.
DIM_RE = re.compile(
    r"\b(\d{2,4})\s*(?:mm\b|h\b|w\b|high\b|wide\b|x\b|\*)", re.I)


def tokens(text: str) -> set[str]:
    return {t for t in TOKEN_RE.findall((text or "").lower())
            if t not in STOPWORDS and len(t) > 1}


def dimensions(text: str) -> set[int]:
    """Numbers that look like millimetre sizes — 900, 1200, 65, 16."""
    return {int(m) for m in DIM_RE.findall(text or "")}


def units_compatible(a: str, b: str) -> bool:
    a, b = (a or "").lower(), (b or "").lower()
    if a == b:
        return True
    for group in UNIT_EQUIVALENTS.values():
        if a in group and b in group:
            return True
    return False


@dataclass
class Candidate:
    code: str | None
    description: str
    unit: str
    prices: dict
    poa: bool
    page: int
    score: float
    why: str            # human-readable reason, so a review is not a black box


@dataclass
class MappingResult:
    """One takeoff line, and what the catalogue had to say about it."""
    quantity_id: str
    item: str
    unit: str
    status: str                     # "mapped" | "needs-human"
    code: str | None = None         # set only when remembered
    confirmed_by: str | None = None
    candidates: list = field(default_factory=list)
    note: str = ""


def _signature(item: str, unit: str) -> str:
    """Stable key for remembering a decision. Normalised so trivial rewording
    of the same item still hits the memory, but the unit is part of the key —
    the same words in a different unit are a different commercial decision."""
    return f"{unit.lower()}|" + " ".join(sorted(tokens(item)))


class MappingStore:
    """Per-supplier memory of confirmed mappings.

    Plain JSON on disk: a builder can read it, audit it, and correct it without
    this tool. Each entry records who confirmed it and when, because a binding
    between a measured line and a purchase order is a decision someone owns.
    """

    def __init__(self, supplier: str, path: str | Path | None = None):
        self.supplier = supplier
        self.path = Path(path) if path else Path(f"pricing/out/{supplier}-mappings.json")
        self._entries: dict[str, dict] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text("utf-8"))
            self._entries = data.get("mappings", {})

    def get(self, item: str, unit: str) -> dict | None:
        return self._entries.get(_signature(item, unit))

    def confirm(self, item: str, unit: str, code: str, by: str,
                when: str, note: str = "") -> None:
        """Record a human decision. `when` is passed in rather than read from
        the clock so callers stay deterministic and testable."""
        self._entries[_signature(item, unit)] = {
            "code": code, "item": item, "unit": unit,
            "confirmed_by": by, "confirmed_at": when, "note": note,
        }

    def forget(self, item: str, unit: str) -> bool:
        return self._entries.pop(_signature(item, unit), None) is not None

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"supplier": self.supplier, "mappings": self._entries},
            indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    def __len__(self) -> int:
        return len(self._entries)


def score(item: str, unit: str, row: dict) -> tuple[float, str]:
    """How well one catalogue row answers one takeoff line, and why.

    Returns (score, reason). A score of 0 means "not a candidate at all".
    """
    if not units_compatible(unit, row.get("unit", "")):
        return 0.0, f"unit {row.get('unit')!r} cannot fulfil {unit!r}"

    want, have = tokens(item), tokens(row.get("description", ""))
    if not want or not have:
        return 0.0, "nothing to compare"

    shared = want & have
    if not shared:
        return 0.0, "no shared terms"

    # Jaccard over description words, so a long catalogue description does not
    # win simply by containing more words.
    overlap = len(shared) / len(want | have)

    want_dims, have_dims = dimensions(item), dimensions(row.get("description", ""))
    dim_bonus = 0.0
    dim_note = ""
    if want_dims and have_dims:
        matched = want_dims & have_dims
        if matched:
            dim_bonus = 0.25 * (len(matched) / len(want_dims))
            dim_note = f", dimensions {sorted(matched)} match"
        else:
            # Same words, different size, is usually the WRONG product.
            dim_bonus = -0.15
            dim_note = ", but no dimension matches"

    total = max(0.0, min(1.0, overlap + dim_bonus))
    return total, (f"{len(shared)}/{len(want)} terms match "
                   f"({', '.join(sorted(shared)[:4])}){dim_note}")


def propose(item: str, unit: str, catalogue: list[dict], store: MappingStore,
            quantity_id: str = "", limit: int = 5,
            min_score: float = 0.15) -> MappingResult:
    """Resolve ONE takeoff line against the catalogue."""
    remembered = store.get(item, unit)
    if remembered:
        return MappingResult(
            quantity_id=quantity_id, item=item, unit=unit, status="mapped",
            code=remembered["code"], confirmed_by=remembered.get("confirmed_by"),
            note="from confirmed mapping" +
                 (f" — {remembered['note']}" if remembered.get("note") else ""))

    scored = []
    for row in catalogue:
        value, why = score(item, unit, row)
        if value >= min_score:
            scored.append(Candidate(
                code=row.get("code"), description=row.get("description", ""),
                unit=row.get("unit", ""), prices=row.get("prices", {}),
                poa=bool(row.get("poa")), page=row.get("page", 0),
                score=round(value, 3), why=why))

    # Deterministic order: score desc, then code/description so equal scores
    # never shuffle between runs.
    scored.sort(key=lambda c: (-c.score, c.code or "", c.description))

    note = ("no catalogue row shares enough with this line — it may need a "
            "different supplier, or a custom item"
            if not scored else
            "candidates only — a human confirms before this can be ordered")
    return MappingResult(
        quantity_id=quantity_id, item=item, unit=unit, status="needs-human",
        candidates=scored[:limit], note=note)


def map_takeoff(quantities: list[dict], catalogue: list[dict],
                store: MappingStore, **kw) -> list[MappingResult]:
    """Resolve every line of a takeoff. Order follows the takeoff."""
    return [propose(q.get("item", ""), q.get("unit", ""), catalogue, store,
                    quantity_id=q.get("id", ""), **kw)
            for q in quantities]


def summarise(results: list[MappingResult]) -> dict:
    """What a human needs to see before trusting an order sheet."""
    mapped = [r for r in results if r.status == "mapped"]
    unresolved = [r for r in results if r.status != "mapped"]
    return {
        "lines": len(results),
        "mapped_from_memory": len(mapped),
        "needs_human": len(unresolved),
        "with_candidates": sum(1 for r in unresolved if r.candidates),
        "no_candidates": sum(1 for r in unresolved if not r.candidates),
    }


def to_dicts(results: list[MappingResult]) -> list[dict]:
    return [asdict(r) for r in results]
