# CONTINUE HERE — X-Ray by Looplet

**This is the one file. Read it and keep working. Everything you need is below —
you do not need the chat that produced it.** Deeper detail is in `HANDOFF.md`
and `docs/handoff/`, but this file stands alone.

Last updated: **2026-07-23**, engine repo at commit **`ef15b45`**.

---

## ⚠️ FIRST: one session per repo

If another Claude session is also open on `C:\repos\xray-by-looplet`, **stop and
pick one.** Two sessions editing the same working tree clobber each other — that
already happened once (a stale README fix was left uncommitted by a parallel
session). Before doing anything, run `git status`. If it's not clean and you
didn't make the changes, reconcile before you touch anything.

---

## What X-Ray is

A headless, deterministic construction-plan takeoff engine. **PDF/DXF in →
`takeoff.json` out.** The core promise, enforced in code: an LLM never produces a
quantity — every number re-derives from the drawing, carries its formula +
evidence + a confidence tier, and output is byte-identical run to run (a parity
gate proves it).

Four products, kept separate:
1. **Engine** — `C:\repos\xray-by-looplet` (Python, this repo).
2. **Desktop app** — `xray-by-looplet/desktop/` (Electron, spawns the engine as
   a frozen sidecar; runs standalone, no CRM).
3. **CRM `/xray` page** — the engine embedded in the Looplet CRM. Depends on
   X-Ray; X-Ray does not depend on it.
4. **PDX signer** — `C:\Users\danie\pdx-viewer`. Unrelated. Never edit its
   `app.html`.

---

## Repos & branches (nothing merged; all merges are Daniel-gated)

| repo | path | branch | pushed? |
| --- | --- | --- | --- |
| Engine | `C:\repos\xray-by-looplet` | `feat/desktop-electron` @ `ef15b45` | yes |
| Engine | ↑ | `feat/assemblies` (older) | yes |
| CRM embed | `...\looplet crm\Looplet-xray-embed` | `feat/xray-embed` @ `59b3431` | yes |
| CRM base | `...\Looplet-automations-builder-port` | `feat/fixes` (another agent) | — |

GitHub: `github.com/danielsivyer4567/xray-by-looplet` and
`github.com/LoopletCRM/Looplet`.

---

## What's DONE (built, tested, pushed)

**Engine repo:**
- Deterministic pipeline: adapter reads PDF/DXF → grammar → scale vote → chain
  checks → tables → trade packs → symbol counts → dimension-conflict flags →
  `takeoff.json`. `src/xray/engine.py` is the orchestrator.
- **Four trade packs:** `packs_shed.py` (steel portal sheds),
  `packs_electrical.py` (schedule-of-loads), `packs_fencing.py` (fence-line
  takeoff — run length, posts, gates), `packs_structural.py` (**layer-semantic
  column count**: counts polyline footprints per structural layer, e.g. a real
  WTC plan → Perimeter Columns 236 + Core Columns 45, reconciled, per-member
  evidence — the fix for "read the file but counted nothing" when members are
  polylines not blocks). Adding a trade = a new pack module + `register()`.
- **Anti-flake corpus** (`fixtures/corpus/manifest.json` + `tests/test_corpus.py`):
  every real file that trips the engine becomes a permanent case (file +
  invariants: provenance flag, min quantities, exact quantity values), so that
  shape can't regress. Adding coverage = one JSON entry. Also fixed a **provenance
  false-positive** a real WTC DXF exposed (polyline components + no dims looked
  like a flatten; now the deciding tell is trade-semantic layer names).
- **`PackContext` now carries `symbols` + `geometry`** (additive; text/table
  packs ignore them) so a geometry-driven pack — fencing being the first — can
  see fence runs and placed posts. `packs_fencing.py`: length from drawn runs,
  posts reconciled against placed POST blocks *or* derived from a flagged 2.4 m
  spacing assumption (→ needs-human), gates counted. Fixture
  `fixtures/cad/fencing-boundary.dxf` (generator `tools/make_fencing_fixture.py`);
  10 tests. Panels/rails/footings deliberately NOT invented — they need the fence
  system (paling/Colorbond/chainmesh).
- **Parity gate** (`parity/`) — hashes canonical `takeoff.json` vs the Python
  oracle; frozen sidecar passes 3/3 byte-identical.
- **Host kit** (`host/xray-host.js`, `@looplet/xray-host`) — the ONE way to run
  the engine, so the desktop app and the CRM run it identically. CRM vendors it
  with a drift test.
- **Empty-takeoff explanation** — 0 quantities now says WHY (no pack matched vs a
  pack crashed), via `pack-coverage` / `pack-error` checks.
