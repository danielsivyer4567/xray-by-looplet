"""End-to-end tests: engine.run() + CLI against BOTH real fixtures.

These encode the session's proven ground truths (see CONTEXT.md). If any of
them fail, the engine has regressed below what was demonstrated by hand.
"""
import json
import subprocess
import sys
from pathlib import Path

import pikepdf
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

import jsonschema  # noqa: E402

from xray import ENGINE_NAME, engine  # noqa: E402

SHED = REPO / "fixtures" / "shed-manners-aline.pdf"
WAREHOUSE = REPO / "fixtures" / "warehouse-design21.pdf"
SCHEMA = json.loads((REPO / "schema" / "takeoff.schema.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def shed_result():
    return engine.run(str(SHED))


@pytest.fixture(scope="module")
def wh_result():
    return engine.run(str(WAREHOUSE))


# --- schema + identity --------------------------------------------------------

def test_shed_result_conforms_to_schema(shed_result):
    jsonschema.validate(shed_result, SCHEMA)


def test_warehouse_result_conforms_to_schema(wh_result):
    jsonschema.validate(wh_result, SCHEMA)


def test_engine_identity(shed_result):
    assert shed_result["engine"]["name"] == ENGINE_NAME == "xray-by-looplet"
    assert shed_result["engine"]["version"]


def test_document_meta(shed_result, wh_result):
    assert len(shed_result["document"]["pages"]) == 5
    assert len(wh_result["document"]["pages"]) == 50
    assert len(shed_result["document"]["sha256"]) == 64
    assert "Paper Capture" in wh_result["document"]["producer"]


def test_warehouse_raster_pages_detected(wh_result):
    kinds = {p["n"]: p["kind"] for p in wh_result["document"]["pages"]}
    for n in (23, 24, 25, 26, 29):
        assert kinds[n] == "raster", f"page {n} should be raster, got {kinds[n]}"
    for n in (2, 3, 4, 5):
        assert kinds[n] == "vector", f"page {n} should be vector, got {kinds[n]}"


# --- shed ground truths -------------------------------------------------------

def _checks(result, kind=None, status=None):
    out = result["checks"]
    if kind:
        out = [c for c in out if c["kind"] == kind]
    if status:
        out = [c for c in out if c["status"] == status]
    return out


def test_shed_three_16000_chains_pass(shed_result):
    # the overall 16000 sits on its own dimension line, so these surface as
    # cross-stated checks ("sum matches overall stated separately")
    hits = [c for c in _checks(shed_result, status="pass")
            if c["kind"] in ("chain-sum", "cross-sheet")
            and "16000" in c["detail"] and "-p0-" in c["id"]]
    assert len(hits) >= 3, f"expected >=3 16000 chains on page 0, got {len(hits)}"


def test_shed_trig_793(shed_result):
    trigs = _checks(shed_result, "trig", "pass")
    assert trigs, "trig check missing"
    assert "793" in trigs[0]["detail"]


def test_shed_portal_rafter_count(shed_result):
    counts = _checks(shed_result, "count", "pass")
    assert any("PORTAL RAFTER" in c["detail"] and "5" in c["detail"]
               for c in counts), "PORTAL RAFTER 5x count check missing"


def test_shed_no_phone_or_copyright_chains(shed_result):
    for c in _checks(shed_result, "chain-sum"):
        for banned in ("5452", "2255", "2019"):
            assert banned not in c["detail"], f"false-positive chain: {c['detail']}"


def _qty(result, item_fragment):
    for q in result["quantities"]:
        if item_fragment in q["item"]:
            return q
    return None


def test_shed_quantities(shed_result):
    frames = _qty(shed_result, "portal frames")
    assert frames and frames["qty"] == 5 and frames["unit"] == "ea"
    assert frames["tier"] == "reconciled"

    steel = _qty(shed_result, "portal frame steel")
    assert steel and steel["unit"] == "lm"
    assert abs(steel["qty"] - 87.7) <= max(1.0, 0.005 * 87.7)

    roof = _qty(shed_result, "roof sheeting")
    assert roof and roof["unit"] == "m2"
    assert abs(roof["qty"] - 146.2) <= max(1.0, 0.005 * 146.2)


def test_shed_cladding_needs_human_and_reviewed(shed_result):
    clad = _qty(shed_result, "cladding")
    assert clad, "wall cladding quantity missing"
    assert clad["tier"] == "needs-human"  # bay 1 OPEN both sides -> assumption
    refs = {r["ref"] for r in shed_result.get("review", [])}
    assert clad["id"] in refs


def test_shed_every_quantity_has_formula_and_evidence(shed_result):
    for q in shed_result["quantities"]:
        assert q["formula"].strip(), f"{q['id']} missing formula"
        assert q["evidence"], f"{q['id']} missing evidence"


# --- warehouse ground truths --------------------------------------------------

def test_warehouse_glyph_split_recovered(wh_result):
    reassembled = {e["raw"] for e in wh_result["entities"]
                   if e["source"] == "reassembled"}
    for target in ("29995", "13530", "2745"):
        assert target in reassembled, f"{target} not recovered by reassembler"


def test_warehouse_29995_chain_passes(wh_result):
    hits = [c for c in _checks(wh_result, status="pass")
            if c["kind"] in ("chain-sum", "cross-sheet")
            and "29995" in c["detail"] and "13530" in c["detail"]]
    assert hits, "29995 = 13530 + 16465 chain check missing"


def test_warehouse_panel_chain_flagged_delta_2(wh_result):
    flags = [c for c in _checks(wh_result, status="flag")
             if c["delta"] is not None and abs(abs(c["delta"]) - 2.0) < 0.01
             and "16465" in c["detail"]]
    assert flags, "concrete-panel 16467 vs 16465 FLAG check missing"


# --- CLI end-to-end -----------------------------------------------------------

def test_cli_run_shed(tmp_path):
    env_src = str(REPO / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "xray", "run", str(SHED), "--out", str(tmp_path)],
        capture_output=True, text=True, timeout=600,
        env={**__import__("os").environ, "PYTHONPATH": env_src},
    )
    assert proc.returncode == 0, proc.stderr

    json_path = tmp_path / "shed-manners-aline.xray.json"
    marked_path = tmp_path / "shed-manners-aline.marked.pdf"
    assert json_path.is_file() and marked_path.is_file()

    result = json.loads(json_path.read_text("utf-8"))
    jsonschema.validate(result, SCHEMA)
    assert result["engine"]["name"] == "xray-by-looplet"
    assert "xray-by-looplet" in proc.stdout

    with pikepdf.open(marked_path) as pdf:
        annots = [a for p in pdf.pages for a in (p.obj.get("/Annots") or [])]
        branded = [a for a in annots
                   if str(a.get("/T", "")) == "X-Ray by Looplet"]
        assert branded, "no X-Ray by Looplet annotations in marked.pdf"
        for a in branded:
            assert "/NM" in a and "/Subj" in a
        names = pdf.Root.Names.EmbeddedFiles.Names
        assert any("takeoff.json" in str(n) for n in names)
