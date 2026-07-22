"""The public-facing safety layer: every hostile input fails safe with a 4xx
and the service stays up. Also proves the idempotency cache and the API-key
gate, and that a wedged parse dies with its child process, not the server.
"""
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from server import app as appmod
from server import hardening

client = TestClient(appmod.app)
PDF = "fixtures/electrical-schedule.pdf"
DXF = "fixtures/cad/architectural_test_fixtures_v2.dxf"


@pytest.fixture(autouse=True)
def _fresh_cache():
    hardening.cache_clear()
    yield
    hardening.cache_clear()


def _post(name, data, key=None):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return client.post("/v1/takeoff/raw",
                       files={"file": (name, data)}, headers=headers)


# ---- hostile inputs fail cheap, early, and safe ---------------------------

def test_wrong_extension_415():
    assert _post("plan.exe", b"MZ....").status_code == 415


def test_empty_upload_400():
    assert _post("plan.pdf", b"").status_code == 400


def test_oversize_413(monkeypatch):
    monkeypatch.setattr(hardening, "MAX_UPLOAD_BYTES", 100)
    assert _post("plan.pdf", b"%PDF-1.7 " + b"A" * 200).status_code == 413


def test_magic_mismatch_415():
    # claims .pdf, is garbage — rejected before any parser touches it
    assert _post("plan.pdf", b"not a pdf at all" * 10).status_code == 415
    # claims .dxf, is a PNG header
    assert _post("plan.dxf", b"\x89PNG\r\n" * 100).status_code == 415


def test_corrupt_pdf_422_service_survives():
    # real magic, garbage body: the parser fails, the SERVICE does not
    r = _post("plan.pdf", b"%PDF-1.7\n" + b"\x00\xff" * 5000)
    assert r.status_code == 422
    assert client.get("/health").status_code == 200


def test_truncated_dxf_422_service_survives():
    r = _post("plan.dxf", b"  0\nSECTION\n  2\nHEADER\n")
    assert r.status_code in (200, 422)   # parse may salvage or fail — never 500
    assert client.get("/health").status_code == 200


# ---- API-key gate ---------------------------------------------------------

def test_open_mode_when_no_keys(monkeypatch):
    monkeypatch.setattr(hardening, "API_KEYS", frozenset())
    with open(PDF, "rb") as f:
        assert _post("p.pdf", f.read()).status_code == 200


def test_keys_required_when_configured(monkeypatch):
    monkeypatch.setattr(hardening, "API_KEYS", frozenset({"xr_secret_1"}))
    with open(PDF, "rb") as f:
        data = f.read()
    assert _post("p.pdf", data).status_code == 401                 # no key
    assert _post("p.pdf", data, key="wrong").status_code == 401    # bad key
    assert _post("p.pdf", data, key="xr_secret_1").status_code == 200


# ---- idempotency cache: determinism as a live feature ---------------------

def test_cache_hit_identical_bytes():
    with open(PDF, "rb") as f:
        data = f.read()
    r1 = _post("p.pdf", data)
    r2 = _post("p.pdf", data)
    assert r1.status_code == r2.status_code == 200
    assert r1.headers["X-XRay-Cache"] == "miss"
    assert r2.headers["X-XRay-Cache"] == "hit"
    assert r1.json() == r2.json()          # byte-identical result, instantly


def test_dxf_upload_returns_symbols():
    with open(DXF, "rb") as f:
        r = _post("plan.dxf", f.read())
    assert r.status_code == 200
    body = r.json()
    assert len(body["symbols"]) == 37      # the verified fixture, over HTTP


# ---- parse isolation: a wedged parse dies with the child, not the server --

def _sleeper(seconds: float) -> str:
    time.sleep(seconds)
    return "done"


def test_run_with_timeout_kills_wedged_child():
    with pytest.raises(hardening.ParseTimeout):
        hardening.run_with_timeout(_sleeper, 30.0, timeout=1.0)
    # pool was rebuilt — the next run works fine
    assert hardening.run_with_timeout(_sleeper, 0.05, timeout=10.0) == "done"


def test_isolated_engine_run_real_fixture():
    result = hardening.run_with_timeout(hardening.engine_run_child, PDF,
                                        timeout=120.0)
    assert result["engine"]["name"] == "xray-by-looplet"
    assert len(result["quantities"]) > 0
