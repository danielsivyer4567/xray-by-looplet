"""graph.py — the building graph (visualization roadmap, Phase 1).

Turns a finished takeoff into a queryable graph WITHOUT re-reading the drawing:
the graph is a *view* of `takeoff.json`, so it inherits the evidence trail for
free. Nothing here measures anything — every count is a query over nodes whose
ids trace back to symbol placements the engine already proved.

Determinism holds by construction: nodes and edges are emitted in a fixed order
(types sorted, then placements in takeoff order, then geometry by index, then
quantities in order), so the same takeoff yields byte-identical graph JSON. It
never mutates the takeoff, and human annotations are kept in a separate field so
a tag can never overwrite a measured number.

Node kinds
    type       — one per block name; the "god node" a placement is an instance
                 of. Its count is len(placements) — "236 columns" as a query.
    component  — one per symbol placement (the leaf that carries evidence).
    measure    — one per geometry run/dimension.
    quantity   — one per emitted quantity, edged to the evidence it was built on.

Edge relations
    instance-of   component -> its type node
    member-of     nested placement -> its parent placement (the assembly DAG)
    evidenced-by  quantity -> each evidence node it cites
"""
from __future__ import annotations

import json
from collections import defaultdict

GRAPH_VERSION = "0.1"


def build_graph(takeoff: dict, annotations: dict | None = None) -> dict:
    """Build `building-graph.json` from a takeoff dict. Pure; never mutates input.

    `annotations` is an optional {node_id: {...}} of human tags. They ride along
    on a node's `annotation` field and are NEVER treated as evidence — metadata,
    not measurement (roadmap Phase 1 rule).
    """
    symbols = takeoff.get("symbols", []) or []
    geometry = takeoff.get("geometry", []) or []
    quantities = takeoff.get("quantities", []) or []
    annotations = annotations or {}

    nodes: list[dict] = []
    edges: list[dict] = []
    ids: set[str] = set()

    def add(nid: str, **kw) -> None:
        node = {"id": nid, **kw}
        if nid in annotations:
            # metadata only — quarantined from every measured field
            node["annotation"] = annotations[nid]
        nodes.append(node)
        ids.add(nid)

    # ---- type / god nodes: one per block name, count = placements -----------
    by_name: dict[str, list] = defaultdict(list)
    for s in symbols:
        by_name[s["blockName"]].append(s)
    for name in sorted(by_name):
        placements = by_name[name]
        add(f"type:{name}", type="type", kind=name, label=name,
            count=len(placements), evidence=[s["id"] for s in placements])

    # ---- component nodes: one per placement (leaf evidence) -----------------
    for s in symbols:
        nid = s["id"]
        add(nid, type="component", kind=s["blockName"], label=s["blockName"],
            count=1, depth=s.get("depth", 0), path=list(s.get("path", []) or []),
            trade=s.get("trade", ""), x=s.get("x"), y=s.get("y"),
            attribs=dict(s.get("attribs", {}) or {}), evidence=[s["id"]])
        parent = s.get("parentId")
        if parent:
            edges.append({"from": nid, "to": parent, "rel": "member-of"})
        edges.append({"from": nid, "to": f"type:{s['blockName']}",
                      "rel": "instance-of"})

    # ---- measure nodes: geometry has no engine id, so index deterministically
    for i, g in enumerate(geometry):
        add(f"geo-{i}", type="measure", kind=g.get("kind", ""),
            label=f"{g.get('kind', '')} {g.get('value')}", value=g.get("value"),
            unit=g.get("unit", ""), layer=g.get("layer", ""),
            trade=g.get("trade", ""), evidence=[])

    # ---- quantity nodes: the bill, edged back to its evidence ---------------
    for q in quantities:
        nid = f"qty:{q['id']}"
        add(nid, type="quantity", kind=q.get("trade", ""), label=q.get("item", ""),
            qty=q.get("qty"), unit=q.get("unit", ""), tier=q.get("tier", ""),
            evidence=list(q.get("evidence", []) or []))
        for ev in q.get("evidence", []) or []:
            if ev in ids:
                edges.append({"from": nid, "to": ev, "rel": "evidenced-by"})

    # ---- communities: one per component type; assemblies fold in via path ---
    communities = []
    for name in sorted(by_name):
        members = [f"type:{name}"] + [s["id"] for s in by_name[name]]
        communities.append({
            "id": f"c:{name}", "label": name, "size": len(by_name[name]),
            "nodeIds": members,
            # a type is a "god node" when it collects many placements — the
            # hub the graphify view draws large. Threshold is the mean count,
            # so it is relative to this drawing, not an absolute guess.
            "god": False,
        })
    if communities:
        mean = sum(c["size"] for c in communities) / len(communities)
        for c in communities:
            c["god"] = c["size"] >= mean and c["size"] > 1

    rollup = {
        "totalComponents": sum(len(v) for v in by_name.values()),
        "byType": {n: len(by_name[n]) for n in sorted(by_name)},
        "measures": len(geometry),
        "quantities": len(quantities),
        "nodes": len(nodes),
        "edges": len(edges),
    }

    graph = {
        "graphVersion": GRAPH_VERSION,
        "engine": takeoff.get("engine"),
        "source": {
            "documentPath": takeoff.get("document", {}).get("path"),
            "documentSha256": takeoff.get("document", {}).get("sha256"),
        },
        "rollup": rollup,
        "communities": communities,
        "nodes": nodes,
        "edges": edges,
    }
    # normalise exotic scalars to plain json types, same as the engine does
    return json.loads(json.dumps(graph, default=str))


