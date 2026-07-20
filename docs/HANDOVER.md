# X-Ray by Looplet — Integration Handover Note

**For:** whoever wires X-Ray into the extensions / Looplet stack.
**Status at handover:** v0.1.0 · 117/117 tests passing · both real-plan fixtures
run clean · `pip check` clean. Verified 2026-07-20.

---

## 1. What you are receiving

A **headless** takeoff engine. It is a pure pipe:

```
plan.pdf  ->  xray  ->  <plan>.xray.json   (the contract: entities, checks, quantities+evidence)
                        <plan>.marked.pdf  (annotated with standard ISO 32000 PDF markup, JSON embedded)
```

There is no UI and no server in the box — that is deliberate. The extension is
the *caller*; the engine is the *callee*. See `docs/GUIDE.md` for full API and
`docs/ACCURACY.md` for proven results.

---

## 2. How an extension consumes it (two supported modes)

**Mode A — subprocess (simplest, recommended first).**
The extension shells out to the CLI and reads the JSON file back.

```
python -m xray run <plan.pdf> --out <dir>
# then read <dir>/<plan>.xray.json
```

**Mode B — worker + HTTP (for Looplet server-side).**
Wrap `engine.run(pdf_path) -> dict` in a thin FastAPI/worker endpoint. A Looplet
job posts a PDF, the worker runs the engine, the returned dict is written to
Postgres and mapped onto draft quote lines. Slots into the existing Supabase
worker pattern; no new infra category.

In **both** modes the engine runs as its **own process** — this is what keeps it
isolated from the extension's runtime.

---

## 3. Dependency clash — assessment

**No cross-language clash is possible.** X-Ray is Python; the extension layer is
JavaScript/TypeScript. They share no package manager and no dependency tree. The
extension calls the engine across a process boundary; it never imports it.

**Python side is internally clean.** `python -m pip check` -> "No broken
requirements found." Runtime deps and verified builds:

| Package | Pinned floor | Verified build | Licence |
|---|---|---|---|
| pymupdf | `>=1.24` | 1.28.0 (MuPDF 1.29.0) | **AGPL-3.0 / commercial** — see 4 |
| pikepdf | `>=9` | 10.10.0 | MPL-2.0 (permissive) |
| jsonschema | `>=4` | 4.26.0 | MIT (permissive) |
| pytest (dev only) | `>=8` | 8.x | MIT |

**The one rule that prevents a clash:** run the engine in a **dedicated Python
venv or container**. Do NOT install it into a shared Python environment that
already pins different pymupdf/pikepdf versions. Requirements floors are recorded
in `requirements.txt`; pin exact versions in the deployed venv for reproducibility.

Runtime requirement for the host: **Python 3.11** available to the worker
(bundled in the container image, or a managed runtime). Nothing else.

---

## 4. Licensing flag (action required before commercial ship)

**PyMuPDF is AGPL-3.0** (or a paid commercial licence from Artifex). pikepdf and
jsonschema are permissive and carry no such obligation. AGPL can trigger
source-disclosure obligations when software is **distributed** or offered as a
**network service** in a commercial product.

**Action:** get a legal read before production. This is not blocking for internal
use or a private prototype. If it becomes an issue, the extraction path
(`reassemble.py`, which is the only PyMuPDF consumer) can be swapped to
`pypdfium2` (BSD/Apache) with contained effort — the rest of the pipeline is
licence-clean.

---

## 5. The contract is stable

The `takeoff.json` shape (see `schema/takeoff.schema.json`) is the integration
boundary. It is validated in CI by `jsonschema`. Renaming the engine changes only
`engine.name`; it never changes the shape. Build the extension against the schema,
not against internal module APIs.

---

## 6. Known limitations to carry forward

- **Warehouse quantity pack not built yet** (by design). v0.1.0 ships the shed
  portal-frame pack only. The warehouse fixture exercises extraction, checks, and
  scan detection but returns 0 quantities. Add a rule pack per `docs/GUIDE.md`
  ("Extending") when a warehouse job appears.
- **Off-baseline near-misses** surface as `flag` / `needs-human`, never as false
  passes. The extension should render `checks[].status == "flag"` and the
  `review[]` array as items a human confirms — that is the trust model, not a bug.

---

## 7. Integrator checklist

- [ ] Provision Python 3.11 for the worker (dedicated venv / container).
- [ ] `pip install -r requirements.txt`; pin exact versions in the deploy lock.
- [ ] Choose Mode A (subprocess) or Mode B (worker endpoint).
- [ ] Map `quantities[]` -> draft quote lines; keep `formula`, `tier`, `evidence`.
- [ ] Surface `tier == needs-human` and `checks[].status == flag` for human review.
- [ ] Store the `marked.pdf` as the reviewable artifact.
- [ ] Resolve the PyMuPDF licence question (section 4).
- [ ] Run `python -m pytest tests -q` in CI as the regression gate (expect 75 passed).

---

## 8. Source of truth

`CONTEXT.md` — every design decision and empirical finding. Read it first. Any
change to APIs, tolerances, or fixtures must update it and add/adjust a test.
