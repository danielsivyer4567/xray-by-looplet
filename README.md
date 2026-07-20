# X-Ray by Looplet

**Sees through plans. PDF in, quantities out.**

A headless construction-plan takeoff engine. Feed it a plan PDF; it returns:

1. `<plan>.xray.json` — typed entities, verification checks, and quantities
   with evidence chains and confidence tiers
   (contract: `schema/takeoff.schema.json`)
2. `<plan>.marked.pdf` — the same PDF with results injected as standard,
   Bluebeam-Revu-compatible annotations, plus the full JSON embedded as an
   attachment so the document is self-contained.

There is deliberately no UI. Presentation is delegated (Looplet CRM, an LLM
formatter, Excel). **An LLM never produces a quantity** — quantities come only
from deterministic grammar + geometry + rules, and every number carries the
formula and the entity IDs that prove it.

## Usage

```
pip install -r requirements.txt
set PYTHONPATH=src        # or: export PYTHONPATH=src
python -m xray run fixtures/shed-manners-aline.pdf [--out DIR]
```

## Trust model

Every quantity is tiered: `reconciled` (independent evidence agrees),
`single-source`, or `needs-human` (an assumption was required — e.g. an
open bay affecting cladding). Chain sums, trigonometry, and label counts
are cross-checked; near-misses are FLAGGED with their delta, never dropped.

## Development

```
python -m pytest tests -q
```

The two PDFs under `fixtures/` are real plan sets and the permanent
acceptance suite; the ground truths encoded in `tests/` were proven by hand.
See `CONTEXT.md` for the full design record and empirical findings.

## Documentation

- `docs/GUIDE.md` — full user & developer guide (usage, dependencies, updating, CLI, pipeline, output contract, trust tiers, module reference, extending).
- `docs/ACCURACY.md` — accuracy results for both real-plan fixtures + adversarial verification summary.
- `docs/mindmap.mermaid` — rendered system mind map (Mermaid source).
- A styled, self-contained HTML reference (rendered mind map + pipeline diagrams, accuracy tables) is available as the "xray-by-looplet-docs" artifact.
