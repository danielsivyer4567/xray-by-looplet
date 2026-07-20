# PDX — Handover: getting the viewer up to scratch

**What PDX is.** PDX is the plan *viewer* — one of the two front doors onto the
model (Looplet CRM is the other). It does **not** produce quantities. It opens a
plan, renders the sheets, and shows the X-Ray engine's takeoff as an interactive
right-hand rail with two-way highlighting back to the drawing. Everything it
displays is produced by the engine; PDX renders it, never recomputes it. That is
the same discipline the deterministic quote formatter follows — the number on the
screen is the number in `takeoff.json`, byte for byte.

**Status / why this note exists.** The engine (X-Ray by Looplet, v0.1.0, 123
tests green) is done and its output contract is stable. PDX itself is not in this
repo and isn't checked out on this machine, so this is the definition of *up to
scratch*: the concrete work PDX has to do against the engine's real contract to
pass its gate. The roadmap calls this **P5 — PDX X-Ray rail**, and the gate is:
*open the marked 50-page warehouse in PDX; click any line → the sheet highlights
its evidence in under 100 ms.*

Before I can write PDX code with you, I need three things (listed at the bottom):
the **PDX source path**, the **framework** it's built on, and whether it ingests
**offline** (embedded JSON) or **live** (engine call) as its primary path.

---

## 1. The contract PDX consumes

Everything PDX needs is in the takeoff result — the dict `engine.run()` returns,
which is also embedded verbatim inside every `marked.pdf` as an attachment named
`takeoff.json`. Shape (see `schema/takeoff.schema.json` for the authority):

- `document.pages[]` — `n` (1-based), `widthPt`, `heightPt`, `kind`
  (`vector` | `raster` | `sparse`), `coverage` (`words`, `entities`,
  `tableCells`, `structuredRatio`), and `scale` (`value`, `mmPerPt`, `methods`,
  `confidence`, **`verified`**).
- `document.coverage` — `overallRatio`, `lowPages[]`.
- `entities[]` — `id`, `page` (1-based), `type`, `value`, `raw`, **`bbox`**,
  `confidence`, `source`. This is what evidence IDs resolve to.
- `checks[]` — `id`, `kind`, `status` (`pass` | `flag`), `detail`, `delta`,
  `page`, `evidence[]` (entity IDs).
- `quantities[]` — `id`, `trade`, `item`, `qty`, `unit`, `formula`, **`tier`**
  (`reconciled` | `single-source` | `needs-human`), `evidence[]` (entity/check
  IDs), `notes`; hardening adds `order_qty`, `allowances`, `purchase`.
- `review[]` — `ref`, `reason` (the items a human must confirm).

**Two conventions that will bite you if missed:**

1. **Page numbers are 1-based** everywhere in the result (`entity.page`,
   `document.pages[].n`). Your renderer is probably 0-based — convert once.
2. **Bboxes are `[x0, y0, x1, y1]` in PDF points with a TOP-LEFT origin, y-DOWN.**
   Not PDF-native (which is bottom-left, y-up). See §4 — this is the single most
   important thing for click-to-highlight to land in the right place.

---

## 2. Ingestion — pick a primary path

Three supported ways in; PDX can support more than one but should have a primary:

- **Offline (recommended for the gate).** Open a `marked.pdf`, pull the embedded
  `takeoff.json` out of the EmbeddedFiles name tree (pikepdf on the Rust/py side,
  or pdf.js `getAttachments()` in JS). Fully self-contained — no engine, no
  network, works on any marked plan someone emails you. This is exactly the gate
  scenario ("open the marked warehouse").
- **Live via MCP.** Call the engine's MCP tools: `run_takeoff(pdf_path)`,
  `run_takeoff_calibrated(pdf_path, page, p0, p1, known_mm)`, `quote_draft(...)`,
  `marked_pdf(...)`, `engine_info()`. Use this when PDX opens a *raw* plan and
  needs a fresh takeoff.
- **Live via worker.** POST the PDF to the FastAPI worker (`server/app.py`) and
  get the same JSON back. Same result, HTTP instead of MCP.

All three return the identical contract, so the rail code is written once.

---

## 3. The rail (what the user actually sees)

Right-hand rail, built from `quantities` (or the `quote_draft` envelope):

- **Grouped by trade.** Each line shows: item, `qty` + `unit`, a **tier badge**
  (reconciled = green, single-source = amber, needs-human = red), the `formula`
  as the audit basis, and a **documented evidence crop** (Sheet N · mark ·
  dimension image — see §5).
- **Review-first.** `needs-human` lines and anything in `review[]` are visually
  distinct and surfaced at the top, each with one-click **confirm** or **edit**.
- **Confidence chip.** Show `document.coverage.overallRatio` as a coverage
  indicator, and badge any page listed in `coverage.lowPages` as "low coverage —
  review". Note: a 33% overall ratio is *normal* — it's structured-output over
  all readable words, a relative diagnostic, not "only read a third of the plan".
  The real signal is `lowPages` (text-heavy sheets that fell below the bar).

---

## 4. Evidence resolution + two-way highlight (the hard part, and the gate)

