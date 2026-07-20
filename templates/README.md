# Templates — pricing & labour (P2 / P3 inputs)

Every price and labour row is **dated** and **region-scoped**. The costing
engine refuses to use a row whose `effective_date` falls outside the user's
freshness window — stale rows flag `needs-human`, they never price a quote.
Every costed line stamps the row date it used (provenance).

## price-list.template.csv
- `item` — must match (or alias to) the engine's quantity item names.
- `alias` — semicolon-separated alternates; absorbs supplier naming.
- `unit` — must agree with the quantity unit (ea/lm/m2/m3/kg/t); mismatch flags.
- `effective_date` + `region` — the freshness/location keys.
- All prices in the shipped template are SAMPLES — replace with your list.

## labour-norms.template.csv
Two blocks: norms (hours per unit per item class) and hourly rates by role.
Same dating/region rules. Shipped values are EDITABLE DEFAULTS pending your
real numbers.

Upload path (P2 build): user uploads CSV → validated against this schema →
matcher links quote lines via item/alias + unit → in-window rows price the
line; everything else flags.
