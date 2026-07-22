# X-Ray by Looplet — desktop app (Electron)

The **one construction tool**: the CAD Studio UI + the deterministic X-Ray
takeoff engine, packaged as a single offline desktop app. The engine stays
Python (byte-identical, tested) and ships as a **frozen sidecar binary** that
Electron spawns as a child process — no Python, no network, no LLM in the
request path.

> Not related to the **PDX signer**, which is a separate, non-construction
> product in its own repo and stays on Tauri. This app is Electron only.

## Architecture (one JSON in, one takeoff.json out)

```
renderer/ (CAD Studio web UI)  --window.xray.runTakeoff-->  main.js (Electron)
                                                              |  spawns child process
                                             engine/bin/xray-engine[.exe]  (frozen Python)
                                                              |  writes <plan>.xray.json
                              takeoff rendered in the UI  <---+
```

- `main.js` — Electron main process; picks a PDF, runs the sidecar into a
  scratch dir it wipes, returns the parsed takeoff.json.
- `preload.js` — the only bridge (contextIsolation on, nodeIntegration off):
  exposes `window.xray.pickPdf()` and `window.xray.runTakeoff(path)`.
- `renderer/index.html` — minimal takeoff UI (charcoal theme). **Swap this file
  for the CAD Studio `studio.html`** when it moves in; keep the two
  `window.xray.*` calls as the contract.
- `engine/` — the frozen-engine entry + build scripts.

## Build & run (local — needs Node + Python; NO Rust)

Prereqs: **Node 18+**, **Python 3.11+**. (No Rust — that's the Tauri app.)

```powershell
# 1. Freeze the engine into a standalone binary (one-time per machine / per engine change)
powershell -ExecutionPolicy Bypass -File desktop\scripts\build-engine.ps1
#    -> desktop\engine\bin\xray-engine.exe   (mac/Linux: bash desktop/scripts/build-engine.sh)

# 2. Install Electron deps
cd desktop
npm install

# 3. Dev run
npm start

# 4. Package a signed Windows installer
npm run dist:win
#    -> desktop\dist\XRay-Setup-0.1.0.exe   (electron-builder bundles engine/bin via extraResources)
```

## Notes
- `engine/bin/` and `node_modules/` are gitignored — rebuilt locally, never
  committed (the frozen binary is ~66 MB).
- **Code signing:** set an EV/OV cert for electron-builder (`win.certificateFile`
  / `CSC_LINK`) before shipping; unsigned installers trip SmartScreen.
- **Keys rule (standing):** any signing/private keys live in OS secure storage,
  never in this repo — same rule as the PDX signer.
- The engine is the tested `src/xray` package; this app never forks it — the
  build script freezes the real thing.

## Embedding in Looplet (Tauri extension page)

X-Ray opens as a page in Looplet's center dashboard overlay (the same mechanism
as the app-launcher buttons). The renderer is host-agnostic via
`engine-client.js`; the Looplet (Tauri) side implements ONE command that spawns
the same frozen `xray-engine` sidecar — mirror of Electron's `main.js`:

```rust
// Looplet src-tauri: bundle binaries/xray-engine as a sidecar, then:
#[tauri::command]
async fn xray_run_takeoff(app: tauri::AppHandle, pdf_path: String) -> Result<serde_json::Value, String> {
    use tauri_plugin_shell::ShellExt;
    let out = std::env::temp_dir().join(format!("xray-{}", std::process::id()));
    std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let sc = app.shell().sidecar("xray-engine").map_err(|e| e.to_string())?;
    let o = sc.args(["run", &pdf_path, "--out", &out.to_string_lossy()])
        .output().await.map_err(|e| e.to_string())?;
    if !o.status.success() { return Err(String::from_utf8_lossy(&o.stderr).into()); }
    let f = std::fs::read_dir(&out).map_err(|e| e.to_string())?
        .filter_map(|e| e.ok()).map(|e| e.path())
        .find(|p| p.extension().map_or(false, |x| x == "json"))
        .ok_or("no takeoff.json")?;
    let raw = std::fs::read_to_string(f).map_err(|e| e.to_string())?;
    serde_json::from_str(&raw).map_err(|e| e.to_string())
}
```

Then the X-Ray launcher button loads this renderer as a local webview/route. Same
UI, same engine binary, offline — no fork.
