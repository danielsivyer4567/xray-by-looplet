"""advisor.py — the input-quality advisor.

At the door, tell the user whether their file is a good takeoff source and, if
not, what to export instead. It reads only signals the engine already computes —
page kinds (vector / raster / sparse), coverage, the provenance and
unit-unverified flags, and whether real CAD geometry was found — so it invents
nothing and never changes the takeoff.

The ladder it encodes (best first):
  native CAD (DXF / SVG groups / vector PDF)  ->  exact, ideal
  vector PDF                                  ->  lossless, ideal
  raster / scanned sheet                      ->  OCR needed (PNG, not JPEG);
                                                  re-export as DXF/vector-PDF for exact counts
  traced / vectorised scan (flattened)        ->  flagged, not a trustworthy source
  sparse / photo-like                         ->  export the vector file
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def assess_input(takeoff: dict) -> dict:
    doc = takeoff.get("document", {}) or {}
    pages = doc.get("pages", []) or []
    kinds = Counter(p.get("kind") for p in pages)
    vec, ras, spa = kinds.get("vector", 0), kinds.get("raster", 0), kinds.get("sparse", 0)
    checks = takeoff.get("checks", []) or []
    has_prov = any(c.get("kind") == "provenance" for c in checks)
    unit_unverified = any(c.get("kind") == "unit-unverified" for c in checks)
    has_cad = bool(takeoff.get("symbols") or takeoff.get("geometry"))
    cov = (doc.get("coverage") or {}).get("overallRatio")

    if has_prov:
        grade, verdict = "poor", "Traced / flattened drawing — not native CAD."
        guidance = ("Counts and lengths here are unverified (no blocks, no measured "
                    "dimensions). Get the native DXF or a CAD-plotted vector PDF for a "
                    "reliable takeoff — a vectorised scan is a picture, not CAD.")
    elif has_cad:
        grade, verdict = "excellent", "Native CAD geometry — the ideal takeoff source."
        guidance = "Components counted exactly from the drawing."
        if unit_unverified:
            guidance += (" Confirm the drawing unit — it rests only on the file header, "
                         "so areas are flagged for review.")
    elif vec and vec >= (ras + spa):
        grade, verdict = "excellent", "Vector PDF — a lossless takeoff source."
        guidance = "Text and geometry read directly; nothing was rasterised."
        if ras:
            guidance += f" ({ras} scanned page(s) still need OCR.)"
    elif ras:
        grade, verdict = "good", "Raster / scanned sheet — no text layer."
        guidance = ("X-Ray must OCR this: run with --ocr and an engine installed, and "
                    "use PNG (not JPEG — its compression smears thin lines and text). "
                    "For exact counts, re-export from the CAD program as DXF or "
                    "plot-to-PDF instead.")
    else:
        grade, verdict = "poor", "Sparse / photo-like input — little readable structure."
        guidance = ("Looks like a photo or a near-empty sheet. Export the vector file "
                    "(DXF / vector-PDF / SVG) from the CAD program for an accurate takeoff.")

    return {
        "grade": grade, "verdict": verdict, "guidance": guidance,
        "signals": {
            "pageKinds": dict(kinds), "coverage": cov, "nativeCAD": has_cad,
            "provenanceFlag": has_prov, "unitUnverified": unit_unverified,
            "producer": doc.get("producer", ""),
        },
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="xray.advisor",
        description="Assess a takeoff's input quality and advise on the best export.")
    ap.add_argument("takeoff")
    a = ap.parse_args(argv)
    r = assess_input(json.loads(Path(a.takeoff).read_text(encoding="utf-8")))
    print(f"[{r['grade'].upper()}] {r['verdict']}")
    print(f"  {r['guidance']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
