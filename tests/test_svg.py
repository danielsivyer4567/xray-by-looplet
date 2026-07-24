"""SVG source adapter — the third vector format (PDF / DXF / SVG).

Proven against fixtures/svg/sample-plan.svg (a CAD-style export: named groups as
layers, rects as column footprints, a text dimension). The same trade packs that
key on layer names work on it, and the unit rules apply (SVG width is declared,
so unverified -> area needs-human).
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray.engine import run                       # noqa: E402
from xray.sources import find_adapter             # noqa: E402
from xray.sources.svg import SvgAdapter           # noqa: E402

FIXTURE = REPO / "fixtures" / "svg" / "sample-plan.svg"


def _q(result, item):
    return next((q for q in result["quantities"] if q["item"] == item), None)


@pytest.fixture(scope="module")
def result():
    return run(str(FIXTURE))


def test_svg_adapter_claims_svg():
    assert find_adapter(FIXTURE).name == "svg"


def test_named_groups_become_layers_and_pack_counts_them(result):
    """The PERIMETER_COLUMNS group's rects are counted by the structural pack —
    an SVG whose groups are named like CAD layers works like a DXF."""
    per = _q(result, "Perimeter Columns")
    assert per is not None and per["qty"] == 5.0 and per["tier"] == "reconciled"


def test_closed_shape_area_converts_by_unit(result):
    """The 12 m x 8 m footprint rect -> 96 m2; needs-human because the SVG width
    unit is declared, not corroborated."""
    area = _q(result, "Footprint area")
    assert area is not None and area["qty"] == 96.0 and area["unit"] == "m2"
    assert area["tier"] == "needs-human"


def test_svg_unit_is_read_but_unverified(result):
    u = result["document"]["units"]
    assert u["resolved"] == "mm" and u["verified"] is False
    assert any(c["kind"] == "unit-unverified" for c in result["checks"])


def test_svg_is_vector_and_text_reads(result):
    assert result["document"]["pages"][0]["kind"] == "vector"
    # the <text>16000</text> became an entity through the text pipeline
    assert any("16000" in str(e.get("raw", "")) for e in result["entities"])


def test_use_and_line_parse(tmp_path):
    """<use> is the block-instance equivalent (a Symbol); <line> is geometry."""
    svg = textwrap.dedent('''\
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:xlink="http://www.w3.org/1999/xlink"
             width="100mm" height="100mm" viewBox="0 0 100 100">
          <g id="COLS"><use xlink:href="#col" x="10" y="10"/><use xlink:href="#col" x="90" y="10"/></g>
          <line x1="0" y1="0" x2="30" y2="40"/>
        </svg>''')
    f = tmp_path / "u.svg"
    f.write_text(svg, encoding="utf-8")
    read = SvgAdapter().read(f)
    assert len(read.symbols) == 2 and read.symbols[0].block_name == "col"
    assert read.symbols[0].layer == "COLS"
    lines = [g for g in read.geometry if g.kind == "line"]
    assert len(lines) == 1 and abs(lines[0].value - 50.0) < 1e-6   # 3-4-5 -> 50
