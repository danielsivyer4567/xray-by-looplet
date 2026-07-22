"""hardening.py — pre-pitch hardening: turn quantities into ORDERABLE numbers.

Four things a tradie checks first, applied deterministically with dated,
editable defaults (a builder overrides them):
  H1 wastage    order_qty = base x (1 + waste%)
  H2 laps       sheet materials carry a side/end-lap allowance
  H3 purchase   linear steel rounded to stock lengths (with offcut)
  H4 accessories ridge/barge capping, gutter, downpipes, screws from geometry

Every enrichment and accessory cites its source rule. Nothing here invents a
number an LLM would — it applies published factors to measured quantities.
"""
from __future__ import annotations

import dataclasses
import math

from xray.quantify import Quantity

DEFAULTS_DATE = "2026-07-20"

DEFAULT_CONFIG = {
    "date": DEFAULTS_DATE,
    "wastage": {"roof sheeting": 0.10, "cladding": 0.10, "steel": 0.05},
    "sheet_lap": {"roof sheeting": 0.05, "cladding": 0.05},
    "steel_stock_lengths_m": [12.0, 9.0, 6.0],
    "roof_screws_per_m2": 6.0,
    "gutter_m_per_downpipe": 12.0,
}


def _round(v):
    return round(float(v), 1)


def _match(item, table):
    it = str(item).lower()
    for key in table:
        if key in it:
            return key
    return None


def _enrich(q, cfg):
    """wastage + laps -> order_qty; linear steel -> purchase units."""
    order = q.qty
    lap_key = _match(q.item, cfg["sheet_lap"])
    if lap_key:
        f = cfg["sheet_lap"][lap_key]
        order *= (1 + f)
        q.allowances.append({"name": "laps", "factor": f,
                             "source": f"sheet lap allowance (default {cfg['date']})"})
    waste_key = _match(q.item, cfg["wastage"])
    if waste_key:
        f = cfg["wastage"][waste_key]
        order *= (1 + f)
        q.allowances.append({"name": "wastage", "factor": f,
                             "source": f"wastage {int(f * 100)}% (default {cfg['date']})"})
    if q.allowances:
        q.order_qty = _round(order)

    if q.unit == "lm" and "steel" in str(q.item).lower():
        total = q.order_qty if q.order_qty is not None else q.qty
        # Delegate stock selection to the tested optimiser (xray.orders): it picks
        # the MINIMUM-WASTE stock length, not merely the longest — one kernel.
        from xray.orders import StockProfile, convert_linear
        res = convert_linear(
            total, StockProfile("steel", preferred=tuple(cfg["steel_stock_lengths_m"])))
        q.purchase.append({
            "stock_length_m": res.stock_length_m, "count": res.order_qty,
            "ordered_m": _round(res.order_qty * res.stock_length_m),
            "offcut_m": _round(res.total_offcut_m),
            "source": f"stock lengths {cfg['steel_stock_lengths_m']} (default {cfg['date']})",
        })


def _accessories(spec, cfg, ev):
    L, W, pitch = float(spec["L"]), float(spec["W"]), float(spec["pitch"])
    rake = (W / 2.0) / math.cos(math.radians(pitch))
    roof_m2 = 2.0 * L * rake
    gutter = 2.0 * L
    date = cfg["date"]
    rows = []

    def A(qid, item, qty, unit, formula, note):
        rows.append(Quantity(id=qid, trade="roofing", item=item, qty=_round(qty),
                             unit=unit, formula=formula, tier="single-source",
                             evidence=list(ev),
                             notes=f"accessory rule (default {date}): {note}"))

    A("qty-acc-ridge", "ridge capping", L, "lm",
      f"ridge = building length L = {L:g} lm", "ridge runs the building length")
    A("qty-acc-barge", "barge / gable capping", 4 * rake, "lm",
      f"4 rakes x (W/2)/cos(pitch) = 4 x {rake:.3f} = {_round(4 * rake)} lm",
      "gable rake capping, 4 rakes")
    A("qty-acc-gutter", "gutter", gutter, "lm",
      f"2 x L (both eaves) = {gutter:g} lm", "gutter to both eaves")
    A("qty-acc-downpipe", "downpipes",
      math.ceil(gutter / cfg["gutter_m_per_downpipe"]), "ea",
      f"ceil({gutter:g} m gutter / {cfg['gutter_m_per_downpipe']:g} m per downpipe)",
      "1 downpipe per 12 m of gutter")
    A("qty-acc-screws", "roof screws", roof_m2 * cfg["roof_screws_per_m2"], "ea",
      f"roof {_round(roof_m2)} m2 x {cfg['roof_screws_per_m2']:g}/m2",
      "roof fixing screws per m2")
    return rows


def harden(quantities, spec=None, config=None, base_evidence=None):
    """Return quantities enriched with order_qty/allowances/purchase, plus
    accessory quantities. Pure; does not mutate the inputs."""
    cfg = config or DEFAULT_CONFIG
    out = []
    for q in quantities:
        q2 = dataclasses.replace(q, allowances=list(q.allowances),
                                 purchase=list(q.purchase))
        _enrich(q2, cfg)
        out.append(q2)
    if spec:
        out.extend(_accessories(spec, cfg, base_evidence or []))
    return out
