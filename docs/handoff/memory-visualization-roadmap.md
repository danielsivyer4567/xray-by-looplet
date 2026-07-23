---
name: xray-visualization-roadmap
description: "X-Ray future direction — DXF → counted building graph → WebGL wireframe → photoreal (Unreal/USD) render; roadmap only, nothing built"
metadata: 
  node_type: memory
  type: project
  originSessionId: c4929069-94e4-403a-bd70-14e8664a48fa
  modified: 2026-07-23T04:44:40.535Z
---

**2026-07-23 — Daniel's vision, captured as a to-do roadmap (NOT built).** Full doc committed at `docs/ROADMAP-visualization.md` on `feat/desktop-electron` (19bc15c). Prompted by a WebGL wireframe of WTC1 ("281 columns extruded from plan").

Pipeline: **CAD/DXF (text) → fully-counted building graph (every member/fixing a node w/ id, annotatable) → WebGL wireframe → near-real 8K render (Unreal or USD/path-tracer).** Like graphify but for a building.

Phases:
- **Phase 0 = already done** (further than the vision assumed): DXF read as text (`src/xray/sources/dxf.py`), `Symbol` counts components exactly by block_name with evidence ids, `Measure` extracts geometry, and takeoff.json already emits `entities`+`symbols`+`geometry`. That's the "count every nut and bolt" seed.
- **Phase 1** = building-graph.json (nodes=components, edges=connects/supports/member-of) built as a VIEW of an existing takeoff (no re-reading DXF) → inherits evidence trail. Counts are query results, not typed numbers. Annotations are metadata, never evidence.
- **Phase 2** = extrude to glTF/USD tagged with graph node ids → WebGL viewer (the shippable win, no Unreal needed) → round-trip counts back through geometry and gate vs takeoff (parity thinking for geometry).
- **Phase 3** = export USD/Datasmith → materials/lighting from graph → 8K path-traced render; AI upscale allowed.

**The rule that cannot bend:** the render is PRESENTATION, never a source of truth. Geometry/counts flow one-way (drawing→graph→wireframe→render, never back); every renderable element keeps the id of the component it came from; **determinism ends at Phase 2 on purpose** so the heavy non-deterministic renderer changes no quantity. Extends the existing "viewer on top of a proven engine" principle [[sitemark-takeoff-engine]] from 2D marked PDF to 3D.

**Build-as-a-ledger (Daniel's addition):** mm-precise coordinates make each component a self-contained slice → build → verify vs graph node → checkpoint → stitch by shared absolute coordinates (no global fit-up); GPU holds one slice at a time; unchanged slices cache. **Uses the ledger LOGIC only — NOT autopro/work skills or any agent runner** (Daniel explicit). Ordinary deterministic build code.

Honest unknowns stated in the doc: photoreal needs materials/lighting/context beyond geometry; an "Unreal extension" is realistically a USD/Datasmith export PIPELINE, not an in-engine plugin. Attack order: Phase 1 (highest value/lowest risk) → Phase 2 → Phase 3 last, never render before Phase 2 proves it's the right building.
