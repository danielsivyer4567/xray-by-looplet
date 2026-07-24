# X-Ray by Looplet

**Sees through plans. PDF in, quantities out.**

A headless construction-plan takeoff engine. Feed it a plan PDF; it returns
structured quantities with evidence and trust tiers, and a marked-up PDF. There
is deliberately no UI — presentation is delegated (Looplet, the PDX viewer, an
LLM formatter, Excel). **An LLM never produces a quantity, price, or compliance
verdict** — every number comes from deterministic grammar + geometry + rule
packs, and carries the formula and evidence that prove it.

Status: **v0.1.0** · three trade packs (steel sheds, electrical, fencing) ·
**408 tests passing** · extraction is permissively licensed (pypdfium2 + pikepdf).

---

## Install

```
python -m pip install -r requirements.txt          # engine
python -m pip install -r server/requirements.txt   # + HTTP worker and MCP server
```

Runtime deps: Python 3.11, `pypdfium2`, `pikepdf`, `jsonschema`.

## Quick start (CLI)

```
set PYTHONPATH=src            # Windows cmd;  $env:PYTHONPATH="src" (pwsh);  export PYTHONPATH=src (bash)
python -m xray run fixtures\shed-manners-aline.pdf --out out
```

Writes `out\<plan>.xray.json` (the contract) and `out\<plan>.marked.pdf`
(annotations + the JSON embedded), and prints a one-screen summary.

```
python -m xray run <plan.pdf> [--out DIR]
python -m xray --version
```

## Three ways to call it

**1. CLI** — `python -m xray run <plan.pdf>` (above).

**2. HTTP worker** (`server/app.py`, FastAPI):
```
uvicorn server.app:app --port 8000
# POST /v1/takeoff  (multipart 'file' = plan PDF)  ->  quote-draft envelope
```

**3. MCP server** (`server/mcp_server.py`) — the clean Looplet integration:
```
python -m server.mcp_server        # stdio transport
```
Tools: `run_takeoff(pdf_path)`, `quote_draft(pdf_path)` (Looplet-ready lines),
`run_takeoff_calibrated(pdf_path, page, p0, p1, known_mm)`,
`marked_pdf(pdf_path, out_path)`, `engine_info()`.

## What comes out

`takeoff.json` (see `schema/takeoff.schema.json`): `engine`, `document`
(pages with kind + scale), `entities`, `checks` (pass/flag, with evidence),
`quantities` (qty, unit, formula, tier, evidence), `review`.

**Trust tiers:** `reconciled` (independent evidence agrees) · `single-source`
(one source, no assumption) · `needs-human` (an assumption was required —
surfaced in `review`). Near-misses are **flagged with their delta, never
dropped**.

**Coverage (confidence report):** each page carries `coverage`
(`words`, `entities`, `tableCells`, `structuredRatio`) and the document a
`coverage` summary (`overallRatio`, `lowPages`) — how much of the readable
text became structured output, and which text-heavy pages fell below the bar.
It's a **diagnostic, not a gate** ("read 94%, here's the 6% I couldn't"): it
never drops a quantity or changes a tier. The `quote_draft` surfaces it too as
`summary.coverage_ratio` + `summary.low_coverage_pages`.

## Trade packs

Quantify runs through a pluggable **pack registry** (`src/xray/packs.py`), so a
trade is added without touching the engine:

- `packs_shed.py` — steel portal-frame sheds (dimension geometry).
- `packs_electrical.py` — electrical Schedule of Loads (table extraction →
  reconciled BOM: breakers, cable, boards, loads).
- `packs_fencing.py` — fence-line takeoff (geometry-driven): run length, posts
  (reconciled against placed blocks or derived from a flagged spacing
  assumption), gates. The first pack to consume `ctx.geometry` / `ctx.symbols`.

Add a pack: implement `Pack.detect()` + `Pack.quantify()`, `register()` it, and
add a real fixture with hand-proven ground truths. See `docs/GUIDE.md`.

## Scale calibration

If the auto-detected scale isn't trustworthy the page carries `scale.verified =
false` (the signal to prompt for calibration). A manual calibration overrides
it:
```
engine.run(pdf, calibrations={0: {"p0": [x, y], "p1": [x, y], "known_mm": 5000}})
```
Two points in PDF coordinates + the real distance → exact mm-per-point.

## Testing

```
set PYTHONPATH=src && python -m pytest tests -q      # expect: 408 passed
```
The two real plan sets under `fixtures/` are the permanent acceptance suite; the
ground truths in `tests/` were proven by hand.

## Layout

```
src/xray/        engine (extract, reassemble, grammar, scale, tables, chains,
                 quantify, packs*, markup_writer, engine, cli)
server/          FastAPI worker + MCP server + quote-line mapping
schema/          takeoff.schema.json — the output contract
fixtures/        real plan sets (shed, warehouse) + electrical schedule
tests/           pytest suite (fixtures are the ground truths)
tools/           dev scripts + the electrical fixture generator
docs/            GUIDE · ACCURACY · HANDOVER · ROADMAP · mind map
templates/       price / labour / overhead upload templates
```

## Docs

- `docs/GUIDE.md` — full user & developer guide.
- `docs/ACCURACY.md` — accuracy results for both fixtures.
- `docs/HANDOVER.md` — integration handover.
- `docs/ROADMAP.md` — the build order (plan of record).
- `CONTEXT.md` — design decisions + empirical findings (source of truth).
