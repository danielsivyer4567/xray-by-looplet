"""base.py — the source-adapter interface.

A **source adapter** is the engine's front door for one input format. It answers
one question — "given this file, what did we read off it?" — and returns pure
data. `engine.run()` then drives the same downstream pipeline (grammar -> scale
-> checks -> tables -> packs) regardless of where the words came from.

Adapters registered today:
    pdf   — pypdfium2 text layer (see sources/pdf.py)

Planned:
    dxf   — native CAD via ezdxf (NOT built; ezdxf is not yet a dependency)
    dwg   — convert to DXF first, then the DXF path
    ocr   — raster sheets

## The two reserved slots

`ReadResult` carries `symbols` and `geometry` alongside `pages`. Both are empty
for PDF and **nothing reads them yet**. They exist so that adding a CAD adapter
later is a new module plus a `register()` call, rather than a second re-cut of
this seam.

The split is the count-vs-measure axis, which the engine already makes: symbols
are counted (`ea`), geometry is measured (`lm`, `m2`, `m3`). It is not a
CAD-specific invention.

**The element types inside those lists are deliberately UNDEFINED.** Shaping
them requires a real native CAD file to shape them against — what an INSERT /
LINE / HATCH actually carries, which layer names appear, whether doors are
individual block references or one block with a count attribute. Designing that
from assumptions is how you end up reworking it when the first real file lands.
Define these when a native DXF is in hand, not before.
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
class ReadResult:
    """Everything one source file yielded. Pure data — no open file handles.

    Adapters fully drain and close their underlying document before returning,
    so nothing downstream ever holds a live handle.
    """
    pages: list[PageRead]
    producer: str = ""       # source identity; "" when the format has none

    # --- reserved; empty for the PDF adapter, unread by anything today ---
    symbols: list = field(default_factory=list)   # counted things (-> ea)
    geometry: list = field(default_factory=list)  # measured things (-> lm/m2/m3)


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
