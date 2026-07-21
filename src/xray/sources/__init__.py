"""sources — pluggable input adapters (one per file format).

Importing this package registers every built-in adapter. Adding a format is a
new module plus a `register()` call; `engine.run()` needs no change.
"""
from xray.sources.base import (  # noqa: F401
    PageRead, ReadResult, SourceAdapter, adapters, find_adapter, register,
)
import xray.sources.pdf  # noqa: F401  (registers PdfAdapter)
