"""freeze.py — (re)freeze the oracle references the parity gate judges against.

This is the ONLY writer of parity/reference/*.json and parity/manifest.json, and
it is deliberately a separate, explicit, manually-run step. If freezing happened
automatically whenever output changed, the gate would rubber-stamp every
regression it was built to catch.

Run it only after you have confirmed the new numbers are CORRECT — either
because the engine legitimately improved, or because the native PDF stack moved
and you have decided to adopt the new build:

    python -m parity.freeze              # re-freeze every fixture
    python -m parity.freeze --check      # report drift, write nothing

The manifest records the environment each reference was frozen under, because
byte-identity is a property of (engine + fixture + native PDF stack) — see the
module docstring in parity.compare.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from parity.compare import (  # noqa: E402
    MANIFEST_PATH, REFERENCE_DIR, canonical, current_environment, digest,
    load_manifest,
)

# The fixtures the oracle is frozen over: a clean vector plan, a text-heavy
# schedule, and a big raster-mixed set. Between them they exercise the paths
# most sensitive to a PDFium change.
FIXTURES = ("shed-manners-aline", "electrical-schedule", "warehouse-design21")


def oracle(fixture: str) -> dict:
    from xray import engine  # imported here so --help works without deps
    return engine.run(str(REPO / "fixtures" / f"{fixture}.pdf"))


def freeze(check_only: bool = False) -> int:
    from xray import ENGINE_NAME  # noqa: F401  (identity sanity)

    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    previous = load_manifest() if MANIFEST_PATH.exists() else {"fixtures": {}}
    entries: dict[str, dict] = {}
    changed: list[str] = []

    for fixture in FIXTURES:
        result = oracle(fixture)
        sha = digest(result)
        was = previous.get("fixtures", {}).get(fixture, {}).get("sha256")
        if was and was != sha:
            changed.append(f"{fixture}: {was[:16]} -> {sha[:16]}")
        entries[fixture] = {
            "sha256": sha,
            "pages": len(result.get("document", {}).get("pages", [])),
            "quantities": len(result.get("quantities", [])),
        }
        if not check_only:
            # Written in canonical form so the file on disk IS the bytes hashed.
            (REFERENCE_DIR / f"{fixture}.json").write_text(
                canonical(result), encoding="utf-8")

    manifest = {
        "note": ("Frozen oracle output of the Python engine. Regenerate with "
                 "`python -m parity.freeze` — never edit by hand."),
        "canonical_form": ("document.path removed, then json.dumps(sort_keys="
                           "True, separators=(',',':'), ensure_ascii=False), "
                           "sha256 of the UTF-8 bytes"),
        "environment": current_environment(),
        "fixtures": entries,
    }

    if check_only:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        if changed:
            print("\nDRIFT vs the frozen manifest:")
            for c in changed:
                print(f"  {c}")
            return 1
        print("\nno drift — every fixture matches its frozen digest")
        return 0

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for fixture, entry in entries.items():
        print(f"froze {fixture:22s} {entry['sha256'][:16]}  "
              f"{entry['pages']} pages, {entry['quantities']} quantities")
    if changed:
        print("\nCHANGED vs the previous manifest:")
        for c in changed:
            print(f"  {c}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="parity.freeze", description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report drift and write nothing")
    args = ap.parse_args(argv)
    return freeze(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