# --------------------------------------------------------------------- queries

def count_by_type(graph: dict) -> dict:
    """{block_name: count} — the canonical 'how many of each' query."""
    return dict(graph["rollup"]["byType"])


def nodes_of_type(graph: dict, kind: str) -> list[dict]:
    """Every component placement of one block name."""
    return [n for n in graph["nodes"]
            if n.get("type") == "component" and n.get("kind") == kind]


def neighbours(graph: dict, node_id: str) -> list[tuple[str, str]]:
    """(relation, other_id) for every edge touching node_id, either direction."""
    out = []
    for e in graph["edges"]:
        if e["from"] == node_id:
            out.append((e["rel"], e["to"]))
        elif e["to"] == node_id:
            out.append((e["rel"] + "-of", e["from"]))
    return out


def bill_of_materials(graph: dict) -> list[dict]:
    """A BOM rollup: counted component types plus the emitted quantities, each
    with its evidence count so the number always traces back."""
    bom = []
    for name, count in count_by_type(graph).items():
        bom.append({"item": name, "qty": count, "unit": "ea",
                    "source": "component-count", "tier": "reconciled"})
    for n in graph["nodes"]:
        if n.get("type") == "quantity":
            bom.append({"item": n["label"], "qty": n.get("qty"),
                        "unit": n.get("unit", ""), "source": "quantity",
                        "tier": n.get("tier", "")})
    return bom


# ------------------------------------------------------------------- html view

_TIER_COLOUR = {"reconciled": "#1a7f37", "single-source": "#9a6700",
                "needs-human": "#cf222e"}


