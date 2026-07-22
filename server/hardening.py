"""hardening.py — the public-facing safety layer for the takeoff worker.

Parsing strangers' files is the attack surface. This module holds every
guardrail between an untrusted upload and engine.run():

  - size caps       (XRAY_MAX_UPLOAD_MB, default 50)
  - magic-byte checks (a .pdf must look like a PDF before we parse it)
  - API keys        (XRAY_API_KEYS, comma-separated; unset = open local mode)
  - parse isolation (XRAY_ISOLATE_PARSE=1 -> engine runs in a child process
                     with a hard timeout, XRAY_PARSE_TIMEOUT_S, default 60;
                     a hostile file can hang/kill the child, never the server)
  - idempotency     (sha256 + engine version -> LRU-cached result; identical
                     input returns the identical output, instantly — which is
                     also a live demonstration of determinism)

Defaults preserve today's local-dev behaviour exactly: no keys required,
in-process parse, generous limits. The public deployment flips env vars.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path


# ---- config (env, read at import; tests monkeypatch the module values) ----
MAX_UPLOAD_BYTES = int(float(os.environ.get("XRAY_MAX_UPLOAD_MB", "50")) * 1024 * 1024)
PARSE_TIMEOUT_S = float(os.environ.get("XRAY_PARSE_TIMEOUT_S", "60"))
ISOLATE_PARSE = os.environ.get("XRAY_ISOLATE_PARSE", "0") == "1"
API_KEYS = frozenset(k.strip() for k in os.environ.get("XRAY_API_KEYS", "").split(",") if k.strip())
CACHE_SIZE = int(os.environ.get("XRAY_CACHE_SIZE", "64"))

ALLOWED_EXTENSIONS = (".pdf", ".dxf")


def check_api_key(authorization: str | None) -> bool:
    """True if the request may proceed. Open mode when no keys configured."""
    if not API_KEYS:
        return True
    if not authorization or not authorization.lower().startswith("bearer "):
        return False
    presented = authorization[7:].strip()
    # constant-time compare against each configured key
    return any(secrets.compare_digest(presented, k) for k in API_KEYS)


def magic_ok(name: str, data: bytes) -> bool:
    """Cheap pre-parse sanity: the bytes must look like the claimed format.
    A PDF carries %PDF- in its first 1024 bytes (spec allows a preamble);
    an ASCII DXF opens with a group-code/SECTION structure near the top."""
    low = name.lower()
    head = data[:1024]
    if low.endswith(".pdf"):
        return b"%PDF-" in head
    if low.endswith(".dxf"):
        return (b"SECTION" in data[:4096]) or head.startswith(b"AutoCAD Binary DXF")
    return False


# ---- idempotency cache: (sha256, engine version) -> result ----------------
_CACHE: "OrderedDict[tuple[str, str], dict]" = OrderedDict()


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cache_get(sha: str, version: str) -> dict | None:
    key = (sha, version)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None


def cache_put(sha: str, version: str, result: dict) -> None:
    _CACHE[(sha, version)] = result
    while len(_CACHE) > CACHE_SIZE:
        _CACHE.popitem(last=False)


def cache_clear() -> None:
    _CACHE.clear()


# ---- parse isolation: run a callable in a child process with a deadline ----

class ParseTimeout(Exception):
    pass


def run_with_timeout(target, arg, timeout: float | None = None):
    """Run `target(arg)` in a fresh child process; raise ParseTimeout on
    deadline. `target` must be a module-level (picklable) callable.

    One executor per call — no shared pool state, so a wedged child is
    terminated and discarded without ever touching another request. Spawn
    overhead is acceptable here because the idempotency cache absorbs
    repeats, and correctness beats microseconds at a security boundary.
    """
    t = PARSE_TIMEOUT_S if timeout is None else timeout
    ex = ProcessPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(target, arg)
        try:
            return fut.result(timeout=t)
        except FutureTimeout:
            # capture the child handles BEFORE shutdown clears them
            procs = list(getattr(ex, "_processes", {}).values() or [])
            for p in procs:
                try:
                    p.terminate()
                except Exception:
                    pass
            raise ParseTimeout(f"parse exceeded {t:g}s")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def engine_run_child(pdf_path: str) -> dict:
    """Module-level engine entry so it pickles across the process boundary."""
    import sys as _sys
    src = str(Path(__file__).resolve().parents[1] / "src")
    if src not in _sys.path:
        _sys.path.insert(0, src)
    from xray import engine as _engine
    return _engine.run(pdf_path)
