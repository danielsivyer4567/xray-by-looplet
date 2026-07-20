"""markup_writer.py — pipeline step 7: inject takeoff results into the PDF.

Writes ``<name>.marked.pdf``: for every quantity and every check in the result
dict that carries evidence (entity ids resolvable to bboxes), a standard PDF
Square/Polygon markup annotation is added on the evidence entity's page, using
only ISO 32000 standard annotation keys (/NM, /Subj, /T, /Contents,
/CreationDate, /M, /C, /F). Quantities with unit ``lm``/``m2`` also get a
standard ISO 32000 rectilinear ``/Measure`` dictionary (built from the page's
``mmPerPt`` scale, when the result carries one) and ``/IT /PolygonDimension``,
so any standards-compliant PDF viewer displays the scaled measurement.

The full result JSON is embedded as ``takeoff.json`` in the output PDF's
EmbeddedFiles name tree, making the marked document self-contained.

Conventions:
  * entity/check ``page`` numbers and ``document.pages[].n`` are 1-based
    (the extractor's 0-based page index is an internal detail).
  * entity bboxes use points with a TOP-LEFT origin; PDF annotation rects
    need a bottom-left origin, so ``pdf_y = page_height - y``.
  * No appearance streams are generated (v0.1): viewers regenerate them or
    render Square/Polygon border-only, which is acceptable.
  * The source PDF is never modified — output goes to ``out`` only.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

import pikepdf
from pikepdf import Array, Dictionary, Name, String

AUTHOR = "X-Ray by Looplet"
SUBJ_PREFIX = "X-Ray "
ATTACHMENT_NAME = "takeoff.json"

# /C colors per CONTEXT.md
COLOR_CHECK_FLAG = (1.0, 0.0, 0.0)
COLOR_CHECK_PASS = (0.0, 0.6, 0.0)
COLOR_QUANTITY = (0.0, 0.3, 1.0)

MEASURED_UNITS = ("lm", "m2")  # units that get /Measure + /IT /PolygonDimension
ANNOT_FLAGS = 4  # /F 4 = Print


# ---------------------------------------------------------------- helpers

def _pdf_date(dt: datetime | None = None) -> str:
    """PDF date string, D:YYYYMMDDHHmmSS."""
    return (dt or datetime.now()).strftime("D:%Y%m%d%H%M%S")


def _entity_index(result: dict) -> dict:
    return {e.get("id"): e for e in result.get("entities", []) if e.get("id")}


def _page_scales(result: dict) -> dict:
    """Map 1-based page number -> scale dict ({'value':..., 'mmPerPt':...})."""
    scales = {}
    for p in result.get("document", {}).get("pages", []) or []:
        n = p.get("n")
        scale = p.get("scale")
        if isinstance(n, int) and isinstance(scale, dict):
            scales[n] = scale
    return scales


def _evidence_bboxes(item: dict, entities: dict):
    """Yield (page_no_1based, bbox) for each resolvable evidence entity."""
    for eid in item.get("evidence", []) or []:
        ent = entities.get(eid)
        if not ent:
            continue
        bbox = ent.get("bbox")
        page = ent.get("page")
        if bbox is None or len(bbox) != 4 or not isinstance(page, int):
            continue
        yield page, [float(v) for v in bbox]


def _pdf_rect(bbox, page_height: float):
    """Top-left-origin (y-down) bbox -> bottom-left-origin PDF rect."""
    x0, y0, x1, y1 = bbox
    ry0 = page_height - y1
    ry1 = page_height - y0
    return (min(x0, x1), min(ry0, ry1), max(x0, x1), max(ry0, ry1))


def _number_format(unit: str, factor: float, precision: int = 100) -> Dictionary:
    return Dictionary({
        "/Type": Name("/NumberFormat"),
        "/U": String(unit),
        "/C": factor,
        "/D": precision,
        "/F": Name("/D"),  # decimal display
    })


def _measure_rl(mm_per_pt: float, ratio: str) -> Dictionary:
    """Standard ISO 32000 rectilinear measure dict from a mm-per-point scale."""
    return Dictionary({
        "/Type": Name("/Measure"),
        "/Subtype": Name("/RL"),
        "/R": String(ratio),
        # user-space pt -> real-world mm
        "/X": Array([_number_format("mm", mm_per_pt)]),
        # distance shown in mm; area shown in m2 (mm^2 * 1e-6)
        "/D": Array([_number_format("mm", 1.0)]),
        "/A": Array([_number_format("m2", 0.000001)]),
    })


def _make_annot(subtype: str, rect, subj: str, contents: str, color, now: str,
                vertices=None, intent: str | None = None,
                measure: Dictionary | None = None) -> Dictionary:
    annot = Dictionary({
        "/Type": Name("/Annot"),
        "/Subtype": Name(subtype),
        "/Rect": Array([float(v) for v in rect]),
        "/NM": String(str(uuid.uuid4())),
        "/Subj": String(subj),
        "/T": String(AUTHOR),
        "/Contents": String(contents),
        "/CreationDate": String(now),
        "/M": String(now),
        "/C": Array([float(c) for c in color]),
        "/F": ANNOT_FLAGS,
        "/BS": Dictionary({"/W": 1.5, "/S": Name("/S")}),
    })
    if vertices is not None:
        annot["/Vertices"] = Array([float(v) for v in vertices])
    if intent:
        annot["/IT"] = Name(intent)
    if measure is not None:
        annot["/Measure"] = measure
    return annot


def _append_annot(pdf: pikepdf.Pdf, page: pikepdf.Page, annot: Dictionary) -> None:
    pageobj = page.obj
    annots = pageobj.get("/Annots")
    if annots is None:
        pageobj["/Annots"] = pdf.make_indirect(Array())
        annots = pageobj["/Annots"]
    annots.append(pdf.make_indirect(annot))


def _page_height(page: pikepdf.Page) -> float:
    mb = page.obj.get("/MediaBox") or Array([0, 0, 595, 842])
    return float(mb[3]) - float(mb[1])


# ---------------------------------------------------------------- main API

def write_marked_pdf(src: str, out: str, result: dict) -> None:
    """Annotate ``src`` with the checks/quantities in ``result`` -> ``out``.

    Adds one Square/Polygon annotation per resolvable evidence bbox and embeds
    the full ``result`` as ``takeoff.json``. The source file is not touched.
    """
    src = os.fspath(src)
    out = os.fspath(out)
    now = _pdf_date()
    entities = _entity_index(result)
    scales = _page_scales(result)

    with pikepdf.open(src) as pdf:
        n_pages = len(pdf.pages)

        def place(page_no: int, bbox, subtype: str, subj: str, contents: str,
                  color, intent=None, measure=None):
            if not (1 <= page_no <= n_pages):
                return
            page = pdf.pages[page_no - 1]
            rect = _pdf_rect(bbox, _page_height(page))
            vertices = None
            if subtype == "/Polygon":
                x0, y0, x1, y1 = rect
                vertices = [x0, y0, x1, y0, x1, y1, x0, y1]
            annot = _make_annot(subtype, rect, subj, contents, color, now,
                                vertices=vertices, intent=intent, measure=measure)
            _append_annot(pdf, page, annot)

        # -- quantities (blue; lm/m2 get Polygon + /Measure + /IT) --
        for q in result.get("quantities", []) or []:
            unit = q.get("unit", "")
            subj = SUBJ_PREFIX + str(q.get("item", "quantity"))
            contents = f"{q.get('item', '?')}: {q.get('qty', '?')} {unit}"
            measured = unit in MEASURED_UNITS
            subtype = "/Polygon" if measured else "/Square"
            intent = "/PolygonDimension" if measured else None
            for page_no, bbox in _evidence_bboxes(q, entities):
                measure = None
                if measured:
                    scale = scales.get(page_no) or {}
                    mm_per_pt = scale.get("mmPerPt")
                    if mm_per_pt:
                        ratio = scale.get("value") or f"1 pt = {mm_per_pt:.6g} mm"
                        measure = _measure_rl(float(mm_per_pt), str(ratio))
                place(page_no, bbox, subtype, subj, contents, COLOR_QUANTITY,
                      intent=intent, measure=measure)

        # -- checks (red = flag, green = pass) --
        for c in result.get("checks", []) or []:
            status = c.get("status", "flag")
            color = COLOR_CHECK_PASS if status == "pass" else COLOR_CHECK_FLAG
            subj = SUBJ_PREFIX + str(c.get("kind", "check"))
            contents = f"{c.get('kind', 'check')} {status}: {c.get('detail', '')}"
            for page_no, bbox in _evidence_bboxes(c, entities):
                place(page_no, bbox, "/Square", subj, contents, color)

        # -- embed the full result JSON (EmbeddedFiles name tree) --
        payload = json.dumps(result, ensure_ascii=False, indent=2,
                             default=str).encode("utf-8")
        filespec = pikepdf.AttachedFileSpec(
            pdf, payload,
            description="X-Ray by Looplet takeoff result",
            filename=ATTACHMENT_NAME,
            mime_type="application/json",
        )
        pdf.attachments[ATTACHMENT_NAME] = filespec

        pdf.save(out)
