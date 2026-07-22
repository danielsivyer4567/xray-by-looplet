"""The hardening pass now delegates steel purchase to the tested orders kernel —
one optimiser, and it's the MINIMUM-WASTE one (an upgrade over always-longest).
"""
from xray.hardening import harden, DEFAULT_CONFIG
from xray.quantify import Quantity


def _steel(qty):
    return Quantity(id="q", trade="structural steel", item="steel beam",
                    qty=qty, unit="lm", formula="", tier="single-source")


def test_purchase_now_picks_min_waste_stock():
    # 50 lm steel, +5% wastage -> 52.5 lm. Stocks [12, 9, 6]:
    #   12m->5 (60, drop 7.5) | 9m->6 (54, 1.5) | 6m->9 (54, 1.5)
    # OLD hardening picked longest (12m, 7.5 drop). The optimiser picks 9m
    # (1.5 drop) — 6 kg less to buy, provably less waste.
    out = harden([_steel(50.0)])
    p = out[0].purchase[0]
    assert p["stock_length_m"] == 9.0
    assert p["count"] == 6
    assert p["ordered_m"] == 54.0
    assert p["offcut_m"] == 1.5


def test_shed_steel_result_unchanged_byte_for_byte():
    # The real shed case (87.7 lm, +5% -> 92.1) still resolves to 8 x 12.0m:
    # min-waste ties 12m & 6m at 96 m, longer wins — same as the committed
    # baseline, so byte-identity is preserved through the refactor.
    out = harden([_steel(87.7)])
    p = out[0].purchase[0]
    assert p == {"stock_length_m": 12.0, "count": 8, "ordered_m": 96.0,
                 "offcut_m": 3.9,
                 "source": f"stock lengths [12.0, 9.0, 6.0] (default {DEFAULT_CONFIG['date']})"}
