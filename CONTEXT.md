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
- No warehouse/industrial quantity rule pack yet (by design). Trade packs so far:
  shed, electrical, fencing (see the 2026-07-23 additions below).

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

**Still on fitz (dev-only, NOT shipped, NOT in requirements):**
`tools/extract_entities.py` / `tools/probe_layers.py`. Migrate in P8.

*(An earlier note here also listed "the DXF export tool". There is no such tool
in the repo — no DXF reader or writer is tracked, and `ezdxf` is not a
dependency. `out/*.dxf`, if present, is a stray artifact from a one-off
prototype, not something the codebase generates.)*

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

## Session additions (2026-07-23) — geometry packs, graph, wireframe, costing

Test count now **422** (was 305). Parity: `warehouse-design21` was re-frozen
because its empty-takeoff `pack-coverage` message now lists `fencing` among the
measurable trades (the only byte change; shed + electrical untouched).

- **PackContext gains `symbols` + `geometry`** (`packs.py`, additive with
  `field(default_factory=list)`). `engine.run` passes `read.symbols` /
  `read.geometry`. Text/table packs (shed, electrical) ignore them; a
  geometry-driven pack consumes them. Does not change any PDF-path output.
- **Structural-count pack** (`packs_structural.py`) — LAYER-SEMANTIC counting.
  Components drawn as polylines (not blocks) on named layers weren't counted; a
  real WTC column plan read as 0 quantities. `RE_COLUMN` matches column layers
  (PERIMETER_COLUMNS / CORE_COLUMNS / PIER / PILE …); the pack counts polylines
  per such layer -> a `reconciled` quantity per layer with per-member evidence
  (each polyline's id). Boundary layers (FOOTPRINT, walls) are not counted.
  Fixture `fixtures/cad/structural-columns.dxf` (12 perimeter + 4 core, generator
  `tools/make_structural_fixture.py`). Fires only on DXF column layers, so no
  existing fixture/parity output changes. 5 tests.
- **Anti-flake corpus** (`fixtures/corpus/manifest.json`, `tests/test_corpus.py`).
  A rules engine flakes on unanticipated file shapes; the cure is discipline —
  every real file that trips it becomes a permanent case (file + `expect`:
  `provenance` bool, `minQuantities`, `quantities` {item: qty}) run via a
  parametrized harness. Adding coverage is a JSON edit. Seeded across 7 shapes
  (vector PDF, electrical, empty-match warehouse, fence, polyline-columns, nested
  blocks, flattened-fake). See `fixtures/corpus/README.md`.
- **Provenance fix (2026-07-24):** a real WTC DXF false-flagged as a flattened
  plot — it draws columns as polylines with no DIMENSION entities. The deciding
  tell is now the LAYERS: suspicion requires no blocks AND no dims AND **no
  trade-semantic layer** (`trade_for(layer)` empty for all geometry). Generic
  buckets (0/GEOMETRY/TEXT) still flag; named trade layers read clean.
- **Fencing pack** (`packs_fencing.py`) — the first geometry-driven trade.
  `detect`: any LINE/LWPOLYLINE on a layer matching `/FENC/i`, or a POST/GATE
  block on such a layer. `quantify`: fence run length (lm) = summed runs
  converted to metres by the resolved unit (`UNIT_TO_M`; unresolved unit ->
  needs-human, never a guessed scale); posts = **reconciled** when placed POST
  blocks equal the spacing estimate `floor(L/2.4)+1`, **single-source + flagged
  `count` check** when they disagree, **needs-human** when derived from the 2.4 m
  spacing ASSUMPTION alone; gates = exact count of GATE blocks. Panels/rails/
  footings deliberately NOT emitted (need the fence system). Fixture
  `fixtures/cad/fencing-boundary.dxf` (gen `tools/make_fencing_fixture.py`):
  48.0 lm run, 21 posts, 1 gate — exact by construction. 10 tests.
- **Building graph** (`graph.py`, visualization Phase 1). `build_graph(takeoff,
  annotations=None) -> graph` — a VIEW of a takeoff, no re-reading the drawing.
  Nodes: `type` (god node per block name, count = placements), `component` (per
  placement, carries evidence), `measure`, `quantity`. Edges: `instance-of`,
  `member-of` (the assembly DAG), `evidenced-by`. Deterministic + never mutates
  the takeoff; annotations are metadata, never evidence. Queries:
  `count_by_type`, `nodes_of_type`, `neighbours`, `bill_of_materials`.
  `render_html` = self-contained offline view. CLI `python -m xray.graph`.
  12 tests.
- **Wireframe** (`wireframe.py`, visualization Phase 2). `build_scene(takeoff,
  heights=None, default_height=None) -> scene`: one vertical element per placed
  component at its measured (x,y), tagged with its graph node id. x,y faithful;
  height `given` if supplied, else an ASSUMED viewing value flagged
  `needs-human` (never a quantity). `roundtrip_check(scene, takeoff)` re-derives
  counts from the scene and gates them against the takeoff. `render_html` =
  self-contained WebGL viewer. CLI `python -m xray.wireframe`. 10 tests.
- **Costing** (`pricing/costing.py`, P2 — NO LLM). `load_price_list(csv)` reads
  the `templates/price-list.template.csv` shape. `cost_takeoff(quantities,
  price_rows, as_of=None, freshness_days=None, region=None) -> {lines, summary}`:
  joins on item/alias + unit (unit is a hard gate via `mapping.units_compatible`),
  multiplies, stamps provenance. Unmatched / ambiguous / stale / POA / wrong-unit
  all flag `needs-human`, rate null. `as_of` is explicit (never "today" ->
  reproducible). Exports `to_csv` (Excel) + `quote_html`. CLI
  `python -m pricing.costing`. 12 tests.
- **Bad-input boundary** (`preflight.py`, engine-level; distinct from the
  network-facing `server/hardening.py`). `check_input(path, max_bytes=300MB) ->
  adapter` raises a typed `InputError(kind, detail)` — kind ∈ {not-found, empty,
  too-large, unsupported, malformed, encrypted, unreadable} — for empty /
  oversized / wrong-format (magic bytes) / password-protected / corrupt files,
  before any parser runs. `engine.run` calls it first and wraps `adapter.read`
  so a parser failure surfaces as `InputError`, never a traceback. `cli.py`
  prints a one-line reason and returns exit 2 (1 for not-found). 13 tests.
- **DXF provenance flag.** A plot flattened into a DXF container parses cleanly
  but has no CAD semantics; `sources/dxf.py` sets `ReadResult.provenance =
  {suspect, reasons}` when the structural signature holds (no INSERTs AND no
  DIMENSIONs AND has loose geometry; `$LASTSAVEDBY==ezdxf` only corroborates,
  never triggers alone — the repo's own fixtures are ezdxf-authored). `engine.run`
  emits a `provenance` flag check (new schema kind) that reaches `review[]`, so
  `fixtures/negative/shed-flattened-from-pdf.dxf` is flagged not ingested. Real
  fixtures are untouched. `Measure`/`ReadResult` gained `id`/`provenance` fields.
- **Solid glTF export** (`solid.py`, visualization Phase 3 on-ramp). Phase 2 drew
  lines; a renderer needs solids. `build_solids(takeoff, heights=None,
  default_height=None, post_size=None)` extrudes each placed component to a box
  prism at its measured (x,y); `to_gltf(solids)` writes a valid, self-contained
  **glTF 2.0** (buffer embedded as a base64 data URI, pure stdlib struct/base64)
  where every mesh is a node whose `name` is the graph node id and whose `extras`
  carry `xrayType`/`xrayTrade`/`heightTier` — so the tag rides into Unreal /
  Blender / Omniverse / a path-tracer. Deterministic (fixed vertex/index order,
  no timestamps). x,y measured; height given or an ASSUMED value flagged per mesh
  (determinism ends at the geometry, same as Phase 2). `roundtrip_check` gates
  mesh counts vs the takeoff. CLI `python -m xray.solid <takeoff.json>` -> `.gltf`.
  10 tests (incl. decoding the embedded buffer to verify real coordinates).
  The **render itself** (materials/lighting from the graph -> Unreal/path-tracer)
  is downstream, non-deterministic, and GPU-bound — not in this repo.
- **OCR stage** (`ocr.py`). Scanned/photographed sheets carry pixels, not a text
  layer. `render_page(pdf, i, dpi) -> (PIL image, scale)` (pdfium); an `OcrBackend`
  protocol (`recognize(image) -> list[OcrWord]`); `ocr_words(boxes, page, scale)`
  converts pixel boxes -> `reassemble.Word` in PDF points (point = pixel/scale)
  tagged `source="ocr"`. Backends: `StubBackend` (deterministic, test/demo only —
  recognises nothing), `TesseractBackend` (activates only when pytesseract + the
  tesseract binary exist, else raises a clear install message; PaddleOCR fits the
  same interface). `available_backend()` returns a real backend or None. Rendering
  + conversion + the source tag are tested; **recognition is the backend's job and
  no engine is bundled.** **Wired into `engine.run(pdf, ocr=...)` as OPT-IN**
  (`engine.OCR_DPI`, `engine._resolve_ocr`): `ocr=True` auto-detects an installed
  engine (raises `RuntimeError` if none) or pass an `OcrBackend`; the CLI has
  `--ocr`. Default `None` → byte-identical output, so the parity gate holds; OCR
  fires ONLY on `raster`/`sparse` PDF pages (never vector pages or DXF), and the
  recovered words join the pipeline tagged `source="ocr"` and bump the coverage
  denominator. A scanned fixture with hand-proven ground truths (to prove real
  end-to-end recognition) is still a future slice. 12 tests (7 unit + 5 wire).
