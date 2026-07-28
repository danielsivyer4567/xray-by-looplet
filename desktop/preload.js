// preload.js — the ONLY bridge between the (sandboxed) web UI and Node.
// contextIsolation is on and nodeIntegration is off, so the renderer can touch
// nothing except this narrow, explicit surface. Same discipline as the engine:
// a small, auditable contract instead of broad ambient power.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("xray", {
  // Open a native file picker, return the chosen PDF path (or null if cancelled).
  pickPdf: () => ipcRenderer.invoke("pick-pdf"),
  // Run a deterministic takeoff on a plan PDF via the frozen engine sidecar.
  // Resolves to the parsed takeoff.json; rejects with the engine's stderr.
  runTakeoff: (pdfPath) => ipcRenderer.invoke("run-takeoff", pdfPath),
});
