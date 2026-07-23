"""base.py — the source-adapter interface.

A **source adapter** is the engine's front door for one input format. It answers
one question — "given this file, what did we read off it?" — and returns pure
data. `engine.run()` then drives the same downstream pipeline (grammar -> scale
-> checks -> tables -> packs) regardless of where the words came from.

Adapters registered today:
    pdf   — pypdfium2 text layer (see sources/pdf.py)
    dxf   — native CAD via ezdxf (see sources/dxf.py; optional dep)

Planned:
    dwg   — convert to DXF first, then the DXF path
    ocr   — raster sheets

## The two reserved slots

`ReadResult` carries `symbols` and `geometry` alongside `pages`. Both are empty
for PDF. CAD fills them:

  symbols  — list[Symbol]  (INSERT placements → counted ea)
  geometry — list[Measure] (DIMENSION / LINE / LWPOLYLINE → measured)

The split is the count-vs-measure axis the engine already makes. Shapes are
defined in this module (`Symbol`, `Measure`), driven by
fixtures/cad/architectural_test_fixtures.dxf.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# A page with fewer readable words than this is "sparse" — too little text to
# judge. Format-agnostic (it counts words, not PDF objects), so it lives here:
# adapters use it to classify pages, and the engine uses it to decide which
# pages are text-heavy enough for the low-coverage diagnostic.
SPARSE_WORD_COUNT = 15


@dataclass
class PageRead:
    """One page as read from the source, before any interpretation.

    `words` are already reassembled (glyph-split runs merged) — the contract the
    rest of the pipeline expects. `raw_word_count` is the pre-reassembly count,
    kept because coverage is measured against raw readable text.
    """
    words: list              # list[reassemble.Word], reassembled
    raw_word_count: int      # count BEFORE reassembly (coverage denominator)
    width_pt: float
    height_pt: float
    kind: str                # vector | raster | sparse


@dataclass
class Symbol:
    """A placed block reference — a thing that is COUNTED (-> ea).

    Shaped against a real native DXF (fixtures/cad/architectural_test_fixtures.dxf),
    not from assumptions. `block_name` is the identity that makes counting exact:
    grouping placements by name yields a true count with no recognition step, which
    is the thing a PDF text layer fundamentally cannot provide.

    `rotation` is degrees CCW; scales are per-axis (a mirrored placement arrives as
    a negative scale, so counting must not assume 1.0).
    """
    block_name: str
    layer: str
    x: float
    y: float
    rotation: float = 0.0
    xscale: float = 1.0
    yscale: float = 1.0
    trade: str = ""          # layer -> trade tag, "" when unmapped

    # Nesting. A block may contain INSERTs of other blocks, so a component's real
    # count is only visible after recursing the block DAG and applying the
    # cumulative transform. `depth` 0 is a modelspace placement; `path` names the
    # containing assemblies, which is what makes a nested count auditable.
    depth: int = 0
    path: tuple = ()         # e.g. ("ASSEMBLY_GIRDER_JOINT", "STRUCTURAL_BRACKET")

    # Instance attributes (ATTRIB) merged over the block's ATTDEF defaults. An
    # instance override is the drawing's statement about THIS placement (a higher
    # bolt grade, say) and must win over the block default.
    attribs: dict = field(default_factory=dict)
    overridden: tuple = ()   # tags whose instance value differs from the default

    # Per-placement identity. `id` is the chain of INSERT entity handles from
    # the modelspace root placement down to this one. A definition INSERT has
    # ONE handle but many placements — only the full chain is unique per
    # placement. Handles are fixed in the file, so ids are deterministic across
    # runs and stable under entity reordering (unlike ordinals). `parent_id` is
    # the chain minus its last hop; None for a modelspace placement.
    id: str = ""
    parent_id: str | None = None

    @property
    def anonymous(self) -> bool:
        """`*U1`-style names are generated per file, so they are countable here
        but NEVER stable identity across files."""
        return self.block_name.startswith("*")


@dataclass
class Measure:
    """A MEASURED span or run (-> lm/m2/m3).

    `kind` is "dimension" for an associative DIMENSION entity — whose value comes
    from `get_measurement()`, i.e. the geometry it measures, never the display
    text — or "line"/"polyline" for drawn geometry whose length we compute.

    A dimension is the high-value case: it is the drawing's own statement of a
    distance, so it can RECONCILE against measured geometry. That cross-check is
    what lets a CAD source reach the `reconciled` tier where a PDF usually cannot.
    """
    kind: str                # dimension | line | polyline
    value: float             # measurement in drawing units
    layer: str
    unit: str = ""           # resolved unit, "" when unresolved
    text: str = ""           # raw dim text; "<>" means derived, never typed
    trade: str = ""
    # Stable per-run identity so a quantity built from this run can cite it as
    # evidence (the entity handle from the source file; deterministic per file).
    # "" for adapters that cannot supply one.
    id: str = ""

    # An override dimension states a number the geometry does not support. BOTH
    # are kept: `value` is what the drawing measures, `text_value` is what it
    # claims. When they disagree the quantity is `needs-human` — silently
    # trusting either one is how a wrong number reaches a quote.
    text_value: float | None = None
    conflict: bool = False


@dataclass
class ReadResult:
    """Everything one source file yielded. Pure data — no open file handles.

    Adapters fully drain and close their underlying document before returning,
    so nothing downstream ever holds a live handle.
    """
    pages: list[PageRead]
    producer: str = ""       # source identity; "" when the format has none

    # Non-text content. Empty for PDF (a text layer has neither), populated by
    # CAD adapters. Split on the count-vs-measure axis the engine already makes.
    symbols: list = field(default_factory=list)   # list[Symbol]  -> ea
    geometry: list = field(default_factory=list)  # list[Measure] -> lm/m2/m3

    # Unit provenance. A CAD header can declare a unit that the geometry
    # contradicts, so the resolved unit and the evidence for it travel together
    # and any conflict is surfaced, never silently propagated.
    units: dict = field(default_factory=dict)     # {declared, resolved, basis, mismatch}

    # File provenance. A valid-but-fake file (e.g. a PDF plot flattened into a
    # DXF container) parses cleanly yet has no real CAD semantics; the adapter
    # sets {suspect: bool, reasons: [...]} so the engine can flag it rather than
    # emit confident nonsense. Empty for adapters that don't assess it.
    provenance: dict = field(default_factory=dict)


class SourceAdapter:
    """One input format. Stateless; `read` must not leak an open document."""

    name = "base"

    def can_read(self, path: str | Path) -> bool:
        """Cheap check — extension and/or magic bytes. No full parse."""
        raise NotImplementedError

    def read(self, path: str | Path) -> ReadResult:
        """Fully read `path` and return pure data, closing any handle first."""
        raise NotImplementedError


_ADAPTERS: list[SourceAdapter] = []


def register(adapter: SourceAdapter) -> None:
    _ADAPTERS.append(adapter)


def adapters() -> list[SourceAdapter]:
    return list(_ADAPTERS)


def find_adapter(path: str | Path) -> SourceAdapter:
    """First registered adapter that claims `path`.

    Raises ValueError naming the registered formats, so an unsupported file
    fails with a useful message instead of a parser stack trace.
    """
    for a in _ADAPTERS:
        if a.can_read(path):
            return a
    known = ", ".join(a.name for a in _ADAPTERS) or "(none registered)"
    raise ValueError(
        f"no source adapter can read {Path(path).name!r}; registered: {known}")
