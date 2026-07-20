"""Tests for src/xray/markup_writer.py — standalone (no other engine modules).

Synthesizes a minimal result dict (no grammar/chains/quantify imports), runs
write_marked_pdf against fixtures/shed-manners-aline.pdf, then verifies the
output with pikepdf AND pypdfium2.

Run:  python -m pytest tests/test_writer.py -x -q   (cwd = repo root)
"""
import hashlib
import json
import sys
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))  # standalone: no PYTHONPATH needed

from xray.markup_writer import write_marked_pdf  # noqa: E402

FIXTURE = REPO / "fixtures" / "shed-manners-aline.pdf"
MM_PER_PT_1_100 = 25.4 / 72.0 * 100.0  # 1:100 -> 35.2778 mm of world per pt

# evidence bboxes resolved: pass-check 2 + flag-check 1 + lm quantity 1
EXPECTED_NEW_ANNOTS = 4


def make_result():
    _pdf = pdfium.PdfDocument(str(FIXTURE))
    w, h = _pdf[0].get_size()
    _pdf.close()
    return {
        "engine": {"name": "xray-by-looplet", "version": "0.1.0"},
        "document": {
            "path": str(FIXTURE),
            "sha256": "0" * 64,
            "producer": "Skia/PDF",
            "pages": [
                {
                    "n": 1, "widthPt": w, "heightPt": h, "kind": "vector",
                    "scale": {
                        "value": "1:100",
                        "mmPerPt": MM_PER_PT_1_100,
                        "methods": ["declared"],
                        "confidence": 0.9,
                    },
                },
            ],
        },
        "entities": [
            {"id": "e-dim-1", "page": 1, "type": "DIM", "value": 6000,
             "raw": "6000", "bbox": [120.0, 150.0, 160.0, 162.0],
             "confidence": 0.99, "source": "text"},
            {"id": "e-dim-2", "page": 1, "type": "DIM", "value": 3500,
             "raw": "3500", "bbox": [200.0, 150.0, 240.0, 162.0],
             "confidence": 0.99, "source": "text"},
            {"id": "e-label-1", "page": 1, "type": "LABEL",
             "value": "PORTAL RAFTER", "raw": "PORTAL RAFTER",
             "bbox": [300.0, 220.0, 380.0, 232.0],
             "confidence": 0.9, "source": "text"},
        ],
        "checks": [
            {"id": "c-pass-1", "kind": "chain-sum", "status": "pass",
             "detail": "6000+3500+3500+3000 = 16000", "delta": 0.0,
             "page": 1, "evidence": ["e-dim-1", "e-dim-2"]},
            {"id": "c-flag-1", "kind": "chain-sum", "status": "flag",
             "detail": "panel chain 16467 vs stated 16465", "delta": 2.0,
             "page": 1, "evidence": ["e-label-1"]},
        ],
        "quantities": [
            {"id": "q-steel-1", "trade": "structural steel",
             "item": "portal frame steel", "qty": 87.7, "unit": "lm",
             "formula": "5 * (2*4.2 + 2*4.5696)", "tier": "reconciled",
             "evidence": ["e-dim-1"], "notes": ""},
        ],
    }


def _xray_annots(pdf):
    out = []
    for page in pdf.pages:
        for a in page.obj.get("/Annots") or []:
            if str(a.get("/Subj", "")).startswith("X-Ray "):
                out.append(a)
    return out


def _annot_count(path):
    with pikepdf.open(path) as pdf:
        return sum(len(p.obj.get("/Annots") or []) for p in pdf.pages)


@pytest.fixture(scope="module")
def marked(tmp_path_factory):
    """Write the marked PDF once; return (out_path, result, baseline_count, src_sha)."""
    out_dir = tmp_path_factory.mktemp("writer")
    out = out_dir / "shed.marked.pdf"
    result = make_result()
    src_sha = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    baseline = _annot_count(FIXTURE)
    write_marked_pdf(str(FIXTURE), str(out), result)
    return out, result, baseline, src_sha


def test_annotation_count_increases_by_expected(marked):
    out, _result, baseline, _sha = marked
    assert _annot_count(out) == baseline + EXPECTED_NEW_ANNOTS


