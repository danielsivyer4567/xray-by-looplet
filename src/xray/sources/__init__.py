"""sources — pluggable input adapters (one per file format).

Importing this package registers every built-in adapter. Adding a format is a
new module plus a `register()` call; `engine.run()` needs no change.
"""
from xray.sources.base import (  # noqa: F401
    Measure, PageRead, ReadResult, SourceAdapter, Symbol,
    adapters, find_adapter, register,
)
import xray.sources.pdf  # noqa: F401  (registers PdfAdapter)

# DXF needs ezdxf; if it isn't installed the PDF path must still work, so the
# adapter simply goes unregistered rather than breaking the import.
try:
    import xray.sources.dxf  # noqa: F401  (registers DxfAdapter)
except ImportError:  # pragma: no cover - exercised only without the CAD extra
    pass
