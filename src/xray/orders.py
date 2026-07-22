"""orders.py — deterministic order/cut conversion (measured qty -> orderable stock).

WHY this exists
---------------
A takeoff says "87.7 lm of framing" or "33 studs". A builder orders *pieces of
real stock lengths*. Every market tool researched converts with a formula plus a
flat waste %, then a manual rounding function — NONE run a real stock-length cut
optimiser (PlanSwift makes you hand-write If/Then stock->SKU rules; Buildxact a
per-centre divisor; Quick Bid back-solves a waste factor to hit whole packs).

WHAT this is
------------
A pure, deterministic optimiser that turns a required quantity into `order_qty`
+ `purchase[{stock_length_m, count, offcut_m}]` — the fields already on Quantity.
It PREFERS an exact stock length, FALLS BACK to cutting from longer stock when the
preferred length isn't stocked, and CHOOSES the fallback that minimises offcut.
Nothing here is probabilistic: same inputs -> byte-identical output (tested).

HOW it stays honest
-------------------
The measured quantity is evidence and never changes. This layer only INTERPRETS
it for purchasing, and every step is auditable: the chosen method, the per-length
offcut, the total waste, and each named allowance with its source all travel in
the result. No magic numbers — a waste factor is a named `Allowance` with a
`source`, not an opaque %.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Allowance:
    """A named, sourced multiplicative factor (1.05 = +5%). Modelled separately
    (not bundled into one opaque waste %) so a reviewer sees exactly why."""
    name: str
    factor: float
    source: str


@dataclass(frozen=True)
class StockProfile:
    """How a material is bought. Lengths in metres.

    preferred: ideal cut/stock lengths, best first (e.g. [2.7, 3.0]).
    fallback:  longer lengths to cut down from when preferred isn't stocked.
    available: which lengths are actually purchasable now; None = all of
               preferred+fallback are available.
    kerf_m:    saw kerf consumed per cut between pieces.
    pack_size: order in multiples of this many pieces (bundles); 1 = singles.
    kg_per_m:  mass per metre for weight rollup; None = weight not computed.
    """
    name: str
    preferred: tuple[float, ...]
    fallback: tuple[float, ...] = ()
    available: tuple[float, ...] | None = None
    kerf_m: float = 0.0
    pack_size: int = 1
    kg_per_m: float | None = None

    def sourceable(self) -> set[float]:
        if self.available is not None:
            return set(self.available)
        return set(self.preferred) | set(self.fallback)


@dataclass
class Purchase:
    """One buy line: `count` pieces of `stock_length_m`, each leaving `offcut_m`
    of drop when cut to the required piece (0 when bought at exact length)."""
    stock_length_m: float
    count: int
    offcut_m: float


@dataclass
class OrderResult:
    order_qty: int                       # stock pieces to buy (== sum of purchase counts)
    stock_length_m: float                # chosen stock length
    pieces_per_length: int               # required pieces cut from one stock length
    total_offcut_m: float                # true total drop across all lengths
    yield_pct: float                     # used / purchased length, 0..100
    method: str                          # "exact-stock" | "cut-from-<L>m"
    purchase: list[Purchase]
    delivered_weight_kg: float | None = None
    notes: str = ""

    def as_dict(self) -> dict:
        """Shape that drops straight into Quantity.purchase / order_qty."""
        return {
            "order_qty": self.order_qty,
            "purchase": [
                {"stock_length_m": p.stock_length_m, "count": p.count,
                 "offcut_m": round(p.offcut_m, 4)} for p in self.purchase],
            "total_offcut_m": round(self.total_offcut_m, 4),
            "yield_pct": round(self.yield_pct, 1),
            "method": self.method,
            "delivered_weight_kg": (round(self.delivered_weight_kg, 2)
                                    if self.delivered_weight_kg is not None else None),
            "notes": self.notes,
        }


class CannotSource(Exception):
    """No stocked length can yield even one of the required pieces -> needs-human."""


def apply_allowances(base_qty: float, allowances: list[Allowance]) -> tuple[float, list[dict]]:
    """Multiply base by each named factor in order. Returns (adjusted, records).
    Records are audit rows — every factor keeps its name and source."""
    adjusted = float(base_qty)
    records: list[dict] = []
    for a in allowances:
        before = adjusted
        adjusted *= a.factor
        records.append({"name": a.name, "factor": a.factor, "source": a.source,
                        "from": round(before, 4), "to": round(adjusted, 4)})
    return adjusted, records


def _pieces_per_length(stock: float, cut: float, kerf: float) -> int:
    """Max whole pieces of `cut` from one `stock` length, accounting for kerf.
    n pieces need n*cut + (n-1)*kerf <= stock (kerf sits BETWEEN pieces)."""
    if cut <= 0 or stock < cut:
        return 0
    # solve largest n: n*cut + (n-1)*kerf <= stock
    n = int((stock + kerf) / (cut + kerf) + 1e-9)
    return max(n, 0)


def _round_to_pack(qty: int, pack: int) -> int:
    if pack <= 1:
        return qty
    return math.ceil(qty / pack) * pack


def convert_uniform(cut_len_m: float, count: int, profile: StockProfile) -> OrderResult:
    """Convert N identical fixed-length pieces (e.g. studs) into a buy plan.

    1. If the piece length is itself a stocked length -> buy `count` of it (0 drop).
    2. Else cut from the fallback length that MINIMISES total drop (tie: fewer
       lengths, then longer stock to reduce joins). This is the optimiser the
       leaders don't have.
    Raises CannotSource if nothing stocked can yield even one piece.
    """
    if count <= 0:
        return OrderResult(0, cut_len_m, 0, 0.0, 100.0, "none", [], notes="zero required")
    avail = profile.sourceable()
    kerf = profile.kerf_m

    # 1) exact stock length available
    if any(abs(s - cut_len_m) < 1e-9 for s in avail):
        order = _round_to_pack(count, profile.pack_size)
        wpk = (order * cut_len_m * profile.kg_per_m) if profile.kg_per_m else None
        spare = order - count
        total_offcut = spare * cut_len_m  # only over-ordered packs are "drop"
        return OrderResult(
            order_qty=order, stock_length_m=cut_len_m, pieces_per_length=1,
            total_offcut_m=total_offcut,
            yield_pct=round(100.0 * (count * cut_len_m) / (order * cut_len_m), 1),
            method="exact-stock",
            purchase=[Purchase(cut_len_m, order, 0.0)],
            delivered_weight_kg=wpk,
            notes=(f"bought at exact {cut_len_m:g} m length"
                   + (f"; {spare} spare from pack rounding" if spare else "")))

    # 2) cut from a longer stocked length; pick the min-waste option
    candidates = sorted(s for s in avail if s >= cut_len_m - 1e-9)
    best = None  # (total_offcut, lengths_needed, -stock, stock, per, per_off)
    for stock in candidates:
        per = _pieces_per_length(stock, cut_len_m, kerf)
        if per < 1:
            continue
        lengths = math.ceil(count / per)
        total_stock = lengths * stock
        total_off = total_stock - count * cut_len_m
        per_off = stock - (per * cut_len_m + max(0, per - 1) * kerf)
        key = (round(total_off, 6), lengths, -stock)
        if best is None or key < best[0]:
            best = (key, stock, lengths, per, total_off, per_off)
    if best is None:
        raise CannotSource(
            f"no stocked length yields a {cut_len_m:g} m piece "
            f"(stocked: {sorted(avail)})")

    _, stock, lengths, per, total_off, per_off = best
    order = _round_to_pack(lengths, profile.pack_size)
    if order != lengths:                    # pack rounding adds more drop
        total_off = order * stock - count * cut_len_m
    wpk = (order * stock * profile.kg_per_m) if profile.kg_per_m else None
    return OrderResult(
        order_qty=order, stock_length_m=stock, pieces_per_length=per,
        total_offcut_m=total_off,
        yield_pct=round(100.0 * (count * cut_len_m) / (order * stock), 1),
        method=f"cut-from-{stock:g}m",
        purchase=[Purchase(stock, order, round(per_off, 4))],
        delivered_weight_kg=wpk,
        notes=(f"{cut_len_m:g} m not stocked -> {per} per {stock:g} m length, "
               f"{per_off:g} m drop/length"))


@dataclass
class CutBin:
    """One stock length and the mixed pieces cut from it (a real cut list)."""
    stock_length_m: float
    pieces: list[float]
    offcut_m: float


def pack_cutlist(cut_lengths: list[float], stock_len: float,
                 kerf: float = 0.0) -> list[CutBin]:
    """First-Fit-Decreasing bin-pack of MIXED-length pieces into `stock_len`
    stock, minimising the number of lengths. This is the general cut optimiser
    for a real cut list (e.g. studs of different heights around openings) — the
    capability no researched competitor ships.

    Deterministic: pieces are sorted descending, ties broken by original index,
    so the output is identical every run.
    """
    order = sorted(range(len(cut_lengths)),
                   key=lambda i: (-cut_lengths[i], i))
    bins: list[CutBin] = []
    for i in order:
        piece = cut_lengths[i]
        if piece > stock_len + 1e-9:
            raise CannotSource(
                f"piece {piece:g} m exceeds stock length {stock_len:g} m")
        placed = False
        for b in bins:                       # first-fit into an existing length
            need = piece + (kerf if b.pieces else 0.0)
            if b.offcut_m + 1e-9 >= need:
                b.pieces.append(piece)
                b.offcut_m -= need
                placed = True
                break
        if not placed:                       # open a new stock length
            bins.append(CutBin(stock_len, [piece], stock_len - piece))
    for b in bins:
        b.offcut_m = round(b.offcut_m, 4)
        b.pieces.sort(reverse=True)
    return bins


def kg_per_m_from_designation(name: str) -> float | None:
    """AS/NZS steel sections encode mass/m in the name: 310UB40.4 -> 40.4,
    200UC59.5 -> 59.5. Returns the trailing mass, or None if not encoded."""
    m = re.search(r"(?:UB|UC|PFC|TFB|UBP|RSJ)\s*(\d+(?:\.\d+)?)\s*$", name, re.I)
    return float(m.group(1)) if m else None


def weight_kg(length_m: float, kg_per_m: float) -> float:
    """Deterministic member/stock weight for logistics and cranage totals."""
    return length_m * kg_per_m


def convert_linear(total_m: float, profile: StockProfile) -> OrderResult:
    """Cover a linear run of `total_m` with whole stock lengths.

    HONEST LIMITATION: from a *sum* of lengths this is an estimate — order
    `ceil(total / stock)` lengths and note it. The exact cut-optimal answer
    needs the individual member lengths (a cut list); feed those to
    `pack_cutlist` instead. For a linear run we prefer the length that
    minimises total drop (tie: longer stock -> fewer joins).
    """
    if total_m <= 0:
        return OrderResult(0, 0.0, 0, 0.0, 100.0, "none", [], notes="zero required")
    avail = sorted(profile.sourceable())
    best = None
    for stock in avail:
        lengths = math.ceil(total_m / stock - 1e-9)
        drop = lengths * stock - total_m
        key = (round(drop, 6), -stock)     # min drop, then longer stock
        if best is None or key < best[0]:
            best = (key, stock, lengths, drop)
    if best is None:
        raise CannotSource("no stocked length configured")
    _, stock, lengths, drop = best
    order = _round_to_pack(lengths, profile.pack_size)
    if order != lengths:
        drop = order * stock - total_m
    wpk = (order * stock * profile.kg_per_m) if profile.kg_per_m else None
    return OrderResult(
        order_qty=order, stock_length_m=stock, pieces_per_length=0,
        total_offcut_m=round(drop, 4),
        yield_pct=round(100.0 * total_m / (order * stock), 1),
        method=f"linear-from-{stock:g}m",
        purchase=[Purchase(stock, order, round(drop, 4))],
        delivered_weight_kg=wpk,
        notes=(f"{order} x {stock:g} m covers {total_m:g} m run (sum-based "
               f"estimate; exact cut needs a member cut list)"))


# Note: the *application* layer that maps a takeoff quantity -> a buy plan lives
# in xray.hardening (the config/wiring pass). This module is the pure, tested
# optimisation KERNEL it calls — one implementation, one place.
