"""Layer A (assemblies) — every number here is hand-computed, so the test is the
oracle, not the code. The measured wall length is evidence and never changes;
the recipe only expands it into components and a real buy plan via the tested
xray.orders kernel.
"""
from xray.assemblies import (
    WallInput, expand_wall, pack_stud_cutlist, DEFAULT_WALL_CONFIG,
)
from xray.orders import Allowance


# A 6.0 m wall, 2.4 m high, default recipe (600 centres, single top plate,
# 1 noggin row, 90x45). Hand-derived:
#   bays  = ceil(6.0 / 0.6)        = 10
#   studs = bays + 1               = 11   (each 2.4 m -> exact stock, 0 drop)
#   plates= 2 rows x 6.0 m         = 12.0 lm -> 2 x 6.0 m (0 drop)
#   noggins = 10 bays x 1 row      = 10 @ 0.555 m -> 1 x 6.0 m (0.45 m drop)
#   fixings = 11 studs x 4         = 44
WALL = WallInput(length_m=6.0, height_m=2.4, evidence=("qty-wall-A",), label="wA")


def _by_item(rows):
    return {r.item: r for r in rows}


def test_component_set_and_counts():
    rows = expand_wall(WALL)
    got = _by_item(rows)
    assert set(got) == {
        "wall studs 90x45", "wall plates 90x45",
        "wall noggins 90x45", "stud-to-plate fixings",
    }
    assert got["wall studs 90x45"].qty == 11.0
    assert got["wall plates 90x45"].qty == 12.0
    assert got["wall noggins 90x45"].qty == 10.0
    assert got["stud-to-plate fixings"].qty == 44.0


def test_studs_bought_at_exact_stock_zero_drop():
    studs = _by_item(expand_wall(WALL))["wall studs 90x45"]
    assert studs.order_qty == 11
    assert studs.purchase == [{
        "stock_length_m": 2.4, "count": 11, "ordered_m": 26.4,
        "offcut_m": 0.0, "method": "exact-stock",
        "source": f"stud stock {list(DEFAULT_WALL_CONFIG['stud_stock_m'])} "
                  f"(default {DEFAULT_WALL_CONFIG['date']})",
    }]
    assert studs.tier == "reconciled"


def test_plates_linear_two_by_six():
    plates = _by_item(expand_wall(WALL))["wall plates 90x45"]
    assert plates.qty == 12.0
    assert plates.order_qty == 2
    p = plates.purchase[0]
    assert p["stock_length_m"] == 6.0 and p["count"] == 2
    assert p["ordered_m"] == 12.0 and p["offcut_m"] == 0.0
    assert p["method"] == "linear-from-6m"


def test_noggins_cut_optimised_single_six_metre_length():
    # 10 noggins x 0.555 m = 5.55 m all fit one 6.0 m length -> 0.45 m drop.
    # The optimiser picks 6.0 m (1 length, 0.45 drop) over 3.0 m (2 lengths,
    # same 0.45 drop) on the fewer-lengths tie-break — a real cut decision no
    # flat-waste formula makes.
    noggins = _by_item(expand_wall(WALL))["wall noggins 90x45"]
    assert noggins.qty == 10.0
    assert noggins.order_qty == 1
    p = noggins.purchase[0]
    assert p["stock_length_m"] == 6.0 and p["count"] == 1
    assert p["offcut_m"] == 0.45 and p["method"] == "cut-from-6m"


def test_fixings_count():
    fixings = _by_item(expand_wall(WALL))["stud-to-plate fixings"]
    assert fixings.qty == 44.0 and fixings.order_qty == 44
    assert fixings.purchase == []  # a count, no stock conversion


def test_measured_length_is_evidence_on_every_row():
    rows = expand_wall(WALL)
    for r in rows:
        # the measured quantity id AND the recipe rule are both cited
        assert "qty-wall-A" in r.evidence
        assert any(e.startswith("recipe:") for e in r.evidence)
    # the recipe never rewrites the measured driver — 6.0 m stays 6.0 m
    # (it appears only as the source of the derivation, in the formula)
    assert "6" in _by_item(rows)["wall plates 90x45"].formula


def test_deterministic():
    def snap(rows):
        return [(r.id, r.qty, r.order_qty, tuple(sorted(map(str, r.purchase))),
                 r.formula) for r in rows]
    assert snap(expand_wall(WALL)) == snap(expand_wall(WALL))


def test_450_centres():
    # 6000 / 450 = 13.33 -> 14 spaces -> 15 studs
    rows = expand_wall(WallInput(6.0, 2.4, label="c450"),
                       {**DEFAULT_WALL_CONFIG, "stud_centre_m": 0.450})
    got = _by_item(rows)
    assert got["wall studs 90x45"].qty == 15.0
    assert got["wall noggins 90x45"].qty == 14.0  # 14 bays x 1 row


def test_double_top_plate_three_rows():
    rows = expand_wall(WALL, {**DEFAULT_WALL_CONFIG, "double_top_plate": True})
    plates = _by_item(rows)["wall plates 90x45"]
    assert plates.qty == 18.0        # 3 rows x 6.0 m
    assert plates.order_qty == 3     # 3 x 6.0 m


def test_named_allowance_is_recorded_and_lifts_count():
    # Layer C: a +5% breakage allowance takes 11 studs -> ceil(11.55) = 12,
    # and the factor+source travel with the row (auditable, not a magic %).
    cfg = {**DEFAULT_WALL_CONFIG,
           "stud_allowances": (Allowance("breakage", 1.05,
                                         "company default (timber)"),)}
    rows = expand_wall(WALL, cfg)
    got = _by_item(rows)
    studs = got["wall studs 90x45"]
    assert studs.order_qty == 12
    assert studs.allowances and studs.allowances[0]["name"] == "breakage"
    assert studs.allowances[0]["source"] == "company default (timber)"
    assert studs.allowances[0]["factor"] == 1.05
    # fixings follow the lifted stud count
    assert got["stud-to-plate fixings"].qty == 48.0  # 12 x 4


def test_no_allowance_by_default_means_exact_counts():
    # base recipe must NOT inflate — the cut optimiser reports real drop instead
    studs = _by_item(expand_wall(WALL))["wall studs 90x45"]
    assert studs.allowances == []


def test_pack_stud_cutlist_mixed_heights():
    # Jack/cripple studs of mixed heights around an opening -> FFD bin-pack.
    #   [2.4, 2.4, 1.2, 1.2, 0.9] into 6.0 m stock:
    #   bin1: 2.4+2.4+1.2 = 6.0 (0 drop) ; bin2: 1.2+0.9 = 2.1 (3.9 drop)
    bins = pack_stud_cutlist([2.4, 2.4, 1.2, 1.2, 0.9])
    assert bins == [
        {"stock_length_m": 6.0, "pieces": [2.4, 2.4, 1.2], "offcut_m": 0.0},
        {"stock_length_m": 6.0, "pieces": [1.2, 0.9], "offcut_m": 3.9},
    ]


def test_zero_length_wall_is_empty_buy_plan():
    rows = expand_wall(WallInput(0.0, 2.4, label="z"))
    got = _by_item(rows)
    # ceil(0) = 0 bays -> 1 stud, 0 noggins; no crash, honest small plan
    assert got["wall noggins 90x45"].qty == 0.0
    assert got["wall studs 90x45"].qty == 1.0
