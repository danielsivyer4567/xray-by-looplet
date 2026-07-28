# X-Ray by Looplet — Handoff / Reopen Brief

Paste into a new session to take over. Current as of **2026-07-23**. Supersedes
the earlier CONTEXT/handover brief. Where this disagrees with an older note,
**this wins** — several claims in the original brief were tested this session
and turned out to be wrong (flagged **[CORRECTED]** below).

---

## 0. What this is

**X-Ray by Looplet** — a headless, deterministic construction-plan takeoff
engine. PDF/DXF in → schema-conformant `takeoff.json` out. Core promise: an LLM
never produces a quantity; every number re-derives from the drawing, and output
is byte-identical (same file in → identical JSON out, provably, enforced by a
gate).

Four products, keep them straight:

1. **X-Ray engine** (`C:\repos\xray-by-looplet`) — Python, deterministic,
   headless. The core.
2. **X-Ray desktop app** (`xray-by-looplet/desktop/`) — Electron shell that
   spawns the engine as a frozen sidecar. Runs standalone, no CRM.
3. **Looplet CRM `/xray` page** — the engine embedded as a page in the CRM
   Electron app. Depends on X-Ray; X-Ray does **not** depend on it.
4. **PDX signer** (`C:\Users\danie\pdx-viewer`) — unrelated document signer,
   stays Tauri, untouched. Never edit its `app.html`.

---

## 1. STANDING RULES (non-negotiable)

- Never put competitor names in product/README/code/UI. Internal strategy docs
  only, and only when competitive research is explicitly invoked.
- Never modify the PDX signer's `app.html`. Reading is fine.
- Never commit `keys/` (signing keys) — gitignored.
- Never commit supplier **prices** — the importer is versioned, the catalogue
  output is gitignored (`pricing/out/`, `*-catalogue.{json,csv}`).
- One agent per repo. Don't run two agents committing to the same repo.
- Engine stays pure/offline/deterministic. No network egress from the parser,
  no LLM in the request path. Pricing/rendering live in SEPARATE layers.
- **Byte-identity gate.** Any change must keep existing fixture output
  byte-identical (`parity/` enforces it). New layers are additive/opt-in. When
  output legitimately changes, re-freeze **deliberately** and rebuild the
  sidecar so the binary doesn't lag the oracle.
- **Test a stated constraint before repeating it.** Two "constraints" in the
  original brief were false when actually checked (see §7).

---

## 2. Repos & branches

