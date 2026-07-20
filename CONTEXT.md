# X-Ray by Looplet — build context

**READ THIS FIRST.** This file is the single source of truth for design decisions,
empirical findings, module APIs, and test expectations. Do not deviate from the
APIs or the schema without updating this file.

## What this is

A **headless** construction-plan takeoff engine. Input: a plan PDF. Output:
1. `takeoff.json` — structured entities, verification checks, quantities with
   evidence chains (conforms to `schema/takeoff.schema.json`)
2. `<name>.marked.pdf` — the same PDF with results injected as **standard ISO
   32000 PDF markup annotations**, so any standards-compliant viewer renders them.

There is deliberately NO UI. Presentation is delegated (Looplet CRM, an LLM
formatter, Excel). **An LLM never produces a quantity** — quantities come only
from deterministic grammar + geometry + rules.

## Pipeline

```
1 extract   PDF text char boxes + image objects (pypdfium2; lossless on vector PDFs)
2 reassemble glyph-split text runs -> whole tokens        [src/xray/reassemble.py]
3 grammar   tokens -> typed entities                      [src/xray/grammar.py]
4 scale     per-page scale voting                         [src/xray/scale.py]
5 checks    chain sums, trig, cross-sheet reconciliation  [src/xray/chains.py]
6 quantify  rule packs -> quantities w/ evidence          [src/xray/quantify.py]
7 write     takeoff.json + marked.pdf                     [src/xray/markup_writer.py]
   orchestrated by                                        [src/xray/engine.py]
   CLI                                                    [src/xray/cli.py]
```

## Empirical findings (2026-07-21, from the two fixtures — tests must encode these)

### fixtures/warehouse-design21.pdf (Design21 Architecture, 50 pages)
- Producer "Adobe Acrobat Pro DC Paper Capture", Creator PScript5 (CAD print).
- Pages 1-13 = vector drawing sheets (sheet 04: ~213k line segments, 1026 words).
  Pages 14-50 = documentation; pages 23-26, 29 are raster scans.
- **GLYPH SPLITTING**: many dimension strings exist in the text layer only as
  fragmented runs. Proven: `29995`, `13530`, `2745`, `5010`, `6700` on sheet 04
  are absent as whole words but present when all text is concatenated. 12% of
  words are single characters. Module `reassemble` must recover them by
  clustering glyphs/fragments that share a baseline (or a vertical line for
  rotated text) with small inter-fragment gaps.
- Known-true chain sums on sheet 04 (acceptance tests):
  `29995 = 13530 + 16465`; `3579 = 2289 + 90 + 1200`.
  Known near-miss with explanation: concrete-panel chain `2745*5 + 2742 = 16467`
  vs stated `16465` (drawing note says panel sizes are approximate) -> must be
  reported as a FLAG check, delta +2, not silently dropped.
- Sheet 01 contains a DRAWING INDEX table (sheet no -> title -> scale). Declared
  scales: 02=1:200, 03..07=1:100, 08..11=1:100, 12=1:100, 13=1:50 (+1:10 inset
  on sheet 10). Title block bottom-right carries "SCALE @A2 1:100" style tokens.
- Embedded-text quirk: `W0l` appears where `W01` is meant -> tag normalizer must
  map lowercase l->1 / O->0 inside TAG tokens.

### fixtures/shed-manners-aline.pdf (A-Line / North VIC Sheds garage, 5 pages)
- Producer Skia/PDF (Chromium print). Whole-word text, NO glyph splitting.
  => reassembler must be a no-op passthrough here (regression test).
- Title-block spec token `16Lx9Wx4.2H|10°|4bays` (regex: degree sign may arrive
  as `°` or `o`). Parse to L/W/eave/pitch/bays.
- All three floorplan chains sum exactly: `6000+3500+3500+3000 = 16000`,
  `200+5775+350+2850+650+2850+3325 = 16000`,
  `200+5775+350+2850+4915+820+1090 = 16000`.
- Trig check: rise = tan(pitch) * W/2 = tan(10 deg)*4500 = 793 mm, and `793`
  is drawn on the elevations; rafter = 4500/cos(10 deg) = 4570 mm.
- `PORTAL RAFTER` label appears exactly 5x on page 1 (5 frames = 4 bays + 1).
- FALSE-POSITIVE chains to mask: `[5452,2255,2732]` = phone "03 5452 2255" +
  postcode 2732; `[3400,2850,2019]` = opening-schedule row + copyright year.
  => chains must exclude tokens inside detected title-block / table regions
  (title block = bottom band of page; opening schedule = ruled table region).
  Minimum viable masking: exclude the bottom ~22% of the page and any token
  whose neighbors include `P:` / `Copyright` / postcode-after-state patterns.
