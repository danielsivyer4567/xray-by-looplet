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

import sys
import tempfile
from pathlib import Path

# make the src-layout package importable without an install step
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from xray import ENGINE_NAME, __version__, engine
from xray.markup_writer import write_marked_pdf

from server.quote_lines import build_quote_draft

app = FastAPI(title="X-Ray by Looplet - takeoff worker", version=__version__)

# Browser clients (e.g. the PDX CAD viewer served from a local static server)
# post plans straight from the page, so the worker must answer the preflight.
# Localhost origins only -- widen deliberately if you ever expose this.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


async def _read_plan_upload(file: UploadFile) -> tuple[Path, Path]:
    """Validate + spool an uploaded plan PDF. Returns (workdir, pdf_path)."""
    name = file.filename or ""
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="expected a .pdf upload")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")

    workdir = Path(tempfile.mkdtemp(prefix="xray-"))
    pdf_path = workdir / Path(name).name
    pdf_path.write_bytes(data)
    return workdir, pdf_path


def _run_engine(pdf_path: Path) -> dict:
    """engine.run with a uniform failure contract (422, never a raw 500 stack)."""
    try:
        return engine.run(str(pdf_path))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"takeoff failed: {exc}")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": ENGINE_NAME, "version": __version__}


@app.post("/v1/takeoff/raw")
async def takeoff_raw(file: UploadFile = File(...)) -> JSONResponse:
    """The engine result verbatim -- entities, checks, quantities, review.

    Same shape the CLI writes to <plan>.xray.json, so a viewer can load either
    one interchangeably. No marked PDF: callers of this route render the plan
    themselves and draw evidence from entities[].bbox.
    """
    _workdir, pdf_path = await _read_plan_upload(file)
    return JSONResponse(_run_engine(pdf_path))


@app.post("/v1/takeoff")
async def takeoff(
    file: UploadFile = File(...),
    marked_pdf: bool = Query(True, description="also write the marked PDF"),
) -> JSONResponse:
    workdir, pdf_path = await _read_plan_upload(file)
    result = _run_engine(pdf_path)
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

    return JSONResponse(draft)
