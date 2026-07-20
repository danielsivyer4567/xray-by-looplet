# Templates — rough scaffolds only

**These are starting scaffolds, not schemas.** Pricing structure varies wildly
between builders, so we do NOT dictate it. Delete the sample rows and put in
**your own items, your own structure, your own prices**. The engine adapts to
you, not the other way around.

## The one thing the system anchors on: unit of measure

Every quantity the engine produces carries a **unit** — `ea`, `lm`, `m2`, `m3`,
`kg`, `t`. That unit is the join key. A price row matches a quantity on
**item (or alias) + unit**, and the price only multiplies the quantity when the
**units agree**. That's the whole contract:

> Give the engine your items with a unit of measure it recognises, and a price.
> It matches on item + unit and does the multiplication.

Price however you run your business — per lm, per m2, per each, per kg, lump
sum. We read whatever unit you price in and match it.

### When your unit differs from the engine's
If you price steel per **tonne** but the engine emits **lm**, a deterministic
conversion from the standards data pack bridges it (lm x section mass -> kg/t,
e.g. 200UB25 = 25.4 kg/m). Where no safe conversion exists, the line **flags**
for you rather than guessing.

## Still enforced, regardless of your structure
- **Dated + region-scoped** every row (`effective_date`, `region`).
- **Freshness window**: rows outside it flag `needs-human`, never price a quote.
- **Provenance**: every costed line stamps the row + date it used.
- The engine does the arithmetic; an LLM never does.

## Files
- `price-list.template.csv` — materials. Item/alias, **unit**, price, date, region.
- `labour-norms.template.csv` — hours per unit + hourly rates (editable defaults).
- `overhead-schedule.template.csv` — running costs -> daily overhead rate.
