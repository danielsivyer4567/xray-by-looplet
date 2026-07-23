"""Building graph (visualization roadmap, Phase 1).

The graph is a *view* of a takeoff, so its truths are the takeoff's truths seen a
second way: the nested-bolt DAG becomes member-of edges, the exact block counts
become type-node counts and query results, and the whole thing is deterministic
and non-destructive. Proven against the same CAD fixtures the adapter uses, so
the ground truths are already hand-verified upstream.
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

pytest.importorskip("ezdxf", reason="CAD deps not installed")

from xray.engine import run                                    # noqa: E402
from xray.graph import (                                       # noqa: E402
    build_graph, count_by_type, nodes_of_type, neighbours,
    bill_of_materials, render_html,
)

CAD2 = REPO / "fixtures" / "cad" / "architectural_test_fixtures_v2.dxf"
FENCE = REPO / "fixtures" / "cad" / "fencing-boundary.dxf"


@pytest.fixture(scope="module")
def takeoff():
    return run(str(CAD2))


@pytest.fixture(scope="module")
def graph(takeoff):
    return build_graph(takeoff)


def _node(graph, nid):
    return next((n for n in graph["nodes"] if n["id"] == nid), None)


# ------------------------------------------------------------- counts as queries

def test_type_counts_match_the_takeoff(graph):
    """The headline: counts are query results over placement nodes, not typed."""
    assert count_by_type(graph) == {
        "ASSEMBLY_GIRDER_JOINT": 3,
        "STRUCTURAL_BRACKET": 6,
        "BOLT_M16": 25,
        "*U1": 3,
    }


def test_god_node_carries_the_full_count(graph):
    god = _node(graph, "type:BOLT_M16")
    assert god["type"] == "type" and god["count"] == 25
    assert len(god["evidence"]) == 25          # every placement id rides along
    assert len(nodes_of_type(graph, "BOLT_M16")) == 25


# --------------------------------------------------------------- the assembly DAG

def test_nested_bolt_has_member_of_edge_to_its_bracket(graph):
    """A depth-2 bolt must edge up to a real bracket placement node — the DAG the
    adapter recovered, re-expressed as graph edges."""
    deep = [n for n in graph["nodes"]
            if n.get("kind") == "BOLT_M16" and n.get("depth") == 2]
    assert deep, "expected bolts two levels down"
    b = deep[0]
    rels = neighbours(graph, b["id"])
    parents = [other for rel, other in rels if rel == "member-of"]
    assert len(parents) == 1
    parent = _node(graph, parents[0])
    assert parent is not None and parent["kind"] == "STRUCTURAL_BRACKET"


def test_every_component_is_an_instance_of_its_type(graph):
    comps = [n for n in graph["nodes"] if n["type"] == "component"]
    for n in comps:
        rels = neighbours(graph, n["id"])
        assert (f"type:{n['kind']}") in [o for r, o in rels if r == "instance-of"]


# ---------------------------------------------------------- non-destructive tags

def test_annotation_is_metadata_never_evidence(takeoff):
    """Tagging a node must not touch a measured field, and the tag must not leak
    into evidence."""
    target = "type:BOLT_M16"
    g = build_graph(takeoff, annotations={target: {"note": "transfer bolts"}})
    n = _node(g, target)
    assert n["annotation"] == {"note": "transfer bolts"}
    assert n["count"] == 25                      # measured field untouched
    assert "transfer bolts" not in json.dumps(n["evidence"])


def test_unannotated_build_has_no_annotation_field(graph):
    assert all("annotation" not in n for n in graph["nodes"])


# --------------------------------------------------------------- determinism

def test_graph_is_byte_deterministic(takeoff):
    a = json.dumps(build_graph(takeoff), sort_keys=True)
    b = json.dumps(build_graph(takeoff), sort_keys=True)
    assert a == b


def test_build_graph_does_not_mutate_the_takeoff(takeoff):
    before = json.dumps(takeoff, sort_keys=True)
    build_graph(takeoff)
    assert json.dumps(takeoff, sort_keys=True) == before


# ----------------------------------------------------------- quantities in graph

def test_quantity_nodes_edge_to_their_evidence(graph):
    """A quantity node must connect to evidence nodes that actually exist, so the
    bill traces back into the component graph."""
    qnodes = [n for n in graph["nodes"] if n["type"] == "quantity"]
    assert qnodes
    q = next(n for n in qnodes if n["id"] == "qty:q-sym-bolt-m16")
    ev_edges = [o for r, o in neighbours(graph, q["id"]) if r == "evidenced-by"]
    assert len(ev_edges) == 25
    assert all(_node(graph, e) is not None for e in ev_edges)


def test_bom_rollup_lists_types_and_quantities(graph):
    bom = bill_of_materials(graph)
    items = {r["item"] for r in bom}
    assert "BOLT_M16" in items                   # component-count line
    assert any(r["source"] == "quantity" for r in bom)


# ------------------------------------------------------------------ fence view

def test_fence_takeoff_graph_has_measure_and_quantity_nodes():
    g = build_graph(run(str(FENCE)))
    kinds = {n["type"] for n in g["nodes"]}
    assert "measure" in kinds                    # the fence-line polyline
    assert any(n["id"] == "qty:q-fence-length" for n in g["nodes"])
    # the drawn run is one polyline measure node
    measures = [n for n in g["nodes"] if n["type"] == "measure"]
    assert len(measures) == 1 and measures[0]["kind"] == "polyline"


# --------------------------------------------------------------------- html

def test_html_is_self_contained_and_shows_counts(graph):
    html = render_html(graph)
    assert html.startswith("<!doctype html>")
    assert "http://www.w3.org/2000/svg" in html
    assert "BOLT_M16" in html
    # no external references — a strict-CSP / offline view
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "src=" not in html and "<script" not in html
