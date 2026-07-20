"""quantify.py — stage 6: rule packs turning spec + entities + checks into
quantities with evidence chains.

Deterministic only: an LLM never produces a quantity. Entities and checks are
duck-typed (grammar/chains objects or equivalents); this module never imports
grammar.

Shed pack expectations (CONTEXT.md, tolerance +/-1 unit / 0.5%):
  frames = bays + 1 = 5 ea
  portal steel lm = frames * (2*eave + 2*(W/2 / cos(pitch))) = 87.7
  roof sheeting m2 = 2 * L * (W/2 / cos(pitch)) = 146.2
  openings from schedule TAGs as counted items (single-source)
  wall cladding = needs-human with OPEN-bay note (bay 1 open both sides)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


@dataclass
class Quantity:
    id: str
    trade: str
    item: str
    qty: float
    unit: str            # ea|lm|m2|m3|kg|t
    formula: str
    tier: str            # reconciled|single-source|needs-human
    evidence: list[str] = field(default_factory=list)
    notes: str = ""
    order_qty: float | None = None       # orderable amount after allowances (None => use qty)
    allowances: list = field(default_factory=list)   # [{name, factor, source}]
    purchase: list = field(default_factory=list)     # [{stock_length_m, count, offcut_m, ...}]


def _r1(v: float) -> float:
    return round(float(v), 1)


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _frame_count_confirmed(checks, frames: int):
    """A count-evidence check that confirms the frame count (e.g. the
    'PORTAL RAFTER' label appearing exactly frames times)."""
    for c in checks or []:
        if getattr(c, "kind", None) != "count" or getattr(c, "status", None) != "pass":
            continue
        detail = str(getattr(c, "detail", "") or "")
        keyword = re.search(r"portal|rafter|frame", detail, re.I) is not None
        numbers = {int(n) for n in re.findall(r"\d+", detail)}
        if keyword or frames in numbers:
            return c
    return None


def shed_pack(spec: dict, entities, checks) -> list[Quantity]:
    """Quantity rule pack for portal-frame sheds (spec token LxWxH|pitch|bays)."""
    L = float(spec["L"])
    W = float(spec["W"])
    eave = float(spec["eave"])
    pitch = float(spec["pitch"])
    bays = int(spec["bays"])

    entities = list(entities or [])
    checks = list(checks or [])

    spec_ent = next((e for e in entities if getattr(e, "type", None) == "SPEC"), None)
    base_ev = [spec_ent.id] if spec_ent is not None else []

    out: list[Quantity] = []

    # --- frames -------------------------------------------------------------
    frames = bays + 1
    count_check = _frame_count_confirmed(checks, frames)
    frames_tier = "reconciled" if count_check is not None else "single-source"
    frames_ev = base_ev + ([count_check.id] if count_check is not None else [])
    out.append(Quantity(
        id="qty-frames",
        trade="structural steel",
        item="portal frames",
        qty=_r1(frames),
        unit="ea",
        formula=f"bays + 1 = {bays} + 1 = {frames}",
        tier=frames_tier,
        evidence=frames_ev,
        notes=("frame count confirmed by label count check"
               if count_check is not None else
               "frame count derived from spec token only"),
    ))

    # --- portal steel -------------------------------------------------------
    rafter_m = (W / 2.0) / math.cos(math.radians(pitch))
    per_frame = 2.0 * eave + 2.0 * rafter_m
    portal_lm = _r1(frames * per_frame)
    out.append(Quantity(
        id="qty-portal-steel",
        trade="structural steel",
        item="portal frame steel (columns + rafters)",
        qty=portal_lm,
        unit="lm",
        formula=(f"{frames} x (2 x {_fmt(eave)} + 2 x ({_fmt(W)}/2 / cos {_fmt(pitch)}deg)) "
                 f"= {frames} x {per_frame:.4f} = {portal_lm} lm"),
        tier=frames_tier,
        evidence=frames_ev,
        notes="member lengths from spec geometry; no haunch/purlin allowance",
    ))

    # --- roof sheeting --------------------------------------------------------
    roof_m2 = _r1(2.0 * L * rafter_m)
    out.append(Quantity(
        id="qty-roof-sheeting",
        trade="roofing",
        item="roof sheeting",
        qty=roof_m2,
        unit="m2",
        formula=(f"2 x {_fmt(L)} x ({_fmt(W)}/2 / cos {_fmt(pitch)}deg) "
                 f"= 2 x {_fmt(L)} x {rafter_m:.4f} = {roof_m2} m2"),
        tier="single-source",
        evidence=base_ev,
        notes="plan area on slope, both roof planes; no laps/flashings",
    ))

    # --- openings from TAG / schedule entities --------------------------------
    tag_groups: dict[str, list] = {}
    for e in entities:
        if getattr(e, "type", None) != "TAG":
            continue
        v = getattr(e, "value", None)
        label = v if isinstance(v, str) and v else str(getattr(e, "raw", "") or "")
        label = label.strip().upper()
        if not label:
            continue
        tag_groups.setdefault(label, []).append(e)
    for label in sorted(tag_groups):
        group = tag_groups[label]
        slug = re.sub(r"[^A-Z0-9]+", "-", label).strip("-").lower()
        out.append(Quantity(
            id=f"qty-opening-{slug}",
            trade="openings",
            item=f"opening {label}",
            qty=_r1(len(group)),
            unit="ea",
            formula=f"count of {label} tags on plan = {len(group)}",
            tier="single-source",
            evidence=[e.id for e in group],
            notes="from opening tags/schedule; sizes per schedule row",
        ))

    # --- wall cladding (needs-human: OPEN bay) --------------------------------
    open_labels = [
        e for e in entities
        if getattr(e, "type", None) == "LABEL"
        and "OPEN" in str(getattr(e, "raw", "") or "").upper()
    ]
    bay_len = L / bays if bays else 0.0
    side_walls = 2.0 * L * eave
    open_deduct = 2.0 * bay_len * eave if open_labels else 0.0
    rise_m = math.tan(math.radians(pitch)) * (W / 2.0)
    ends = 2.0 * (W * eave + 0.5 * W * rise_m)
    cladding_m2 = _r1(side_walls - open_deduct + ends)
    if open_labels:
        formula = (f"2 x {_fmt(L)} x {_fmt(eave)} - 2 x {bay_len:g} x {_fmt(eave)} (OPEN bay) "
                   f"+ 2 x ({_fmt(W)} x {_fmt(eave)} + 0.5 x {_fmt(W)} x {rise_m:.3f}) "
                   f"= {cladding_m2} m2")
        notes = ("OPEN bay marked both sides - one bay of side-wall cladding excluded; "
                 "confirm open extents and opening deductions before ordering")
    else:
        formula = (f"2 x {_fmt(L)} x {_fmt(eave)} "
                   f"+ 2 x ({_fmt(W)} x {_fmt(eave)} + 0.5 x {_fmt(W)} x {rise_m:.3f}) "
                   f"= {cladding_m2} m2")
        notes = ("no OPEN-bay label found - verify whether any bay is open "
                 "before ordering wall cladding")
    out.append(Quantity(
        id="qty-wall-cladding",
        trade="cladding",
        item="wall cladding",
        qty=cladding_m2,
        unit="m2",
        formula=formula,
        tier="needs-human",
        evidence=base_ev + [e.id for e in open_labels],
        notes=notes,
    ))

    return out
