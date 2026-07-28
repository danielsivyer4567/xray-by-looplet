# Corpus — the anti-flake regression net

A rules engine doesn't flake randomly (the parity gate proves same-input →
same-output). It flakes when it meets a **file shape it wasn't tuned for**: a
heuristic mis-fires (false positive) or a real component isn't recognised
(coverage gap). Both were hit by real files this project has seen — a plot
flattened into a DXF, and a floor plan whose columns are polylines, not blocks.

The cure is discipline, not cleverness:

> **Every real file that trips the engine becomes a permanent case here, with
> hand-checked expectations — so that shape can never regress.**

## How it works

`manifest.json` lists cases; each is one file + the invariants it must satisfy.
`tests/test_corpus.py` parametrizes over them, so **adding a case is one JSON
entry**, and the whole corpus runs on every change.

Supported expectations (`expect`):
- `provenance` (bool) — whether a `provenance` flag must (not) be raised.
- `minQuantities` (int) — at least this many quantities.
- `quantities` ({item: qty}) — a quantity with this exact item + value exists.

## Adding a file that flaked

1. Drop the file under `fixtures/` (a real client file → anonymise it, or build a
   synthetic fixture of the same shape with a generator in `tools/`).
2. Run it, hand-check the numbers, add a case to `manifest.json`.
3. If it exposed a bug, fix the engine — the case now guards the fix forever.

That is the whole anti-flake loop: the engine gets monotonically harder to break
every time a new real drawing is fed to it.