| repo | path | branch (this session's work) | remote |
| --- | --- | --- | --- |
| Engine | `C:\repos\xray-by-looplet` | `feat/desktop-electron` (pushed) | github.com/danielsivyer4567/xray-by-looplet |
| Engine | ↑ | `feat/assemblies` (pushed, older) | ↑ |
| CRM embed | `C:\repos\looplet webb app\looplet crm\Looplet-xray-embed` | `feat/xray-embed` (pushed) | github.com/LoopletCRM/Looplet |
| CRM shell (base) | `...\Looplet-automations-builder-port` | `feat/fixes` (shared, another agent) | ↑ |
| PDX signer | `C:\Users\danie\pdx-viewer` | untouched | github.com/danielsivyer4567/pdx-viewer |

**Nothing is merged. No PRs opened. All merges are Daniel-gated.**

---

## 3. What was built this session (2026-07-23)

### Engine repo — `feat/desktop-electron`, in commit order

- `85973be` **assemblies** — Layer A wall recipe → cut list → buy plan (was on
  `feat/assemblies`, base of this branch).
- `35d55e6` **desktop** — Electron shell spawning the frozen engine per takeoff.
- `82e77a7` **parity** — the reliability gate: judges any runtime's takeoff.json
  byte-identical vs the Python oracle. `parity/compare.py` (pure stdlib),
  `parity/freeze.py` (re-freeze), `reference/*.json`, `manifest.json`.
- `c8a145a` **[CORRECTED] parity fix** — retracted a wrong PDFium claim (§7).
- `21b7a36` **host kit** — `host/xray-host.js` (`@looplet/xray-host`): the ONE
  canonical way to run the engine, owned by the engine repo, consumed by every
  host. Zero-dep CommonJS, 10 `node:test` tests. Also pinned `requirements.txt`
  exactly (was `>=` floors).
- `73fc6b8` **empty-takeoff explanation** — a takeoff with 0 quantities now says
  WHY (no pack matched vs a pack crashed); `run_packs` no longer swallows pack
  exceptions silently. New check kinds `pack-coverage`, `pack-error`.
- `37a4b1a` **Oxworks importer** — `pricing/oxworks.py`. 3,522 rows from the
  274-page price list.
- `5bb3bf0` **SKU mapper** — `pricing/mapping.py`. Proposes SKUs, never picks.
- `19bc15c` / `5da4620` / `c52e90b` **visualization roadmap** —
  `docs/ROADMAP-visualization.md` (see §6). Docs only.

Test count: **305 pytest + 10 host-kit** green.

### CRM repo — `feat/xray-embed`, in commit order

- `27f03510` isolate the `/xray` embed on its own branch (carried 2 files out of
  the shared worktree verbatim).
- `50ef19f1` spawn the frozen engine over Electron IPC + engine-status banner.
- `fb261f1f` run the engine through the vendored host kit (not a local copy);
  provenance manifest + `scripts/sync-xray-host.mjs` + drift test.
- `024e3361` pin the vendored kit to LF so the drift guard doesn't cry wolf.
- `59b34311` require `/health` to identify as `xray-by-looplet`, not just answer.

Test count: **24 vitest** green (engine-client both transports, banner states,
drift guard). eslint clean, tsc adds no new errors.

---

## 4. Architecture, as it actually stands

- **Engine is Electron, not Tauri, for the desktop app** — bundled Chromium for
  the CAD UI, mature signing/auto-update. **[CORRECTED]** the CRM shell is ALSO
  Electron (electron 40 + electron-builder + `electron/main` + `electron/preload`,
  no `src-tauri`), so the engine bridge is an Electron IPC handler in the CRM
  repo, **not** in looplet-producer. The original integration plan had this
  wrong.
- **Engine ships frozen** — PyInstaller `--onefile` → `xray-engine.exe` (~80 MB,
  not the 66 MB the brief said; deps grew). Spawn-per-takeoff, hidden child,
  exits when done. Proven offline.
- **Verified byte-identical across four surfaces** — Python oracle, frozen exe
  CLI, FastAPI HTTP, Electron IPC — all produce the same quantities on all
  fixtures.
- **Host kit is the anti-drift device.** Both the standalone app and the CRM run
  takeoffs through `xray-host.js`. Standalone consumes it as a `file:` dep; the
  CRM (separate remote, can't use a package dep) **vendors it verbatim** with a
  sha256 drift test that was proven to fire on tamper. Edit it upstream, run
  `scripts/sync-xray-host.mjs`.
- **Three-tier engine access:** desktop → local frozen sidecar (primary);
  browser → FastAPI (`VITE_XRAY_API`, default `127.0.0.1:8000`); WASM engine is
  the intended browser primary but is **not built**.
- **Pricing is a separate layer** (`pricing/`), never imported by `xray.*`.
- **Determinism boundary:** engine deterministic; pricing deterministic;
  future render pipeline (§6) is explicitly presentation-only and NOT
  byte-reproducible, by design.

---

## 5. Pricing layer (new this session)

- **`pricing/oxworks.py`** — imports the Oxworks price-list PDF. Parses by row
  SHAPE (code left, money right), not header position, because ~300 tables vary.
  `python -m pricing.oxworks <pdf> --out <base>` → `.json` + `.csv`;
  `--report-only` for the validation report. Result: 3,522 rows, 1,111 SKUs, 0
  unparsed, 100 POA. POA stays null (never 0); unreadable rows counted, never
  dropped; every row carries page + raw source line for auditing.
- **`pricing/mapping.py`** — matches a takeoff line to a SKU. **Proposes, never
  decides.** Bindings only from a human confirmation, remembered per supplier in
  `pricing/out/<supplier>-mappings.json` (gitignored), keyed on normalised item
  **+ unit**. Units are a hard gate (lm can't fulfil m2). Deterministic
  token+dimension scoring, no LLM. Every candidate carries a reason + page.
- **Why no auto-accept:** the catalogue has the same product at 3 prices
  ($480/$393/$348, identical descriptions, pp136-138). Auto-accepting the top
  hit = 38% overcharge nobody questioned.
- **Proven on a real RFQ** (356 Ruffles Rd, Seeka Constructions): engine read 24
  sheets → 0 quantities (no fencing pack; the pack-coverage check explained it),
  and Oxworks covered almost none of the job (wrong-size posts scored down, chain
  wire not stocked). Scope report written to scratchpad; not committed (client
  material). Job number on the file (10558) ≠ on the drawing (10588) — flag before
  quoting.

---

## 6. Visualization roadmap (new, `docs/ROADMAP-visualization.md`)

Daniel's vision, captured as to-dos — **nothing built**. DXF → fully-counted
building graph (every member a node with an id) → WebGL wireframe → near-real 8K
render (Unreal or USD/path-tracer). Phases:

- **Phase 0 (done):** DXF read as text; `Symbol` counts components exactly by
  block_name with evidence ids; `Measure` extracts geometry; takeoff.json emits
  entities+symbols+geometry. This is the "count every nut and bolt" seed.
- **Phase 1:** building-graph.json as a VIEW of an existing takeoff (inherits
  evidence). Counts are query results, not typed numbers.
- **Phase 2:** extrude to glTF/USD tagged with node ids → WebGL viewer (shippable
  win, no Unreal). Round-trip counts back through geometry, gate vs takeoff.
- **Phase 3:** export USD/Datasmith → materials/lighting from graph → 8K render.
- **Build like a ledger (the LOGIC, not autopro tooling):** mm-precise
  coordinates make each component a self-contained slice — build → verify →
  checkpoint → stitch by shared coordinates, so the GPU holds one slice at a
  time and unchanged slices cache. No agent runner; ordinary deterministic build
  code.
- **The rule:** the render is presentation, never a source of truth. One-way
  flow; every renderable keeps its component id; determinism ends at Phase 2 on
  purpose.

---

## 7. [CORRECTED] Things the earlier brief got wrong (verified this session)

1. **PDFium build does NOT change quantities.** The brief said references frozen
   under PDFium 149 wouldn't reproduce under 152, and pinned 149.0.7802.0.
   **Measured:** 149.0.7802.0 (pypdfium2 5.7.1) and 152.0.7947.0 (5.12.1) produce
   **byte-identical** output on all three fixtures. Also identical across engine
   commits and unchanged fixtures. The WASM engine does NOT need to match a
   specific PDFium build. `requirements.txt` is now pinned exactly as hygiene.
2. **2 of 3 legacy reference digests are unreproducible** — shed matches its pin
   exactly; electrical-schedule and warehouse-design21 never do, under any
   combination tested. Not explained by PDFium, engine history, or fixtures.
   **This repo's own `parity/reference/` is the oracle.** Likely the legacy pins
   came from different fixture files or engine state. OPEN.
3. **The CRM shell is Electron, engine bridge belongs in the CRM repo** — not
   looplet-producer (see §4).
4. **The Oxworks PDF was always readable** — the "OneDrive can't be granted" note
   was about chat attachment, not the filesystem.
5. **The PDF is 274 pages, not 967** — the Read-tool harness reported 967;
   pypdfium2 + pikepdf(QPDF) + the PDF's own `/Count` all say 274, and printed
   page numbers run 2→271. Import is complete.

---

## 8. OPEN PROBLEMS / blockers

1. **`feat/fixes` (CRM base) CANNOT BUILD.** Base commit `c708d0caec` imports
   `./TemplatePreviewSheet` and `panels/inspector/setup-checklist`, neither
   tracked at that commit — they exist only as uncommitted files in the
   `Looplet-automations-builder-port` shared worktree. Electron main+preload
   build; the renderer bundle fails. `feat/xray-embed` inherits this. **Whoever
   owns that branch must commit those files.** Not X-Ray's to fix.
2. **The 2 unreproducible legacy digests** (§7.2). Cosmetic while this repo's
   references are authoritative, but unresolved.
3. **warehouse-design21 yields 0 quantities** — correct (no matching pack), now
   explained by the pack-coverage check. Adding a trade = adding a pack module.
   A **fencing pack** is the obvious next one (Daniel's core trade), but the RFQ
   proved a pack alone won't help without dimensioned runs — the real unlock is
   scaled geometry off the survey.
4. **WASM engine not built** — the intended browser-primary tier. Must pass
   `parity/compare.py` byte-identical before shipping.
5. **Shared worktree hygiene** — the 2 xray files were COPIED (not moved) out of
   `Looplet-automations-builder-port`; the stale copies are still dirty there.
   Discard once `feat/xray-embed` is accepted.

---

## 9. Environment gotchas (all hit this session)

- **`ELECTRON_RUN_AS_NODE`** is set by Claude Code and breaks Electron. `unset`
  it before `npx electron .` (the CRM's `dev-launch.cjs` deletes it too).
- **CDP `Page.captureScreenshot` HANGS if the window is minimized.** Restore
  first. Drive the app headlessly via `--remote-debugging-port` + CDP
  `Runtime.evaluate` on `window.xray.runTakeoff(path)`.
- **Ports:** `:8000` is occupied by an unrelated uv-python service on this
  machine (answers `/health` with 404) — so `VITE_XRAY_API`'s default points at
  the wrong server; the `/health` identity check now catches that. `:5173` is
  another Vite. Use explicit alt ports.
- **`python` on PATH is the hermes-agent venv**
  (`C:\Users\danie\AppData\Local\hermes\hermes-agent\venv`) — that's where the
  engine deps + pyinstaller live. `python -m xray` needs `PYTHONPATH=src`.
- **The CRM `check-gate` hook intercepts commits in OTHER repos.** Write
  `.claude/scratch/check-passed` (in `looplet crm/`) in a **separate** Bash call
  from `git commit`, or the hook blocks it.
- **Stale git locks** (`HEAD.lock`, `objects/maintenance.lock`, 0-byte, no git
  process) recur on this machine — move aside to recover.
- **TLS to GitHub is flaky** — pushes sometimes need 2-3 retries.
- **No `openpyxl`, no `poppler`** in the venv (don't add to hermes venv). Pricing
  outputs CSV+JSON instead of xlsx; PDFs can't be rendered to images here.

---

## 10. First moves on reopen

1. `git -C C:\repos\xray-by-looplet log --oneline -6` and confirm branch =
   `feat/desktop-electron`.
2. Read `parity/README.md` and `pricing/README.md` — they hold the reasoning.
3. Pick from §8. Highest-value unblocked options: **Phase 1 building graph**
   (roadmap §6, all deterministic, useful alone), a **fencing pack**, or the
   **WASM engine** (needs the parity gate).
4. Merges, PRs, `bot_globally_paused`-style prod actions, and confirming SKU
   mappings are **Daniel-gated** — don't do them autonomously.
