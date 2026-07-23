"""solid.py — visualization Phase 3 on-ramp: node-tagged solid geometry (glTF).

Phase 2 (wireframe) draws each component as a line. A renderer needs *solids* it
can light, so this extrudes every placed component to a box prism at its measured
(x, y) and writes a standard **glTF 2.0** file — the neutral, engine-agnostic
format Unreal (via USD/Datasmith or direct glTF), Blender, Omniverse, and any
path-tracer import. Each mesh is a glTF node whose `name` is the graph node id
and whose `extras` carry the trade/type/height-basis, so the tag rides all the
way into the renderer and every pixel still traces back to the drawing.

The one rule holds (roadmap): the render is presentation, never truth. x, y are
measured; height is `given` or an ASSUMED viewing value flagged on every mesh —
determinism ends here, at the geometry, exactly as Phase 2 does. `roundtrip_check`
re-derives the component counts from the exported meshes and gates them against
the takeoff.

Pure stdlib (struct + base64): the glTF buffer is embedded as a data URI, so the
output is a single self-contained .gltf file. Deterministic — no timestamps, a
fixed vertex/index order — so the same takeoff yields byte-identical glTF.
"""
from __future__ import annotations

import base64
import json
import struct
from collections import Counter

SOLID_VERSION = "0.1"

# 8 corners of a box (x0,y0,z0)-(x1,y1,z1) and its 12-triangle index list.
# Winding is outward-consistent; materials can still be double-sided downstream.
_BOX_TRIS = [
    0, 2, 1, 0, 3, 2,      # z0 (bottom)
    4, 5, 6, 4, 6, 7,      # z1 (top)
    0, 1, 5, 0, 5, 4,      # y0
    1, 2, 6, 1, 6, 5,      # x1
    2, 3, 7, 2, 7, 6,      # y1
    3, 0, 4, 3, 4, 7,      # x0
]


def _corners(b):
    x0, y0, z0, x1, y1, z1 = b
    return [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]


