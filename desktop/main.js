// main.js — Electron main process for the X-Ray construction app.
//
// The whole app is offline. The deterministic takeoff engine stays PYTHON,
// frozen by PyInstaller into a single self-contained binary (proven: it runs a
// full takeoff with no Python and no network). Electron just renders the CAD
// Studio UI and spawns that binary as a child process — one JSON in, one
// takeoff.json out. No network egress, no LLM in the request path.
const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("path");
const os = require("os");
const fs = require("fs");
const { execFile } = require("child_process");

// Resolve the frozen engine: packaged -> resources/engine/<exe>; dev -> engine/bin/<exe>.
function enginePath() {
  const exe = process.platform === "win32" ? "xray-engine.exe" : "xray-engine";
  const packaged = path.join(process.resourcesPath || "", "engine", exe);
  if (fs.existsSync(packaged)) return packaged;
  return path.join(__dirname, "engine", "bin", exe);
}

// Run one takeoff. The engine writes <name>.xray.json into a scratch dir we own
// and wipe; we never leave client files on shared storage (public-API rule,
// applied to the desktop too).
function runTakeoff(pdfPath) {
  return new Promise((resolve, reject) => {
    const bin = enginePath();
    if (!fs.existsSync(bin)) {
      return reject(new Error(
        "engine binary not found — run scripts/build-engine first (" + bin + ")"));
    }
    const outDir = fs.mkdtempSync(path.join(os.tmpdir(), "xray-"));
    execFile(bin, ["run", pdfPath, "--out", outDir], { timeout: 120000 },
      (err, _stdout, stderr) => {
        try {
          if (err) return reject(new Error(stderr || err.message));
          const jsonFile = fs.readdirSync(outDir).find((f) => f.endsWith(".json"));
          if (!jsonFile) return reject(new Error("engine produced no takeoff.json"));
          const raw = fs.readFileSync(path.join(outDir, jsonFile), "utf8");
          resolve(JSON.parse(raw));
        } catch (e) {
          reject(e);
        } finally {
          fs.rm(outDir, { recursive: true, force: true }, () => {});
        }
      });
  });
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
