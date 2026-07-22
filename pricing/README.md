# pricing — supplier catalogues

The layer between "the drawing says 87.7 lm of 65×16 radiator panel" and "that
costs $232/m from Oxworks".

**This is not the engine.** The engine measures drawings and must stay pure,
offline and deterministic; what a supplier charges this month is none of its
business. Keeping them apart is what lets engine output stay byte-identical
while prices move underneath. Nothing here is imported by `xray.*`.

## The catalogue schema

Every supplier's price file, whatever shape the source document was, lands in
these columns. This is the contract a new supplier importer targets.

| field | meaning |
| --- | --- |
| `code` | supplier SKU. **May be null** — some tables print no code column, and inventing one makes the row unorderable |
| `description` | product text as printed, with the colour/lead-time columns peeled off |
| `unit` | `ea`, `lm`, `m2`, `pack` — what the price is *per* |
| `prices` | `{retail, trade, stock, …}` named from the table header; extra columns land as `price2…priceN` rather than being guessed |
| `poa` | price on application. The price is `null`, **never `0`** |
| `colour` | finish/colour column where the table has one |
| `lead_time` | days (`5-7`) or availability (`Stock`, `Clearance`, `Ex Warehouse`) — the catalogue uses one column for both |
| `category` | nearest table header, for grouping |
| `page` | 1-based page in the source PDF |
| `source_line` | the raw printed line this row was parsed from |

`page` + `source_line` exist so any figure can be checked against the original
in seconds. **A price nobody can trace is a price nobody should quote.**

## Importing Oxworks

```bash
python -m pricing.oxworks "<path to price list>.pdf" --out oxworks-catalogue
python -m pricing.oxworks "<path>.pdf" --report-only   # quality report, writes nothing
```

Writes `.json` (full fidelity) and `.csv` (interchange). Always read the
validation report — it counts rather than corrects, and it is what makes an
import trustworthy enough to price real work from:

```
rows, distinct_codes, rows_without_code, rows_with_a_real_price,
poa_rows, unparsed_lines, odd_looking_codes, non_positive_prices, units
```

`unparsed_lines` is the one to watch. A row that looks like a product but did
not parse is recorded, never dropped — a catalogue that silently comes up short
is worse than none, because it still looks authoritative.

### Current result (East Coast list, effective 26 Sep 2025)

3,522 rows over 274 pages · 1,111 distinct SKUs · 0 unparsed · 100 POA ·
units: 2,394 `lm`, 991 `ea`, 137 `m2`

Two things that were wrong before they were measured, both worth knowing when
writing the next supplier importer:

- **Units.** Only the bracketed `[Per Metre]` form was obvious. The catalogue
  also writes "Per Metre Standard", "Per Metre x 1200H", "Per Mtr", "Per Lineal
  Metre" — about 1,900 rows were silently typed `ea`. Fencing quoted per metre
  but recorded as each turns a 30 m run into one unit.
- **Codeless tables.** 40 rows print no SKU column, so the leftmost token was
  the word "PRICE". Reading that as a code invents products nobody can order.

## Generated data is not committed

Supplier pricing is commercially sensitive and dates fast. `pricing/out/` and
`*-catalogue.{json,csv}` are gitignored: the **importer** is version-controlled,
the **prices** are not. Regenerate from the source PDF whenever you need them.

## Adding a supplier

Write `pricing/<supplier>.py` producing `CatalogueRow`s and a `validate()`
report. Parse defensively — most price lists are designed documents, not data
exports, so bind to row *shape* rather than column position, and count what you
could not read instead of quietly dropping it.

## Mapping a takeoff to SKUs

```python
from pricing.mapping import MappingStore, map_takeoff, summarise

store = MappingStore("oxworks")            # pricing/out/oxworks-mappings.json
results = map_takeoff(takeoff["quantities"], catalogue_rows, store)
```

**The mapper proposes; a human decides.** A line is bound to a SKU only because
someone confirmed it once — after that it is remembered and nobody is asked
again. Everything else comes back as ranked candidates or `needs-human`, the
same tier the engine uses when a drawing will not tell it something.

That restraint is the feature, and the catalogue shows why. "65 x 16mm Radiator
Panel 1800MM HIGH" matches **three** rows scoring 1.00 — identical descriptions
at **$480, $393 and $348** on pages 136, 137 and 138. Auto-accepting the top hit
would quietly cost 38% more on an order nobody questioned.

- **Units are a gate, not a score.** A per-metre product cannot fulfil an m2
  line, whatever the words say. Mismatch disqualifies outright.
- **Deterministic.** Token and dimension arithmetic only — no LLM, no network.
  The same inputs always rank the same way, so a review is reproducible.
- **Explained.** Every candidate carries a `why` and the source page, so a
  price can be checked against the PDF before it is trusted.
- **Memory is per supplier**, keyed on the normalised item *and* its unit —
  buying "panel" by the metre and by the square metre are different commercial
  decisions and are confirmed separately. Stored as readable JSON with who
  confirmed each one and when; a builder can audit or correct it by hand.

Mappings live in `pricing/out/` and are gitignored along with the prices.
