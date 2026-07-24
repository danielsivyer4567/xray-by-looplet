"""rollup.py — whole-building totals from a per-floor takeoff + project params.

A floor plan states ONE floor. Building-wide numbers — total built area,
column-line length, building height — need the **floor count** and **storey
height**, which are not on the drawing. So they are inputs, and every derived
total is tiered `needs-human`: it rests on a parameter someone supplied, not on
the measured drawing. The arithmetic is deterministic; the honesty is in the tier.

If the per-floor area it builds on was itself flagged (e.g. an unverified unit),
that uncertainty is carried forward in the note — a rollup never launders a
flagged number into a confident one.
"""
from __future__ import annotations

import json
from pathlib import Path


def _columns(quantities) -> float:
    """Total columns counted on the floor (ea quantities whose item is a column)."""
    return sum(q.get("qty", 0) for q in quantities
               if q.get("unit") == "ea" and "column" in (q.get("item", "").lower()))


def _per_floor_area(quantities):
    return next((q for q in quantities
                 if str(q.get("id", "")).startswith("q-area-")), None)


def project_rollup(takeoff: dict, floors: int, floor_height_m: float) -> dict:
    """Derive building-wide totals. `floors` and `floor_height_m` are project
    inputs (not from the drawing), so every total is needs-human."""
    q = takeoff.get("quantities", [])
    building_height = round(floors * floor_height_m, 2)
    totals = [{
        "item": "building height", "qty": building_height, "unit": "m",
        "tier": "needs-human",
        "formula": f"{floors} floors x {floor_height_m:g} m storey = {building_height} m",
        "notes": "from the supplied floor count + storey height, not the drawing",
    }]

    cols = _columns(q)
    if cols:
        col_line = round(cols * building_height, 1)
        totals.append({
            "item": "column-line length", "qty": col_line, "unit": "m",
            "tier": "needs-human",
            "formula": f"{cols:g} columns x {building_height} m height = {col_line} m",
            "notes": "total vertical column length; rests on the supplied floors/height",
        })

    area = _per_floor_area(q)
    if area is not None:
        total_area = round(area.get("qty", 0) * floors, 1)
        totals.append({
            "item": "total built area", "qty": total_area, "unit": "m2",
            "tier": "needs-human",
            "formula": f"{area.get('qty')} m2/floor x {floors} floors = {total_area} m2",
            "notes": (f"per-floor area was tier '{area.get('tier')}'"
                      + ("; that flag carries forward — confirm it first"
                         if area.get("tier") != "single-source" else "")
                      + "; total rests on the supplied floor count"),
        })

    return {"floors": floors, "floorHeightM": floor_height_m,
            "perFloorColumns": cols, "totals": totals}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="xray.rollup",
        description="Whole-building totals from a floor-plan takeoff + floor count.")
    ap.add_argument("takeoff")
    ap.add_argument("--floors", type=int, required=True)
    ap.add_argument("--floor-height", type=float, required=True,
                    metavar="M", help="storey height in metres")
    a = ap.parse_args(argv)

    takeoff = json.loads(Path(a.takeoff).read_text(encoding="utf-8"))
    r = project_rollup(takeoff, a.floors, a.floor_height)
    print(f"{r['floors']} floors x {a.floor_height:g} m, "
          f"{r['perFloorColumns']:g} columns/floor:")
    for t in r["totals"]:
        print(f"  [{t['tier']}] {t['item']:<22} {t['qty']:>12,.1f} {t['unit']:<3} "
              f"{t['formula']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
