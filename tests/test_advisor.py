"""Input-quality advisor — the door verdict, across input types.

Reads only signals the engine already computes, so these run on real takeoffs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray.engine import run                    # noqa: E402
from xray.advisor import assess_input           # noqa: E402


def test_vector_pdf_is_excellent():
    a = assess_input(run(str(REPO / "fixtures" / "shed-manners-aline.pdf")))
    assert a["grade"] == "excellent" and "Vector PDF" in a["verdict"]


def test_native_cad_is_excellent():
    pytest.importorskip("ezdxf")
    a = assess_input(run(str(REPO / "fixtures" / "cad" / "structural-columns.dxf")))
    assert a["grade"] == "excellent" and "Native CAD" in a["verdict"]
    assert a["signals"]["nativeCAD"] is True


def test_svg_native_geometry_is_excellent():
    a = assess_input(run(str(REPO / "fixtures" / "svg" / "sample-plan.svg")))
    assert a["grade"] == "excellent" and a["signals"]["nativeCAD"] is True


def test_flattened_scan_is_flagged_poor():
    """A traced / vectorised scan (the flattened fake) -> poor, and the guidance
    tells the user to get the native file — the format ladder's key warning."""
    pytest.importorskip("ezdxf")
    a = assess_input(run(str(REPO / "fixtures" / "negative" / "shed-flattened-from-pdf.dxf")))
    assert a["grade"] == "poor" and "not native CAD" in a["verdict"]
    assert "native" in a["guidance"].lower()
    assert a["signals"]["provenanceFlag"] is True


def test_warehouse_is_vector_with_a_scanned_page_note():
    """Mostly-vector set with some raster doc pages -> excellent vector, but the
    guidance names the scanned pages that need OCR."""
    a = assess_input(run(str(REPO / "fixtures" / "warehouse-design21.pdf")))
    assert a["grade"] == "excellent"
    assert "OCR" in a["guidance"]
