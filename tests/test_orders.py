"""Deterministic order/cut optimiser — rigorously worked, hand-verified cases.

The headline example (the stud case the spec promised) is test_stud_fallback:
33 studs @ 2.7m, 2.7m NOT stocked -> 17 x 6.0m lengths, 0.6m drop/length. Every
number here is checked against a by-hand calculation, and determinism is proven.
"""
import pytest

from xray.orders import (
    Allowance, StockProfile, Purchase, OrderResult, CannotSource,
    apply_allowances, convert_uniform, pack_cutlist,
    kg_per_m_from_designation, weight_kg, _pieces_per_length,
)

MGP10 = StockProfile(name="MGP10 90x45", preferred=(2.7, 3.0),
                     fallback=(5.4, 6.0), kg_per_m=2.2)


def test_exact_stock_no_cutting():
    # 2.7m IS stocked -> buy 33 pieces of 2.7m, zero drop, 100% yield
    p = StockProfile("t", preferred=(2.7,), available=(2.7, 6.0))
    r = convert_uniform(2.7, 33, p)
    assert r.method == "exact-stock"
    assert r.order_qty == 33
    assert r.total_offcut_m == 0.0
    assert r.yield_pct == 100.0
    assert r.purchase == [Purchase(2.7, 33, 0.0)]


def test_stud_fallback_the_headline_example():
    # 2.7m NOT stocked; only 6.0m available in fallback. By hand:
    #   6.0 / 2.7 -> 2 studs per length (2*2.7=5.4 <= 6.0; 3*2.7=8.1 > 6.0)
    #   ceil(33 / 2) = 17 lengths
    #   per-length drop = 6.0 - 5.4 = 0.6 m
    #   total drop = 17*6.0 - 33*2.7 = 102 - 89.1 = 12.9 m
    p = StockProfile("t", preferred=(2.7,), fallback=(6.0,), available=(6.0,))
    r = convert_uniform(2.7, 33, p)
    assert r.method == "cut-from-6m"
    assert r.pieces_per_length == 2
    assert r.order_qty == 17
    assert r.purchase == [Purchase(6.0, 17, 0.6)]
    assert round(r.total_offcut_m, 4) == 12.9


def test_optimiser_picks_minimum_waste_stock():
    # Both 5.4m and 6.0m stocked. 5.4/2.7 = 2 per (0 drop); 6.0/2.7 = 2 per (0.6).
    # The optimiser must choose 5.4m — the leaders make you pick by hand.
    p = StockProfile("t", preferred=(2.7,), fallback=(5.4, 6.0),
                     available=(5.4, 6.0))
    r = convert_uniform(2.7, 33, p)
    assert r.stock_length_m == 5.4
    assert r.pieces_per_length == 2
    assert r.order_qty == 17           # ceil(33/2)
    # total drop = 17*5.4 - 33*2.7 = 91.8 - 89.1 = 2.7 (one spare stud only)
    assert round(r.total_offcut_m, 4) == 2.7
    assert r.purchase[0].offcut_m == 0.0   # 2*2.7 == 5.4 exactly, no per-length drop


def test_kerf_reduces_pieces_per_length():
    # 3 studs @ 1.95m from 6.0m: no kerf -> 3 per (5.85<=6.0). With 0.1 kerf:
    #   3*1.95 + 2*0.1 = 6.05 > 6.0 -> only 2 per length.
    assert _pieces_per_length(6.0, 1.95, 0.0) == 3
    assert _pieces_per_length(6.0, 1.95, 0.1) == 2


def test_pack_rounding_bundles():
    # pack_size 5: 17 lengths -> rounded up to 20 (multiple of 5).
    p = StockProfile("t", preferred=(2.7,), fallback=(6.0,), available=(6.0,),
                     pack_size=5)
    r = convert_uniform(2.7, 33, p)
    assert r.order_qty == 20
    # drop recomputed on the rounded order: 20*6.0 - 89.1 = 30.9
    assert round(r.total_offcut_m, 4) == 30.9


def test_cannot_source_flags_needs_human():
    # need a 7.0m member but nothing stocked reaches it
    p = StockProfile("t", preferred=(7.0,), fallback=(6.0,), available=(6.0,))
    with pytest.raises(CannotSource):
        convert_uniform(7.0, 3, p)


