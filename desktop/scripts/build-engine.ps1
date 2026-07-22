# build-engine.ps1 — freeze the X-Ray Python engine into ONE offline binary
# that Electron ships as a sidecar. Run from the repo root on Windows:
#     powershell -ExecutionPolicy Bypass -File desktop\scripts\build-engine.ps1
#
# Produces desktop\engine\bin\xray-engine.exe (self-contained: no Python, no
# network needed at runtime — proven against the shed/warehouse/electrical
# fixtures). This exact flag set was validated in CI.
$ErrorActionPreference = "Stop"
$root   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # repo root
$engine = Join-Path $root "desktop\engine"
Set-Location $engine

Write-Host "== installing build deps (engine + pyinstaller) =="
python -m pip install --upgrade pip
python -m pip install -r (Join-Path $root "requirements.txt")
python -m pip install pyinstaller

Write-Host "== freezing engine =="
pyinstaller --onefile --name xray-engine `
  --paths (Join-Path $root "src") `
  --collect-all pypdfium2 --collect-all pypdfium2_raw `
  --collect-all pikepdf --collect-all ezdxf `
  --collect-submodules xray `
  xray_engine_entry.py

New-Item -ItemType Directory -Force -Path (Join-Path $engine "bin") | Out-Null
Copy-Item -Force (Join-Path $engine "dist\xray-engine.exe") (Join-Path $engine "bin\xray-engine.exe")
Write-Host "== done: desktop\engine\bin\xray-engine.exe =="
