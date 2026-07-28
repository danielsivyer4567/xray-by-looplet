"""Tests for the Oxworks price-list importer.

The lines here are SYNTHETIC but follow the printed format exactly. Real
supplier pricing is commercially sensitive and does not belong in a repo, and
the real catalogue is proven separately by `pricing.oxworks.validate`, which
reports coverage over the actual PDF.

The bias throughout: a wrong number must never look like a right one. Unparsed
rows are counted, POA is never coerced to zero, and a unit is never guessed.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pricing.oxworks import (  # noqa: E402
    SKU_RE, parse_line, parse_pages, validate,
)

HEADER = "CODE 65 x 16mm Radiator PANELS & GATES - 100mm Gap COLOUR LT RETAIL TRADE "
ROW = ("R1760 65 x 16mm Radiator Panel - 900MM HIGH [Per Metre] "
       "Std Colour 5-7 $291.00 $232.00 ")


def one(line, category="cat", page=1, labels=("retail", "trade")):
    return parse_line(line, category, page, list(labels))


# --- the ordinary row ----------------------------------------------------------

def test_a_standard_row_splits_into_its_columns():
    row = one(ROW)

    assert row.code == "R1760"
    assert row.description == "65 x 16mm Radiator Panel - 900MM HIGH [Per Metre]"
    assert row.unit == "lm"
    assert row.prices == {"retail": 291.00, "trade": 232.00}
    assert row.colour == "Std Colour"
    assert row.lead_time == "5-7"
    assert row.poa is False


def test_the_raw_line_and_page_survive_for_auditing():
    """A price nobody can trace back to the page is a price nobody should quote."""
    row = one(ROW, page=138)

    assert row.page == 138
    assert row.source_line.startswith("R1760")


def test_thousands_separators_are_handled():
    row = one("R1780 Sliding Gate [Per Metre] Std Colour 5-7 $1,054.00 $879.00")
    assert row.prices["retail"] == 1054.00


# --- POA must never become zero -------------------------------------------------

def test_poa_is_preserved_as_unknown_not_as_free():
    row = one("R9700 Custom Spaced Radiator Panel Std Colour 5-7 $POA $POA")

    assert row.poa is True
    assert row.prices == {"retail": None, "trade": None}


def test_a_partly_poa_row_keeps_the_price_it_does_have():
    row = one("R9710 Custom Swing Gate Std Colour 5-7 $250.00 $POA")

    assert row.poa is True
    assert row.prices["retail"] == 250.00
    assert row.prices["trade"] is None


# --- units: the expensive mistake ----------------------------------------------

@pytest.mark.parametrize("text,unit", [
    ("Panel - 900MM HIGH [Per Metre]", "lm"),
    ("Panel Per Metre Standard", "lm"),
    ("Panel Per Metre x 1200H", "lm"),
    ("Glazing Post - Per Mtr", "lm"),
    ("Custom Stile Per Lineal Metre", "lm"),
    ("Laser Screen PLAIN SHEET ONLY - PER SQM", "m2"),
    ("Screen per m2", "m2"),
    ("Screen per square metre", "m2"),
    ("Fixings [Per Pack]", "pack"),
    ("Gate Latch", "ea"),
])
def test_unit_is_read_from_however_the_catalogue_phrased_it(text, unit):
    """Fencing quoted per metre but recorded as "each" turns a 30 m run into one
    unit. Only the bracketed form was common enough to notice at first, which
    silently mistyped roughly 1,900 rows."""
    assert one(f"R1000 {text} Std Colour 5-7 $10.00 $9.00").unit == unit


@pytest.mark.parametrize("text", [
    "Sawtooth Panel /C Colour",
    "Package /House",
    "Infill /1200mm",
])
def test_a_bare_slash_is_not_a_unit(text):
    """This catalogue uses "/" for colour codes and pack descriptions, not units."""
    assert one(f"R1000 {text} Std Colour 5-7 $10.00 $9.00").unit == "ea"


# --- rows that are not products -------------------------------------------------

@pytest.mark.parametrize("line", [
    "General Specifications: *NB // All Picket tops finished with cast caps",
    "* Available Swing Gate Customisations within Configurator",
    "",
    "   ",
    "CAST CAP",
])
def test_non_product_lines_are_not_invented_into_rows(line):
    assert one(line) is None


def test_a_header_word_is_not_treated_as_a_product_code():
    """Some tables print no code column. Reading the header word as a SKU would
    invent products that cannot be ordered."""
    row = one("PRICE COLOURSMART SAWTOOTH PANEL 2400*1200 Stock $100.58 $88.60")

    assert row.code is None
    assert "COLOURSMART" in row.description
    assert row.prices["retail"] == 100.58


def test_stock_words_are_read_as_availability_not_description():
    row = one("FR6001P Glass Gate Hinge - Polish SS-316L Stock $70.00 $60.00")

    assert row.lead_time.lower().startswith("stock")
    assert "Stock" not in row.description


# --- page-level parsing ---------------------------------------------------------

def test_the_table_header_sets_category_and_price_column_names():
    result = parse_pages([HEADER + "\n" + ROW])

    assert len(result.rows) == 1
    row = result.rows[0]
    assert "Radiator" in row.category
    assert set(row.prices) == {"retail", "trade"}


def test_a_trade_only_table_does_not_mislabel_its_price_as_retail():
    result = parse_pages(["CODE Brackets COLOUR LT TRADE\nB100 Bracket Std Colour 5-7 $12.00"])

    assert result.rows[0].prices == {"trade": 12.00}


def test_the_effective_date_is_taken_from_the_page():
    result = parse_pages(["Current September 26th 2025 // Prices Ex GST\n" + HEADER + "\n" + ROW])
    assert result.effective == "September 26th 2025"


# --- validation reports rather than corrects ------------------------------------

def test_validate_counts_what_matters():
    report = validate(parse_pages([HEADER + "\n" + ROW]))

    assert report["rows"] == 1
    assert report["distinct_codes"] == 1
    assert report["unparsed_lines"] == 0
    assert report["non_positive_prices"] == 0
    assert report["units"] == {"lm": 1}


def test_validate_surfaces_codeless_rows_instead_of_hiding_them():
    result = parse_pages(["PRICE Panel 2400*1200 Stock $100.58 $88.60"])
    assert validate(result)["rows_without_code"] == 1


@pytest.mark.parametrize("code,ok", [
    ("R1760", True), ("FR6001P", True), ("JIG02", True), ("FW10.5", True),
    ("PACKAGING", False), ("CHARGE", False),
])
def test_sku_shape_is_only_used_to_flag_not_to_discard(code, ok):
    assert bool(SKU_RE.match(code)) is ok
