"""The mapper proposes; a human decides.

The failure this guards against is a confident wrong order: a takeoff line bound
to a plausible-looking SKU that nobody checked, arriving as delivered steel. So
the tests care less about ranking quality than about the mapper's refusal to
auto-accept, and about units being a hard gate.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pricing.mapping import (  # noqa: E402
    MappingStore, map_takeoff, propose, score, summarise, tokens,
    units_compatible,
)

CATALOGUE = [
    {"code": "R1760", "description": "65 x 16mm Radiator Panel - 900MM HIGH [Per Metre]",
     "unit": "lm", "prices": {"retail": 291.0, "trade": 232.0}, "poa": False, "page": 138},
    {"code": "R1761", "description": "65 x 16mm Radiator Panel - 1800MM HIGH [Per Metre]",
     "unit": "lm", "prices": {"retail": 430.0, "trade": 348.0}, "poa": False, "page": 138},
    {"code": "LS100", "description": "Laser Screen PLAIN SHEET ONLY - PER SQM",
     "unit": "m2", "prices": {"retail": 217.0, "trade": 197.0}, "poa": False, "page": 83},
    {"code": "G500", "description": "Gate Latch Heavy Duty", "unit": "ea",
     "prices": {"retail": 40.0, "trade": 32.0}, "poa": False, "page": 20},
]


@pytest.fixture
def store(tmp_path):
    return MappingStore("oxworks", tmp_path / "m.json")


# --- units are a gate -----------------------------------------------------------

def test_a_per_metre_product_cannot_fulfil_an_area_line(store):
    """No description similarity makes $232/m the right answer for m2."""
    result = propose("Radiator Panel 65 x 16mm", "m2", CATALOGUE, store)

    assert all(c.unit != "lm" for c in result.candidates)


def test_unit_mismatch_scores_zero_not_merely_less():
    value, why = score("Radiator Panel 900MM", "ea", CATALOGUE[0])

    assert value == 0.0
    assert "cannot fulfil" in why


@pytest.mark.parametrize("a,b,ok", [
    ("lm", "lm", True), ("lm", "m", True), ("m2", "sqm", True),
    ("ea", "each", True), ("lm", "ea", False), ("m2", "lm", False),
    ("ea", "pack", False),
])
def test_unit_compatibility(a, b, ok):
    assert units_compatible(a, b) is ok


# --- nothing is auto-accepted ---------------------------------------------------

def test_a_perfect_looking_match_is_still_needs_human(store):
    """Even an obvious match must not bind itself. Confirmation is the product."""
    result = propose("65 x 16mm Radiator Panel - 900MM HIGH", "lm", CATALOGUE, store)

    assert result.status == "needs-human"
    assert result.candidates[0].code == "R1760"
    assert "human confirms" in result.note


def test_a_line_with_no_plausible_match_says_so(store):
    result = propose("bituminous roof membrane", "m2", CATALOGUE, store)

    assert result.status == "needs-human"
    assert result.candidates == []
    assert "different supplier" in result.note


# --- memory ---------------------------------------------------------------------

def test_a_confirmed_mapping_is_used_next_time(store):
    store.confirm("65 x 16mm Radiator Panel - 900MM HIGH", "lm", "R1760",
                  by="daniel", when="2026-07-23")

    result = propose("65 x 16mm Radiator Panel - 900MM HIGH", "lm", CATALOGUE, store)

    assert result.status == "mapped"
    assert result.code == "R1760"
    assert result.confirmed_by == "daniel"


def test_memory_survives_a_round_trip_to_disk(store, tmp_path):
    store.confirm("Gate Latch", "ea", "G500", by="daniel", when="2026-07-23")
    store.save()

    reloaded = MappingStore("oxworks", store.path)

    assert len(reloaded) == 1
    assert propose("Gate Latch", "ea", CATALOGUE, reloaded).code == "G500"


def test_reworded_but_equivalent_lines_hit_the_same_memory(store):
    """Word order and case should not force a second confirmation."""
    store.confirm("Heavy Duty Gate Latch", "ea", "G500", by="daniel",
                  when="2026-07-23")

    assert propose("gate latch heavy duty", "ea", CATALOGUE, store).code == "G500"


def test_the_same_words_in_a_different_unit_is_a_separate_decision(store):
    """Buying "panel" by the metre and by the square metre are different
    commercial choices and must be confirmed separately."""
    store.confirm("Radiator Panel", "lm", "R1760", by="daniel", when="2026-07-23")

    assert propose("Radiator Panel", "m2", CATALOGUE, store).status == "needs-human"


def test_a_mapping_can_be_withdrawn(store):
    store.confirm("Gate Latch", "ea", "G500", by="daniel", when="2026-07-23")

    assert store.forget("Gate Latch", "ea") is True
    assert propose("Gate Latch", "ea", CATALOGUE, store).status == "needs-human"


# --- ranking is deterministic and explained -------------------------------------

def test_the_matching_dimension_outranks_the_mismatched_one(store):
    result = propose("65 x 16mm Radiator Panel 1800MM HIGH", "lm", CATALOGUE, store)

    assert result.candidates[0].code == "R1761"


def test_every_candidate_explains_itself(store):
    result = propose("65 x 16mm Radiator Panel - 900MM HIGH", "lm", CATALOGUE, store)

    for candidate in result.candidates:
        assert candidate.why
        assert 0.0 < candidate.score <= 1.0


def test_ranking_is_stable_across_runs(store):
    a = propose("Radiator Panel", "lm", CATALOGUE, store)
    b = propose("Radiator Panel", "lm", CATALOGUE, store)

    assert [c.code for c in a.candidates] == [c.code for c in b.candidates]


def test_candidates_carry_the_page_so_the_price_can_be_checked(store):
    result = propose("Gate Latch", "ea", CATALOGUE, store)

    assert result.candidates[0].page == 20


# --- whole takeoff --------------------------------------------------------------

def test_map_takeoff_reports_what_still_needs_a_person(store):
    store.confirm("Gate Latch", "ea", "G500", by="daniel", when="2026-07-23")
    quantities = [
        {"id": "q1", "item": "Gate Latch", "unit": "ea"},
        {"id": "q2", "item": "65 x 16mm Radiator Panel - 900MM HIGH", "unit": "lm"},
        {"id": "q3", "item": "bituminous roof membrane", "unit": "m2"},
    ]

    results = map_takeoff(quantities, CATALOGUE, store)

    assert summarise(results) == {
        "lines": 3, "mapped_from_memory": 1, "needs_human": 2,
        "with_candidates": 1, "no_candidates": 1,
    }
    assert [r.quantity_id for r in results] == ["q1", "q2", "q3"]


def test_tokens_drop_noise_words():
    assert "radiator" in tokens("65 x 16mm Radiator Panel")
    assert "mm" not in tokens("65 x 16mm Radiator Panel")


@pytest.mark.parametrize("text,expected", [
    ("1800mm high", {1800}),
    ("1800H", {1800}),
    ("sliding gate 1800 high", {1800}),
    ("Sliding Gate Per Metre x 1800H", {1800}),
    ("65 x 16mm panel", {65, 16}),
    ("Gate Latch", set()),
])
def test_dimensions_are_read_however_the_line_phrases_them(text, expected):
    """A takeoff says "1800 high" where the catalogue says "1800H". Missing that
    left every gate height scoring identically — and height is exactly what the
    builder is choosing between."""
    from pricing.mapping import dimensions
    assert dimensions(text) == expected


def test_the_right_height_now_outranks_the_wrong_one(store):
    catalogue = [
        {"code": "T1030", "description": "Sliding Gate Per Metre x 1200H",
         "unit": "lm", "prices": {"trade": 420.0}, "poa": False, "page": 201},
        {"code": "T1030", "description": "Sliding Gate Per Metre x 1800H",
         "unit": "lm", "prices": {"trade": 538.0}, "poa": False, "page": 201},
    ]
    result = propose("sliding gate 1800 high", "lm", catalogue, store)

    assert "1800H" in result.candidates[0].description
