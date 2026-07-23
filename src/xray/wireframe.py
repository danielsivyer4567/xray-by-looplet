"""wireframe.py — visualization roadmap, Phase 2: reconstruct 3D from the graph.

Extrude a takeoff's placed components into a spinnable wireframe — the WTC
"281 columns from the DXF, carried the full height" idea, generalised to any
drawing. Each symbol placement has a measured (x, y); it becomes a vertical
element at that position, tagged with the component's node id so the wireframe
and the graph are the same object seen two ways.

The one rule that cannot bend (roadmap): **the render is presentation, never a
source of truth.** So:

  * x, y come from the measured drawing — faithful.
  * z (height) is NOT in a 2D plan. A height is either supplied explicitly, or
    it is an ASSUMED viewing height, flagged `needs-human` on every element and
    in the scene meta. A guessed height never becomes a quantity — the engine's
    numbers are untouched; this module only draws.
  * The round-trip gate (`roundtrip_check`) re-derives component counts FROM the
    reconstructed scene and compares them to the takeoff. If the model disagrees
    with the drawing, the model is wrong — parity thinking applied to geometry.

Deterministic: elements are emitted in takeoff order, colours are assigned by
sorted type, and no clock or randomness is used — same takeoff, same scene bytes.
"""
from __future__ import annotations

import json
from collections import Counter

SCENE_VERSION = "0.1"

# a small, fixed palette cycled by sorted type index — deterministic colour.
_PALETTE = ["#7fdbff", "#2d9cdb", "#e8f4fb", "#5b7f9c", "#8fb3cc",
            "#1c6ea4", "#b3e08f", "#d99cdb"]


def build_scene(takeoff: dict, heights: dict | None = None,
                default_height: float | None = None) -> dict:
    """Build a wireframe scene from a takeoff. Pure; never mutates input.

    heights: optional {block_name: height} in drawing units — a measured or
    engineered storey height. Any type absent from it is drawn at an *assumed*
    height and every such element is flagged.
    default_height: the assumed viewing height for un-supplied types. When None,
    a proportion of the plan's horizontal extent is used so the model reads
    sensibly — still flagged, never a quantity.
    """
    symbols = takeoff.get("symbols", []) or []
    heights = heights or {}

    xs = [s["x"] for s in symbols if s.get("x") is not None]
    ys = [s["y"] for s in symbols if s.get("y") is not None]
    if default_height is None:
        span = max((max(xs) - min(xs)) if xs else 0.0,
                   (max(ys) - min(ys)) if ys else 0.0)
        default_height = span * 0.6 if span else 1.0

    types = sorted({s["blockName"] for s in symbols})
    colour = {name: _PALETTE[i % len(_PALETTE)] for i, name in enumerate(types)}

    elements = []
    assumed_any = False
    for s in symbols:
        name = s["blockName"]
        if name in heights:
            h, tier = float(heights[name]), "given"
        else:
            h, tier = float(default_height), "needs-human"
            assumed_any = True
        x, y = float(s.get("x") or 0.0), float(s.get("y") or 0.0)
        elements.append({
            "nodeId": s["id"], "type": name, "kind": "column",
            "colour": colour[name], "heightTier": tier,
            "a": [x, y, 0.0], "b": [x, y, h],
        })

    pts = [(e["a"], e["b"]) for e in elements]
    flat = [p for ab in pts for p in ab] or [[0.0, 0.0, 0.0]]
    bounds = {
        "min": [min(p[i] for p in flat) for i in range(3)],
        "max": [max(p[i] for p in flat) for i in range(3)],
    }

    scene = {
        "sceneVersion": SCENE_VERSION,
        "engine": takeoff.get("engine"),
        "source": {
            "documentPath": takeoff.get("document", {}).get("path"),
            "units": (takeoff.get("document", {}).get("units") or {}).get("resolved", ""),
        },
        "meta": {
            "heightBasis": "given" if heights and not assumed_any else "assumed",
            "assumedHeight": default_height,
            "note": ("x,y are measured; height is an assumed viewing value and is "
                     "flagged on every un-supplied element — never a quantity"),
        },
        "types": [{"name": n, "colour": colour[n],
                   "count": sum(1 for s in symbols if s["blockName"] == n)}
                  for n in types],
        "elements": elements,
        "bounds": bounds,
    }
    return json.loads(json.dumps(scene, default=str))


