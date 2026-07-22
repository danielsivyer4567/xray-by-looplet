"""Sidecar entry point — the exact CLI Electron invokes as a child process.

Frozen by PyInstaller into one standalone executable (see scripts/build-engine).
No Python, no network, no shared state: file in -> takeoff.json out.
"""
import sys

from xray.cli import main

if __name__ == "__main__":
    sys.exit(main())
