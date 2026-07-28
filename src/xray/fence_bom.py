"""fence_bom.py — expand a measured fence run into a full, orderable bill.

The fencing pack measures what the drawing states: run length, posts, gates.
The *rest* of a fence bill — panels/palings, rails, footings, concrete, caps —
follows from the run length PLUS the fence **system** (Colorbond vs paling vs
chainmesh), which the drawing rarely spells out. So the system is an input, and
this module expands the measured length into the material list deterministically.

Honesty is in the tiers:
  * the run length is measured -> its expansions are `single-source`;
  * `concrete` rests on an assumed footing size (a site/engineering call) ->
    `needs-human`;
  * every system default (spacing, paling coverage, footing dims) is stated in
    the note, and overridable, so nothing is a silent magic number.

Defaults are common Australian conventions; a contractor confirms or overrides
them. This is trade configuration, not fabricated data.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

# Fence systems. Every value is a stated default a user can override; none is
# hidden. Dimensions in metres.
SYSTEMS = {
    "colorbond": {
        "label": "Colorbond steel",
        "post_spacing_m": 2.4, "panel_width_m": 2.4,
        "rails_per_bay": 2, "mid_rail_over_m": 1.8,   # +1 rail above this height
        "footing_dia_m": 0.25, "footing_depth_m": 0.6, "post_cap": True,
    },
    "paling": {
        "label": "Timber paling",
        "post_spacing_m": 2.4, "paling_cover_m": 0.09,   # 90 mm effective cover
        "rails_per_bay": 2, "mid_rail_over_m": 1.8,
        "footing_dia_m": 0.25, "footing_depth_m": 0.6, "post_cap": False,
    },
    "chainmesh": {
        "label": "Chainmesh",
        "post_spacing_m": 3.0, "mesh": True, "top_rail": True,
        "footing_dia_m": 0.2, "footing_depth_m": 0.6, "post_cap": False,
    },
}


def _find(quantities, qid):
    return next((q for q in quantities if q.get("id") == qid), None)


def _line(item, qty, unit, tier, formula, notes, evidence):
    slug = re.sub(r"[^a-z0-9]+", "-", item.lower()).strip("-")
    return {"id": f"q-bom-{slug}", "item": item, "qty": round(qty, 3), "unit": unit,
            "tier": tier, "formula": formula, "notes": notes,
            "evidence": list(evidence or [])}


def fence_bom(takeoff: dict, system: str = "colorbond",
              height_m: float = 1.8, overrides: dict | None = None) -> dict:
    """Expand a fence takeoff into a full material list for the chosen system."""
    if system not in SYSTEMS:
        raise ValueError(f"unknown fence system {system!r}; "
                         f"known: {', '.join(sorted(SYSTEMS))}")
    s = dict(SYSTEMS[system])
    s.update(overrides or {})

    q = takeoff.get("quantities", [])
    length_q = _find(q, "q-fence-length")
    posts_q = _find(q, "q-fence-posts")
    if length_q is None:
        return {"system": system, "height_m": height_m, "lines": [],
                "note": "no fence run in this takeoff"}

    length = float(length_q["qty"])
    run_ev = length_q.get("evidence", [])
    posts = float(posts_q["qty"]) if posts_q else None

    rails = s.get("rails_per_bay", 2) + (1 if height_m > s.get("mid_rail_over_m", 1e9) else 0)
    lines = []

    # posts + gates come straight from the measured takeoff (the physical items
    # to buy — the BOM would be incomplete without them)
    if posts is not None:
        lines.append(_line("Fence posts", posts, "ea",
            posts_q.get("tier", "single-source"), posts_q.get("formula", ""),
            "posts to set", posts_q.get("evidence", [])))
    gates_q = _find(q, "q-fence-gates")
    if gates_q:
        lines.append(_line("Gates", float(gates_q["qty"]), "ea", "single-source",
            gates_q.get("formula", ""), "gate leaf + hardware per gate",
            gates_q.get("evidence", [])))

    # rails span the whole run
    if not s.get("mesh"):
        lines.append(_line(
            f"{s['label']} rails", rails * length, "lm", "single-source",
            f"{rails} rails x {length:g} lm run = {rails * length:g} lm",
            f"{rails} rails/bay (system default; +1 mid rail above "
            f"{s.get('mid_rail_over_m')} m)", run_ev))

    # infill: sheets / palings / mesh
    if system == "colorbond":
        sheets = math.ceil(length / s["panel_width_m"])
        lines.append(_line("Colorbond sheets", sheets, "ea", "single-source",
            f"ceil({length:g} lm / {s['panel_width_m']:g} m sheet) = {sheets}",
            f"one {s['panel_width_m']:g} m sheet per bay", run_ev))
    elif system == "paling":
        palings = math.ceil(length / s["paling_cover_m"])
        lines.append(_line("Palings", palings, "ea", "single-source",
            f"ceil({length:g} lm / {s['paling_cover_m']:g} m cover) = {palings}",
            f"{s['paling_cover_m'] * 1000:g} mm effective coverage per paling", run_ev))
    elif system == "chainmesh":
        lines.append(_line("Chainmesh", round(length * height_m, 1), "m2", "single-source",
            f"{length:g} lm x {height_m:g} m high = {length * height_m:g} m2",
            "mesh area = run length x fence height", run_ev))
        lines.append(_line("Top rail", length, "lm", "single-source",
            f"{length:g} lm top rail along the run", "one top rail", run_ev))

    # footings + concrete + caps, one per post
    if posts is not None:
        lines.append(_line("Footings", posts, "ea", "single-source",
            f"one footing per post = {posts:g}", "post holes", posts_q.get("evidence", [])))
        vol = math.pi * (s["footing_dia_m"] / 2) ** 2 * s["footing_depth_m"]
        lines.append(_line("Concrete (footings)", posts * vol, "m3", "needs-human",
            f"{posts:g} footings x pi x ({s['footing_dia_m']:g}/2)^2 x "
            f"{s['footing_depth_m']:g} m = {posts * vol:.3f} m3",
            f"ASSUMES {s['footing_dia_m'] * 1000:g} mm dia x "
            f"{s['footing_depth_m'] * 1000:g} mm deep footings — confirm with the "
            "engineer/soil; footing size is a site call", posts_q.get("evidence", [])))
        if s.get("post_cap"):
            lines.append(_line("Post caps", posts, "ea", "single-source",
                f"one cap per post = {posts:g}", "", posts_q.get("evidence", [])))

    return {"system": system, "systemLabel": s["label"], "height_m": height_m,
            "runLength_m": length, "lines": lines}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="xray.fence_bom",
        description="Expand a fence takeoff into a full material list.")
    ap.add_argument("takeoff")
    ap.add_argument("--system", default="colorbond", choices=sorted(SYSTEMS))
    ap.add_argument("--height", type=float, default=1.8, metavar="M")
    ap.add_argument("--prices", metavar="CSV",
                    help="price-list CSV — cost the BOM (no LLM); see templates/")
    a = ap.parse_args(argv)

    takeoff = json.loads(Path(a.takeoff).read_text(encoding="utf-8"))
    bom = fence_bom(takeoff, system=a.system, height_m=a.height)
    print(f"{bom.get('systemLabel', a.system)} @ {a.height:g} m over "
          f"{bom.get('runLength_m', 0):g} lm:")

    if not a.prices:
        for ln in bom["lines"]:
            print(f"  [{ln['tier']:>13}] {ln['item']:<22} {ln['qty']:>8g} "
                  f"{ln['unit']:<3} {ln['formula']}")
        return 0

    # BOM -> costing: the lines are already quantity-shaped, so they feed the
    # deterministic costing engine straight through (join on item+unit, no LLM).
    from pricing.costing import load_price_list, cost_takeoff
    costed = cost_takeoff(bom["lines"], load_price_list(a.prices))
    for ln in costed["lines"]:
        amt = "" if ln["amount"] is None else f"${ln['amount']:,.2f}"
        tail = ln["provenance"] or ln["reason"]
        print(f"  {ln['item']:<22} {ln['qty']:>8g} {ln['unit']:<3} {amt:>11}  "
              f"[{ln['status']}] {tail}")
    s = costed["summary"]
    print(f"  {'TOTAL (priced)':<35} ${s['total']:,.2f}"
          f"   ({s['priced']} priced, {s['needsHuman']} need a price)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
