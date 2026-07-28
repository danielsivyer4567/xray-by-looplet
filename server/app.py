"""app.py — Mode B worker: FastAPI wrapper around xray.engine.run().

Run (from repo root):
    pip install -r server/requirements.txt
    set PYTHONPATH=src            # or: pip install -e .
    uvicorn server.app:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /health         -> liveness + engine identity
    POST /v1/takeoff     -> multipart 'file' = plan PDF
                            returns { engine, document, quote_lines, flags, summary,
                                      marked_pdf_path? }
    POST /v1/takeoff/raw -> multipart 'file' = plan PDF
                            returns the engine result verbatim
                            { engine, document, entities, checks, quantities, review }

Why two routes: /v1/takeoff returns the quote-draft envelope (quote_lines) for
pricing consumers, which deliberately drops entities/bboxes. Plan VIEWERS need
those bboxes to highlight evidence on the page, so /v1/takeoff/raw hands back
engine.run() untouched -- the same shape as an on-disk <plan>.xray.json.

The engine runs in-process here for simplicity; for heavier loads move engine.run
behind a task queue and keep this as the thin HTTP edge.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

# make the src-layout package importable without an install step
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from xray import ENGINE_NAME, __version__, engine
from xray.markup_writer import write_marked_pdf

from server import hardening
from server.quote_lines import build_quote_draft

app = FastAPI(title="X-Ray by Looplet - takeoff worker", version=__version__)

# Browser clients post plans straight from the embedded PDX CAD viewer, so the
# worker must answer both ordinary CORS and Chrome's loopback/private-network
# preflight. Keep the production origin explicit: this worker can read local
# plan files submitted by the user and must not become a general web endpoint.
_ALLOWED_BROWSER_ORIGIN = re.compile(
    r"^(?:https?://(?:localhost|127\.0\.0\.1)(?::\d+)?|"
    r"https://app\.looplet\.com\.au)$"
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_ALLOWED_BROWSER_ORIGIN.pattern,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_private_network=True,
)


@app.middleware("http")
async def allow_approved_private_network_requests(request: Request, call_next):
    """Opt approved viewer origins into browser loopback access.

    Chromium sends ``Access-Control-Request-Private-Network: true`` before a
    public HTTPS page may call a service on localhost. The response header is
    deliberately limited to the same origins accepted by CORS.
    """
    response = await call_next(request)
    origin = request.headers.get("origin", "")
    private_network_header = "Access-Control-Allow-Private-Network"
    if (
        not _ALLOWED_BROWSER_ORIGIN.fullmatch(origin)
        and private_network_header in response.headers
    ):
        del response.headers[private_network_header]
    return response


def _auth(authorization: str | None = Header(None)) -> None:
    """API-key gate. Open when XRAY_API_KEYS is unset (local dev mode)."""
    if not hardening.check_api_key(authorization):
        raise HTTPException(status_code=401, detail="missing or invalid API key")


async def _read_plan_upload(file: UploadFile) -> tuple[Path, Path, bytes]:
    """Validate + spool an uploaded plan. Returns (workdir, path, bytes).

    Guardrails before any parser touches the bytes: extension allow-list,
    size cap (413), and magic-byte sanity (415) — a hostile upload fails
    cheap and early, never inside pdfium/ezdxf.
    """
    name = file.filename or ""
    if not name.lower().endswith(hardening.ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=415,
                            detail="expected a .pdf or .dxf upload")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(data) > hardening.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"upload exceeds {hardening.MAX_UPLOAD_BYTES // (1024*1024)} MB limit")
    if not hardening.magic_ok(name, data):
        raise HTTPException(status_code=415,
                            detail="file content does not match its extension")

    workdir = Path(tempfile.mkdtemp(prefix="xray-"))
    pdf_path = workdir / Path(name).name
    pdf_path.write_bytes(data)
    return workdir, pdf_path, data


def _run_engine(pdf_path: Path, data: bytes) -> tuple[dict, bool]:
    """engine.run with cache + optional child-process isolation.

    Returns (result, cache_hit). Identical bytes + identical engine version
    -> the identical cached result, instantly: idempotency as a live
    demonstration of determinism. Failures are a uniform 422 (never a raw
    500 stack); a wedged parse in isolated mode dies with the child, not
    with the server.
    """
    sha = hardening.sha256_of(data)
    cached = hardening.cache_get(sha, __version__)
    if cached is not None:
        return cached, True
    try:
        if hardening.ISOLATE_PARSE:
            result = hardening.run_with_timeout(hardening.engine_run_child,
                                                str(pdf_path))
        else:
            result = engine.run(str(pdf_path))
    except hardening.ParseTimeout as exc:
        raise HTTPException(status_code=422, detail=f"takeoff failed: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"takeoff failed: {exc}")
    hardening.cache_put(sha, __version__, result)
    return result, False


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": ENGINE_NAME, "version": __version__}


@app.post("/v1/takeoff/raw", dependencies=[Depends(_auth)])
async def takeoff_raw(file: UploadFile = File(...)) -> JSONResponse:
    """The engine result verbatim -- entities, checks, quantities, review.

    Same shape the CLI writes to <plan>.xray.json, so a viewer can load either
    one interchangeably. No marked PDF: callers of this route render the plan
    themselves and draw evidence from entities[].bbox.
    """
    _workdir, pdf_path, data = await _read_plan_upload(file)
    result, hit = _run_engine(pdf_path, data)
    return JSONResponse(result,
                        headers={"X-XRay-Cache": "hit" if hit else "miss"})


@app.post("/v1/takeoff", dependencies=[Depends(_auth)])
async def takeoff(
    file: UploadFile = File(...),
    marked_pdf: bool = Query(True, description="also write the marked PDF"),
) -> JSONResponse:
    workdir, pdf_path, data = await _read_plan_upload(file)
    result, hit = _run_engine(pdf_path, data)
    draft = build_quote_draft(result)

    if marked_pdf:
        marked = workdir / f"{pdf_path.stem}.marked.pdf"
        try:
            write_marked_pdf(str(pdf_path), str(marked), result)
            draft["marked_pdf_path"] = str(marked)
        except Exception as exc:
            draft["marked_pdf_path"] = None
            draft["flags"].append(
                {"ref": "marked-pdf", "reason": f"annotation write failed: {exc}"})

    return JSONResponse(draft,
                        headers={"X-XRay-Cache": "hit" if hit else "miss"})
