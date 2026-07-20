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
from fastapi.responses import JSONResponse

from xray import ENGINE_NAME, __version__, engine
from xray.markup_writer import write_marked_pdf

from server.quote_lines import build_quote_draft

app = FastAPI(title="X-Ray by Looplet - takeoff worker", version=__version__)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": ENGINE_NAME, "version": __version__}


@app.post("/v1/takeoff")
async def takeoff(
    file: UploadFile = File(...),
    marked_pdf: bool = Query(True, description="also write the marked PDF"),
) -> JSONResponse:
    name = file.filename or ""
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="expected a .pdf upload")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")

    workdir = Path(tempfile.mkdtemp(prefix="xray-"))
    pdf_path = workdir / Path(name).name
    pdf_path.write_bytes(data)

    try:
        result = engine.run(str(pdf_path))
    except Exception as exc:  # engine failure -> 422, never a raw 500 stack
        raise HTTPException(status_code=422, detail=f"takeoff failed: {exc}")

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