def test_delivered_weight_is_deterministic():
    # 33 @ 2.7 from 6.0m at 2.2 kg/m -> 17*6.0*2.2 = 224.4 kg delivered
    p = StockProfile("t", preferred=(2.7,), fallback=(6.0,), available=(6.0,),
                     kg_per_m=2.2)
    r = convert_uniform(2.7, 33, p)
    assert r.delivered_weight_kg == 224.4


def test_determinism_identical_output():
    a = convert_uniform(2.7, 33, MGP10).as_dict()
    b = convert_uniform(2.7, 33, MGP10).as_dict()
    assert a == b


# ---- mixed-length cut list (FFD bin-pack) --------------------------------

def test_cutlist_ffd_packs_and_minimises_bins():
    # pieces [2.4, 2.4, 1.2, 0.6] into 6.0m stock. FFD (desc): 2.4,2.4,1.2,0.6
    #   bin1: 2.4 -> 4.8 -> 6.0 (2.4+2.4+1.2); 0.6 doesn't fit -> bin2
    bins = pack_cutlist([2.4, 2.4, 1.2, 0.6], 6.0)
    assert len(bins) == 2
    assert bins[0].pieces == [2.4, 2.4, 1.2]
    assert bins[0].offcut_m == 0.0
    assert bins[1].pieces == [0.6]
    assert bins[1].offcut_m == 5.4


def test_cutlist_piece_over_stock_raises():
    with pytest.raises(CannotSource):
        pack_cutlist([7.0], 6.0)


def test_cutlist_deterministic_on_ties():
    # equal-length pieces must pack identically every run
    assert ([b.pieces for b in pack_cutlist([2.0]*7, 6.0)]
            == [b.pieces for b in pack_cutlist([2.0]*7, 6.0)])
    # 7 x 2.0m into 6.0m -> 3 per bin -> 3 bins (3+3+1)
    bins = pack_cutlist([2.0] * 7, 6.0)
    assert len(bins) == 3
    assert sorted(len(b.pieces) for b in bins) == [1, 3, 3]


# ---- named/sourced allowances (beats one opaque waste %) -----------------

def test_allowances_compound_and_stay_auditable():
    base = 100.0
    adj, records = apply_allowances(base, [
        Allowance("cutting_waste", 1.05, "company default (timber)"),
        Allowance("lap", 1.075, "AS 3600 rebar splice 40d"),
    ])
    # 100 * 1.05 * 1.075 = 112.875 — laps modelled SEPARATELY, not bundled
    assert round(adj, 3) == 112.875
    assert [r["name"] for r in records] == ["cutting_waste", "lap"]
    assert records[1]["source"] == "AS 3600 rebar splice 40d"
    assert records[0]["to"] == 105.0        # audit trail: 100 -> 105 -> 112.875


def test_allowances_empty_is_identity():
    adj, records = apply_allowances(50.0, [])
    assert adj == 50.0 and records == []


# ---- AS/NZS steel weight from designation --------------------------------

def test_kg_per_m_from_designation():
    assert kg_per_m_from_designation("310UB40.4") == 40.4
    assert kg_per_m_from_designation("200UC59.5") == 59.5
    assert kg_per_m_from_designation("250PFC35.5") == 35.5
    assert kg_per_m_from_designation("90x45 MGP10") is None   # not a steel section


def test_weight_kg_deterministic():
    # a 6.0m 310UB40.4 beam weighs 6.0 * 40.4 = 242.4 kg
    assert round(weight_kg(6.0, kg_per_m_from_designation("310UB40.4")), 1) == 242.4


# ---- linear run -> stock lengths (min-waste selection) -------------------

def test_convert_linear_min_waste_length():
    from xray.orders import convert_linear
    # 92.085 m over {6,8,9}: 6m->16 (96, drop 3.915); 8m->12 (96, 3.915);
    # 9m->11 (99, 6.915). Min drop 3.915, tie 6/8 -> longer 8m wins.
    r = convert_linear(92.085, StockProfile("s", preferred=(6.0, 8.0, 9.0)))
    assert r.stock_length_m == 8.0
    assert r.order_qty == 12
    assert round(r.total_offcut_m, 3) == 3.915


def test_convert_linear_zero():
    from xray.orders import convert_linear
    r = convert_linear(0.0, StockProfile("s", preferred=(6.0,)))
    assert r.order_qty == 0
