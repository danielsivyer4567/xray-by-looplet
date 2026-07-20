"""MCP server smoke tests. Skips cleanly if `mcp` isn't installed."""
import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytest.importorskip("mcp", reason="mcp not installed")
from server.mcp_server import mcp, quote_draft, run_takeoff  # noqa: E402


def test_tools_registered():
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"run_takeoff", "quote_draft", "marked_pdf",
            "run_takeoff_calibrated", "engine_info"} <= names


def test_quote_draft_tool_runs():
    d = quote_draft(str(REPO / "fixtures" / "electrical-schedule.pdf"))
    assert d["summary"]["lines"] == 13
    assert d["engine"]["name"] == "xray-by-looplet"


def test_run_takeoff_tool_runs():
    r = run_takeoff(str(REPO / "fixtures" / "shed-manners-aline.pdf"))
    assert any(q["id"] == "qty-frames" for q in r["quantities"])
