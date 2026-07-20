"""Tests for scale calibration + the verified flag."""
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray.scale import MM_PER_PT, calibrate, vote_scale  # noqa: E402
from xray import engine  # noqa: E402

A4 = (842.0, 595.0)  # A4 landscape in points


@dataclass
class FakeEnt:
    type: str
    raw: str
    bbox: tuple
    value: str = ""


def test_calibrate_math():
    # 100 pt across = 3527.78 mm  ->  mmPerPt = 35.2778  ->  1:100
    s = calibrate([0, 0], [100, 0], MM_PER_PT * 100 * 100)
    assert abs(s["mmPerPt"] - MM_PER_PT * 100) < 1e-6
    assert s["value"] == "1:100"
    assert s["confidence"] == 1.0 and s["verified"] is True
    assert s["methods"] == ["manual-calibration"]


def test_calibrate_rejects_degenerate():
    assert calibrate([0, 0], [0, 0], 1000)["mmPerPt"] is None
    assert calibrate([0, 0], [100, 0], 0)["verified"] is False


def test_calibration_wins_in_vote():
    s = vote_scale([], A4, None, {"p0": [0, 0], "p1": [200, 0], "known_mm": 20000})
    assert s["methods"] == ["manual-calibration"]
    assert s["confidence"] == 1.0 and s["verified"] is True
    s2 = vote_scale([], A4, None, {"mmPerPt": 50.0})
    assert s2["mmPerPt"] == 50.0 and s2["verified"] is True


def test_verified_false_when_only_paper_prior():
    s = vote_scale([], A4, None)          # no scale entity -> paper prior only
    assert s["value"] == "1:100"
    assert s["methods"] == ["paper-size"]
    assert s["verified"] is False         # honest: it's a guess, prompt to calibrate


def test_verified_true_with_titleblock_scale():
    ent = FakeEnt("SCALE", "SCALE 1:100", (620.0, 480.0, 700.0, 490.0))  # bottom-right
    s = vote_scale([ent], A4, None)
    assert s["value"] == "1:100"
    assert "titleblock-scale" in s["methods"]
    assert s["verified"] is True


def test_engine_run_accepts_calibration():
    shed = REPO / "fixtures" / "shed-manners-aline.pdf"
    cal = {0: {"p0": [0, 0], "p1": [100, 0], "known_mm": 1000}}  # mmPerPt = 10
    result = engine.run(str(shed), calibrations=cal)
    sc = result["document"]["pages"][0]["scale"]
    assert sc["methods"] == ["manual-calibration"]
    assert abs(sc["mmPerPt"] - 10.0) < 1e-6 and sc["verified"] is True