Each quantity's `evidence[]` holds entity/check IDs. Resolve them:

- entity ID → `entities[]` entry → its `page` + `bbox`.
- check ID → `checks[]` entry → its own `evidence[]` of entity IDs → bboxes.

**Coordinate math.** `bbox = [x0, y0, x1, y1]`, PDF points, **top-left origin,
y-down**.

- Rendering a page to a canvas at scale `s` (top-left origin — pdf.js, PDFium
  bitmaps): the highlight rect is simply `[x0*s, y0*s, (x1-x0)*s, (y1-y0)*s]`.
  **No flip.**
- Overlaying in a PDF-native (bottom-left, y-up) coordinate space instead: flip
  y with the page height — `y_pdf = heightPt - y1 … heightPt - y0`. Page height
  is `document.pages[n].heightPt`. (This is the exact flip `markup_writer._pdf_rect`
  does when it writes annotations, so you can cross-check against the marked PDF.)

**Interactions:**

- Click a rail line → pan to the entity's page, zoom to the *union* of its
  evidence bboxes (pad ~8pt), flash a highlight.
- Click a mark on the sheet → hit-test the cursor against entity bboxes on that
  page → select the corresponding rail line.

**Hit the <100 ms gate** by precomputing on load: an `id → entity` map, a
`page → entities[]` index, and per-quantity a cached union-bbox. Don't walk the
arrays on every click.

---

## 5. Evidence crops

For each quantity, render a cropped image of the union of its evidence bboxes
(with padding) from the source page, labelled `Sheet N · <mark> · <dimension>`.
Render lazily and cache — 50-page plans with dozens of lines shouldn't crop
eagerly. On raster pages the crop is just a region of the page image; on vector
pages, rasterise the region at display DPI.

---

## 6. Scale + calibration UX (accuracy backbone — don't skip)

Read `document.pages[n].scale.verified`.

- `verified: true` — scale came from a title-block token or a manual calibration;
  measured quantities on that page are trustworthy.
- `verified: false` — scale is only a paper-size guess. **Prompt to calibrate.**
  The user clicks two points on a known dimension and types the real length in mm;
  PDX calls `run_takeoff_calibrated(pdf_path, page, p0, p1, known_mm)` and reloads
  the result for that page. Wrong scale = every measured number wrong, so this
  prompt is non-negotiable for any `lm`/`m2`/`m3` line on an unverified page.

---

## 7. Review, override, and the provenance rule

This is where PDX could quietly reintroduce the exact trust problem the engine
was built to avoid, so hold the line:

- `needs-human` items → one-click **confirm** (promotes as-is) or **edit**.
- A manual measure/override tool is fine and expected — but it must write the
  result back as a **new quantity carrying its own evidence** (the mark the user
  drew, its bbox, `tier: "manual"` or similar), **never a silent mutation of an
  engine number**. Engine-derived and human-entered numbers stay separately
  traceable. PDX displays engine numbers; it does not recompute them.
- Keep the source `takeoff.json` immutable; layer edits as an overlay/patch with
  their own provenance so an auditor can always see what the engine said vs. what
  a human changed.

---

## 8. Actions out

- **Push-to-Looplet** — build the quote-draft envelope (`server/quote_lines.build_quote_draft`,
  or call the `quote_draft` MCP tool) and POST to Looplet. `rate`/`amount` stay
  `null` until pricing (P2) fills them; PDX ships the takeoff, not the price.
- **CSV / Excel export** — `report.quote_rows(result)` gives one dict per line
  (id, trade, item, qty, unit, formula, tier, evidence, notes); map straight to
  columns. An HTML quote is already available via `report.render_quote_html` if
  PDX wants a print/preview.

---

## 9. Performance budget

Tauri (Rust core + web UI), 60 fps rail interactions, virtualised rail list,
lazy + cached crops, precomputed evidence indices. A 50-page plan must stay
snappy; the gate is a click-to-highlight round trip under 100 ms.

---

## 10. Definition of done (the P5 gate)

Open the marked 50-page warehouse in PDX and:

1. The rail populates from the embedded `takeoff.json`, grouped by trade, with
   tier badges, formulas, and evidence crops.
2. Click any line → the sheet pans and highlights its evidence in **< 100 ms**;
   click a mark → the rail selects the line.
3. A page with `scale.verified: false` prompts for calibration; calibrating
   updates its measured quantities.
4. A `needs-human` line can be confirmed or edited, with the edit stored as a
   provenance-tagged overlay.
5. Push-to-Looplet and CSV export both produce correct output.

---

## What I need from you to build it with you

1. **PDX source path / repo** — it's not under `C:\repos` on this machine. Point
   me at it (or say "scaffold a new one") and I can work in it directly.
2. **Framework** — the roadmap says Tauri; confirm the frontend (React / Svelte /
   vanilla) and the PDF renderer (pdf.js vs. a Rust PDFium binding).
3. **Primary ingest path** — offline (embedded JSON from the marked PDF) or live
   (MCP / worker). This decides the first slice of code.

Give me those and the first milestone is: load a marked PDF, render page 1, and
light up one evidence bbox from the rail — the smallest end-to-end proof the
contract is wired correctly.
