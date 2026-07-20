# Looplet Build Suite — Master Roadmap

**X-Ray · PDX · BLDR** — plan of record, agreed 2026-07-20.
Engine v0.1.0 shipped and verified (86 tests, 2 real-plan fixtures).

---

## 1. North star

One deterministic **building model** is the single source of truth. Two front
doors feed it:

- **X-Ray** — reads existing plan PDFs into the model (built, v0.1.0)
- **BLDR** — generates new models from prompts/references/material lists (future)

Everything else is a **derivation** of the model: quantities, BOM, costs,
estimates, compliance flags, exports (PDF / DXF / IFC / PNG), the PDX side
rail, and Looplet quote lines. Build each derivation once; both front doors
get it for free.

## 2. The laws (non-negotiable; already in force in v0.1.0)

1. **An LLM never produces a quantity, price, or compliance verdict.** LLMs
   translate intent (BLDR chat, dialect triage, prose). Deterministic code
   makes every number.
2. **Stale or uncertain data is never silently used** — it becomes a
   `needs-human` flag. Applies equally to dimensions, prices, and code
   versions.
3. **Provenance on everything**: engine version, price-list date, code-pack
   version, evidence refs. Any output can always say what it was derived from.
4. **Every item carries two IDs**: a human **mark number** (M12, S03, B26) and
   a machine **UUID**. The mark is for drawings, rails, and conversations; the
   UUID is for databases, sync, and dedupe. Both are stable for the life of
   the item and travel together across plan, JSON, rail, CAD, and quote.
5. **No feature ships without a real fixture** and hand-proven ground truths
   in the test suite.

## 3. Built today (Phase 0 — done, verified)

| Piece | State |
|---|---|
| X-Ray engine v0.1.0 (extract → reassemble → grammar → scale → checks → quantify → write) | 86/86 tests green; shed + warehouse fixtures |
| Worker (FastAPI) + quote-line mapping | Tested end-to-end; `rate`/`amount` slots deliberately null awaiting P2 |
| Marked-PDF output (standards-compliant annotations + embedded takeoff.json) | Confirmed rendering live in PDX |
| Docs (GUIDE, ACCURACY, HANDOVER, mind map) | Committed |
| DXF passthrough export | Proven — audit-clean R2010, opens in any CAD; productionize in P8a |
| PDX X-Ray rail design | Mockup approved; market patterns researched (markups-list rigor, price-book costing, on-drawing verification) |

## 4. Phase map

```
P1 marks+UUIDs ─→ P2 costing ─→ P3 estimating ─→ P4 routing/MCP
      ├─→ P5 PDX rail
      └─→ P6 BOM/connections
P7 compliance packs (independent, ongoing)
P8a DXF (done) ─→ P8b recon-to-dims ─→ P8c IFC/BIM ─→ P9 BLDR (+ texture library)
P10 trade packs (independent, per fixtures supplied)
```

Sizes: S = short focused build · M = a few working sessions · L = a serious
module · XL = staged program. No dates promised; gates decide "done".

### P1 — Marks, UUIDs & contract v0.2 (S)

Human marks per trade (M## members, S## sheets/cladding, O## openings, later
B## bolts) assigned deterministically so the same plan always yields the same
marks; machine UUID alongside every mark (the annotation layer already writes
/NM UUIDs — formalise into the JSON contract). Schema bump 0.1 → 0.2 adds
`mark` + `uuid` to entities and quantities, back-compatible.
**Gate:** same shed run twice → identical marks; UUIDs stable across
re-derivations; tests updated.

### P2 — Costing (M) — FIRST, per your call

- User uploads **their own** price list (CSV): item/alias, unit, price,
  **date**, **location/region**. Their list, their prices — never ours.
- User sets a **freshness window**: rolling max age ("no older than 30 days")
  or hard cutoff date.
- Matcher: quote line (mark / item / unit) → price row; alias table absorbs
  supplier naming differences.
- In-window match → `rate`/`amount` filled and stamped ("priced from your
  list dated 12 Jul 2026"). Out-of-window or unmatched → `needs-human` flag;
  rate stays null. **Stale data never becomes a quote; it becomes a flag.**
**Gate:** shed draft costed from a sample list; stale-price and missing-price
tests flag correctly; provenance stamp on every costed line.

### P3 — Estimating (M)

- Labour norms table (user's): hours per unit per item class; hourly rates by
  location. Same freshness/provenance law as prices.
- Margins: tiered by client type / job type; show or hide cost vs sell.
- Output: sell-priced quote draft = materials + labour + margin.
**Gate:** costed shed → full estimate with labour lines; margin math tested.

### P4 — Routing & automation (M) — needs: which automations app

- MCP server exposing `takeoff`, `cost`, `estimate` as tools — one wrapper
  serves the automations app, PDX, and Looplet alike.
- Output adapters: Looplet job, quote document, CSV/Excel.
- Pre-wired automation template: trigger (plan lands) → X-Ray → cost →
  estimate → chosen destination. The user's only decision is the output
  location; optional pricing-refresh automation chains on top.
**Gate:** end-to-end run from trigger to a Looplet draft with zero manual
steps.

### P5 — PDX X-Ray rail (M–L) — needs: PDX source path

- Read the embedded takeoff.json straight out of the marked PDF.
- Clean right rail: grouped by trade, tier badges, formula, mark, and a
  **documented evidence crop** per line (Sheet N · mark · dimension image).
- **Two-way click-to-highlight**: click a rail line → sheet pans and lights up
  its evidence (bbox → page coords); click a mark on the sheet → rail selects
  the line.
- Review-first UX for `needs-human` / flags: visually distinct, one-click
  confirm or edit.
- Push-to-Looplet and CSV export actions.
- **Silky budget**: 60 fps rail interactions, lazy crop rendering, 50-page
  plans stay snappy — lightweight Tauri, no bloat.
**Gate:** open the marked 50-page warehouse in PDX; click any line →
highlight in under 100 ms.

### P6 — BOM & connections library (M) — needs: engineering details

- Assemblies (portal knee, apex, base plate…) → member cuts + fastener counts,
  each with a B## mark + UUID, **citing the engineering detail or standard it
  came from**. Fasteners are computed from the structure, never "seen" on the
  2D plan — and the citation is the evidence.
- Model → complete material list (members, sheets, fixings) with marks; feeds
  costing automatically.
**Gate:** shed BOM down to bolts; every line evidenced to a detail; priced
via P2.

### P7 — Compliance packs & code updater (M per pack; ongoing)

- Per-provision deterministic checks against named NCC / AS-NZS clauses
  (spans, bracing, wind region, egress…). Result = **flag + clause ref +
  evidence — never a compliance certificate.** That line is permanent, by
  design and for liability.
- Every result stamped with the code-pack version it ran against.
- Updater = monitored source feed → human-reviewed pack release → versioned
  distribution. The engine never auto-trusts a scrape of legal text.
**Gate:** first pack (sheds) flags a seeded-violation fixture and passes a
compliant one.

### P8 — CAD line (a done · b L · c M · d S)

- **a)** `xray export dxf` productionized — the passthrough underlay (proven).
- **b)** **Reconstruction-to-dimensions** (from scratch; the hard module):
  build the model from the *extracted dimensions* (16000 × 9000, 4 bays), not
  the plotted pixels — squared topology, real walls/openings. The drawing
  approximates; the dimensions are truth; we build to truth.
- **c)** IFC/BIM emit via FreeCAD headless (LGPL, Python-scriptable) —
  architect-editable model that carries its BOM natively. FreeCAD doubles as
  the free import test bench.
