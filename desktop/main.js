// main.js — Electron main process for the X-Ray construction app.
//
// The whole app is offline. The deterministic takeoff engine stays PYTHON,
// frozen by PyInstaller into a single self-contained binary (proven: it runs a
// full takeoff with no Python and no network). Electron just renders the CAD
// Studio UI and spawns that binary as a child process — one JSON in, one
// takeoff.json out. No network egress, no LLM in the request path.
const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("path");

// The spawn logic lives in ../host, owned by the engine repo, so this app and
// any embedding host (e.g. the Looplet CRM) run the engine the SAME way. When
// that logic was copied per-host the copies drifted, and the busier host quietly
// became the real implementation.
// Declared as a file: dependency (see package.json) rather than required by
// relative path, so npm places it in node_modules and electron-builder packages
// it — a "../host" require would resolve in dev and vanish from the installer.
const xrayHost = require("@looplet/xray-host");

// Where this app might find the binary. The host kit does the resolving; only
// the candidate list is app-specific.
function engineCandidates() {
  return [
    path.join(process.resourcesPath || "", "engine", xrayHost.EXE), // packaged
    path.join(__dirname, "engine", "bin", xrayHost.EXE),            // dev build
  ];
}

function runTakeoff(pdfPath) {
  return xrayHost.runTakeoff(pdfPath, { candidates: engineCandidates() });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    backgroundColor: "#1e1e1e",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(() => {
  ipcMain.handle("pick-pdf", async () => {
    const r = await dialog.showOpenDialog({
      properties: ["openFile"],
      filters: [{ name: "Plan PDFs", extensions: ["pdf"] }],
    });
    return r.canceled ? null : r.filePaths[0];
  });
  ipcMain.handle("run-takeoff", (_e, pdfPath) => runTakeoff(pdfPath));

  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
