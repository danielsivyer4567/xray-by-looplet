"""preflight.py — the engine's bad-input boundary.

Between a path and the parser sits one question: can this file be safely read?
A corrupt, encrypted, empty, oversized, or wrong-format input must produce a
CLEAR, typed error — never a raw parser traceback, and never a
silently-wrong-number. Every caller of `engine.run` gets this guard.

(The HTTP worker adds its own network-facing layer in `server/hardening.py` —
API keys, parse isolation, an idempotency cache. This module is the parse-safety
floor beneath all of that, so the CLI and any direct caller are protected too.)
"""
from __future__ import annotations

from pathlib import Path

# Generous: real plan sets run large (the warehouse fixture is 10 MB, a full
# supplier price PDF ~90 MB). This is a sanity ceiling against absurd or hostile
# inputs, not a working limit.
DEFAULT_MAX_BYTES = 300 * 1024 * 1024

# The bytes must look like the extension claims BEFORE any parser touches them —
# a renamed image with a .pdf name is caught here, cheaply.
_MAGIC = {
    ".pdf": lambda head: b"%PDF-" in head[:1024],
    ".dxf": lambda head: (b"SECTION" in head) or head.startswith(b"AutoCAD Binary DXF"),
    ".svg": lambda head: (b"<svg" in head) or (b"<?xml" in head[:64]),
}


class InputError(Exception):
    """A file we will not parse. `kind` is machine-readable, `detail` is fit to
    show a user. kind ∈ {not-found, empty, too-large, unsupported, malformed,
    encrypted, unreadable}."""

    def __init__(self, kind: str, detail: str):
        self.kind = kind
        self.detail = detail
        super().__init__(detail)


def check_input(path, max_bytes: int = DEFAULT_MAX_BYTES):
    """Raise InputError if `path` cannot be safely parsed; else return the source
    adapter that will read it. Cheap checks only — nothing parses the whole file."""
    p = Path(path)
    if not p.is_file():
        raise InputError("not-found", f"no such file: {p}")
    size = p.stat().st_size
    if size == 0:
        raise InputError("empty", f"{p.name} is empty (0 bytes)")
    if size > max_bytes:
        raise InputError(
            "too-large",
            f"{p.name} is {size / 1e6:.0f} MB, over the "
            f"{max_bytes / 1e6:.0f} MB limit")

    from xray.sources import find_adapter
    try:
        adapter = find_adapter(p)
    except ValueError as e:
        raise InputError("unsupported", str(e)) from e

    ext = p.suffix.lower()
    check = _MAGIC.get(ext)
    if check is not None:
        with open(p, "rb") as f:
            head = f.read(4096)
        if not check(head):
            raise InputError(
                "malformed",
                f"{p.name} does not look like a {ext[1:].upper()} inside — "
                "wrong format or a corrupt file")

    if ext == ".pdf":
        _check_pdf(p)
    return adapter


def _check_pdf(p: Path) -> None:
    """Distinguish an encrypted PDF (needs a password — a user action, not our
    job) from a structurally broken one, using pikepdf (already a dep). Both are
    turned into a clear InputError instead of a pdfium crash deep in the read."""
    try:
        import pikepdf
    except ImportError:  # pragma: no cover - pikepdf is a hard dep
        return
    try:
        with pikepdf.open(str(p)):
            pass
    except pikepdf.PasswordError as e:
        raise InputError(
            "encrypted",
            f"{p.name} is password-protected — supply an unlocked copy") from e
    except Exception as e:
        raise InputError(
            "malformed",
            f"{p.name} is not a readable PDF ({type(e).__name__})") from e
