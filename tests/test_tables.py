"""Unit tests for tables.extract_tables on synthetic word lists."""
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from xray.tables import extract_tables  # noqa: E402


@dataclass
class W:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int = 0
    source: str = "text"


def _row(y, cells):
    return [W(t, x, y, x + max(1, len(t)) * 4.0, y + 8.0) for t, x in cells]


def test_simple_table():
    words = []
    words += _row(10, [("Name", 20), ("Qty", 120), ("Unit", 200)])
    words += _row(20, [("Beam", 20), ("5", 120), ("ea", 200)])
    words += _row(30, [("Bolt", 20), ("40", 120), ("ea", 200)])
    words += _row(40, [("Plate", 20), ("8", 120), ("kg", 200)])
    tables = extract_tables(words, (300, 300))
    assert len(tables) == 1
    t = tables[0]
    assert t.headers == ["Name", "Qty", "Unit"]
    ds = t.as_dicts()
    assert len(ds) == 3
    assert ds[0] == {"Name": "Beam", "Qty": "5", "Unit": "ea"}
    assert ds[2] == {"Name": "Plate", "Qty": "8", "Unit": "kg"}


def test_multiword_cell_stays_in_column():
    words = []
    words += _row(10, [("Item", 20), ("Value", 160)])
    words += _row(20, [("Air", 20), ("Con", 45), ("5", 160)])  # "Air Con" both in col 0
    words += _row(30, [("Pump", 20), ("9", 160)])
    words += _row(40, [("Fan", 20), ("3", 160)])
    tables = extract_tables(words, (300, 300))
    assert len(tables) == 1
    ds = tables[0].as_dicts()
    assert ds[0]["Item"] == "Air Con"
    assert ds[0]["Value"] == "5"


def test_two_tables_split_by_vertical_gap():
    words = []
    words += _row(10, [("H1", 20), ("H2", 120)])
    words += _row(18, [("a1", 20), ("b1", 120)])
    words += _row(26, [("a2", 20), ("b2", 120)])
    words += _row(34, [("a3", 20), ("b3", 120)])
    # big gap -> second table
    words += _row(140, [("X", 20), ("Y", 120)])
    words += _row(148, [("x1", 20), ("y1", 120)])
    words += _row(156, [("x2", 20), ("y2", 120)])
    tables = extract_tables(words, (300, 300))
    assert len(tables) == 2
    assert tables[0].headers == ["H1", "H2"]
    assert tables[1].headers == ["X", "Y"]


def test_preamble_row_is_not_the_header():
    words = []
    words += _row(6, [("REPORT TITLE", 20)])          # 1-word preamble, doesn't align
    words += _row(20, [("Name", 20), ("Qty", 120), ("Unit", 200)])
    words += _row(30, [("Beam", 20), ("5", 120), ("ea", 200)])
    words += _row(40, [("Bolt", 20), ("40", 120), ("ea", 200)])
    tables = extract_tables(words, (300, 300))
    assert tables and tables[0].headers == ["Name", "Qty", "Unit"]
