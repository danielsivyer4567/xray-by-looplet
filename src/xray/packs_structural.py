"""packs_structural.py — count structural components drawn as polylines.

Not every drawing places components as blocks. A structural plan routinely draws
each column as a closed polyline footprint on a named layer
(PERIMETER_COLUMNS, CORE_COLUMNS). The block-counter sees nothing there; this
pack counts polylines per structural layer, so "236 perimeter + 45 core columns"
becomes a real, evidenced quantity the same way a block count would.

This is the durable fix for the flake "the engine read the file but counted
nothing": it is **layer-semantic** — it recognises a countable component from the
LAYER NAME plus the geometry, not from a block. The same idea makes provenance
robust (a trade-semantic layer means a real drawing), so counting and
authenticity share one notion of "what this layer means".
"""
from __future__ import annotations

import re
from collections import defaultdict

from xray.quantify import Quantity
from xray.packs import Pack, register

# Layers that carry COUNTABLE structural members — one polyline = one member.
# Word-boundary-ish so COLUMN/COL/PIER/PILE match but a stray substring doesn't.
RE_COLUMN = re.compile(r"COLUMN|(?:^|[^A-Z])COL(?:[^A-Z]|$)|PIER|PILE|STANCHION", re.I)
# Layers whose CLOSED outline is a plan AREA (gross floor / slab), not a member.
RE_AREA = re.compile(r"FOOTPRINT|GROSS|SLAB|FLOOR.?PLATE", re.I)

# drawing unit -> metres; "" (unresolved) -> None so an area can't be faked in m2
UNIT_TO_M = {"mm": 0.001, "cm": 0.01, "dm": 0.1, "m": 1.0, "km": 1000.0,
             "in": 0.0254, "ft": 0.3048, "yd": 0.9144}


def _column_layers(geometry):
    """{layer: [polyline Measures]} for every layer whose name means 'column'."""
    groups: dict[str, list] = defaultdict(list)
    for g in geometry or []:
        if getattr(g, "kind", None) != "polyline":
            continue
        layer = getattr(g, "layer", "") or ""
        if RE_COLUMN.search(layer):
            groups[layer].append(g)
    return groups


def _area_polys(geometry):
    """Closed polylines on an area layer (footprint / slab) that carry an area."""
    return [g for g in geometry or []
            if getattr(g, "kind", None) == "polyline"
            and getattr(g, "area", None)
            and RE_AREA.search(getattr(g, "layer", "") or "")]


def _humanise(layer: str) -> str:
    return layer.replace("_", " ").replace("-", " ").title().strip()


class StructuralCountPack(Pack):
    name = "structural-count"
    trade = "structural steel"

    def detect(self, ctx) -> bool:
        geo = getattr(ctx, "geometry", [])
        return bool(_column_layers(geo) or _area_polys(geo))

    def quantify(self, ctx):
        geometry = getattr(ctx, "geometry", [])
        quants = []

        # --- countable members (columns) ------------------------------------
        for layer in sorted(_column_layers(geometry)):
            members = _column_layers(geometry)[layer]
            n = len(members)
            slug = re.sub(r"[^a-z0-9]+", "-", layer.lower()).strip("-")
            quants.append(Quantity(
                id=f"q-struct-{slug}",
                trade="structural steel",
                item=_humanise(layer),
                qty=float(n),
                unit="ea",
                formula=f"count of polyline footprints on layer {layer} = {n}",
                # exact count of placed footprints, corroborated by the layer's
                # own name — two signals agree, so reconciled (as a block count is).
                tier="reconciled",
                evidence=[g.id for g in members if getattr(g, "id", "")],
                notes="each closed polyline on this structural layer is one member"))

        # --- gross plan area from a closed footprint/slab outline ------------
        for g in _area_polys(geometry):
            layer = getattr(g, "layer", "") or ""
            slug = re.sub(r"[^a-z0-9]+", "-", layer.lower()).strip("-")
            factor = UNIT_TO_M.get(getattr(g, "unit", "") or "")
            ev = [g.id] if getattr(g, "id", "") else []
            if factor is None:                       # unit unresolved -> flag, don't fake
                quants.append(Quantity(
                    id=f"q-area-{slug}", trade="structural", item=f"{_humanise(layer)} area",
                    qty=round(g.area, 1), unit="m2", tier="needs-human", evidence=ev,
                    formula=f"closed area on layer {layer} (drawing units, unit unresolved)",
                    notes="drawing unit could not be resolved — set units and re-run"))
            else:
                area_m2 = round(g.area * factor * factor, 1)
                quants.append(Quantity(
                    id=f"q-area-{slug}", trade="structural", item=f"{_humanise(layer)} area",
                    qty=area_m2, unit="m2", tier="single-source", evidence=ev,
                    formula=f"polygon area of the {layer} outline = {area_m2} m2",
                    notes="gross plan area of the closed outline (one floor)"))
        return quants, []


register(StructuralCountPack())
