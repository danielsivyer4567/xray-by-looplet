"""assemblies.py — Layer A: expand ONE measured quantity into a real component
cut list, then a real buy plan.

WHY this exists
---------------
A takeoff measures a wall as "6.0 lm". A builder buys studs, plates, noggins and
fixings — each a different piece, each cut from real stock. Every market tool
researched does this the same way: a recipe of per-part formulas (count =
length / centre) times a flat waste %, then a manual round. NONE of them then
run a real stock-length cut optimiser on the result — they make you hand-author
the stock->SKU mapping. This module is the recipe layer (table stakes) wired
straight into the cut optimiser (the differentiator, xray.orders).

WHAT this is
------------
A deterministic recipe: given a measured wall length (+ height) and a dated,
editable config, it emits component `Quantity` rows — studs, plates, noggins,
fixings — each carrying `order_qty` and `purchase[]` computed by the tested
kernel in xray.orders (convert_uniform for identical pieces, convert_linear for
runs, pack_cutlist for mixed-height cut lists).

HOW it stays honest
-------------------
The measured length is EVIDENCE and never changes — every component cites it,
plus the named recipe rule. Counts are exact integer formulas, not an LLM guess.
Waste is not a magic %: the cut optimiser reports the REAL offcut of real stock,
and any extra breakage factor is a named `Allowance` with a source (Layer C),
applied auditable-ly and off by default so the base numbers are exact.

This layer is ADDITIVE and OPT-IN. It is not auto-applied by the engine or the
hardening pass, so existing takeoff baselines (and their byte-identity gate) are
untouched. A caller invokes `expand_wall(...)` explicitly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from xray.quantify import Quantity
from xray.orders import (
    StockProfile, Allowance, OrderResult,
    convert_uniform, convert_linear, pack_cutlist,
    apply_allowances,
)

ASSEMBLY_DEFAULTS_DATE = "2026-07-22"

# Common Australian sawn-timber stock lengths (m), shortest first. A builder
# edits this; nothing here is hardcoded past this dated default.
AU_TIMBER_STOCK_M = (2.4, 2.7, 3.0, 3.6, 4.2, 4.8, 5.4, 6.0)

DEFAULT_WALL_CONFIG = {
    "date": ASSEMBLY_DEFAULTS_DATE,
    "recipe": "external_wall_90x45_MGP10",
    "stud_centre_m": 0.600,          # AS framing: 450 or 600 centres
    "double_top_plate": False,       # single top + single bottom = 2 plate rows
    "noggin_rows": 1,                # rows of noggins/blocking up the wall
    "stud_thickness_m": 0.045,       # 90x45 -> 45 mm face (noggin = centre - thickness)
    "fixings_per_stud": 4,           # 2 fixings each end (to top + bottom plate)
    # Stock profiles for each component. Cut lengths are chosen by the optimiser.
    "stud_stock_m": AU_TIMBER_STOCK_M,
    "plate_stock_m": AU_TIMBER_STOCK_M,
    "noggin_stock_m": AU_TIMBER_STOCK_M,
    "kerf_m": 0.0,                   # saw kerf between pieces; 0 = ignore
    "timber_kg_per_m": None,         # set to enable timber weight rollup (else omitted)
    # Layer C — named breakage/cutting allowances applied to raw COUNTS before
    # ordering. Empty by default: the cut optimiser already reports real offcut,
    # so we do not inflate with a magic %. A builder adds e.g.
    # Allowance("breakage", 1.05, "company default (timber)").
    "stud_allowances": (),
}


def _r1(v: float) -> float:
    return round(float(v), 1)


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _purchase_rows(res: OrderResult, source: str) -> list[dict]:
    """OrderResult.purchase -> Quantity.purchase dict rows, each sourced."""
    rows = []
    for p in res.purchase:
        rows.append({
            "stock_length_m": p.stock_length_m,
            "count": p.count,
            "ordered_m": round(p.stock_length_m * p.count, 4),
            "offcut_m": round(p.offcut_m, 4),
            "method": res.method,
            "source": source,
        })
    return rows


@dataclass(frozen=True)
class WallInput:
    """One measured wall. `length_m` is the takeoff evidence this recipe expands;
    `height_m` is the stud cut length (finished wall height). `evidence` carries
    the id(s) of the measured quantity so every component traces back to it."""
    length_m: float
    height_m: float
    evidence: tuple[str, ...] = ()
    label: str = "wall"


def expand_wall(wall: WallInput, config: dict | None = None) -> list[Quantity]:
    """Expand ONE measured wall length into component quantities + buy plans.

    Deterministic. Emits: studs (identical pieces -> convert_uniform), plates
    (linear runs -> convert_linear), noggins (identical short pieces ->
    convert_uniform), fixings (a count). The measured length is evidence and
    never changes; every row cites it plus the recipe rule.
    """
    cfg = config or DEFAULT_WALL_CONFIG
    date = cfg["date"]
    recipe = cfg["recipe"]
    centre = float(cfg["stud_centre_m"])
    kerf = float(cfg.get("kerf_m", 0.0))
    kgm = cfg.get("timber_kg_per_m")
    L = float(wall.length_m)
    H = float(wall.height_m)
    lbl = wall.label
    rule_id = f"recipe:{recipe}/{lbl}"
    ev = list(wall.evidence) + [rule_id]
    out: list[Quantity] = []

    # --- studs: ceil(L / centre) + 1, each cut to wall height ---------------
    bays = math.ceil(L / centre - 1e-9)          # openings between end studs
    raw_studs = bays + 1
    allowances = list(cfg.get("stud_allowances", ()))
    stud_count = raw_studs
    stud_alw_records: list[dict] = []
    if allowances:
        adjusted, stud_alw_records = apply_allowances(raw_studs, allowances)
        stud_count = math.ceil(adjusted - 1e-9)
    stud_profile = StockProfile(
        "stud", preferred=tuple(cfg["stud_stock_m"]), kerf_m=kerf,
        kg_per_m=kgm)
    stud_res = convert_uniform(H, stud_count, stud_profile)
    stud_formula = (f"ceil({_fmt(L)} / {_fmt(centre)}) + 1 = {bays} + 1 "
                    f"= {raw_studs} studs @ {_fmt(H)} m")
    if allowances:
        stud_formula += f" -> {stud_count} after allowances"
    q = Quantity(
        id=f"qty-{lbl}-studs", trade="carpentry", item="wall studs 90x45",
        qty=_r1(stud_count), unit="ea", formula=stud_formula, tier="reconciled",
        evidence=list(ev),
        notes=(f"studs at {int(centre * 1000)} mm centres (recipe {recipe}, "
               f"default {date}); {stud_res.notes}"),
        order_qty=stud_res.order_qty,
        allowances=stud_alw_records,
        purchase=_purchase_rows(
            stud_res, f"stud stock {list(cfg['stud_stock_m'])} (default {date})"))
    if stud_res.delivered_weight_kg is not None:
        q.notes += f"; ~{round(stud_res.delivered_weight_kg, 1)} kg delivered"
    out.append(q)

    # --- plates: (2 + double_top) rows running the wall length -------------
    plate_rows = 2 + (1 if cfg["double_top_plate"] else 0)
    plate_lm = plate_rows * L
    plate_profile = StockProfile(
        "plate", preferred=tuple(cfg["plate_stock_m"]), kerf_m=kerf, kg_per_m=kgm)
    plate_res = convert_linear(plate_lm, plate_profile)
    out.append(Quantity(
        id=f"qty-{lbl}-plates", trade="carpentry", item="wall plates 90x45",
        qty=_r1(plate_lm), unit="lm",
        formula=(f"{plate_rows} rows x {_fmt(L)} m "
                 f"({'double' if cfg['double_top_plate'] else 'single'} top + "
                 f"bottom) = {_fmt(plate_lm)} lm"),
        tier="reconciled", evidence=list(ev),
        notes=(f"plates run the wall length (recipe {recipe}, default {date}); "
               f"{plate_res.notes}"),
        order_qty=plate_res.order_qty,
        purchase=_purchase_rows(
            plate_res, f"plate stock {list(cfg['plate_stock_m'])} (default {date})")))

    # --- noggins: one per bay per row, each (centre - stud thickness) long --
    noggin_len = centre - float(cfg["stud_thickness_m"])
    noggin_count = bays * int(cfg["noggin_rows"])
    noggin_profile = StockProfile(
        "noggin", preferred=tuple(cfg["noggin_stock_m"]), kerf_m=kerf, kg_per_m=kgm)
    noggin_res = convert_uniform(noggin_len, noggin_count, noggin_profile)
    out.append(Quantity(
        id=f"qty-{lbl}-noggins", trade="carpentry", item="wall noggins 90x45",
        qty=_r1(noggin_count), unit="ea",
        formula=(f"{bays} bays x {int(cfg['noggin_rows'])} row(s) = {noggin_count} "
                 f"noggins @ {noggin_len:g} m (centre {_fmt(centre)} - "
                 f"thickness {_fmt(cfg['stud_thickness_m'])})"),
        tier="reconciled", evidence=list(ev),
        notes=(f"noggins between studs (recipe {recipe}, default {date}); "
               f"{noggin_res.notes}"),
        order_qty=noggin_res.order_qty,
        purchase=_purchase_rows(
            noggin_res, f"noggin stock {list(cfg['noggin_stock_m'])} (default {date})")))

    # --- fixings: a count, no stock conversion ------------------------------
    fixings = stud_count * int(cfg["fixings_per_stud"])
    out.append(Quantity(
        id=f"qty-{lbl}-fixings", trade="carpentry", item="stud-to-plate fixings",
        qty=_r1(fixings), unit="ea",
        formula=(f"{stud_count} studs x {int(cfg['fixings_per_stud'])} per stud "
                 f"= {fixings}"),
        tier="single-source", evidence=list(ev),
        notes=(f"{int(cfg['fixings_per_stud'])} fixings/stud (2 each end; "
               f"recipe {recipe}, default {date})"),
        order_qty=fixings))

    return out


def pack_stud_cutlist(heights_m: list[float], config: dict | None = None,
                      stock_len_m: float | None = None) -> list[dict]:
    """Bin-pack a MIXED-height cut list (e.g. jack/cripple studs around an
    opening) into stock lengths via the tested optimiser (orders.pack_cutlist).

    Returns one dict per stock length bought: {stock_length_m, pieces, offcut_m}.
    This is the general cut-list path the recipe uses when pieces are NOT all the
    same length — the capability no researched competitor ships.
    """
    cfg = config or DEFAULT_WALL_CONFIG
    kerf = float(cfg.get("kerf_m", 0.0))
    if stock_len_m is None:
        stock_len_m = max(cfg["stud_stock_m"])
    bins = pack_cutlist(list(heights_m), float(stock_len_m), kerf=kerf)
    return [{"stock_length_m": b.stock_length_m, "pieces": list(b.pieces),
             "offcut_m": round(b.offcut_m, 4)} for b in bins]
