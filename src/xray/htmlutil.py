"""htmlutil.py — one HTML-escape helper for the presentation views.

The building-graph, wireframe, and costing views all emit self-contained HTML
from untrusted-ish strings (block names, item descriptions). Escaping lived in
three copies, one of them missing quote-escaping; this is the single source.
Escapes the five characters that matter in both text and attribute contexts.
"""
from __future__ import annotations


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))
