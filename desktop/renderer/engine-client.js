// engine-client.js — host-agnostic bridge to the X-Ray takeoff engine.
//
// The SAME CAD Studio UI runs in three hosts; this file hides the difference so
// the UI never hard-codes where it lives:
//   1. Electron (standalone SKU) -> window.xray preload IPC -> spawns the sidecar
//   2. Looplet (Tauri extension) -> invoke("xray_run_takeoff") -> Rust spawns the
//      SAME frozen sidecar binary (see "Embedding in Looplet" in README.md)
//   3. Browser / embedded web    -> HTTP POST to the FastAPI engine
// Detection is at runtime. pickPdf() returns a path string on desktop or a File
// on web; runTakeoff() accepts whichever the host produced.
(function () {
  const hasElectron = typeof window !== "undefined" && window.xray && window.xray.runTakeoff;
  const hasTauri = typeof window !== "undefined" && window.__TAURI__;
  const API_BASE = ((typeof window !== "undefined" && window.XRAY_API_BASE) ||
                    "http://127.0.0.1:8000").replace(/\/$/, "");

  async function pickPdfElectron() { return window.xray.pickPdf(); }
  async function runTakeoffElectron(pdfPath) { return window.xray.runTakeoff(pdfPath); }

  async function pickPdfTauri() {
    const picked = await window.__TAURI__.dialog.open({
      multiple: false, filters: [{ name: "Plan PDFs", extensions: ["pdf"] }] });
    return picked || null;
  }
  async function runTakeoffTauri(pdfPath) {
    return window.__TAURI__.core.invoke("xray_run_takeoff", { pdfPath });
  }

  function pickPdfWeb() {
    return new Promise((resolve) => {
      const input = document.createElement("input");
      input.type = "file"; input.accept = "application/pdf";
      input.onchange = () => resolve(input.files && input.files[0] ? input.files[0] : null);
      input.click();
    });
  }
  async function runTakeoffWeb(file) {
    const form = new FormData();
    form.append("file", file, (file && file.name) || "plan.pdf");
    const res = await fetch(API_BASE + "/v1/takeoff/raw", { method: "POST", body: form });
    if (!res.ok) throw new Error("engine API " + res.status + ": " + (await res.text()));
    return res.json();
  }

  const host = hasElectron ? "electron" : hasTauri ? "tauri" : "web";
  window.XRayEngine = {
    host,
    pickPdf: host === "electron" ? pickPdfElectron : host === "tauri" ? pickPdfTauri : pickPdfWeb,
    runTakeoff: host === "electron" ? runTakeoffElectron : host === "tauri" ? runTakeoffTauri : runTakeoffWeb,
  };
})();
