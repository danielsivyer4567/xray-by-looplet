"""DXF adapter — the hard paths, against fixtures/cad/architectural_test_fixtures_v2.dxf.

v1 proves the adapter can count blocks and read dimensions. This file proves it
survives the four traps that make CAD takeoff genuinely difficult:

  1. nested block DAG    — one INSERT can stand for dozens of parts
  2. ATTRIB overrides    — the instance's value beats the block default
  3. anonymous blocks    — countable, but never stable identity
  4. override dimensions — stated text contradicting measured geometry

Every expected number is hard-coded and was verified directly against the file
with ezdxf before the adapter was written. The recursion case is the thesis of
the whole build: a top-level-only scan reports 1 BOLT_M16 and looks perfectly
plausible while missing 24 of them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytest.importorskip("ezdxf", reason="CAD deps not installed")

from xray.sources import find_adapter  # noqa: E402
from xray.sources.dxf import block_counts  # noqa: E402

CAD2 = REPO / "fixtures" / "cad" / "architectural_test_fixtures_v2.dxf"


@pytest.fixture(scope="module")
def read():
    return find_adapter(CAD2).read(CAD2)


# ------------------------------------------------------------ nested block DAG

def test_recursion_finds_every_nested_bolt(read):
    """THE headline number. 3 assemblies x 2 brackets x 4 bolts = 24 nested,
    plus 1 free-standing = 25. A top-level scan sees only the 1."""
    assert block_counts(read.symbols)["BOLT_M16"] == 25


def test_top_level_scan_would_have_undercounted(read):
    """Guards the failure mode directly: depth-0 placements alone are 1 bolt."""
    top = [s for s in read.symbols if s.depth == 0 and s.block_name == "BOLT_M16"]
    assert len(top) == 1
    nested = [s for s in read.symbols if s.depth > 0 and s.block_name == "BOLT_M16"]
    assert len(nested) == 24


def test_full_recursive_counts(read):
    assert block_counts(read.symbols) == {
        "ASSEMBLY_GIRDER_JOINT": 3,
        "STRUCTURAL_BRACKET": 6,      # 3 assemblies x 2
        "BOLT_M16": 25,               # 24 nested + 1 direct
        "*U1": 3,
    }


def test_one_assembly_contains_eight_bolts(read):
    """The source prose claimed 24 bolts per assembly; the geometry says 8. The
    re-derived number is the evidence, not the description."""
    per = [s for s in read.symbols
           if s.block_name == "BOLT_M16" and s.path[:1] == ("ASSEMBLY_GIRDER_JOINT",)]
    assert len(per) == 24            # across all 3 assemblies
    assert len(per) / 3 == 8         # => 8 per assembly


def test_nesting_path_is_recorded(read):
    """The containment chain is what makes a nested count auditable."""
    deep = [s for s in read.symbols if s.block_name == "BOLT_M16" and s.depth == 2]
    assert deep, "expected bolts two levels down"
    assert all(s.path == ("ASSEMBLY_GIRDER_JOINT", "STRUCTURAL_BRACKET")
               for s in deep)


def test_nested_positions_use_cumulative_transform(read):
    """Nested parts report true model-space positions, not block-local ones, so
    they cannot all collapse onto the same coordinate."""
    nested = [(round(s.x, 3), round(s.y, 3))
              for s in read.symbols if s.block_name == "BOLT_M16" and s.depth > 0]
    assert len(set(nested)) == 24     # 24 distinct locations, none stacked


# ------------------------------------------------------------ ATTRIB overrides

def test_instance_attribs_beat_block_defaults(read):
    """Block ATTDEF defaults are GRADE 8.8 / TORQUE_NM 210; this placement
    overrides both. Reading the default here would understate the spec."""
    over = [s for s in read.symbols if s.overridden]
    assert len(over) == 1
    s = over[0]
    assert s.block_name == "BOLT_M16"
    assert (round(s.x), round(s.y)) == (400, 500)
    assert s.attribs["GRADE"] == "10.9"
    assert s.attribs["TORQUE_NM"] == "290"
    assert set(s.overridden) == {"GRADE", "TORQUE_NM"}


def test_unoverridden_instances_keep_defaults(read):
    """Nested bolts carry no instance ATTRIBs, so they inherit 8.8/210."""
    nested = [s for s in read.symbols
              if s.block_name == "BOLT_M16" and s.depth > 0]
    assert nested and all(s.attribs.get("GRADE") == "8.8" for s in nested)
    assert all(not s.overridden for s in nested)


# ------------------------------------------------------------ anonymous blocks

def test_anonymous_blocks_counted_but_marked(read):
    anon = [s for s in read.symbols if s.anonymous]
    assert len(anon) == 3
    assert {s.block_name for s in anon} == {"*U1"}
    assert all(s.layer == "ANONYMOUS_GROUPS" for s in anon)
    # named blocks must NOT be flagged anonymous
    assert not any(s.anonymous for s in read.symbols if s.block_name == "BOLT_M16")


# ------------------------------------------------------ override dimension trap

def test_override_dimension_keeps_both_values(read):
    """Two dimensions BOTH measure 500. One states '650.0 mm (FIELD VERIFY)'.
    The adapter must surface the disagreement, never silently pick a side."""
    dims = [g for g in read.geometry if g.kind == "dimension"]
    assert len(dims) == 2
    assert [d.value for d in dims] == [500.0, 500.0]

    clean = [d for d in dims if not d.conflict]
    bad = [d for d in dims if d.conflict]
    assert len(clean) == 1 and len(bad) == 1

    assert clean[0].text == "<>"           # derived, no override
    assert clean[0].text_value is None

    assert bad[0].value == 500.0           # what the geometry measures
    assert bad[0].text_value == 650.0      # what the drawing claims
    assert "FIELD VERIFY" in bad[0].text


def test_conflicting_dimension_is_on_its_own_layer(read):
    bad = [g for g in read.geometry if g.kind == "dimension" and g.conflict]
    assert bad[0].layer == "DIMENSIONS_OVERRIDDEN"


# ------------------------------------------------------------ units (mm trap)

def test_resolves_mm_not_the_declared_metres(read):
    """$INSUNITS says 6 (metres); an M16 bolt drawn 16 units across says mm."""
    u = read.units
    assert u["declared"] == "m"
    assert u["resolved"] == "mm"
    assert u["mismatch"] is True
    assert "BOLT_M16" in u["basis"]
    assert "$INSUNITS" not in u["basis"]


def test_resolved_unit_travels_with_measurements(read):
    assert all(g.unit == "mm" for g in read.geometry if g.kind == "dimension")
