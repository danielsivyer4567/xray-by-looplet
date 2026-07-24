"""packs.py — trade-pack registry for the X-Ray by Looplet engine.

A pack turns entities/tables into Quantities (and may add Checks). Packs are
registered at import; engine.run consults every registered pack whose detect()
matches. Adding a trade = adding a pack module, without touching engine.run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# base construction units (schema-validated). Packs may declare extras
# (e.g. electrical VA) via register_units so the engine stays trade-agnostic.
BASE_UNITS = {"ea", "lm", "m2", "m3", "kg", "t"}
_extra_units = set()


def register_units(*units):
    _extra_units.update(units)


def allowed_units():
    return BASE_UNITS | set(_extra_units)


@dataclass
class PackContext:
    entities: list          # list[Entity]
    checks: list            # list[Check] produced so far (chain checks)
    tables: list            # list[tables.Table] across all pages
    pages: list             # page meta dicts
    # Non-text CAD content, empty for a PDF source. A geometry-driven pack
    # (fencing, earthworks) needs the runs and placements the PDF path can't
    # provide; a text/table pack (shed, electrical) simply ignores both.
    symbols: list = field(default_factory=list)    # list[sources.base.Symbol]
    geometry: list = field(default_factory=list)   # list[sources.base.Measure]
    # {declared, resolved, basis, mismatch, verified} for a CAD source, {} for a
    # PDF. `verified` False means the unit rests only on the header — a pack
    # emitting a unit-dependent quantity should flag rather than assert.
    units: dict = field(default_factory=dict)


class Pack:
    name = "base"
    trade = "base"

    def detect(self, ctx: "PackContext") -> bool:
        raise NotImplementedError

    def quantify(self, ctx: "PackContext"):
        """Return (list[Quantity], list[Check]) — extra checks the pack made."""
        raise NotImplementedError


_registry = []


def register(pack):
    _registry.append(pack)


def iter_packs():
    return list(_registry)


def run_packs(ctx: "PackContext"):
    """Run every registered pack whose detect() matches; concat results.

    A pack that raises must never crash the run — one broken trade should not
    cost the operator every other trade's numbers. But it must never be silent
    either: a swallowed failure is indistinguishable from "there was nothing
    here to measure", and for a takeoff those two mean opposite things. A
    builder who is told nothing was found will move on; a builder who is told
    the steel pack broke will look again. So failures become flagged checks,
    which the engine surfaces in review[].
    """
    from xray.chains import Check  # local: keeps this module import-light

    quantities, extra_checks = [], []
    for p in _registry:
        try:
            applies = p.detect(ctx)
        except Exception as e:
            extra_checks.append(Check(
                id=f"chk-pack-{p.name}-detect", kind="pack-error", status="flag",
                detail=(f"trade pack {p.name!r} failed while deciding whether it "
                        f"applies to this document, so its trade was not "
                        f"measured: {type(e).__name__}: {e}")))
            continue
        if not applies:
            continue
        try:
            q, c = p.quantify(ctx)
            quantities.extend(q or [])
            extra_checks.extend(c or [])
        except Exception as e:
            extra_checks.append(Check(
                id=f"chk-pack-{p.name}-quantify", kind="pack-error", status="flag",
                detail=(f"trade pack {p.name!r} recognised this document but failed "
                        f"while producing quantities, so its trade is missing from "
                        f"this takeoff: {type(e).__name__}: {e}")))
    return quantities, extra_checks
