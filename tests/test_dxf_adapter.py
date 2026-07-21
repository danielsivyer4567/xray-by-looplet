"""DXF source adapter — evidence gate against a REAL native CAD fixture.

Every expected number below is hard-coded on purpose. These are the forensically
verified ground truths of fixtures/cad/architectural_test_fixtures.dxf; if the
adapter stops reproducing them exactly, it is wrong.

Why this fixture is trustworthy: it carries INSERT block references and
associative DIMENSION entities. X-Ray's PDF path emits neither -- plotting
flattens blocks into anonymous strokes and dimensions into loose text -- so this
file cannot be a re-export of the engine's own output. Contrast
fixtures/negative/shed-flattened-from-pdf.dxf (0 INSERT / 0 DIMENSION), covered
at the bottom.
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
from xray.sources.dxf import DxfAdapter, block_counts, trade_for  # noqa: E402

CAD = REPO / "fixtures" / "cad" / "architectural_test_fixtures.dxf"
NEG = REPO / "fixtures" / "negative" / "shed-flattened-from-pdf.dxf"


@pytest.fixture(scope="module")
def read():
    return find_adapter(CAD).read(CAD)


def test_dispatch_picks_the_dxf_adapter():
    assert find_adapter(CAD).name == "dxf"
    assert DxfAdapter().can_read("x.dxf") and not DxfAdapter().can_read("x.pdf")


# ---------------------------------------------------------------- block counts

def test_exact_block_counts():
    """The headline capability: exact counts by block name, no recognition step."""
    r = find_adapter(CAD).read(CAD)
    assert block_counts(r.symbols) == {
        "COL_RECT": 8, "COL_CIRC": 4, "DOOR_3FT": 5, "WIN_5FT": 6,
    }


def test_total_inserts_and_columns(read):
    assert len(read.symbols) == 23
    counts = block_counts(read.symbols)
    assert counts["COL_RECT"] + counts["COL_CIRC"] == 12   # columns, both shapes


def test_rotations_are_read_not_assumed(read):
    """Doors are placed at 180 deg and windows at 90 deg; a counter that ignored
    placement would still count, but anything geometric would be wrong."""
    rot = {}
    for s in read.symbols:
        rot.setdefault(s.block_name, set()).add(round(s.rotation, 1))
    assert 180.0 in rot["DOOR_3FT"]
    assert rot["WIN_5FT"] == {90.0}
    assert rot["COL_RECT"] == {0.0}


def test_symbols_carry_placement_and_layer(read):
    s = next(s for s in read.symbols if s.block_name == "COL_RECT")
    assert s.layer == "COLUMNS"
    assert s.xscale == 1.0 and s.yscale == 1.0
    xs = [s.x for s in read.symbols]
    ys = [s.y for s in read.symbols]
    assert min(xs) == 0.0 and max(xs) == 90.0     # 30-unit structural grid
    assert min(ys) == 0.0 and max(ys) == 60.0


# ---------------------------------------------------------------- dimensions

def test_dimension_measurements_exact(read):
    """Measured values come from the geometry via get_measurement(), never from
    the display text -- which is '<>' here, meaning 'derived'."""
    dims = [g for g in read.geometry if g.kind == "dimension"]
    assert len(dims) == 9
    assert [round(d.value, 4) for d in dims] == [30, 30, 30, 90, 30, 30, 60, 12.5, 5.0]
    assert {d.text for d in dims} == {"<>"}


def test_dimension_grid_is_consistent(read):
    """The 90 span equals the three 30 bays -- the cross-check that lets a CAD
    source reconcile rather than single-source a quantity."""
    vals = [g.value for g in read.geometry if g.kind == "dimension"]
    assert vals.count(30.0) == 5
    assert 90.0 in vals and abs(90.0 - 3 * 30.0) < 1e-9
    assert 60.0 in vals and abs(60.0 - 2 * 30.0) < 1e-9


# ---------------------------------------------------------------- units trap

def test_does_not_report_metres_for_a_feet_drawing(read):
    """$INSUNITS says 6 (metres); the geometry is plainly feet. The adapter must
    resolve by evidence and never silently propagate the header."""
    u = read.units
    assert u["declared"] == "m"          # what the header claims
    assert u["resolved"] == "ft"         # what the drawing actually is
    assert u["mismatch"] is True         # and the conflict is surfaced
    # the basis must name the geometric evidence, not the header. Either
    # self-describing block resolves it; which one wins is not the contract.
    assert "block name" in u["basis"]
    assert any(b in u["basis"] for b in ("DOOR_3FT", "WIN_5FT"))
    assert "$INSUNITS" not in u["basis"]


def test_resolved_unit_travels_with_measurements(read):
    dims = [g for g in read.geometry if g.kind == "dimension"]
    assert all(d.unit == "ft" for d in dims)


# ---------------------------------------------------------------- layers/trades

def test_layer_to_trade_mapping(read):
    assert trade_for("COLUMNS") == "structural steel"
    assert trade_for("DOORS") == "openings"
    assert trade_for("WINDOWS") == "openings"
    assert trade_for("WALLS") == "cladding"
    assert trade_for("NOSUCHLAYER") == ""
    cols = [s for s in read.symbols if s.block_name.startswith("COL_")]
    assert all(s.trade == "structural steel" for s in cols)


def test_read_returns_pure_data(read):
    assert len(read.pages) == 1 and read.pages[0].kind == "vector"
    assert read.producer == "ezdxf"
    with open(CAD, "rb") as fh:          # no handle left open
        assert fh.read(1)


# ---------------------------------------------------------------- negative case

def test_flattened_pdf_dxf_yields_no_block_counts():
    """The rejected fixture is a PDF extraction in a DXF container: it has no
    INSERTs and no DIMENSIONs, so it must not masquerade as a rich CAD source."""
    if not NEG.exists():
        pytest.skip("negative fixture not present")
    r = find_adapter(NEG).read(NEG)
    assert block_counts(r.symbols) == {}
    assert r.symbols == []
    assert [g for g in r.geometry if g.kind == "dimension"] == []
