# X-Ray by Looplet — User & Developer Guide

**Sees through plans. PDF in, quantities out.**

Version 0.1.0 · engine id `xray-by-looplet` · Python 3.11 · 381/381 tests passing

X-Ray by Looplet is a **headless** construction-plan takeoff engine. Feed it a
plan PDF; it returns a structured `takeoff.json` (typed entities, verification
checks, quantities with evidence chains) and a `marked.pdf` (the same drawing
with results injected as standard ISO 32000 PDF markup annotations, plus the
full JSON embedded as an attachment so the file is self-contained).

There is deliberately **no UI**. Presentation is delegated (Looplet CRM, an LLM
formatter, Excel). **An LLM never produces a quantity** — quantities come only
from deterministic grammar + geometry + rule packs, and every number carries the
formula and the entity IDs that prove it.

---

## Table of contents

1. [Quick start](#quick-start)
2. [Dependencies](#dependencies)
3. [Installing](#installing)
4. [Updating the engine safely](#updating-the-engine-safely)
5. [CLI reference](#cli-reference)
6. [The pipeline](#the-pipeline)
7. [Output contract](#output-contract)
8. [Trust tiers](#trust-tiers)
9. [Module reference](#module-reference)
10. [Extending — new plan types](#extending--new-plan-types)
11. [Accuracy & tests](#accuracy--tests) (see also `docs/ACCURACY.md`)
12. [Known limitations](#known-limitations)
13. [Patent guardrails](#patent-guardrails)
14. [Roadmap](#roadmap)

---

## Quick start

```
# from the repo root: C:\repos\xray-by-looplet
pip install -r requirements.txt
set PYTHONPATH=src              # Windows (cmd)
# $env:PYTHONPATH="src"         # Windows (PowerShell)
# export PYTHONPATH=src         # macOS / Linux

python -m xray run fixtures\shed-manners-aline.pdf --out out
```

This writes `out\shed-manners-aline.xray.json` and
`out\shed-manners-aline.marked.pdf`, and prints a one-screen summary of the
entities, checks, and quantities found.

---

## Dependencies

Three runtime libraries and one test library. No heavy frameworks, no ML
runtime, no cloud services — everything runs locally (a deliberate selling
point: builders' plans are commercially sensitive and never leave the machine).

| Package | Pinned (`requirements.txt`) | Verified build | Role |
|---|---|---|---|
| `pypdfium2` | `>=4` | 4.x (PDFium) | Text char boxes, image objects, page classification, rendering — permissive (Apache/BSD) licence |
| `pikepdf` | `>=9` | 10.x (qpdf) | Annotation injection, `/Measure` dicts, embedded `takeoff.json` |
| `jsonschema` | `>=4` | 4.26.0 | Enforces the output contract at test time |
| `pytest` | `>=8` | 8.x | Test runner; the two real fixtures are the regression suite |

**Runtime:** Python 3.11 (uses `X | None` unions, dataclasses). No compiled
extensions of our own; both PDF libraries ship wheels, and both are
permissively licensed (no AGPL).

**Deliberate non-dependencies:** cloud OCR (Azure / Google Document AI) — local
only removes a per-page cost; ML for quantities — the trust engine is arithmetic
reconciliation, not black-box scores; any third-party markup SDK — writing
plain ISO 32000 annotation keys directly is the stronger, dependency-free
position and opens in any standards-compliant PDF viewer.

---

## Installing

```
git clone <repo> C:\repos\xray-by-looplet
cd C:\repos\xray-by-looplet
python -m pip install -r requirements.txt
```

The package uses a `src/` layout. Either set `PYTHONPATH=src` (per quick start)
or, once a `pyproject.toml` is added (see roadmap), `pip install -e .` to make
`xray` importable anywhere.

---

## Updating the engine safely

The two fixtures under `fixtures/` are the safety net. The engine can never
silently regress below what has been proven by hand.

1. **Edit** a module under `src/xray/`.
2. **Run the full suite:** `python -m pytest tests -q` — expect `381 passed`.
3. **Re-run the CLI on both fixtures** and confirm exit 0 + both output files:
   ```
   set PYTHONPATH=src
   python -m xray run fixtures\shed-manners-aline.pdf --out out
   python -m xray run fixtures\warehouse-design21.pdf --out out
   ```
4. **Diff the summary** against `docs/ACCURACY.md`. A dropped `pass` or a changed
   quantity is a regression.
5. **Update `CONTEXT.md`** — the single source of truth for design decisions and
   empirical findings. Any new API, tolerance, or fixture fact goes there.

**Golden rule:** if you change a banding tolerance, a regex, or a merge guard,
add or update a test that encodes the new expected behaviour on a fixture. Never
loosen a check just to make a number appear — that is how a plausible-but-wrong
quantity slips through.

---

## CLI reference

```
python -m xray run <plan.pdf> [--out DIR]
python -m xray --version
```

| Argument | Meaning |
|---|---|
| `run` | The only subcommand. Runs a full takeoff on one plan PDF. |
| `<plan.pdf>` | Input plan. Vector CAD prints and Paper-Capture scans both handled. |
| `--out DIR` | Output directory. Default: next to the input PDF. Created if missing. |
| `--version` | Prints `xray-by-looplet 0.1.0`. |

For input `<plan>.pdf` it writes `<plan>.xray.json` and `<plan>.marked.pdf`.
Exit code `0` on success, `1` on a missing input file.

---

## The pipeline

Seven stages, each a pure-Python module, each independently unit-tested.
Orchestrated by `engine.run(pdf) -> dict`; wrapped by `cli.py`.

```
PDF -> 1 extract -> 2 reassemble -> 3 grammar -> 4 scale
    -> 5 checks -> 6 quantify -> 7 write -> takeoff.json + marked.pdf
```

| # | Stage | Module | What it does |
|---|---|---|---|
| 1 | extract | `reassemble.py` | Text words + vector segments (lossless on vector PDFs) |
| 2 | reassemble | `reassemble.py` | Cluster glyph fragments sharing a baseline into whole tokens; no-op on clean PDFs |
| 3 | grammar | `grammar.py` | Classify tokens (DIM/TAG/SCALE/SPEC/LABEL/LEVEL/STD/NOTEKEY); normalise `W0l->W01`; parse spec tokens |
| 4 | scale | `scale.py` | Vote a per-page scale -> mm-per-point |
| 5 | checks | `chains.py` | Chain sums, trig, label counts, cross-sheet; mask phone/postcode/copyright false positives |
| 6 | quantify | `quantify.py` | Rule packs -> quantities with formula, tier, evidence |
| 7 | write | `markup_writer.py` | Standard ISO 32000 PDF markup annotations (`/NM`,`/Subj`,`/T`,`/Measure`) + embed the JSON |

A rendered mind map of the whole system lives at `docs/mindmap.mermaid` (and in
the HTML documentation reference).

---

## Output contract

The `takeoff.json` shape is the stable contract every consumer depends on.
Renaming the engine never changes this shape, only `engine.name`.

```json
{
  "engine":    { "name": "xray-by-looplet", "version": "0.1.0" },
  "document":  { "path", "sha256", "producer", "pages": [ {n, widthPt, heightPt, kind, scale} ] },
  "entities":  [ {id, page, type, value, raw, bbox, confidence, source} ],
  "checks":    [ {id, kind, status, detail, delta, page, evidence} ],
  "quantities":[ {id, trade, item, qty, unit, formula, tier, evidence, notes} ],
  "review":    [ {ref, reason} ]
}
```

- **Entity types:** `DIM` `TAG` `SCALE` `SPEC` `LABEL` `LEVEL` `STD` `NOTEKEY`
- **Check kinds:** `chain-sum` `trig` `count` `cross-sheet` `schedule-match`; status `pass` or `flag`
- **Units:** `ea` `lm` `m2` `m3` `kg` `t`
- **Page kinds:** `vector` `raster` `sparse`

The marked PDF: each annotation carries `/NM` (UUID), `/Subj`, `/T` =
"X-Ray by Looplet", `/Contents`, dates, and — for measurements — a standard
ISO-32000 `/Measure` dict so any standards-compliant PDF viewer renders scaled
values. The full JSON is embedded as an attachment named `takeoff.json`.

---

## Trust tiers

Every quantity declares how much it can be trusted — a stated reconciliation
status a human can audit, not a black-box confidence score.

| Tier | Meaning | Example |
|---|---|---|
| `reconciled` | Independent evidence agrees | portal frames = 5, confirmed by the PORTAL RAFTER count |
| `single-source` | One source, no independent confirmation, no assumption | roof sheeting 146.2 m2 from the spec token |
| `needs-human` | An assumption was required; surfaced in `review` | wall cladding — bay 1 marked OPEN both sides |

Near-miss checks are **flagged with their delta, never dropped**. A chain summing
to 16,467 against a stated 16,465 becomes a `flag` with `delta +2`.

---

## Module reference

| Module | LOC | Key API |
|---|---|---|
| `reassemble.py` | 252 | `extract_words(doc, page_no)`, `reassemble(words)` |
| `grammar.py` | 338 | `classify(words, page_rect)`, `parse_spec_token(text)`, `normalize_tag(text)` |
| `scale.py` | 132 | `vote_scale(entities, page_rect, declared, calibration=None)`, `calibrate(p0, p1, known_mm)` |
| `chains.py` | 322 | `find_chain_checks(entities, page_rect)`, `trig_check(spec, entities)`, `titleblock_mask(page_rect)` |
| `tables.py` | 181 | `extract_tables(words, page_rect)` -> schedule rows |
| `quantify.py` | 186 | `shed_pack(spec, entities, checks)` |
| `packs*.py` | — | registry + shed / electrical / **fencing** packs; `hardening.py` (wastage, laps, accessories) |
| `graph.py` | — | `build_graph(takeoff)` → building graph (a view); `count_by_type`, `bill_of_materials`, `render_html` |
| `wireframe.py` | — | `build_scene(takeoff)` + `roundtrip_check`; self-contained WebGL viewer |
| `pricing/costing.py` | — | `cost_takeoff(quantities, price_rows, …)` → priced quote (no LLM) |
| `markup_writer.py` | 225 | `write_marked_pdf(src, out, result)` |
| `engine.py` | 178 | `run(pdf_path, calibrations=None) -> dict` |
| `cli.py` | 79 | `main(argv)` |

---

## Extending — new plan types

To support a new drawing family (e.g. steel-framed warehouses):

1. Add a rule pack to `quantify.py` that consumes entities + checks and emits
   `Quantity` objects with a `formula`, a `tier`, and `evidence` entity IDs.
2. Wire it into `engine.run()` behind a spec/heuristic gate.
3. Add a fixture PDF under `fixtures/` and acceptance tests in `tests/` that
   encode the hand-proven ground truths for it.
4. Record the empirical findings in `CONTEXT.md`.

---

## Accuracy & tests

Full results in `docs/ACCURACY.md`. Summary: **381/381 tests pass**, and every
ground truth is re-proven on each run against the fixtures.

The suite spans the pipeline (reassemble, grammar, scale, chains, tables,
writer, `engine.run` end-to-end + schema conformance), the DXF adapter, the
three trade packs (shed, electrical, fencing), and the derived layers — the
building graph, the wireframe with its round-trip gate, and costing. The two
real plan sets under `fixtures/`, the CAD fixtures, and the generated fixtures
are the permanent acceptance suite; ground truths were proven by hand. CAD/graph/
wireframe suites `pytest.importorskip("ezdxf")` so a bare install still passes.

---

## Known limitations

Documented honestly in `CONTEXT.md`. Every one degrades to a human-review flag —
never a wrong quantity or a false pass.

- **Off-baseline chain members:** the proven warehouse chain
  `3579 = 2289 + 90 + 1200` emits as a `flag` (delta -4) rather than a pass,
  because the drawn "90" sits 7.2 pt below the band baseline (over the 6 pt
  tolerance) while a genuine "86" from an adjacent detail stack sits on it. No
  provably safe banding change fixes this without risking cascading merges on
  213k-segment sheets.
- **Small-dim near-misses:** a handful of the same class on both fixtures — all
  review-tier, none false passes.
- **Trade packs:** shed (portal frames), electrical (schedule of loads), and
  fencing (geometry-driven: run length, posts, gates). Warehouse structural is
  not built yet (by design).

---

## Patent guardrails

Engineered around from a verified dossier, baked in as engineering constraints.

- No animated / time-segmented expanding fill UX (headless engine unaffected;
  any future fill stays instant, single-pass).
- No tool-set-linked legend that live-updates cumulative quantities (static
  summary tables only).
- No colour/size pre-filtered visual template search.

---

## Roadmap

**Next modules:** PaddleOCR (local, ONNX) for scanned sheets; OpenCV for
deskew/leader/table detection; AS/NZS static data packs (JSON) for steel mass;
importer for reading existing marked-up PDFs; openpyxl/CSV export.

**Integration:** a thin FastAPI wrapper or worker-invoked CLI — a Looplet job
gets a plan PDF, the worker runs X-Ray, JSON lands in Postgres, quantities appear
as draft quote lines with evidence crops. Slots into the existing Supabase worker
pattern.

**Later — the viewer:** deliberately undecided (Electron + React vs PDFium wasm).
Engine-first means the viewer choice never blocks anything; the standards-based
markup writer is already the file layer either way.
