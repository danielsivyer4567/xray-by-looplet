"""compare.py — the reliability gate for every NON-oracle runtime.

WHY this exists
---------------
The engine's promise is that the same file in produces the same JSON out, and
that this is provable rather than asserted. The Python engine is the ORACLE: it
defines what the right answer is. Every other runtime we ship — the frozen
PyInstaller sidecar on the desktop, the Pyodide/WASM engine in the browser, a
container fallback — is only allowed to ship if it reproduces the oracle's
output byte-for-byte on the frozen fixtures. Anything less and a builder gets a
different quantity depending on which runtime happened to answer, which would
quietly destroy the one guarantee the product is sold on.

This module is deliberately PURE STDLIB and does NOT import xray. A candidate
runtime is judged only by the JSON it produced, so this gate can run anywhere —
in CI, against a WASM build's output, on a machine with no engine installed.
Freezing new references is the opposite job and lives in `parity.freeze`, which
does import the oracle.

WHAT "identical" means
----------------------
Canonical form: `document.path` is removed (it records where the input happened
to sit on disk, which is not a property of the drawing), then the object is
serialised with sorted keys, no whitespace, and no ASCII escaping. That exact
form is what the pinned digests in manifest.json are taken over.

WHY the environment is recorded
-------------------------------
Byte-identity is in principle a property of (engine + fixture + NATIVE PDF
STACK), not of the engine alone: PDFium's text extraction and raster/vector
classification can change between Chromium builds. So the manifest records the
build each reference was frozen under, and a mismatch on a moved stack is
reported as ENVIRONMENT DRIFT rather than a bare "hash differs", keeping two
very different causes apart:

    engine logic changed   -> a real regression, fix the code
    PDFium build changed   -> possible expected drift, investigate first

This is PRECAUTIONARY. It was tested directly and PDFium did NOT matter here:
all three fixtures produced byte-identical output under 149.0.7802.0 and
152.0.7947.0. Three fixtures across two builds is not proof of general
invariance, so `requirements.txt` should still pin pypdfium2 exactly rather than
`>=4` — as hygiene, not as a fix for a known break. See parity/README.md, which
also records a set of legacy reference digests that do not reproduce here and
are not explained by PDFium, by engine history, or by the fixtures.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

PARITY_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = PARITY_DIR / "manifest.json"
REFERENCE_DIR = PARITY_DIR / "reference"

# Fields that describe where the input sat, not what the drawing says. Stripped
# before hashing so the same PDF hashes the same from any directory.
VOLATILE_PATHS: tuple[tuple[str, str], ...] = (("document", "path"),)


# --- canonical form -----------------------------------------------------------

def strip_volatile(obj: dict) -> dict:
    """Return a copy with location-dependent fields removed. Never mutates the
    caller's object — a gate that edits its input is a gate you cannot trust."""
    out = json.loads(json.dumps(obj))  # cheap deep copy, JSON-safe by definition
    for parent, key in VOLATILE_PATHS:
        node = out.get(parent)
        if isinstance(node, dict):
            node.pop(key, None)
    return out


def canonical(obj: dict) -> str:
    """The exact serialisation the pinned digests are taken over."""
    return json.dumps(
        strip_volatile(obj), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False)


def digest(obj: dict) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


# --- divergence reporting -----------------------------------------------------

def first_divergence(expected, actual, path: str = "") -> str | None:
    """Walk both structures and name the FIRST place they differ.

    A bare "sha256 differs" tells you that you have a problem but not where, and
    a takeoff is a big document. This returns something like
    `quantities[3].order_qty: 14 != 15` so the failure is actionable.
    """
    if type(expected) is not type(actual):
        return (f"{path or '<root>'}: type {type(expected).__name__} != "
                f"{type(actual).__name__}")
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            sub = f"{path}.{key}" if path else key
            if key not in expected:
                return f"{sub}: missing in expected, present in actual"
            if key not in actual:
                return f"{sub}: present in expected, missing in actual"
            found = first_divergence(expected[key], actual[key], sub)
            if found:
                return found
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path or '<root>'}: length {len(expected)} != {len(actual)}"
        for i, (e, a) in enumerate(zip(expected, actual)):
            found = first_divergence(e, a, f"{path}[{i}]")
            if found:
                return found
        return None
    if expected != actual:
        return f"{path or '<root>'}: {expected!r} != {actual!r}"
    return None