def test_annotations_have_revu_compat_keys(marked):
    out, _result, _baseline, _sha = marked
    with pikepdf.open(out) as pdf:
        annots = _xray_annots(pdf)
        assert len(annots) == EXPECTED_NEW_ANNOTS
        nms = set()
        for a in annots:
            assert "/NM" in a and len(str(a["/NM"])) >= 8
            nms.add(str(a["/NM"]))
            assert str(a.get("/Subj", "")).startswith("X-Ray ")
            assert str(a.get("/T", "")) == "X-Ray by Looplet"
            assert str(a.get("/Contents", ""))
            assert str(a.get("/CreationDate", "")).startswith("D:")
            assert str(a.get("/M", "")).startswith("D:")
            assert int(a.get("/F", 0)) == 4
            assert str(a.get("/Subtype")) in ("/Square", "/Polygon")
        assert len(nms) == EXPECTED_NEW_ANNOTS  # /NM values unique


def test_annotation_colors_by_kind(marked):
    out, _result, _baseline, _sha = marked
    with pikepdf.open(out) as pdf:
        colors = {tuple(round(float(c), 2) for c in a["/C"])
                  for a in _xray_annots(pdf)}
    assert (1.0, 0.0, 0.0) in colors      # flag check = red
    assert (0.0, 0.6, 0.0) in colors      # pass check = green
    assert (0.0, 0.3, 1.0) in colors      # quantity = blue


def test_lm_quantity_gets_measure_and_intent(marked):
    out, _result, _baseline, _sha = marked
    with pikepdf.open(out) as pdf:
        measured = [a for a in _xray_annots(pdf) if "/Measure" in a]
        assert len(measured) == 1
        a = measured[0]
        assert str(a["/Subtype"]) == "/Polygon"
        assert str(a["/IT"]) == "/PolygonDimension"
        assert len(a["/Vertices"]) == 8
        m = a["/Measure"]
        assert str(m["/Subtype"]) == "/RL"
        assert str(m["/R"]) == "1:100"
        nf = m["/X"][0]
        # pikepdf writes reals with 6-decimal precision
        assert float(nf["/C"]) == pytest.approx(MM_PER_PT_1_100, abs=1e-5)
        assert str(nf["/U"]) == "mm"


def test_rect_converted_to_bottom_left_origin(marked):
    out, result, _baseline, _sha = marked
    page_h = result["document"]["pages"][0]["heightPt"]
    ent = result["entities"][2]  # e-label-1, only evidence of the flag check
    x0, y0, x1, y1 = ent["bbox"]
    with pikepdf.open(out) as pdf:
        flagged = [a for a in _xray_annots(pdf)
                   if tuple(round(float(c), 2) for c in a["/C"]) == (1.0, 0.0, 0.0)]
        assert len(flagged) == 1
        rect = [float(v) for v in flagged[0]["/Rect"]]
    assert rect[0] == pytest.approx(x0)
    assert rect[1] == pytest.approx(page_h - y1)
    assert rect[2] == pytest.approx(x1)
    assert rect[3] == pytest.approx(page_h - y0)


def test_takeoff_json_attachment_roundtrips(marked):
    out, result, _baseline, _sha = marked
    with pikepdf.open(out) as pdf:
        assert "takeoff.json" in pdf.attachments
        data = pdf.attachments["takeoff.json"].get_file().read_bytes()
    assert json.loads(data.decode("utf-8")) == result


def test_output_reopens_and_renders(marked):
    out, _result, _baseline, _sha = marked
    pdf = pdfium.PdfDocument(str(out))
    try:
        assert len(pdf) == 5  # shed fixture is 5 pages
        bitmap = pdf[0].render(scale=1.0)
        assert bitmap.width > 0 and bitmap.height > 0
    finally:
        pdf.close()


def test_source_pdf_untouched(marked):
    _out, _result, _baseline, src_sha = marked
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == src_sha


def test_unresolvable_evidence_is_skipped(tmp_path):
    """Missing evidence ids / empty evidence must not annotate or crash."""
    result = make_result()
    result["checks"] = [
        {"id": "c-x", "kind": "chain-sum", "status": "pass",
         "detail": "no such entity", "delta": None, "evidence": ["ghost-id"]},
        {"id": "c-y", "kind": "trig", "status": "flag",
         "detail": "no evidence at all", "delta": 1.0, "evidence": []},
    ]
    result["quantities"] = []
    out = tmp_path / "empty.marked.pdf"
    write_marked_pdf(str(FIXTURE), str(out), result)
    assert _annot_count(out) == _annot_count(FIXTURE)
    with pikepdf.open(out) as pdf:
        assert "takeoff.json" in pdf.attachments
