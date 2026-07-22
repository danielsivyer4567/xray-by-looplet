// app.js — renderer logic. Talks to the engine ONLY through window.XRayEngine
// (engine-client.js), so this identical file runs standalone (Electron),
// embedded in Looplet (Tauri), or in a browser — no host-specific code here.
const $ = (id) => document.getElementById(id);
const openBtn = $("open"), status = $("status"), tbl = $("tbl"), rows = $("rows"), foot = $("foot");

openBtn.addEventListener("click", async () => {
  try {
    const handle = await window.XRayEngine.pickPdf();   // path (desktop) or File (web)
    if (!handle) return;
    const label = typeof handle === "string" ? handle : handle.name;
    openBtn.disabled = true;
    status.textContent = "Running takeoff on " + label + " … (" + window.XRayEngine.host + ")";
    tbl.hidden = true; rows.innerHTML = "";
    const takeoff = await window.XRayEngine.runTakeoff(handle);
    render(takeoff);
  } catch (e) {
    status.textContent = "Engine error: " + (e && e.message ? e.message : e);
  } finally {
    openBtn.disabled = false;
  }
});

function render(t) {
  const qs = t.quantities || [];
  const doc = (t.document && t.document.path) || "";
  status.textContent = qs.length + " quantities" + (doc ? " from " + doc.split(/[\\/]/).pop() : "");
  for (const q of qs) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      '<td>' + esc(q.trade) + '</td>' +
      '<td>' + esc(q.item) + '</td>' +
      '<td class="qty">' + esc(q.qty) + '</td>' +
      '<td>' + esc(q.unit) + '</td>' +
      '<td><span class="tier ' + esc(q.tier) + '">' + esc(q.tier) + '</span></td>' +
      '<td class="formula">' + esc(q.formula || "") + '</td>';
    rows.appendChild(tr);
  }
  tbl.hidden = qs.length === 0;
  const eng = t.engine || {};
  foot.textContent = "engine: " + (eng.name || "?") + " " + (eng.version || "") +
    "  ·  sha256 " + ((t.document && t.document.sha256 || "").slice(0, 12));
}
function esc(s) { return String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
