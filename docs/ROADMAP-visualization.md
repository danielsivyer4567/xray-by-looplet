# Roadmap — from measured drawing to photoreal render

**Status: proposed. Nothing here is built. This is a to-do list, captured so the
vision is not lost, not a description of current behaviour.**

## The idea

CAD/DXF in (just text) → a fully-counted structural graph of the building
(every member, every fixing, each a node with an ID) → a wireframe you can spin
(WebGL) → a near-real 8K render (Unreal or an equivalent path tracer). Each
stage adds nothing the stage before could not justify, so the pretty picture at
the end is still backed by numbers that trace to the drawing.

The reference image that prompted this — WTC 1, "281 columns from the DXF,
carried the full height", a structural elevation extruded from plan — is the
Phase 2 target: geometry rebuilt from counted components, not hand-modelled.

## The one rule that cannot bend

**The render is presentation. It is never a source of truth.** Today an LLM
never produces a quantity and every number re-derives from the drawing; that is
the whole product. A photoreal image is the most seductive place to break that
rule, because a beautiful render *looks* authoritative. So:

- Geometry, counts and quantities flow **one way**: drawing → graph → wireframe
  → render. Never backwards. A render never feeds a number back into the graph.
- Every renderable element carries the ID of the measured component it came
  from, so "why is that beam there?" always has an answer that ends at the DXF.
- The render pipeline may be as heavy, GPU-bound and non-deterministic as it
  likes (path tracing, denoisers, AI upscalers) precisely *because* it is
  downstream of the deterministic core and changes no quantity. The byte-
  identity gate stays on the engine, not on the picture.

This is the same "viewer on top of a proven engine" principle already in the
project — extended from a 2D marked-up PDF to a 3D model.

## What already exists (Phase 0 — done)

The deterministic core is further along than the vision assumes:

- **DXF is read as text**, not rasterised — `src/xray/sources/dxf.py`.
- **Components are already counted exactly.** `Symbol` (see `sources/base.py`)
  carries `block_name` as identity and every placement's id as evidence, so a
  count is re-derivable from the output alone — this *is* "count every nut and
  bolt", for anything drawn as a block.
- **Geometry is already extracted** — `Measure` carries lines/polylines/
  dimensions with lengths, and reconciles measured geometry against dimension
  text (`dim-override` checks).
- **The takeoff JSON already emits `entities`, `symbols` and `geometry`** with
  IDs (schema/takeoff.schema.json). That document is the seed of the graph.

## Phase 1 — the building graph ("graphify a building")

Turn the flat takeoff into a queryable graph. **Deterministic, no render yet.**

- [ ] Define a building-graph schema: nodes = components (column, beam, plate,
      bolt, panel…), edges = relationships (connects-to, supports, member-of,
      on-floor, part-of-assembly). Reuse the assemblies layer's recipe idea.
- [ ] Build the graph from an existing `takeoff.json` — no re-reading the DXF;
      the graph is a *view* of the measured output, so it inherits the evidence
      trail for free.
- [ ] Node identity + counting: every node has a stable id and a count that
      traces to symbol placements or geometry. "236 perimeter columns" is a
      query result, not a typed-in number.
- [ ] Annotation: let a human tag nodes ("this is the transfer beam") without
      altering any measured quantity — annotations are metadata, never evidence.
- [ ] Graph queries: counts by type/floor/assembly, bill-of-materials rollup,
      "what connects to X". This is where "every individual nut and bolt for
      referencing" actually lives.
- [ ] Output: `building-graph.json` + an HTML graph view (the existing graphify
      pattern — communities, god nodes — applied to a structure instead of a
      codebase).

## Phase 2 — reconstruct geometry (wireframe / WebGL)

From the graph, rebuild 3D geometry. **Still deterministic.**

- [ ] Extrude plan components to their heights using dimensioned values only
      (the WTC image: plan columns × floor-to-floor × 110). Missing a height is
      a `needs-human`, never a guess — same tier discipline as the engine.
- [ ] Emit a neutral geometry format (glTF or USD), each mesh tagged with its
      graph node id, so the wireframe and the graph are the same object viewed
      two ways.
