# X-Ray by Looplet — Accuracy Results

Every result below is re-proven on each run against the two real plan sets and
was independently re-verified by an adversarial pass that ignored the builders'
claims, re-ran the CLI, re-validated both JSONs against the schema, and reopened
the marked PDFs.

**Overall:** 393/393 automated tests pass. Adversarial verdict: PASS on all
checks, zero fixes required.

---

## Fixture A — A-Line garage

`fixtures/shed-manners-aline.pdf` · 5 pages · Skia/PDF (Chromium print) ·
whole-word text (reassembler is a near-passthrough here).

| Metric | Value |
|---|---|
| Entities | 214 |
| Checks | 5 pass / 4 flag |
| Quantities | 8 |
| Generated annotations | 45 |

### Quantities produced

| Item | Qty | Unit | Tier | Formula (abridged) |
|---|---|---|---|---|
| portal frames | 5 | ea | reconciled | `bays + 1 = 4 + 1` |
| portal frame steel | 87.7 | lm | reconciled | `5 x (2x4.2 + 2x(9/2 / cos 10deg))` |
| roof sheeting | 146.2 | m2 | single-source | `2 x 16 x 4.5694` |
| opening D0 | 5 | ea | single-source | count of tags on plan |
| opening D1 | 5 | ea | single-source | count of tags on plan |
| opening D2 | 10 | ea | single-source | count of tags on plan |
| opening D3 | 10 | ea | single-source | count of tags on plan |
| wall cladding | 183.5 | m2 | needs-human | side + gable - OPEN bay 1 |

### Ground-truth checks re-proven

| Check | Result | Detail |
|---|---|---|
| Floorplan chain x3 | pass | `6000+3500+3500+3000`, plus two 7-part chains, all = 16000 |
| Roof-pitch trig | pass | rise = tan(10deg) x 4.5 m = 793 mm; drawn value matches (delta -0.47 mm) |
| Frame count | pass | "PORTAL RAFTER" label appears exactly 5x = bays + 1 |
| Phone / postcode / copyright | pass | false-positive chains (03 5452 2255, postcode 2732, copyright 2019) correctly masked, never emitted |

Expected tolerances (encoded in tests): +/-1 unit or 0.5%.

---

## Fixture B — Design21 warehouse

`fixtures/warehouse-design21.pdf` · 50 pages · Adobe Acrobat Pro DC Paper
Capture / PScript5 (CAD print) · glyph-split text layer.

| Metric | Value |
|---|---|
| Entities | 1,273 |
| Checks | 3 pass / 11 flag |
| Page kinds | 44 vector / 5 raster / 1 sparse |
| Generated annotations | 65 (+25 pre-existing in source) |
| Quantities | 0 (no warehouse rule pack yet — by design) |

### Glyph-split recovery (the hard problem)

On the CAD-printed vector sheets, many dimension strings exist in the text layer
only as fragmented single-glyph runs (12% of words are single characters). The
reassembler recovers whole tokens by clustering fragments that share a baseline.

| Target | Before reassembly | After | Source |
|---|---|---|---|
| `29995` | absent as a whole word | recovered | reassembled |
| `13530` | absent | recovered | reassembled |
| `2745` (x5) | absent | recovered | reassembled |

### Ground-truth checks

| Check | Result | Detail |
|---|---|---|
| Chain reconciliation | pass | `13530 + 16465 = 29995` — recovered members, exact sum |
| Concrete-panel chain | flag | `2745x5 + 2742 = 16467` vs stated 16465 (delta +2); drawing note says panels are approximate — flagged, not dropped |
| Scan-page detection | pass | pages 23, 24, 25, 26, 29 classified `raster` despite an invisible OCR text layer |

---

## Adversarial verification summary

Performed as a fresh, distrustful re-run of everything:

1. `pytest` — 393 passed, exit 0.
2. CLI fresh runs on both fixtures — exit 0, all four output files written.
3. Independent schema validation of both JSONs — valid; `engine.name == "xray-by-looplet"`.
4. Ground truths re-checked inside the JSONs (not via pytest) — all present.
5. Marked PDFs reopened via pikepdf — annotations carry `/NM`, `/Subj`,
   `/T == "X-Ray by Looplet"`; shed has `/Measure` dicts; embedded `takeoff.json`
   roundtrips and matches the sibling `.xray.json` counts exactly.
6. Known discrepancy diagnosed to root cause (see Known limitations in GUIDE.md /
   CONTEXT.md): the off-baseline `3579 = 2289 + 90 + 1200` chain.
7. Junk scan — no spurious pass-check explosion (shed 9 checks, warehouse 14).

**Verdict: PASS — the single known discrepancy degrades safely to a
human-review flag, not a wrong quantity or a false pass.**