def build_solids(takeoff, heights=None, default_height=None, post_size=None):
    """Extrude each placed component to a box prism. Pure; never mutates input.

    heights: {block_name: height} in drawing units — measured/engineered storey
    heights. Absent types get an ASSUMED height, flagged on every mesh.
    post_size: box footprint (drawing units). Default: 5% of the median height,
    so posts read as posts rather than needles.
    """
    symbols = takeoff.get("symbols", []) or []
    heights = heights or {}

    xs = [s["x"] for s in symbols if s.get("x") is not None]
    ys = [s["y"] for s in symbols if s.get("y") is not None]
    if default_height is None:
        span = max((max(xs) - min(xs)) if xs else 0.0,
                   (max(ys) - min(ys)) if ys else 0.0)
        default_height = span * 0.25 if span else 1.0

    # resolve each component's height first (footprint size depends on them)
    resolved = []
    assumed_any = False
    for s in symbols:
        name = s["blockName"]
        if name in heights:
            h, tier = float(heights[name]), "given"
        else:
            h, tier = float(default_height), "needs-human"
            assumed_any = True
        resolved.append((s, h, tier))

    if post_size is None:
        hs = sorted(h for _, h, _ in resolved) or [default_height]
        median = hs[len(hs) // 2]
        post_size = max(1.0, 0.05 * median)
    half = post_size / 2.0

    meshes = []
    for s, h, tier in resolved:
        x, y = float(s.get("x") or 0.0), float(s.get("y") or 0.0)
        meshes.append({
            "nodeId": s["id"], "type": s["blockName"],
            "trade": s.get("trade", ""), "heightTier": tier,
            "box": (x - half, y - half, 0.0, x + half, y + half, h),
        })

    corners = [c for m in meshes for c in _corners(m["box"])] or [(0.0, 0.0, 0.0)]
    bounds = {
        "min": [min(c[i] for c in corners) for i in range(3)],
        "max": [max(c[i] for c in corners) for i in range(3)],
    }
    return {
        "solidVersion": SOLID_VERSION,
        "engine": takeoff.get("engine"),
        "source": {"documentPath": takeoff.get("document", {}).get("path")},
        "meta": {
            "heightBasis": "given" if heights and not assumed_any else "assumed",
            "postSize": post_size,
            "note": ("x,y measured; height given or an assumed viewing value "
                     "flagged per mesh — never a quantity"),
        },
        "meshes": meshes,
        "bounds": bounds,
    }


def to_gltf(solids: dict) -> dict:
    """Assemble a valid, self-contained glTF 2.0 document (buffer embedded as a
    base64 data URI). One node per component, `name` = graph node id."""
    meshes = solids["meshes"]

    # positions section (all meshes, float32), then indices section (uint16).
    # 8 verts * 3 floats * 4 bytes = 96 B/mesh (4-aligned); 36 idx * 2 = 72 B/mesh.
    pos_blob = bytearray()
    idx_blob = bytearray()
    for m in meshes:
        for (vx, vy, vz) in _corners(m["box"]):
            pos_blob += struct.pack("<3f", vx, vy, vz)
        for i in _BOX_TRIS:
            idx_blob += struct.pack("<H", i)
    pos_len = len(pos_blob)
    buffer = bytes(pos_blob + idx_blob)

    accessors, buffer_views, gltf_meshes, nodes = [], [], [], []
    for k, m in enumerate(meshes):
        x0, y0, z0, x1, y1, z1 = m["box"]
        # POSITION bufferView + accessor
        buffer_views.append({"buffer": 0, "byteOffset": 96 * k,
                             "byteLength": 96, "target": 34962})
        accessors.append({
            "bufferView": len(buffer_views) - 1, "componentType": 5126,
            "count": 8, "type": "VEC3",
            "min": [x0, y0, z0], "max": [x1, y1, z1]})
        pos_acc = len(accessors) - 1
        # index bufferView + accessor
        buffer_views.append({"buffer": 0, "byteOffset": pos_len + 72 * k,
                             "byteLength": 72, "target": 34963})
        accessors.append({
            "bufferView": len(buffer_views) - 1, "componentType": 5123,
            "count": 36, "type": "SCALAR"})
        idx_acc = len(accessors) - 1

        gltf_meshes.append({"primitives": [{
            "attributes": {"POSITION": pos_acc}, "indices": idx_acc}]})
        nodes.append({
            "mesh": len(gltf_meshes) - 1, "name": m["nodeId"],
            "extras": {"xrayNodeId": m["nodeId"], "xrayType": m["type"],
                       "xrayTrade": m["trade"], "heightTier": m["heightTier"]}})

    return {
        "asset": {"version": "2.0", "generator": "xray-by-looplet/solid"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": gltf_meshes,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{
            "byteLength": len(buffer),
            "uri": "data:application/octet-stream;base64,"
                   + base64.b64encode(buffer).decode("ascii")}],
        "extras": {"heightBasis": solids["meta"]["heightBasis"],
                   "source": solids.get("source", {})},
    }


def roundtrip_check(solids: dict, takeoff: dict) -> dict:
    """Re-derive component counts FROM the exported meshes and gate them against
    the takeoff — the model must reproduce the drawing's counts exactly."""
    from_solid = Counter(m["type"] for m in solids.get("meshes", []))
    from_takeoff = Counter(s["blockName"] for s in takeoff.get("symbols", []) or [])
    mism = {t: {"solid": from_solid.get(t, 0), "takeoff": from_takeoff.get(t, 0)}
            for t in set(from_solid) | set(from_takeoff)
            if from_solid.get(t, 0) != from_takeoff.get(t, 0)}
    return {"ok": not mism, "byType": dict(from_solid), "mismatches": mism}


def main(argv=None) -> int:
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(
        prog="xray.solid",
        description="Export a takeoff as node-tagged solid geometry (glTF 2.0) "
                    "for Unreal / Blender / a path-tracer.")
    ap.add_argument("takeoff")
    ap.add_argument("--out")
    ap.add_argument("--height", type=float,
                    help="assumed viewing height for all types (drawing units)")
    a = ap.parse_args(argv)

    takeoff = json.loads(Path(a.takeoff).read_text(encoding="utf-8"))
    solids = build_solids(takeoff, default_height=a.height)
    check = roundtrip_check(solids, takeoff)
    gltf = to_gltf(solids)

    out_dir = Path(a.out) if a.out else Path(a.takeoff).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(a.takeoff).name.replace(".xray.json", "").replace(".json", "")
    gp = out_dir / f"{stem}.gltf"
    gp.write_text(json.dumps(gltf), encoding="utf-8")
    print(f"{stem}: {len(solids['meshes'])} solids, round-trip "
          f"{'OK' if check['ok'] else 'MISMATCH ' + str(check['mismatches'])} "
          f"-> {gp.name}")
    return 0 if check["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