def roundtrip_check(scene: dict, takeoff: dict) -> dict:
    """Re-derive component counts FROM the scene and gate them against the
    takeoff's symbols. The model must reproduce the drawing's counts exactly."""
    from_scene = Counter(e["type"] for e in scene.get("elements", []))
    from_takeoff = Counter(s["blockName"] for s in takeoff.get("symbols", []) or [])
    mismatches = {
        t: {"scene": from_scene.get(t, 0), "takeoff": from_takeoff.get(t, 0)}
        for t in set(from_scene) | set(from_takeoff)
        if from_scene.get(t, 0) != from_takeoff.get(t, 0)
    }
    return {"ok": not mismatches, "byType": dict(from_scene),
            "mismatches": mismatches}


def render_html(scene: dict, title: str = "Structural wireframe") -> str:
    """A self-contained, dependency-free WebGL viewer (same lineage as the WTC
    reference): orbit / pan / zoom, Iso / Elevation / Plan presets, isolate by
    type. The scene is embedded inline — offline, no external requests."""
    payload = json.dumps({
        "elements": scene["elements"], "types": scene["types"],
        "bounds": scene["bounds"], "meta": scene.get("meta", {}),
    }, separators=(",", ":"))
    total = len(scene["elements"])
    assumed = scene.get("meta", {}).get("heightBasis") == "assumed"
    type_rows = "".join(
        f'<button class="ty on" data-type="{_esc(t["name"])}" '
        f'style="--c:{t["colour"]}" type="button">{_esc(t["name"])} '
        f'<b>{t["count"]}</b></button>' for t in scene["types"])

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title><style>
 :root{{--bg:#050b14;--rule:#17324d;--foam:#e8f4fb;--mist:#8fb3cc;--dim:#5b7f9c;
  --mono:ui-monospace,Consolas,monospace;color-scheme:dark}}
 *{{box-sizing:border-box}} html,body{{height:100%;margin:0}}
 body{{background:var(--bg);color:var(--foam);font-family:system-ui,sans-serif;overflow:hidden}}
 canvas{{display:block;width:100%;height:100%;cursor:grab;touch-action:none}}
 canvas.drag{{cursor:grabbing}}
 .hud{{position:fixed;pointer-events:none}}
 .tl{{top:22px;left:24px}} .eyebrow{{font-family:var(--mono);font-size:10px;
  letter-spacing:.22em;text-transform:uppercase;color:#2d9cdb;margin:0 0 8px}}
 h1{{font-weight:200;font-size:30px;margin:0}}
 .sub{{font-family:var(--mono);font-size:11px;color:var(--mist);margin:9px 0 0}}
 .warn{{color:#e8b339}}
 .bl{{left:24px;bottom:22px;display:flex;flex-direction:column;gap:9px;pointer-events:auto}}
 .row{{display:flex;gap:7px;flex-wrap:wrap;max-width:60vw}}
 button{{font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;
  background:rgba(10,22,38,.82);color:var(--mist);border:1px solid var(--rule);
  padding:7px 10px;border-radius:2px;cursor:pointer}}
 button:hover{{border-color:#2d9cdb;color:var(--foam)}}
 button.on{{border-color:var(--c,#7fdbff);color:var(--foam)}}
 button.ty b{{color:var(--c);margin-left:4px}}
 .help{{font-family:var(--mono);font-size:10px;color:var(--dim)}}
</style></head><body>
<canvas id="gl"></canvas>
<div class="hud tl"><p class="eyebrow">Structural wireframe · extruded from plan</p>
 <h1>{_esc(title)}</h1>
 <p class="sub">{total} components from the drawing{'' if not assumed else
   ' · <span class="warn">height assumed for view — not measured</span>'}</p></div>
<div class="hud bl">
 <div class="row">{type_rows}</div>
 <div class="row"><button id="vElev" type="button">Elevation</button>
  <button id="vIso" class="on" type="button">Iso</button>
  <button id="vTop" type="button">Plan</button></div>
 <span class="help">drag orbit · right-drag/shift pan · scroll zoom</span></div>
<script>
const S={payload};
const cv=document.getElementById('gl');
const gl=cv.getContext('webgl',{{antialias:true,alpha:false}});
if(!gl){{document.body.innerHTML='<p style="padding:40px;font-family:monospace;color:#8fb3cc">WebGL unavailable.</p>';}}
else{{
const off=S.bounds, mn=off.min, mx=off.max;
const ctr=[(mn[0]+mx[0])/2,(mn[1]+mx[1])/2,(mn[2]+mx[2])/2];
const diag=Math.hypot(mx[0]-mn[0],mx[1]-mn[1],mx[2]-mn[2])||1;
const on={{}}; S.types.forEach(t=>on[t.name]=true);
function hex(h){{return [parseInt(h.slice(1,3),16)/255,parseInt(h.slice(3,5),16)/255,parseInt(h.slice(5,7),16)/255];}}
function build(){{const V=[],C=[];S.elements.forEach(e=>{{if(!on[e.type])return;
  const c=hex(e.colour);V.push(e.a[0],e.a[1],e.a[2],e.b[0],e.b[1],e.b[2]);
  C.push(c[0],c[1],c[2],c[0],c[1],c[2]);}});
  return {{V:new Float32Array(V),C:new Float32Array(C),n:V.length/3}};}}
let mesh=build();
const VS='attribute vec3 aP;attribute vec3 aC;uniform mat4 uMVP;varying vec3 vC;void main(){{gl_Position=uMVP*vec4(aP,1.0);vC=aC;}}';
const FS='precision mediump float;varying vec3 vC;void main(){{gl_FragColor=vec4(vC,0.9);}}';
function sh(t,s){{const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);return o;}}
const pr=gl.createProgram();gl.attachShader(pr,sh(gl.VERTEX_SHADER,VS));
gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,FS));gl.linkProgram(pr);gl.useProgram(pr);
const aP=gl.getAttribLocation(pr,'aP'),aC=gl.getAttribLocation(pr,'aC'),uMVP=gl.getUniformLocation(pr,'uMVP');
const bP=gl.createBuffer(),bC=gl.createBuffer();
function up(){{gl.bindBuffer(gl.ARRAY_BUFFER,bP);gl.bufferData(gl.ARRAY_BUFFER,mesh.V,gl.STATIC_DRAW);
 gl.bindBuffer(gl.ARRAY_BUFFER,bC);gl.bufferData(gl.ARRAY_BUFFER,mesh.C,gl.STATIC_DRAW);}}
up();
function mul(a,b){{const o=new Float32Array(16);for(let i=0;i<4;i++)for(let j=0;j<4;j++){{let s=0;for(let k=0;k<4;k++)s+=a[k*4+j]*b[i*4+k];o[i*4+j]=s;}}return o;}}
function persp(f,ar,n,fa){{const t=1/Math.tan(f/2);return new Float32Array([t/ar,0,0,0,0,t,0,0,0,0,(fa+n)/(n-fa),-1,0,0,2*fa*n/(n-fa),0]);}}
function look(e,c,u){{let z=[e[0]-c[0],e[1]-c[1],e[2]-c[2]];let l=Math.hypot(z[0],z[1],z[2])||1;z=z.map(v=>v/l);
 let x=[u[1]*z[2]-u[2]*z[1],u[2]*z[0]-u[0]*z[2],u[0]*z[1]-u[1]*z[0]];l=Math.hypot(x[0],x[1],x[2])||1;x=x.map(v=>v/l);
 const y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]];
 return new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,
 -(x[0]*e[0]+x[1]*e[1]+x[2]*e[2]),-(y[0]*e[0]+y[1]*e[1]+y[2]*e[2]),-(z[0]*e[0]+z[1]*e[1]+z[2]*e[2]),1]);}}
const cam={{az:-0.7,el:0.35,dist:diag*1.6}},tgt=Object.assign({{}},cam);
function frame(){{
 KEYS.forEach(k=>cam[k]+=(tgt[k]-cam[k])*0.15);
 const dpr=Math.min(devicePixelRatio||1,2),w=cv.clientWidth,h=cv.clientHeight;
 if(cv.width!==Math.round(w*dpr)){{cv.width=Math.round(w*dpr);cv.height=Math.round(h*dpr);}}
 gl.viewport(0,0,cv.width,cv.height);gl.clearColor(0.02,0.043,0.078,1);
 gl.clear(gl.COLOR_BUFFER_BIT);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
 const ce=Math.cos(cam.el),se=Math.sin(cam.el);
 const eye=[ctr[0]+cam.dist*ce*Math.cos(cam.az),ctr[1]+cam.dist*ce*Math.sin(cam.az),ctr[2]+cam.dist*se];
 const mvp=mul(persp(0.7,w/h,diag*0.02,diag*12),look(eye,ctr,[0,0,1]));
 gl.uniformMatrix4fv(uMVP,false,mvp);
 gl.bindBuffer(gl.ARRAY_BUFFER,bP);gl.enableVertexAttribArray(aP);gl.vertexAttribPointer(aP,3,gl.FLOAT,false,0,0);
 gl.bindBuffer(gl.ARRAY_BUFFER,bC);gl.enableVertexAttribArray(aC);gl.vertexAttribPointer(aC,3,gl.FLOAT,false,0,0);
 gl.drawArrays(gl.LINES,0,mesh.n);requestAnimationFrame(frame);}}
const KEYS=['az','el','dist'];
let drag=null;
cv.addEventListener('pointerdown',e=>{{drag={{x:e.clientX,y:e.clientY,pan:(e.button===2||e.shiftKey)}};cv.setPointerCapture(e.pointerId);cv.classList.add('drag');}});
cv.addEventListener('pointermove',e=>{{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
 if(drag.pan){{ctr[0]-=Math.cos(cam.az+Math.PI/2)*dx*diag*0.0016;ctr[1]-=Math.sin(cam.az+Math.PI/2)*dx*diag*0.0016;ctr[2]+=dy*diag*0.0016;}}
 else{{tgt.az+=dx*0.006;tgt.el=Math.max(-0.7,Math.min(1.4,tgt.el-dy*0.005));}}drag.x=e.clientX;drag.y=e.clientY;}});
['pointerup','pointercancel'].forEach(ev=>cv.addEventListener(ev,()=>{{drag=null;cv.classList.remove('drag');}}));
cv.addEventListener('contextmenu',e=>e.preventDefault());
cv.addEventListener('wheel',e=>{{e.preventDefault();tgt.dist=Math.max(diag*0.1,Math.min(diag*8,tgt.dist*(1+Math.sign(e.deltaY)*0.1)));}},{{passive:false}});
const V={{elev:{{az:-Math.PI/2,el:0.02}},iso:{{az:-0.7,el:0.35}},top:{{az:-Math.PI/2,el:1.38}}}};
document.getElementById('vElev').onclick=()=>Object.assign(tgt,V.elev);
document.getElementById('vIso').onclick=()=>Object.assign(tgt,V.iso);
document.getElementById('vTop').onclick=()=>Object.assign(tgt,V.top);
document.querySelectorAll('.ty').forEach(b=>b.onclick=()=>{{const t=b.dataset.type;on[t]=!on[t];
 b.classList.toggle('on',on[t]);mesh=build();up();}});
frame();
}}
</script></body></html>"""


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def main(argv=None) -> int:
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(
        prog="xray.wireframe",
        description="Extrude a takeoff into a 3D wireframe viewer (Phase 2).")
    ap.add_argument("takeoff")
    ap.add_argument("--out")
    ap.add_argument("--height", type=float,
                    help="assumed viewing height for all types (drawing units)")
    a = ap.parse_args(argv)

    tk = json.loads(Path(a.takeoff).read_text(encoding="utf-8"))
    scene = build_scene(tk, default_height=a.height)
    check = roundtrip_check(scene, tk)
    out_dir = Path(a.out) if a.out else Path(a.takeoff).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(a.takeoff).name.replace(".xray.json", "").replace(".json", "")
    (out_dir / f"{stem}.scene.json").write_text(
        json.dumps(scene, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / f"{stem}.wireframe.html").write_text(
        render_html(scene, title=f"{stem} — wireframe"), encoding="utf-8")
    print(f"{stem}: {len(scene['elements'])} elements, round-trip "
          f"{'OK' if check['ok'] else 'MISMATCH ' + str(check['mismatches'])} "
          f"-> {stem}.scene.json / .wireframe.html")
    return 0 if check["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
