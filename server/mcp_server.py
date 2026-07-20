"""mcp_server.py — X-Ray by Looplet as an MCP server.

Exposes the takeoff engine as MCP tools so Looplet (or any MCP client) can call
it directly. This is the clean integration surface: one server, many callers
(Looplet's builder, PDX, an agent). Stdio transport.

Run:  pip install -r server/requirements.txt
      set PYTHONPATH=src            # or: pip install -e .
      python -m server.mcp_server
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mcp.server.fastmcp import FastMCP

from xray import ENGINE_NAME, __version__, engine
from xray.markup_writer import write_marked_pdf

from server.quote_lines import build_quote_draft

mcp = FastMCP("xray-by-looplet")


@mcp.tool()
def engine_info() -> dict:
    """Return the engine name and version."""
    return {"engine": ENGINE_NAME, "version": __version__}


@mcp.tool()
def run_takeoff(pdf_path: str) -> dict:
    """Run a full takeoff on a plan PDF. Returns the structured takeoff result:
    entities, verification checks, and quantities with formulas, trust tiers
    (reconciled / single-source / needs-human) and evidence."""
    return engine.run(pdf_path)


@mcp.tool()
def quote_draft(pdf_path: str) -> dict:
    """Run a takeoff and map it to draft quote lines — the Looplet-ready
    envelope: quote_lines (with basis, tier, review_required), flags, summary.
    rate/amount are left null for a downstream pricing step to fill."""
    return build_quote_draft(engine.run(pdf_path))


@mcp.tool()
def run_takeoff_calibrated(pdf_path: str, page: int,
                           p0: list, p1: list, known_mm: float) -> dict:
    """Run a takeoff with a manual scale calibration on one page: two points in
    PDF coordinates ([x, y] each) and the real-world distance between them (mm).
    The calibrated scale overrides auto-detection for that page."""
    cal = {int(page): {"p0": list(p0), "p1": list(p1), "known_mm": float(known_mm)}}
    return engine.run(pdf_path, calibrations=cal)


@mcp.tool()
def marked_pdf(pdf_path: str, out_path: str) -> dict:
    """Run a takeoff and write a marked-up PDF (standard annotations + embedded
    takeoff.json) to out_path. Returns the path and quantity count."""
    result = engine.run(pdf_path)
    write_marked_pdf(pdf_path, out_path, result)
    return {"marked_pdf": out_path,
            "quantities": len(result.get("quantities", [])),
            "checks": len(result.get("checks", []))}


if __name__ == "__main__":
    mcp.run()