- Opening schedule (page 1 table): D0-1 ROLLER 3400x2850; D2 ROLLER 3000x2850;
  D3 PA DOOR 2040x820. Bay 1 is marked OPEN both sides -> cladding quantity for
  side walls must exclude it and be tiered `needs-human` (assumption flag).

### Shed quantity pack expectations (tests, tolerance ±1 unit/0.5%)
- frames = 5; portal steel lm = 5 * (2*4.2 + 2*4.5696) = 87.7 (unit lm)
- roof sheeting m2 = 2 * 16.0 * 4.5696 = 146.2
- openings from schedule as counted items.

## Standard PDF markup keys (ISO 32000)

Write on each generated annotation, using only standard ISO 32000 keys:
- `/NM` unique UUID string, `/Subj` (e.g. "Length Measurement"), `/T` author
  ("X-Ray by Looplet"), `/Contents` human summary, `/CreationDate`, `/M`.
- Measurements: standard `/Measure` dict (ISO 32000 RL type) + `/IT` intent
  (`LineDimension`, `PolygonDimension`, `PolygonCount`) so any standards-compliant
  viewer shows scaled values. OPTIONAL (phase 2): `/MeasurementTypes` int
  (observed values: 128 Count, 129 Area, 130 Length, 132 Volume, 384 Diameter,
  1152 Angle — treat as observed subset, bitflag-like; do NOT hardcode as a
  closed enum).
- Do NOT write any vendor-proprietary annotation keys — standard keys only, so
  the output stays portable across viewers.
- Also attach `takeoff.json` as a PDF embedded file (EmbeddedFiles name tree)
  so the document is self-contained.

## Patent guardrails (engineer-around, from verified dossier)
- NO animated/time-segmented expanding fill UX (US 10,452,751 / 11,087,069).
  Headless engine unaffected; keep any future fill instant single-pass.
- NO tool-set-linked legend that live-updates cumulative quantities
  (US 10,534,859 family). Static summary tables are fine.
- NO color/size pre-filtered visual template search per US 9,846,707 specifics.

## Module APIs (implement exactly; all pure-Python, py311, deps: pypdfium2, pikepdf)

```python
# reassemble.py
@dataclass
class Word:  # PDF points, origin top-left as PyMuPDF delivers
    text: str; x0: float; y0: float; x1: float; y1: float
    page: int; source: str  # "text" | "reassembled"
def extract_words(doc: fitz.Document, page_no: int) -> list[Word]  # raw
def reassemble(words: list[Word]) -> list[Word]  # merged runs + passthrough

# grammar.py
@dataclass
class Entity:
    id: str; page: int; type: str  # DIM|TAG|SCALE|SPEC|LABEL|LEVEL|STD|NOTEKEY
    value: object; raw: str; bbox: tuple[float,float,float,float]
    confidence: float; source: str
def classify(words: list[Word], page_rect: tuple[float,float]) -> list[Entity]
def parse_spec_token(text: str) -> dict | None  # {"L":16.0,"W":9.0,"eave":4.2,"pitch":10.0,"bays":4}

# scale.py
def vote_scale(entities: list[Entity], page_rect, declared: str | None) -> dict
# -> {"value":"1:100","mmPerPt":..., "methods":[...], "confidence":0..1}

# chains.py
@dataclass
class Check:
    id: str; kind: str  # chain-sum|trig|cross-sheet|count
    status: str         # pass|flag
    detail: str; delta: float | None; evidence: list[str]  # entity ids
def titleblock_mask(page_rect) -> tuple  # region to exclude (bottom band)
def find_chain_checks(entities: list[Entity], page_rect) -> list[Check]
def trig_check(spec: dict, entities: list[Entity]) -> Check | None

# quantify.py
@dataclass
class Quantity:
    id: str; trade: str; item: str; qty: float; unit: str
    formula: str; tier: str  # reconciled|single-source|needs-human
    evidence: list[str]; notes: str
def shed_pack(spec: dict, entities: list[Entity], checks: list[Check]) -> list[Quantity]

# markup_writer.py
def write_marked_pdf(src: str, out: str, result: dict) -> None
# annotate page 1 region of each check/quantity evidence bbox; embed takeoff.json

# engine.py
def run(pdf_path: str, calibrations: dict | None = None) -> dict
# full result conforming to schema/takeoff.schema.json
# cli.py:  python -m xray run <pdf> [--out DIR]  -> writes takeoff.json + marked.pdf
```

