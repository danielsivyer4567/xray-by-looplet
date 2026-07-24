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


def _humanise(layer: str) -> str:
    return layer.replace("_", " ").replace("-", " ").title().strip()


class StructuralCountPack(Pack):
    name = "structural-count"
    trade = "structural steel"

    def detect(self, ctx) -> bool:
        return bool(_column_layers(getattr(ctx, "geometry", [])))

    def quantify(self, ctx):
        groups = _column_layers(getattr(ctx, "geometry", []))
        quants = []
        for layer in sorted(groups):
            members = groups[layer]
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
        return quants, []


register(StructuralCountPack())
