"""The derived-output contracts. Like takeoff.json, the building graph, the
wireframe scene, and the costed quote each have a schema — and the code that
emits them must conform. These tests are the enforcement.
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

jsonschema = pytest.importorskip("jsonschema")
pytest.importorskip("ezdxf", reason="CAD deps not installed")

from xray.engine import run                              # noqa: E402
from xray.graph import build_graph                       # noqa: E402
from xray.wireframe import build_scene                   # noqa: E402
from pricing.costing import cost_takeoff, load_price_list  # noqa: E402

FENCE = REPO / "fixtures" / "cad" / "fencing-boundary.dxf"
PRICES = REPO / "fixtures" / "pricing" / "sample-fence-prices.csv"
SCHEMA = REPO / "schema"


def _schema(name):
    return json.loads((SCHEMA / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def takeoff():
    return run(str(FENCE))


def test_building_graph_conforms(takeoff):
    jsonschema.validate(build_graph(takeoff), _schema("building-graph.schema.json"))


def test_scene_conforms(takeoff):
    jsonschema.validate(build_scene(takeoff), _schema("scene.schema.json"))
    jsonschema.validate(build_scene(takeoff, heights={"POST": 1800.0, "GATE": 1800.0}),
                        _schema("scene.schema.json"))


def test_quote_conforms(takeoff):
    result = cost_takeoff(takeoff.get("quantities", []), load_price_list(PRICES),
                          as_of="2026-07-23", freshness_days=90)
    jsonschema.validate(result, _schema("quote.schema.json"))
