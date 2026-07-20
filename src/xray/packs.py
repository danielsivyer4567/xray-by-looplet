"""packs.py — trade-pack registry for the X-Ray by Looplet engine.

A pack turns entities/tables into Quantities (and may add Checks). Packs are
registered at import; engine.run consults every registered pack whose detect()
matches. Adding a trade = adding a pack module, without touching engine.run.
"""
from __future__ import annotations

from dataclasses import dataclass

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
    A pack that raises is skipped (never crashes the run)."""
    quantities, extra_checks = [], []
    for p in _registry:
        try:
            if p.detect(ctx):
                q, c = p.quantify(ctx)
                quantities.extend(q or [])
                extra_checks.extend(c or [])
        except Exception:
            pass
    return quantities, extra_checks