def render_html(graph: dict, title: str = "Building graph") -> str:
    """A self-contained, dependency-free HTML view: summary, a clustered SVG of
    the component types (god nodes drawn large), and a BOM table with tier
    badges. Layout is a deterministic grid — same graph in, same HTML out."""
    comms = graph.get("communities", [])
    rollup = graph.get("rollup", {})
    src = graph.get("source", {})

    # deterministic grid placement, biggest communities first then by name
    ordered = sorted(comms, key=lambda c: (-c["size"], c["label"]))
    cols = max(1, min(6, len(ordered)))
    cell_w, cell_h, pad = 190, 150, 24
    rows = (len(ordered) + cols - 1) // cols or 1
    svg_w = cols * cell_w + pad * 2
    svg_h = rows * cell_h + pad * 2
    max_size = max((c["size"] for c in ordered), default=1)

    circles = []
    for i, c in enumerate(ordered):
        cx = pad + (i % cols) * cell_w + cell_w / 2
        cy = pad + (i // cols) * cell_h + cell_h / 2
        r = 18 + 34 * (c["size"] / max_size) ** 0.5
        fill = "#0969da" if c.get("god") else "#8c959f"
        circles.append(
            f'<g><circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="{fill}" '
            f'fill-opacity="0.85"/>'
            f'<text x="{cx:.0f}" y="{cy:.0f}" text-anchor="middle" dy="0.35em" '
            f'fill="#fff" font-weight="700" font-size="15">{c["size"]}</text>'
            f'<text x="{cx:.0f}" y="{cy + r + 16:.0f}" text-anchor="middle" '
            f'fill="#57606a" font-size="12">{_esc(c["label"])}</text></g>')

    bom_rows = []
    for row in bill_of_materials(graph):
        tier = row.get("tier", "")
        badge = (f'<span style="background:{_TIER_COLOUR.get(tier, "#57606a")};'
                 f'color:#fff;border-radius:10px;padding:1px 8px;font-size:11px">'
                 f'{_esc(tier)}</span>' if tier else "")
        qty = row.get("qty")
        qty = "" if qty is None else (f"{qty:g}" if isinstance(qty, (int, float)) else _esc(str(qty)))
        bom_rows.append(
            f'<tr><td>{_esc(str(row["item"]))}</td><td style="text-align:right">'
            f'{qty}</td><td>{_esc(row.get("unit", ""))}</td>'
            f'<td>{_esc(row.get("source", ""))}</td><td>{badge}</td></tr>')

    doc_path = _esc(str(src.get("documentPath") or "—"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#1f2328;
       margin:0;padding:24px;background:#fff}}
  h1{{font-size:20px;margin:0 0 2px}} .sub{{color:#57606a;margin:0 0 20px}}
  .stats{{display:flex;gap:24px;flex-wrap:wrap;margin:0 0 20px}}
  .stat b{{font-size:22px;display:block}} .stat span{{color:#57606a;font-size:12px}}
  .card{{border:1px solid #d0d7de;border-radius:10px;padding:16px;margin:0 0 20px;
        overflow-x:auto}}
  svg{{max-width:100%;height:auto}}
  table{{border-collapse:collapse;width:100%;font-size:13px}}
  th,td{{border-bottom:1px solid #eaeef2;padding:6px 10px;text-align:left}}
  th{{color:#57606a;font-weight:600}}
  @media(prefers-color-scheme:dark){{
    body{{background:#0d1117;color:#e6edf3}} .card{{border-color:#30363d}}
    th,td{{border-color:#21262d}} .sub,.stat span,th{{color:#8b949e}}}}
</style></head><body>
<h1>{_esc(title)}</h1>
<p class="sub">{_esc(str(graph.get("engine", {}).get("name", "")))} · view of {doc_path}</p>
<div class="stats">
  <div class="stat"><b>{rollup.get("totalComponents", 0)}</b><span>components</span></div>
  <div class="stat"><b>{len(count_by_type(graph))}</b><span>types</span></div>
  <div class="stat"><b>{rollup.get("measures", 0)}</b><span>measures</span></div>
  <div class="stat"><b>{rollup.get("quantities", 0)}</b><span>quantities</span></div>
  <div class="stat"><b>{rollup.get("nodes", 0)}</b><span>nodes</span></div>
  <div class="stat"><b>{rollup.get("edges", 0)}</b><span>edges</span></div>
</div>
<div class="card"><svg viewBox="0 0 {svg_w} {svg_h}" width="{svg_w}" height="{svg_h}"
  xmlns="http://www.w3.org/2000/svg" role="img"
  aria-label="component types, god nodes drawn larger">
  {''.join(circles) or '<text x="20" y="30" fill="#57606a">no components</text>'}
</svg></div>
<div class="card"><table>
  <thead><tr><th>item</th><th style="text-align:right">qty</th><th>unit</th>
  <th>source</th><th>tier</th></tr></thead>
  <tbody>{''.join(bom_rows) or '<tr><td colspan="5">empty</td></tr>'}</tbody>
</table></div>
</body></html>"""


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ------------------------------------------------------------------------ cli

def main(argv=None) -> int:
    import argparse
    import hashlib
    from pathlib import Path

    ap = argparse.ArgumentParser(
        prog="xray.graph",
        description="Build a building graph from a takeoff.json (a view, no "
                    "re-reading the drawing).")
    ap.add_argument("takeoff", help="path to a *.xray.json takeoff")
    ap.add_argument("--out", help="output dir (default: next to the takeoff)")
    ap.add_argument("--annotations", help="optional {node_id: {...}} json of tags")
    args = ap.parse_args(argv)

    tk_path = Path(args.takeoff)
    if not tk_path.exists():
        print(f"no such takeoff: {tk_path}")
        return 1
    takeoff = json.loads(tk_path.read_text(encoding="utf-8"))
    annotations = None
    if args.annotations:
        annotations = json.loads(Path(args.annotations).read_text(encoding="utf-8"))

    graph = build_graph(takeoff, annotations)
    out_dir = Path(args.out) if args.out else tk_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = tk_path.name.replace(".xray.json", "").replace(".json", "")
    gj = out_dir / f"{stem}.graph.json"
    gh = out_dir / f"{stem}.graph.html"
    gj.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    gh.write_text(render_html(graph, title=f"{stem} — building graph"),
                  encoding="utf-8")
    digest = hashlib.sha256(
        json.dumps(graph, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    print(f"wrote {gj.name} + {gh.name}  ({graph['rollup']['nodes']} nodes, "
          f"{graph['rollup']['edges']} edges, digest {digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
