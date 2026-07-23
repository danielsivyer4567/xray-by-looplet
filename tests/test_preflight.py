"""Bad-input handling — corrupt / encrypted / empty / oversized / wrong-format
files must yield a CLEAR, typed error, never a parser crash or a silently-wrong
number; and a valid-but-fake file (a plot flattened into a DXF) must be flagged,
not ingested as confident nonsense.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from xray.preflight import check_input, InputError   # noqa: E402
from xray import engine, cli                          # noqa: E402

SHED = REPO / "fixtures" / "shed-manners-aline.pdf"
FLAT = REPO / "fixtures" / "negative" / "shed-flattened-from-pdf.dxf"


# ------------------------------------------------------------ structural guards

def test_missing_file_is_not_found(tmp_path):
    with pytest.raises(InputError) as ei:
        check_input(tmp_path / "nope.pdf")
    assert ei.value.kind == "not-found"


def test_empty_file_flags_empty(tmp_path):
    f = tmp_path / "empty.pdf"
    f.write_bytes(b"")
    with pytest.raises(InputError) as ei:
        check_input(f)
    assert ei.value.kind == "empty"


def test_wrong_format_behind_a_pdf_name_is_malformed(tmp_path):
    """A renamed non-PDF is caught by magic bytes before any parser runs."""
    f = tmp_path / "actually-an-image.pdf"
    f.write_bytes(b"\x89PNG\r\n\x1a\n and definitely not a pdf")
    with pytest.raises(InputError) as ei:
        check_input(f)
    assert ei.value.kind == "malformed"


def test_pdf_header_but_corrupt_body_is_malformed(tmp_path):
    """Passes the %PDF- magic check but pikepdf can't parse it -> malformed,
    not a pdfium crash deep in the read."""
    f = tmp_path / "corrupt.pdf"
    f.write_bytes(b"%PDF-1.4\n this is not a real pdf body")
    with pytest.raises(InputError) as ei:
        check_input(f)
    assert ei.value.kind == "malformed"


def test_unsupported_extension(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_bytes(b"hello")
    with pytest.raises(InputError) as ei:
        check_input(f)
    assert ei.value.kind == "unsupported"


def test_oversized_file_flags_too_large():
    with pytest.raises(InputError) as ei:
        check_input(SHED, max_bytes=100)
    assert ei.value.kind == "too-large"


def test_encrypted_pdf_flags_encrypted(tmp_path):
    pikepdf = pytest.importorskip("pikepdf")
    f = tmp_path / "locked.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.save(str(f), encryption=pikepdf.Encryption(owner="o", user="u"))
    with pytest.raises(InputError) as ei:
        check_input(f)
    assert ei.value.kind == "encrypted"


def test_valid_pdf_passes_and_returns_its_adapter():
    assert check_input(SHED).name == "pdf"


# ------------------------------------------------------------- engine + CLI wire

def test_engine_run_raises_inputerror_on_bad_file(tmp_path):
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"not a pdf")
    with pytest.raises(InputError):
        engine.run(str(f))


def test_cli_returns_2_on_bad_input(tmp_path, capsys):
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"not a pdf")
    rc = cli.main(["run", str(f), "--out", str(tmp_path)])
    assert rc == 2
    assert "error:" in capsys.readouterr().err


def test_cli_returns_1_on_missing_file(tmp_path, capsys):
    rc = cli.main(["run", str(tmp_path / "nope.pdf")])
    assert rc == 1


# --------------------------------------------------- provenance: the fake CAD file

def test_flattened_plot_dxf_is_flagged_not_silently_ingested():
    pytest.importorskip("ezdxf")
    r = engine.run(str(FLAT))
    prov = [c for c in r["checks"] if c["kind"] == "provenance"]
    assert len(prov) == 1 and prov[0]["status"] == "flag"
    assert "flattened plot" in prov[0]["detail"]
    # the warning must reach the human-review list, not hide in checks
    assert any(rv["ref"] == "chk-provenance" for rv in r["review"])


def test_real_cad_files_are_not_flagged():
    pytest.importorskip("ezdxf")
    for name in ("architectural_test_fixtures_v2.dxf", "fencing-boundary.dxf"):
        r = engine.run(str(REPO / "fixtures" / "cad" / name))
        assert not [c for c in r["checks"] if c["kind"] == "provenance"], name
