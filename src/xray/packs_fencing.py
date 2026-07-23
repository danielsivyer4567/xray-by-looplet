"""packs_fencing.py — the fencing trade pack.

Fencing is the first *geometry-driven* pack: it quantifies from the fence-line
runs a survey draws (LINE / LWPOLYLINE on a fence layer), not from a spec token
or a schedule table. That is exactly the case the RFQ proved a pack alone can't
serve without dimensioned runs — so this pack reads `ctx.geometry` for the runs
and `ctx.symbols` for placed posts/gates.

What it emits, and how honest each number is:

  fence run length (lm)  — summed drawn runs, converted to metres by the resolved
                           unit. Single-source (the drawing states it once); it
                           reconciles only if a fence-layer DIMENSION confirms it.
  posts (ea)             — the trust tier depends on the evidence:
                             * placed POST blocks AND they equal the spacing
                               estimate      -> reconciled
                             * placed posts that DISAGREE with the estimate
                                              -> single-source + a flagged count
                                                 check carrying the delta
                             * no placed posts, count derived from a spacing
                               ASSUMPTION     -> needs-human (surfaced in review)
  gates (ea)             — exact count of placed GATE blocks (single-source).

Deliberately NOT emitted: panels/palings, rails, footings, concrete. Those
depend on the fence *system* (paling vs Colorbond vs chainmesh — different bills
of material), which the geometry does not state. Inventing them would be exactly
the fabricated-quantity failure this engine exists to prevent, so the length line
carries a note asking for the system instead.
"""
from __future__ import annotations

import re

from xray.chains import Check
from xray.quantify import Quantity
from xray.packs import Pack, register

# A layer whose name mentions fencing. Substring, case-insensitive — real
# drafting layers are "FENCE", "FENCING", "SITE-FENCE", "BOUNDARY_FENCE".
FENCE_LAYER = re.compile(r"FENC", re.I)
# Block names for the two placed things a fence drawing counts directly.
RE_POST = re.compile(r"POST", re.I)
RE_GATE = re.compile(r"GATE", re.I)

# Post spacing is a trade ASSUMPTION, not a fact the drawing states. 2.4 m is the
# common Australian centre (Colorbond/paling), but it is surfaced as an
# assumption every time it is used — a derived post count is never reconciled.
DEFAULT_POST_SPACING_M = 2.4

# Drawing unit -> metres. "" (unresolved) maps to None on purpose: a run whose
# unit is unknown cannot be turned into a trustworthy length, so the pack says so
# rather than guessing a scale.
UNIT_TO_M = {
    "mm": 0.001, "cm": 0.01, "dm": 0.1, "m": 1.0, "km": 1000.0,
    "in": 0.0254, "ft": 0.3048, "yd": 0.9144,
}


def _is_fence_run(g) -> bool:
    return (getattr(g, "kind", None) in ("line", "polyline")
            and FENCE_LAYER.search(getattr(g, "layer", "") or "") is not None)


def _fence_symbols(symbols, matcher):
    return [s for s in symbols or []
            if matcher.search(getattr(s, "block_name", "") or "")
            and FENCE_LAYER.search(getattr(s, "layer", "") or "") is not None]


def _run_metres(g):
    """A run's length in metres, or None if its unit can't be resolved."""
    factor = UNIT_TO_M.get(getattr(g, "unit", "") or "")
    if factor is None:
        return None
    return float(g.value) * factor


def _posts_for_run(length_m: float, spacing_m: float) -> int:
    """Posts along one continuous run: a post at each end plus one per interval.
    floor(L / spacing) intervals + 1. The tiny epsilon keeps an exact multiple
    (48.0 / 2.4 = 20.0) from dropping to 19 on binary-float error."""
    return int(length_m / spacing_m + 1e-9) + 1