Style: match existing tools/ scripts — plain Python, dataclasses, no heavy deps,
no type-checking framework. Tests: pytest, fixtures referenced relative to repo root.

## Known limitations (v0.1.0, adversarially verified 2026-07-20)

- **Off-baseline chain members**: warehouse sheet 04's proven chain
  `3579 = 2289 + 90 + 1200` is emitted as a FLAG (`2289+1200+86 = 3575 vs
  3579, delta -4`) instead of a pass. Root cause: the drawn "90" sits 7.2pt
  below the band baseline (> BAND_TOL_PT 6.0) while a genuinely drawn "86"
  from an adjacent detail-dim stack sits exactly on it. No provably safe
  banding change fixes this without risking cascading merges; the failure
  mode degrades to a human-review flag, never a wrong pass or quantity.
- A handful of small-dim near-miss flags of the same class appear on both
  fixtures (all review-tier, none false passes).
- No warehouse/industrial quantity rule pack yet (by design; shed pack only).

## PDF backend swap: PyMuPDF -> pypdfium2 (2026-07-20)

**Why:** PyMuPDF is AGPL-3.0 (commercial-distribution risk). pypdfium2 is
Apache-2.0 / BSD-3-Clause (permissive, $0). Only the *extraction* stage touched
the library, so the swap is contained.

**What changed (src/xray only — the shipped engine is now fitz-free):**
- `reassemble.extract_words(doc, page_no)` rebuilt on PDFium character boxes:
  group chars into whitespace-delimited tokens; **flip y** (PDFium is
  bottom-left / y-up) to the top-left / y-down convention the Word contract and
  the whole pipeline assume. `doc` is now a `pypdfium2.PdfDocument`.
- `engine._page_kind` uses `PdfImage.get_px_size()` for the raster pixel test
  (PDFium `PdfImage` has no `get_pos`; per-image try/except so one missing
  method can't abort detection). `get_size()` for page dims,
  `get_metadata_value("Producer")` for producer.

**Re-proven (all 86 tests green, both fixtures):**
- Shed quantities IDENTICAL: 5 frames (reconciled), 87.7 lm steel (reconciled),
  183.5 m2 cladding (needs-human); checks 5 pass / 4 flag.
- Warehouse acceptance chain `13530 + 16465 = 29995` still reconciles (pass);
  glyph-split targets 29995/13530/2745/5010/6700 all recovered after reassembly.
- Re-baselined (legitimate backend tokenisation difference, NOT a regression):
  sheet-04 raw token count 1026 -> 1032; the PyMuPDF-specific `150`+`0`->`1500`
  micro-case tokenises differently under PDFium, so that unit test now asserts
  the equivalent real recovery (13530 absent->present) instead.

**Still on fitz (dev-only, NOT shipped, NOT in requirements):** the DXF export
tool + `tools/extract_entities.py` / `tools/probe_layers.py`. Migrate in P8.

## v0.1 additions after initial build (2026-07-20)

- **Pluggable pack registry** (`packs.py`): `Pack.detect/quantify`, `register`,
  `run_packs(PackContext)`. engine.run dispatches quantify through it; ShedPack
  (`packs_shed.py`) reproduces the original behaviour exactly. Packs may declare
  extra units via `register_units` (electrical uses VA). Adding a trade never
  touches engine.run.
- **Table extraction** (`tables.py`): words -> rows (baseline) + columns
  (recurring left-edges) -> Table with headers + `as_dicts()`; drops preamble,
  splits multiple tables by vertical gaps. The bridge from a schedule *drawing*
  to CSV-shaped rows.
- **Electrical pack** (`packs_electrical.py`): consumes tables -> reconciled BOM
  (breakers by rating/poles, cable by size [needs-human: metres need run
  lengths], boards, total connected/demand VA) + reconciliation and
  phase-balance checks. Proven end-to-end from `fixtures/electrical-schedule.pdf`.
- **Scale calibration** (`scale.py`): `calibrate(p0,p1,known_mm)` + a
  `calibration` arg to `vote_scale` that wins outright; new `verified` flag is
  False when the winner rests only on the paper-size prior (PDX's prompt signal).
  `engine.run(pdf, calibrations={page: {...}})` threads per-page overrides.
- **MCP server** (`server/mcp_server.py`): FastMCP exposing run_takeoff,
  quote_draft, run_takeoff_calibrated, marked_pdf, engine_info — the Looplet
  integration surface. HTTP worker (`server/app.py`) + quote-line mapping
  (`server/quote_lines.py`) unchanged.
- Schema: quantity `unit` enum extended (VA/kVA/A/kW); page `scale` gains
  optional `verified`.
