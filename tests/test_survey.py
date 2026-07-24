"""Survey / terrain pack — read a site survey (spot levels, terrain mesh,
contours, breaklines) from an old-style R12 DXF.

THIS TEST IS A PROOF, not just a regression net. Every number asserted below was
derived BY HAND from the five survey coordinates in tools/make_terrain_fixture.py
(the literal shots a surveyor recorded) — see GROUND_TRUTH. The deterministic
engine has to reproduce those exact figures from the .dxf. Three independent
things must agree:

  1. the hand arithmetic in this file,
  2. what xray.engine.run() computes off the fixture, and
  3. the RL numbers you can read yourself by opening
     fixtures/cad/terrain-survey.dxf in any CAD viewer.

If they agree, the *tool* extracted the survey — not a language model asserting a
plausible answer. Run it yourself:  pytest tests/test_survey.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytest.importorskip("ezdxf", reason="CAD deps not installed")

from xray.engine import run                                    # noqa: E402
from xray.packs_survey import SurveyPack, _survey_points        # noqa: E402
from xray.packs import PackContext                              # noqa: E402
from xray.sources.base import SurveyPoint, Measure             # noqa: E402

FIXTURE = REPO / "fixtures" / "cad" / "terrain-survey.dxf"

# --- ground truth, worked by hand from the five shots in the fixture ---------
# SPOT_LEVELS z-values: 267.82, 283.42, 194.71, -40.91, 252.40
#   count                = 5
#   lowest  RL           = -40.91   (shot at 48.20, 827.65)
#   highest RL           = 283.42   (shot at 594.80, 481.67)
#   site fall = hi - lo  = 283.42 - (-40.91) = 324.33
# TERRAIN_MESH is 11 x 11                    = 121 vertices
# CONTOURS_MAJOR: three single-RL polylines  = 3
# BREAKLINES: one variable-z polyline        = 1
GROUND_TRUTH = {
    "spot_levels": 5,
    "lowest_rl": -40.91,
    "highest_rl": 283.42,
    "site_fall": 324.33,
    "mesh_vertices": 121,
    "contours": 3,
    "breaklines": 1,
}


def _q(result, qid):
    return next((q for q in result["quantities"] if q["id"] == qid), None)


@pytest.fixture(scope="module")
def result():
    assert FIXTURE.exists(), (
        f"missing {FIXTURE}; regenerate with: python tools/make_terrain_fixture.py")
    return run(str(FIXTURE))


def test_spot_levels_are_counted(result):
    """5 POINT entities -> 5 spot levels, exact, reconciled (nothing estimated)."""
    q = _q(result, "q-survey-spot-levels")
    assert q is not None
    assert q["qty"] == float(GROUND_TRUTH["spot_levels"])
    assert q["unit"] == "ea" and q["tier"] == "reconciled"
    assert len(q["evidence"]) == GROUND_TRUTH["spot_levels"]   # one id per shot


def test_site_fall_matches_hand_arithmetic(result):
    """max RL - min RL = 283.42 - (-40.91) = 324.33. The single figure that most
    proves the engine read the z-values and did the subtraction itself."""
    q = _q(result, "q-survey-fall")
    assert q is not None
    assert q["qty"] == GROUND_TRUTH["site_fall"]
    assert q["unit"] == "m" and q["tier"] == "reconciled"
    # the formula must literally show both RLs it subtracted
    assert "283.42" in q["formula"] and "-40.91" in q["formula"]
    # and it must cite exactly the lowest and highest shots as evidence
    assert len(q["evidence"]) == 2


def test_extreme_levels_are_the_right_shots(result):
    """The lowest/highest RL the engine used are the actual extremes in the file,
    not an average or a mislabel."""
    pts = [p for p in result["points"] if p["kind"] == "survey"]
    zs = sorted(p["z"] for p in pts)
    assert round(zs[0], 2) == GROUND_TRUTH["lowest_rl"]
    assert round(zs[-1], 2) == GROUND_TRUTH["highest_rl"]


def test_terrain_mesh_vertices(result):
    """An 11 x 11 polygon mesh -> 121 vertices read off the surface."""
    q = _q(result, "q-survey-mesh-vertices")
    assert q is not None and q["qty"] == float(GROUND_TRUTH["mesh_vertices"])
    mesh_pts = [p for p in result["points"] if p["kind"] == "mesh"]
    assert len(mesh_pts) == GROUND_TRUTH["mesh_vertices"]


def test_contours_and_breaklines_are_classified(result):
    """A contour sits at ONE RL (planar); a breakline's z varies. The engine must
    tell them apart from the geometry, not just the layer name."""
    contours = _q(result, "q-survey-contours")
    breaklines = _q(result, "q-survey-breaklines")
    assert contours is not None and contours["qty"] == float(GROUND_TRUTH["contours"])
    assert breaklines is not None and breaklines["qty"] == float(GROUND_TRUTH["breaklines"])
    # the three contour RLs must be surfaced in the notes (100 / 150 / 200)
    assert "100" in contours["notes"] and "150" in contours["notes"] and "200" in contours["notes"]


def test_survey_quantities_never_carry_a_price(result):
    """Law #1: the survey pack reports what the ground IS; it never prices and
    never invents a cut/fill volume (that needs a design surface — a human call)."""
    survey = [q for q in result["quantities"] if q["trade"] == "survey"]
    assert survey, "the survey pack must have fired on a terrain DXF"
    for q in survey:
        assert q["unit"] in {"ea", "m"}          # counts and a fall — no $, no m3
        assert "price" not in q and "cost" not in q


def test_pack_ignores_a_drawing_with_no_survey_data():
    """A plain plan (no POINTs, no mesh) must not trip the survey pack."""
    pack = SurveyPack()
    ctx = PackContext([], [], [], [], geometry=[
        Measure(kind="polyline", value=10, layer="FENCE")], points=[])
    assert pack.detect(ctx) is False


def test_fall_is_derived_purely_from_the_points():
    """Same arithmetic, in isolation from the file: three shots, fall = 90.0."""
    pts = [SurveyPoint(x=0, y=0, z=10.0, id="a", kind="survey"),
           SurveyPoint(x=1, y=1, z=100.0, id="b", kind="survey"),
           SurveyPoint(x=2, y=2, z=55.0, id="c", kind="survey")]
    ctx = PackContext([], [], [], [], points=pts)
    quants, _ = SurveyPack().quantify(ctx)
    fall = next(q for q in quants if q.id == "q-survey-fall")
    assert fall.qty == 90.0                      # 100.0 - 10.0
    assert set(fall.evidence) == {"a", "b"}      # lowest and highest, not the middle
    assert len(_survey_points(pts)) == 3
