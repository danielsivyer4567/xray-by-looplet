"""oxworks.py — import an Oxworks price list PDF into catalogue rows.

WHERE THIS SITS
---------------
This is the PRICING layer, deliberately outside the engine. The engine measures
a drawing and must stay pure, offline and deterministic; what a supplier charges
this month is none of its business. A takeoff says "87.7 lm of 65x16 radiator
panel"; this layer says what Oxworks calls that and what it costs. Keeping them
apart is what lets the engine's output stay byte-identical while prices move.

WHY PARSE FROM THE RIGHT
------------------------
The price list is a designed catalogue, not a data export: 274 pages, ~300
tables, and the column set changes table to table (COLOUR/LT/RETAIL/TRADE in
most, but also TRADE-only, RETAIL-only, plus STOCK, PACK and SIZE variants).
Binding fields to header positions would break on every variant.

What every product row DOES share is shape: a code at the left, money at the
right. So rows are anchored on the trailing price tokens and the leading code,
and the middle is peeled apart from the right — prices, then lead time, then
colour, leaving the description. A row that does not fit is never guessed at;
it is returned in `skipped` so the gap is countable instead of invisible.

PRICES ARE EVIDENCE, NOT TRUTH
------------------------------
Every row carries the page it came from and the raw line it was parsed out of,
so any figure can be checked against the PDF by a human in seconds. A price
nobody can trace is a price nobody should quote.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# Money at the end of a row: "$291.00", "$1,054.00", or "$POA" where Oxworks
# wants you to ring them. POA is preserved as None with a flag — coercing it to
# zero would quietly turn "ask us" into "free" in a quote.
PRICE_RE = re.compile(r"\$\s?(POA|[\d,]+(?:\.\d{2})?)", re.I)

# A product code: leading token, upper-alphanumeric, e.g. R1760, JIG02, FW10.5.
CODE_RE = re.compile(r"^([A-Z0-9][A-Z0-9./\-]{1,14})\s+(.*)$")

# Lead time / availability as printed: "5-7", "3-5", "10", or a stock word.
# Oxworks uses the same column for both "how many days" and "it's on the shelf",
# so both land in lead_time rather than being invented into separate fields.
LT_RE = re.compile(
    r"(?:^|\s)((?:\d{1,3}\s?-\s?\d{1,3})|\d{1,3}|TBA|POA|Stock\*?|Clearance\*?|"
    r"Ex\s+Warehouse)\s*$", re.I)

# Some tables have no code column at all — the leftmost token is a header word
# bleeding into every row. Treating "PRICE" as a product code would invent 40
# SKUs that do not exist and make the catalogue unmatchable against real orders.
NON_CODE_TOKENS = {
    "PRICE", "CODE", "ITEM", "DESC", "DESCRIPTION", "PRODUCT", "SIZE", "RRP",
    "TOTAL", "FROM", "NOTE", "ALL",
}

# The unit the price is quoted in, stated in the description itself.
#
# This must be right or the number is worse than useless: fencing quoted "per
# metre" but recorded as "each" turns a 30 m run into one unit. Oxworks writes
# the same fact many ways — "[Per Metre]", "Per Metre Standard",
# "Per Metre x 1200H", "Per Mtr", "Per Lineal Metre" — and only the bracketed
# form is common enough to notice, so an early version silently typed roughly
# 1,900 per-metre rows as "each".
#
# Matched on the word "per" only. Bare slashes in this catalogue mean other
# things entirely ("/C Colour", "/House", "/1200mm") and must not be read as
# units. Area is tested before length so "per square metre" cannot be caught by
# the metre pattern.
UNIT_PATTERNS = (
    (re.compile(r"\bper\s*(?:sqm|sq\.?\s*m|m2|m²|square\s+met(?:re|er))\b", re.I), "m2"),
    (re.compile(r"\bper\s*(?:lineal\s+|linear\s+)?(?:met(?:re|er)|mtr|lm|m)\b", re.I), "lm"),
    (re.compile(r"\bper\s*pack\b", re.I), "pack"),
    (re.compile(r"\bper\s*(?:each|ea)\b", re.I), "ea"),
)

# Colour phrases Oxworks uses in the colour column.
COLOUR_RE = re.compile(
    r"(std\s+colour|standard\s+colour|custom\s+colour|prem(?:ium)?\s+colour|"
    r"colorbond|mill\s+finish|raw|galv(?:anised)?|black|primed|n/?a)\s*$", re.I)

HEADER_RE = re.compile(r"^CODE\b(.*)$", re.I)

# Column names that mark where the header's category text stops.
HEADER_COLS = ("COLOUR", "LT", "RETAIL", "TRADE", "STOCK", "PACK", "SIZE")


@dataclass
class CatalogueRow:
    code: str | None      # None where the table prints no SKU column
    description: str
    unit: str
    prices: dict            # {"retail": 291.0, "trade": 232.0} — POA -> None
    poa: bool               # price on application; do NOT treat as zero
    colour: str | None
    lead_time: str | None
    category: str           # nearest table header, for grouping
    page: int               # 1-based PDF page, so a human can verify it
    source_line: str        # the raw line, so the parse is auditable


@dataclass
class ImportResult:
    supplier: str = "oxworks"
    currency: str = "AUD"
    tax: str = "ex-GST"
    effective: str | None = None      # as printed on the page footer
    rows: list = field(default_factory=list)
    skipped: list = field(default_factory=list)   # (page, line) never guessed at
    pages: int = 0

    def summary(self) -> str:
        poa = sum(1 for r in self.rows if r.poa)
        return (f"{len(self.rows)} rows across {self.pages} pages "
                f"({poa} POA, {len(self.skipped)} unparsed lines)")


def _parse_price(tok: str):
    if tok.upper() == "POA":
        return None, True
    return float(tok.replace(",", "")), False


def _price_labels(header: str) -> list[str]:
    """Which money columns this table declares, in printed order."""
    upper = header.upper()
    found = [(upper.find(c), c.lower()) for c in ("RETAIL", "TRADE", "STOCK")
             if c in upper]
    return [name for _, name in sorted(found)]


def _category(header_tail: str) -> str:
    """The descriptive text between CODE and the first column name."""
    upper = header_tail.upper()
    cut = len(header_tail)
    for col in HEADER_COLS:
        i = upper.find(col)
        if i != -1:
            cut = min(cut, i)
    return header_tail[:cut].strip(" -–|")


def _unit(description: str) -> str:
    for pattern, unit in UNIT_PATTERNS:
        if pattern.search(description):
            return unit
    return "ea"


def parse_line(line: str, category: str, page: int, labels: list[str]
               ) -> CatalogueRow | None:
    """One printed row -> one CatalogueRow, or None if it is not a product row."""
    raw = line.rstrip()
    stripped = raw.strip()
    if not stripped:
        return None

    prices = list(PRICE_RE.finditer(stripped))
    if not prices:
        return None                      # headings, notes, specs — not products

    head = stripped[: prices[0].start()].rstrip()
    m = CODE_RE.match(head)
    if not m:
        return None                      # money on the line, but no leading token
    code, middle = m.group(1), m.group(2).strip()

    # A header word is not a code. Keep the product (it is real and priced) but
    # say plainly that it has no SKU, so nobody tries to order "PRICE".
    if code.upper() in NON_CODE_TOKENS:
        middle = f"{code} {middle}".strip()
        code = None

    values, poa_any = [], False
    for pm in prices:
        value, is_poa = _parse_price(pm.group(1))
        values.append(value)
        poa_any = poa_any or is_poa

    # Label the money columns from the table header; fall back to position so a
    # table with an unusual header still yields usable numbers.
    names = labels or ["retail", "trade"]
    priced = {names[i] if i < len(names) else f"price{i + 1}": v
              for i, v in enumerate(values)}

    # Peel the right-hand columns off the middle: lead time, then colour.
    lead_time = None
    lt = LT_RE.search(middle)
    if lt:
        lead_time = re.sub(r"\s+", "", lt.group(1))
        middle = middle[: lt.start()].rstrip()

    colour = None
    cm = COLOUR_RE.search(middle)
    if cm:
        colour = cm.group(1).strip()
        middle = middle[: cm.start()].rstrip()

    description = re.sub(r"\s{2,}", " ", middle).strip(" -–|")
    if not description:
        return None

    return CatalogueRow(
        code=code, description=description, unit=_unit(description),
        prices=priced, poa=poa_any, colour=colour, lead_time=lead_time,
        category=category, page=page, source_line=stripped)


def parse_pages(pages: list[str]) -> ImportResult:
    """Parse already-extracted page text into catalogue rows."""
    result = ImportResult(pages=len(pages))
    category, labels = "", ["retail", "trade"]

    for index, text in enumerate(pages):
        page_no = index + 1
        if result.effective is None:
            eff = re.search(r"Current\s+([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?\s+\d{4})",
                            text)
            if eff:
                result.effective = eff.group(1)

        for line in text.splitlines():
            header = HEADER_RE.match(line.strip())
            if header:
                category = _category(header.group(1)) or category
                labels = _price_labels(line) or labels
                continue

            row = parse_line(line, category, page_no, labels)
            if row is not None:
                result.rows.append(row)
            elif PRICE_RE.search(line) and CODE_RE.match(line.strip()):
                # Looks like a product row but did not parse — record it rather
                # than let the catalogue quietly come up short.
                result.skipped.append((page_no, line.strip()))

    return result


def to_dicts(result: ImportResult) -> list[dict]:
    return [asdict(r) for r in result.rows]


# --- validation ---------------------------------------------------------------

# A plausible Oxworks SKU: letters then digits, optionally a finish suffix
# (FR6001P) or a decimal (FW10.5). Used to REPORT quality, never to discard a
# row — an unusual code is a thing to look at, not a thing to delete.
SKU_RE = re.compile(r"^[A-Z]{1,5}[0-9]{2,6}(?:\.[0-9]+)?[A-Z]{0,3}$")


def validate(result: "ImportResult") -> dict:
    """Quality report for one import. Counts, never corrects.

    A catalogue that silently drops or invents rows is worse than no catalogue,
    because it looks authoritative. These numbers are what make the import
    trustworthy enough to price real work from.
    """
    rows = result.rows
    priced = [r for r in rows if any(v is not None for v in r.prices.values())]
    odd_codes = sorted({r.code for r in rows
                        if r.code and not SKU_RE.match(r.code)})
    no_code = [r for r in rows if not r.code]
    negative = [r for r in rows
                for v in r.prices.values() if v is not None and v <= 0]

    return {
        "rows": len(rows),
        "pages": result.pages,
        "effective": result.effective,
        "distinct_codes": len({r.code for r in rows if r.code}),
        "rows_without_code": len(no_code),
        "rows_with_a_real_price": len(priced),
        "poa_rows": sum(1 for r in rows if r.poa),
        "unparsed_lines": len(result.skipped),
        "odd_looking_codes": odd_codes[:20],
        "odd_looking_code_count": len(odd_codes),
        "non_positive_prices": len(negative),
        "units": {u: sum(1 for r in rows if r.unit == u)
                  for u in sorted({r.unit for r in rows})},
        "price_columns": sorted({k for r in rows for k in r.prices}),
    }


# --- extraction + CLI ---------------------------------------------------------

def read_pdf(path: str) -> list[str]:
    """Page text from the price-list PDF. Imported lazily so parsing and
    validation stay usable (and testable) with no PDF stack installed."""
    import pypdfium2

    doc = pypdfium2.PdfDocument(path)
    return [(doc[i].get_textpage().get_text_bounded() or "")
            for i in range(len(doc))]


def import_pdf(path: str) -> ImportResult:
    return parse_pages(read_pdf(path))


CSV_COLUMNS = ("code", "description", "unit", "colour", "lead_time",
               "category", "page", "poa")


def write_csv(result: ImportResult, path: str) -> None:
    """CSV is the interchange format: every supplier's price file lands in these
    columns, whatever shape the source document was. Price columns vary by
    supplier and table, so they are appended as discovered rather than assumed.
    """
    import csv

    price_cols = sorted({k for r in result.rows for k in r.prices})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(list(CSV_COLUMNS) + price_cols + ["source_line"])
        for r in result.rows:
            w.writerow(
                [r.code or "", r.description, r.unit, r.colour or "",
                 r.lead_time or "", r.category, r.page, "yes" if r.poa else ""]
                + [("" if r.prices.get(c) is None else r.prices[c])
                   for c in price_cols]
                + [r.source_line])


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(
        prog="pricing.oxworks",
        description="Import an Oxworks price-list PDF into catalogue rows.")
    ap.add_argument("pdf", help="path to the Oxworks price list PDF")
    ap.add_argument("--out", default="oxworks-catalogue",
                    help="output basename (writes .json and .csv)")
    ap.add_argument("--report-only", action="store_true",
                    help="print the validation report and write nothing")
    args = ap.parse_args(argv)

    result = import_pdf(args.pdf)
    report = validate(result)
    print(json.dumps(report, indent=2))

    if args.report_only:
        return 0

    payload = {
        "supplier": result.supplier,
        "currency": result.currency,
        "tax": result.tax,
        "effective": result.effective,
        "source": args.pdf,
        "report": report,
        "rows": to_dicts(result),
    }
    with open(f"{args.out}.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    write_csv(result, f"{args.out}.csv")
    print(f"\nwrote {args.out}.json and {args.out}.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
