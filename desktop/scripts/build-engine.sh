#!/usr/bin/env bash
# build-engine.sh — freeze the X-Ray engine into one offline binary (mac/Linux).
# Run from repo root:  bash desktop/scripts/build-engine.sh
# Produces desktop/engine/bin/xray-engine (self-contained; no Python/network).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENGINE="$ROOT/desktop/engine"
cd "$ENGINE"

echo "== installing build deps =="
python3 -m pip install --upgrade pip
python3 -m pip install -r "$ROOT/requirements.txt"
python3 -m pip install pyinstaller

echo "== freezing engine =="
pyinstaller --onefile --name xray-engine \
  --paths "$ROOT/src" \
  --collect-all pypdfium2 --collect-all pypdfium2_raw \
  --collect-all pikepdf --collect-all ezdxf \
  --collect-submodules xray \
  xray_engine_entry.py

mkdir -p "$ENGINE/bin"
cp -f "$ENGINE/dist/xray-engine" "$ENGINE/bin/xray-engine"
chmod +x "$ENGINE/bin/xray-engine"
echo "== done: desktop/engine/bin/xray-engine =="