- **d)** CAD → PDF sheet renderer (the easy direction).
**Gate:** shed reconstructed to exact dims; opens in FreeCAD; IFC round-trip
preserves marks + UUIDs.

### P9 — BLDR (XL, staged)

- Model-ops DSL: `add_room`, `add_window(room=lounge)`,
  `add_storey(balcony=true)` — every chat edit is a model mutation, never a
  repainted image. Generation produces the model; the picture is rendered
  from it. (This is what protects accuracy, materials, scaling, and
  architect-editability.)
- LLM translates prompt/chat → ops **only**; guardrails validate ops against
  engineering + compliance packs before they apply.
- Inputs: text prompt, reference images, existing plans (via X-Ray), material
  list.
- Every edit re-derives materials, quantities, and costs live (P1–P3 reused).
- Exports: CAD / PDF / PNG (P8 reused).
- **Texture & material library — the pretty layer, deliberately last**: one
  library entry per product carries *both* appearance (texture map) and
  commercial data (unit, price link). Every model surface (wall, roof,
  counter, door, floor) is addressable: click surface → dropdown → apply.
  Because texture and material are one record, re-skinning the roof also
  updates the material list and the cost. Pretty and priced, from the same
  click.
**Gate:** prompt → draft plan → "add a window to the lounge" → quantity list
updates live → DXF + PDF + PNG export; texture swap changes the costed
material list.

### P10 — Trade expansion (M per pack) — needs: fixtures per trade

- Electrical first (needs 2–3 real plans): legend/symbol counting (GPOs,
  lights, switches, detectors) + circuit/cable runs as scaled lengths.
- Then warehouse structural, plumbing, concrete — same build-and-prove loop
  as the shed pack.
**Gate per pack:** real fixtures + hand-proven ground truths, same standard
as v0.1.0.

## 5. Inputs needed (blockers by phase)

| Input | Unblocks |
|---|---|
| Sample price list CSV + how locations should split (regions vs multiplier) | P2 |
| Labour norms + hourly rates (or approve editable defaults to start) | P3 |
| Which automations app (Looplet builder / n8n / custom) | P4 |
| PDX source repo path | P5 |
| Connection details / engineer specs for the shed system | P6 |
| 2–3 real electrical plans | P10 |
| Legal read on PyMuPDF AGPL (or approve pypdfium2 swap work) | commercial ship |

## 6. Risks & honest limits

- **AGPL licence** on the extraction library — resolve before commercial
  distribution; the swap path (pypdfium2 on the extraction stage only) is
  contained.
- **Compliance is flags-not-certificates, permanently.** The tool checks
  named provisions and cites clauses; a human signs off. Never claim more.
- **BLDR image-gen temptation**: generating pictures instead of models would
  quietly kill accuracy, materials, scaling, and editability. The DSL rule is
  the firewall — hold it.
- **P8b reconstruction is the hardest single module.** Do not let the
  passthrough DXF masquerade as it; they are different products.

## 7. Standing gates (every phase, no exceptions)

Full pytest green (86 and growing) · a real fixture behind every claim ·
CONTEXT.md updated with any new API/tolerance/finding · provenance stamps on
all outputs · marks + UUIDs preserved end-to-end.

---

*Source of truth for design decisions: `CONTEXT.md`. Integration entry point:
`docs/HANDOVER.md`. This file is the build order.*

## 8. Decisions log

| Date | Decision | Choice |
|---|---|---|
| 2026-07-20 | P2 location model | **Regional price lists** — one dated list per region; every price is exactly what that region pays |
| 2026-07-20 | P3 labour starting point | **Editable defaults approved** — template defaults ship, clearly marked, refined in-app |
| 2026-07-20 | P4 automations target | **Looplet's own builder** — X-Ray exposed as an MCP/HTTP node native to Looplet |
| 2026-07-20 | Licence path | Pending — pypdfium2 swap explained, user deciding |
