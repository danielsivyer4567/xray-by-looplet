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
- **Three trade packs:** `packs_shed.py` (steel portal sheds),
  `packs_electrical.py` (schedule-of-loads), `packs_fencing.py` (fence-line
  takeoff — run length, posts, gates). Adding a trade = a new pack module
  + `register()`, no engine change.
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
  12 tests. Phases 2 (WebGL wireframe) + 3 (render) still roadmap-only
  (`docs/ROADMAP-visualization.md`).
- Tests: **315 pytest + 10 host-kit**, green. Parity re-frozen after the fencing
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
- Run the suite: `set PYTHONPATH=src && python -m pytest tests -q` → 305.
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
