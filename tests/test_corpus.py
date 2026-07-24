"""The corpus harness — one parametrized test per real-file case.

Runs every case in fixtures/corpus/manifest.json through engine.run and asserts
its hand-checked invariants. This is the anti-flake net: a file shape that once
misbehaved gets a case here and can never regress. Adding coverage is a JSON edit,
not new test code. See fixtures/corpus/README.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray.engine import run   # noqa: E402

MANIFEST = REPO / "fixtures" / "corpus" / "manifest.json"
CASES = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[Path(c["file"]).name for c in CASES])
def test_corpus_case(case):
    path = REPO / case["file"]
    if path.suffix.lower() == ".dxf":
        pytest.importorskip("ezdxf", reason="CAD deps not installed")
    assert path.exists(), f"corpus file missing: {case['file']}"

    result = run(str(path))
    exp = case["expect"]
    where = case["file"]

    has_prov = bool([c for c in result["checks"] if c["kind"] == "provenance"])
    if "provenance" in exp:
        assert has_prov == exp["provenance"], (
            f"{where}: provenance flag = {has_prov}, expected {exp['provenance']}")

    if "minQuantities" in exp:
        assert len(result["quantities"]) >= exp["minQuantities"], (
            f"{where}: {len(result['quantities'])} quantities < "
            f"expected >= {exp['minQuantities']}")

    for item, qty in exp.get("quantities", {}).items():
        q = next((q for q in result["quantities"] if q["item"] == item), None)
        assert q is not None, f"{where}: missing expected quantity {item!r}"
        assert q["qty"] == qty, f"{where}: {item} = {q['qty']}, expected {qty}"
