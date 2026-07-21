"""End-to-end test of the Mode B worker: posts a REAL fixture PDF through the
FastAPI app via TestClient and checks the response envelope. Skips cleanly if
FastAPI isn't installed (server deps are optional to the core engine).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytest.importorskip("fastapi", reason="server deps not installed")
from fastapi.testclient import TestClient  # noqa: E402

from server.app import app  # noqa: E402

SHED = REPO / "fixtures" / "shed-manners-aline.pdf"
client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "xray-by-looplet"
    assert body["status"] == "ok"


def test_takeoff_shed_returns_quote_lines():
    with open(SHED, "rb") as fh:
        r = client.post("/v1/takeoff",
                        files={"file": ("shed.pdf", fh, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"]["name"] == "xray-by-looplet"
    assert body["summary"]["lines"] == 13  # 8 core + 5 hardening accessories
    assert len(body["quote_lines"]) == 13
    frames = [ln for ln in body["quote_lines"]
              if ln["source_quantity_id"] == "qty-frames"]
    assert frames and frames[0]["quantity"] == 5.0
    assert body["marked_pdf_path"]  # marked PDF written by default


def test_rejects_non_pdf():
    r = client.post("/v1/takeoff",
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_rejects_empty_upload():
    r = client.post("/v1/takeoff",
                    files={"file": ("empty.pdf", b"", "application/pdf")})
    assert r.status_code == 400


def test_raw_returns_engine_shape_with_bboxes():
    """The raw route must carry the keys a plan viewer needs to draw evidence:
    entities (with bboxes) + quantities, which the quote envelope drops."""
    with open(SHED, "rb") as fh:
        r = client.post("/v1/takeoff/raw",
                        files={"file": ("shed.pdf", fh, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("engine", "document", "entities", "checks", "quantities", "review"):
        assert key in body, f"raw takeoff missing {key!r}"
    assert len(body["quantities"]) == 13
    assert body["document"]["coverage"]["overallRatio"] > 0

    # evidence ids must resolve to entities carrying a 4-number bbox + page
    ents = {e["id"]: e for e in body["entities"]}
    frames = [q for q in body["quantities"] if q["id"] == "qty-frames"]
    assert frames, "expected qty-frames in the shed takeoff"
    located = [ents[eid] for eid in frames[0]["evidence"] if eid in ents]
    assert located, "qty-frames evidence resolved to no entities"
    for ent in located:
        assert len(ent["bbox"]) == 4
        assert isinstance(ent["page"], int)


def test_raw_rejects_non_pdf():
    r = client.post("/v1/takeoff/raw",
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_cors_preflight_allows_localhost_viewer():
    """The CAD viewer posts from a local static server; preflight must pass."""
    r = client.options("/v1/takeoff/raw", headers={
        "Origin": "http://localhost:5178",
        "Access-Control-Request-Method": "POST",
    })
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == "http://localhost:5178"
