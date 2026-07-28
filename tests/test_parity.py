"""Tests for the parity gate — the thing that decides whether a non-oracle
runtime (frozen sidecar, WASM, container) is allowed to ship.

The gate's whole value is that it FAILS when it should, so most of these tests
are about detecting tampering and reporting it usefully. A gate that only ever
passes is decoration.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from parity.compare import (  # noqa: E402
    REFERENCE_DIR, canonical, compare, compare_file, digest, first_divergence,
    load_manifest, strip_volatile,
)

MANIFEST = load_manifest()
FIXTURES = sorted(MANIFEST["fixtures"])


def _reference(fixture: str) -> dict:
    return json.loads((REFERENCE_DIR / f"{fixture}.json").read_text("utf-8"))


# --- the references themselves are self-consistent ----------------------------

@pytest.mark.parametrize("fixture", FIXTURES)
def test_reference_file_matches_its_pinned_digest(fixture):
    """The JSON on disk must hash to the digest recorded in the manifest,
    otherwise the two halves of the gate disagree and neither can be trusted."""
    assert digest(_reference(fixture)) == MANIFEST["fixtures"][fixture]["sha256"]


@pytest.mark.parametrize("fixture", FIXTURES)
def test_reference_file_is_stored_in_canonical_form(fixture):
    """The bytes on disk ARE the bytes hashed — no reformatting step in between."""
    raw = (REFERENCE_DIR / f"{fixture}.json").read_text("utf-8")
    assert raw == canonical(json.loads(raw))


@pytest.mark.parametrize("fixture", FIXTURES)
def test_reference_passes_the_gate(fixture):
    result = compare(_reference(fixture), fixture)
    assert result.ok, result.report()


# --- canonical form -----------------------------------------------------------

def test_document_path_is_ignored():
    """The same drawing must hash identically from any directory — otherwise
    every user's output would differ and byte-identity would be meaningless."""
    a = _reference(FIXTURES[0])
    b = json.loads(json.dumps(a))
    b["document"]["path"] = r"D:\somewhere\completely\else.pdf"
    assert digest(a) == digest(b)


def test_strip_volatile_does_not_mutate_its_input():
    a = _reference(FIXTURES[0])
    before = json.dumps(a, sort_keys=True)
    strip_volatile(a)
    assert json.dumps(a, sort_keys=True) == before


def test_key_order_does_not_affect_the_digest():
    a = _reference(FIXTURES[0])
    reversed_top = dict(reversed(list(a.items())))
    assert digest(a) == digest(reversed_top)


# --- the gate detects tampering ----------------------------------------------

def test_changed_quantity_fails_and_is_located():
    """The failure mode that matters: a runtime that reports a different number."""
    fixture = "shed-manners-aline"
    bad = _reference(fixture)
    assert bad["quantities"], "fixture should carry quantities to tamper with"
    bad["quantities"][0]["qty"] = bad["quantities"][0]["qty"] + 1

    result = compare(bad, fixture)
    assert not result.ok
    assert result.divergence is not None
    assert "quantities[0].qty" in result.divergence
    assert "FAIL" in result.report()


def test_dropped_quantity_is_reported_as_a_length_change():
    fixture = "shed-manners-aline"
    bad = _reference(fixture)
    bad["quantities"] = bad["quantities"][:-1]
    result = compare(bad, fixture)
    assert not result.ok
    assert "length" in (result.divergence or "")


def test_unknown_fixture_raises():
    with pytest.raises(KeyError):
        compare({}, "no-such-fixture")


# --- divergence reporting -----------------------------------------------------

def test_first_divergence_returns_none_when_identical():
    a = _reference(FIXTURES[0])
    assert first_divergence(a, json.loads(json.dumps(a))) is None


def test_first_divergence_names_a_nested_path():
    assert first_divergence({"a": {"b": [1, 2]}}, {"a": {"b": [1, 3]}}) == \
        "a.b[1]: 2 != 3"


def test_first_divergence_flags_missing_and_extra_keys():
    assert "missing in expected" in first_divergence({}, {"x": 1})
    assert "missing in actual" in first_divergence({"x": 1}, {})


def test_first_divergence_flags_a_type_change():
    """A runtime emitting "13" where the oracle emits 13 is a real bug — JSON
    number vs string is exactly the kind of thing a WASM port gets wrong."""
    found = first_divergence({"qty": 13}, {"qty": "13"})
    assert "type" in found


# --- file entry point (how CI actually calls it) ------------------------------

def test_compare_file_infers_the_fixture_from_the_filename(tmp_path):
    fixture = FIXTURES[0]
    # Mirrors what the engine writes: "<fixture>.xray.json"
    p = tmp_path / f"{fixture}.xray.json"
    p.write_text(canonical(_reference(fixture)), encoding="utf-8")
    assert compare_file(p).ok


def test_compare_file_accepts_an_explicit_fixture(tmp_path):
    fixture = FIXTURES[0]
    p = tmp_path / "candidate-from-some-wasm-build.json"
    p.write_text(canonical(_reference(fixture)), encoding="utf-8")
    assert compare_file(p, fixture=fixture).ok