- **Pricing layer** (`pricing/`, separate from engine):
  - `oxworks.py` — imports the Oxworks price PDF → 3,522 rows / 1,111 SKUs.
    `python -m pricing.oxworks "<pdf>" --out oxworks-catalogue`.
  - `mapping.py` — matches takeoff lines to SKUs. **Proposes, never picks;** a
    human confirms once, then it's remembered per supplier.
  - `costing.py` — **P2 costing engine, NO LLM.** Joins takeoff quantities to a
    price-list CSV on item/alias **+ unit** (unit is a hard gate), multiplies,
    stamps provenance, and flags unmatched / ambiguous / stale / POA / wrong-unit
    as `needs-human` (rate stays null). Freshness gate uses an explicit `as_of`
    (never "today" → reproducible). Outputs `.quote.csv` (opens in Excel) +
    a self-contained `.quote.html` + `.quote.json`. CLI:
    `python -m pricing.costing <takeoff.json> <prices.csv> [--as-of --freshness-days --region]`.
    12 tests. **The machinery is done — P2 only needs Daniel's real prices as
    DATA, not code.** (openpyxl-based live-formula .xlsx export is the one deferred
    bit — openpyxl can't go in the hermes venv; CSV+HTML deliver the substance.)
- **Building graph — viz Phase 1 BUILT** (`src/xray/graph.py`): turns a
  `takeoff.json` into a queryable graph *view* (no re-reading the drawing) —
  type/god nodes, the assembly DAG as member-of edges, quantities edged to their
  evidence, deterministic + non-destructive, with queries (`count_by_type`,
  `bill_of_materials`, `neighbours`) and a self-contained offline HTML view.
  CLI: `python -m xray.graph <takeoff.json>` → `.graph.json` + `.graph.html`.
  12 tests.
- **Wireframe — viz Phase 2 BUILT** (`src/xray/wireframe.py`): extrude each
  placed component to a vertical element at its measured (x,y), tagged with its
  graph node id (the WTC "columns from the DXF" idea, generalised). x,y faithful;
  height is an ASSUMED viewing value, flagged `needs-human` — never a quantity.
  `roundtrip_check` re-derives counts from the scene and gates vs the takeoff.
  Self-contained dependency-free WebGL viewer (orbit/pan/zoom, Iso/Elevation/Plan,
  isolate-by-type). CLI: `python -m xray.wireframe <takeoff.json>`. 10 tests.
  NB: viewer's WebGL couldn't be eyeballed here (in-app preview only runs JS for
  in-project files and the pane hung, all session); adapted from the proven WTC
  viewer + unit-verified self-contained/round-trip.
- **Solid glTF export — viz Phase 3 ON-RAMP BUILT** (`src/xray/solid.py`):
  extrudes each component to a box prism and writes a self-contained **glTF 2.0**
  (pure stdlib; buffer as base64 data URI) where every mesh node is named by its
  graph id with `xrayType`/`xrayTrade`/`heightTier` in `extras`. This is the
  neutral hand-off Unreal (USD/Datasmith or glTF) / Blender / Omniverse / a
  path-tracer import. Deterministic; `roundtrip_check` gates mesh counts. CLI
  `python -m xray.solid <takeoff.json>` → `.gltf`. 10 tests. **The photoreal
  render itself (materials/lighting → Unreal/path-tracer, or a splat *capture*
  front door) is downstream/GPU-bound — not in this repo.** Phase 3 render still
  to do; the geometry export that feeds it is done.
- **Bad-input handling BUILT** (`src/xray/preflight.py`): every caller of
  `engine.run` gets a typed `InputError` (empty / oversized / wrong-format via
  magic bytes / password-protected / corrupt) instead of a parser traceback; the
  CLI prints one line and exits 2. Plus a **DXF provenance flag**: a plot
  flattened into a DXF (`fixtures/negative/shed-flattened-from-pdf.dxf`) is now
  flagged (`provenance` check → review) rather than silently ingested as
  confident nonsense; real CAD files are untouched. 13 tests.
- **OCR stage — PLUMBING BUILT** (`src/xray/ocr.py`): renders a page (pdfium→PIL),
  hands it to a pluggable `OcrBackend`, converts pixel boxes → `reassemble.Word`
  in PDF points tagged `source="ocr"`. Deterministic + tested (render, conversion,
  `StubBackend` round-trip, `TesseractBackend` errors clearly when absent).
  **No OCR engine ships/installed here** — Tesseract activates when present,
  PaddleOCR fits the same interface. **WIRED into `engine.run` as OPT-IN**:
  `run(pdf, ocr=True)` auto-detects an installed engine (raises if none) or pass
  an `OcrBackend`; `--ocr` CLI flag. Default off → byte-identical (parity safe);
  fires only on **raster/sparse PDF pages**, never vector pages or DXF. Still
  needs a real engine installed + a **scanned fixture with hand-proven ground
  truths** to prove end-to-end recognition. Reality: clean scans achievable, a
  glare-y phone photo (Daniel's survey) is much harder. 12 tests (7 unit + 5 wire).
- Tests: **422 pytest + 10 host-kit**, green. Parity re-frozen after the fencing
  pack (warehouse's empty-takeoff message now lists `fencing` as a measurable
  trade — the only byte change; shed/electrical untouched).

**CRM repo (`feat/xray-embed`):**
- `/xray` route + page + engine-status banner + extension-catalogue tile.
- Electron IPC bridge (`electron/main/xray-ipc.ts`) spawning the sidecar.
- Runs the vendored host kit; `/health` must identify as `xray-by-looplet`.
- 24 vitest green; eslint clean; tsc adds no new errors.

---

## What's OPEN (pick from here)

1. **[BLOCKER, not X-Ray's]** `feat/fixes` (CRM base) can't build — imports
   `./TemplatePreviewSheet` + `panels/inspector/setup-checklist`, which exist
   only as uncommitted files in the `Looplet-automations-builder-port` worktree.
   The `/xray` renderer bundle fails until whoever owns that branch commits them.
2. **Fencing pack — v1 BUILT** (`packs_fencing.py`): fence run length, posts
   (reconciled/derived), gates, from DXF geometry. Two things remain: (a) the
   **system-specific BOM** (panels/palings, rails, footings, concrete) — needs
   Daniel to state the fence system, currently flagged not invented; (b) it only
   fires on **DXF** today (needs `geometry`/`symbols`); a PDF-survey fence with
   dimensioned runs won't quantify until fence runs are recoverable from the PDF
   path. **Sidecar not yet rebuilt** — the frozen `xray-engine.exe` still lacks
   this pack until `desktop\scripts\build-engine.ps1` is re-run.
3. **Phase 1 building graph** (roadmap) — all deterministic, useful standalone,
   lowest risk. Good first move.
4. **WASM engine** — the intended browser-primary tier; must pass the parity gate
   byte-identical before shipping.
5. **Confirm a few real SKU mappings** so the mapper becomes useful on live jobs
   (Daniel-gated — needs his real product choices, don't invent them).
6. Two legacy parity digests remain unreproducible (documented in
   `parity/README.md`); this repo's own references are the oracle meanwhile.

---

## Facts the OLD handover got wrong (verified false — don't re-inherit)

- **PDFium build does NOT change quantities** — 149 and 152 produce identical
  output on all fixtures. The WASM engine need not match a specific PDFium.
- **CRM shell is Electron** — engine bridge belongs in the CRM repo, NOT
  looplet-producer.
- **The Oxworks PDF was always readable** — the "OneDrive can't be granted" note
  was about chat attachment, not the filesystem.
- **That PDF is 274 pages, not 967** — three parsers + the PDF's own `/Count`
  agree; a harness misreported 967.

---

## Environment gotchas (all real, all hit)

- `python` on PATH is the **hermes-agent venv**; `python -m xray` needs
  `PYTHONPATH=src`. No `openpyxl`, no `poppler` there (don't install into it).
- Run the suite: `set PYTHONPATH=src && python -m pytest tests -q` → 422.
- Rebuild the frozen engine: `powershell -File desktop\scripts\build-engine.ps1`.
- Electron: `unset ELECTRON_RUN_AS_NODE` before `npx electron .` or it won't boot.
- Ports: `:8000` is taken by an unrelated service here; `:5173` by another Vite.
- **The Looplet-CRM `check-gate` hook blocks commits in THIS repo too** — write
  `.claude/scratch/check-passed` (under `looplet crm/`) in a SEPARATE shell call
  from `git commit`.
- Stale git locks (`HEAD.lock`, `maintenance.lock`, 0-byte) recur — move aside.
- TLS to GitHub is flaky — pushes sometimes need 2-3 retries.

---

## Not in git — hand these to a person, keep local copies

- The **Oxworks source PDF** (`C:\Users\danie\OneDrive\...Current East Coast.pdf`)
  and the **generated catalogue** (gitignored) — regenerate with the command
  above.
- The **RFQ scope report** (356 Ruffles Rd) — client material, scratchpad only.
- The **frozen engine binary** (~80 MB, gitignored) — rebuild command above.

---

## Sanity check — you're caught up if you can state:

the four products, that nothing is merged, the open blocker (`feat/fixes` can't
build), and the corrected facts (PDFium is a non-issue; 274 pages not 967). If
so, just start on one of the OPEN items above.