class FencingPack(Pack):
    name = "fencing"
    trade = "fencing"

    def detect(self, ctx) -> bool:
        if any(_is_fence_run(g) for g in getattr(ctx, "geometry", []) or []):
            return True
        return bool(_fence_symbols(getattr(ctx, "symbols", []), RE_POST)
                    or _fence_symbols(getattr(ctx, "symbols", []), RE_GATE))

    def quantify(self, ctx):
        geometry = getattr(ctx, "geometry", []) or []
        symbols = getattr(ctx, "symbols", []) or []
        runs = [g for g in geometry if _is_fence_run(g)]
        quants: list[Quantity] = []
        checks: list[Check] = []

        # ---- fence run length ------------------------------------------------
        lengths = [_run_metres(g) for g in runs]
        unresolved = any(x is None for x in lengths)
        total_m = round(sum(x for x in lengths if x is not None), 3)
        n_runs = len(runs)

        if runs:
            if unresolved:
                quants.append(Quantity(
                    id="q-fence-length", trade="fencing", item="fence line",
                    qty=total_m, unit="lm",
                    formula=(f"sum of {n_runs} drawn run(s); some runs had no "
                             f"resolvable unit and are excluded"),
                    tier="needs-human", evidence=[],
                    notes=("a fence run had no resolvable drawing unit, so this "
                           "length is incomplete — set the DXF units / page scale "
                           "and re-run")))
            else:
                quants.append(Quantity(
                    id="q-fence-length", trade="fencing", item="fence line",
                    qty=total_m, unit="lm",
                    formula=f"sum of {n_runs} drawn fence run(s) = {total_m} lm",
                    tier="single-source", evidence=[],
                    notes=("fence system not specified — panels/palings, rails, "
                           "footings and concrete are NOT quantified; provide the "
                           "system (paling / Colorbond / chainmesh) for a full BOM")))

        # ---- posts -----------------------------------------------------------
        placed = _fence_symbols(symbols, RE_POST)
        derived = None
        if runs and not unresolved:
            # one continuous run contributes floor(L/spacing) intervals + 1 post;
            # each additional disconnected run adds its own closing post.
            derived = sum(int(_run_metres(g) / DEFAULT_POST_SPACING_M + 1e-9)
                          for g in runs) + n_runs

        if placed:
            n = len(placed)
            if derived is not None:
                agrees = n == derived
                checks.append(Check(
                    id="chk-fence-posts", kind="count",
                    status="pass" if agrees else "flag",
                    detail=(f"{n} posts placed vs {derived} estimated from "
                            f"{total_m} lm at {DEFAULT_POST_SPACING_M:g} m centres"),
                    delta=float(n - derived) if not agrees else None,
                    evidence=[s.id for s in placed]))
                tier = "reconciled" if agrees else "single-source"
                notes = ("placed count confirmed by the spacing estimate"
                         if agrees else
                         f"placed posts disagree with the {DEFAULT_POST_SPACING_M:g} m "
                         "spacing estimate — verify spacing/extents")
            else:
                tier, notes = "single-source", "count of placed post blocks"
            quants.append(Quantity(
                id="q-fence-posts", trade="fencing", item="fence posts",
                qty=float(n), unit="ea",
                formula=f"count of placed POST blocks = {n}",
                tier=tier, evidence=[s.id for s in placed], notes=notes))
        elif derived is not None:
            quants.append(Quantity(
                id="q-fence-posts", trade="fencing", item="fence posts",
                qty=float(derived), unit="ea",
                formula=(f"{total_m} lm / {DEFAULT_POST_SPACING_M:g} m centres + "
                         f"{n_runs} end post(s) = {derived}"),
                tier="needs-human", evidence=[],
                notes=(f"no posts drawn — count ASSUMES {DEFAULT_POST_SPACING_M:g} m "
                       "centres; confirm spacing and corner/end posts before ordering")))

        # ---- gates -----------------------------------------------------------
        gates = _fence_symbols(symbols, RE_GATE)
        if gates:
            quants.append(Quantity(
                id="q-fence-gates", trade="fencing", item="gates",
                qty=float(len(gates)), unit="ea",
                formula=f"count of placed GATE blocks = {len(gates)}",
                tier="single-source", evidence=[s.id for s in gates],
                notes="gate leaf/hardware per gate schedule"))

        return quants, checks


register(FencingPack())