# --- the gate -----------------------------------------------------------------

@dataclass
class ParityResult:
    fixture: str
    ok: bool
    expected_sha256: str
    actual_sha256: str
    divergence: str | None = None
    environment_drift: list[str] = field(default_factory=list)

    def report(self) -> str:
        head = f"{'PASS' if self.ok else 'FAIL'}  {self.fixture}"
        if self.ok:
            return f"{head}  {self.actual_sha256[:16]}"
        lines = [head,
                 f"      expected {self.expected_sha256}",
                 f"      actual   {self.actual_sha256}"]
        if self.divergence:
            lines.append(f"      first divergence: {self.divergence}")
        if self.environment_drift:
            # ASCII only: this is printed to Windows consoles (cp1252), where a
            # stray em dash comes out as a replacement character.
            lines.append("      ENVIRONMENT DRIFT - the native PDF stack moved, "
                         "so this may be expected drift rather than a code "
                         "regression:")
            lines += [f"        {d}" for d in self.environment_drift]
            lines.append("      Re-freeze deliberately (python -m parity.freeze) "
                         "only after confirming the new numbers are correct.")
        return "\n".join(lines)


def load_manifest(path: Path | None = None) -> dict:
    return json.loads((path or MANIFEST_PATH).read_text("utf-8"))


def current_environment() -> dict:
    """Best-effort description of the native PDF stack in THIS process.

    Imported lazily and defensively: the gate must still run on a machine that
    has no engine dependencies installed (e.g. judging a WASM build's output in
    a bare CI job), where the honest answer is simply "unknown".
    """
    env: dict[str, str] = {}
    try:
        import pypdfium2
        env["pdfium"] = str(getattr(pypdfium2, "PDFIUM_INFO", "unknown"))
    except Exception:
        env["pdfium"] = "unavailable"
    try:
        from importlib.metadata import version
        env["pypdfium2"] = version("pypdfium2")
    except Exception:
        env["pypdfium2"] = "unavailable"
    return env


def _drift(frozen_env: dict, live_env: dict) -> list[str]:
    out = []
    for key, frozen in sorted(frozen_env.items()):
        live = live_env.get(key, "unavailable")
        if live in ("unavailable", "unknown"):
            continue  # cannot compare; silence beats a false accusation
        if str(live) != str(frozen):
            out.append(f"{key}: frozen under {frozen}, running {live}")
    return out


def compare(candidate: dict, fixture: str, manifest: dict | None = None
            ) -> ParityResult:
    """Gate ONE candidate takeoff against the frozen oracle for `fixture`."""
    man = manifest or load_manifest()
    entry = man["fixtures"].get(fixture)
    if entry is None:
        raise KeyError(
            f"no frozen reference for {fixture!r}; known: "
            f"{sorted(man['fixtures'])}")

    actual = digest(candidate)
    expected = entry["sha256"]
    if actual == expected:
        return ParityResult(fixture, True, expected, actual)

    ref_file = REFERENCE_DIR / f"{fixture}.json"
    divergence = None
    if ref_file.exists():
        reference = json.loads(ref_file.read_text("utf-8"))
        divergence = first_divergence(
            strip_volatile(reference), strip_volatile(candidate))
    return ParityResult(
        fixture, False, expected, actual, divergence,
        _drift(man.get("environment", {}), current_environment()))


def compare_file(candidate_path: str | Path, fixture: str | None = None,
                 manifest: dict | None = None) -> ParityResult:
    """Gate a candidate takeoff.json ON DISK — the WASM/sidecar entry point."""
    p = Path(candidate_path)
    if fixture is None:
        # "shed-manners-aline.xray.json" -> "shed-manners-aline"
        fixture = p.name.split(".")[0]
    return compare(json.loads(p.read_text("utf-8")), fixture, manifest)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="parity.compare",
        description="Gate a runtime's takeoff.json against the frozen oracle.")
    ap.add_argument("candidate", nargs="+",
                    help="takeoff JSON file(s) produced by the runtime under test")
    ap.add_argument("--fixture", default=None,
                    help="fixture name (default: inferred from the filename)")
    args = ap.parse_args(argv)

    failures = 0
    for c in args.candidate:
        result = compare_file(c, args.fixture)
        print(result.report())
        failures += 0 if result.ok else 1
    print(f"\n{len(args.candidate) - failures}/{len(args.candidate)} fixtures "
          f"byte-identical to the oracle")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