- [ ] WebGL viewer: spin/section/isolate-by-type, click a member → its graph
      node and evidence. Works in the browser, no Unreal needed — this is the
      shippable milestone.
- [ ] Round-trip check: re-derive counts/lengths *from* the reconstructed
      geometry and gate them against the takeoff. If the model disagrees with
      the drawing, the model is wrong — parity thinking applied to geometry.

## Phase 3 — photoreal render (Unreal or equivalent)

Only now does the heavy renderer enter. **Presentation only.**

- [ ] Export the tagged geometry to the renderer: USD, or Datasmith for Unreal.
      Prefer USD — engine-agnostic, so this is not married to Unreal.
- [ ] Material/lighting assignment driven by the graph (steel, glass, concrete
      per component type), not hand-painted per surface.
- [ ] Render at up to 8K via path tracing; AI denoise/upscale allowed — it is
      downstream of every number and changes none.
- [ ] Keep a component→pixel mapping if feasible (render IDs / object masks), so
      even the final image can point back at the graph. Nice-to-have, not a gate.

### Build it like a ledger, not in one shot

The graph already decomposes the building into small, exactly-specified pieces —
so build the model the way an LLM works a ledger: many bounded slices, each
completed and checkpointed on its own, then stitched, rather than one monolithic
scene the GPU must hold all at once.

This borrows the *logic* of ledger decomposition, not the tooling. It does not
use the autopro or work skills or any agent runner — the render pipeline is
ordinary deterministic build code. "Like a ledger" is the design principle
(bounded, checkpointed, resumable, stitched by exact position), applied by hand
in the build system, not an autonomous agent loop.

This falls straight out of Phase 1. Every graph node is a slice with
**millimetre-precise geometry and a fixed world position**, which is exactly
what makes a slice independently buildable: nothing about column 147 depends on
column 148 having been placed first, because both know precisely where they go.

- [ ] Treat each component (or assembly, or floor) as a ledger slice: build →
      verify against its graph node → save → move on. The slice boundary is the
      graph edge, so the decomposition is free.
- [ ] Checkpoint per slice. A staged import (USD sublayers, or per-floor
      Datasmith batches) means a crash or a change re-runs one slice, not the
      whole 110-storey model. Same reason a ledger persists to disk: resumable.
- [ ] Stitch by shared coordinates. Because positions are absolute and exact,
      slices assemble without a global solve — piece N drops into place because
      its mm coordinates say where, not because it was fitted to its neighbours.
- [ ] Keep the GPU working on one slice at a time. The weight comes off because
      the renderer never needs the entire structure resident — it composites
      staged, pre-built pieces, the way a ledger never holds every task in
      context at once.
- [ ] Cache aggressively: an unchanged slice's built geometry and its render are
      reusable across runs (same input → same output, at the slice level). Only
      changed slices rebuild — the parity idea applied to build artifacts.

The precision is what unlocks all of this. Vague geometry would force a global
fit-up and defeat the staging; mm-exact coordinates make every slice
self-contained, which is the whole point of a ledger.

### Honest unknowns for Phase 3

Worth stating so nobody is surprised later:

- **Photoreal needs more than geometry.** Materials, lighting, surroundings and
  context are most of what makes a render read as real. The graph gives correct
  *shapes*; it does not give a convincing *scene*. Budget for that.
- **"Unreal extension" is really a pipeline.** The realistic shape is an export
  path (USD/Datasmith) + a render project, not a plugin living inside Unreal.
  Start with the export; treat any in-engine plugin as a later optimisation.
- **Determinism ends at Phase 2.** The render will not be byte-reproducible and
  should not try to be. Its correctness claim is "the geometry is faithful",
  proven at Phase 2, not "the pixels are reproducible".

## Suggested order of attack

1. Phase 1 graph from an existing takeoff — highest value, lowest risk, all
   deterministic, and immediately useful for BOM/reference on its own.
2. Phase 2 WebGL wireframe — the visible, shippable win; validates the whole
   idea without any renderer.
3. Phase 3 render — only once 1 and 2 prove the geometry is trustworthy.

Do not start Phase 3 to get a pretty picture before Phase 2 can prove the
picture is of the *right* building.
