"""End-to-end test of the electrical pack: engine.run on the schedule fixture,
via the pack registry + table extraction. Ground truths are the fixture's known
internally-consistent data."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import jsonschema  # noqa: E402
from xray import engine  # noqa: E402

FIX = REPO / "fixtures" / "electrical-schedule.pdf"
SCHEMA = json.loads((REPO / "schema" / "takeoff.schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def result():
    return engine.run(str(FIX))


def _q(result):
    return {x["id"]: x for x in result["quantities"]}


def _c(result):
    return {x["id"]: x for x in result["checks"]}


def test_schema_valid(result):
    jsonschema.validate(result, SCHEMA)  # VA unit must be allowed


def test_detected_as_electrical(result):
    assert any(x["trade"] == "electrical" for x in result["quantities"])
    assert _q(result)["q-elec-boards"]["qty"] == 3


def test_totals_reconciled(result):
    q = _q(result)
    assert q["q-elec-conn"]["qty"] == 26400 and q["q-elec-conn"]["unit"] == "VA"
    assert q["q-elec-conn"]["tier"] == "reconciled"
    assert q["q-elec-dem"]["qty"] == 22212 and q["q-elec-dem"]["tier"] == "reconciled"


def test_breaker_and_cable_bom(result):
    q = _q(result)
    assert q["q-elec-brk-16-1P"]["qty"] == 3
    assert q["q-elec-brk-25-3P"]["qty"] == 3
    assert q["q-elec-cable-2.5"]["qty"] == 4
    assert q["q-elec-cable-2.5"]["tier"] == "needs-human"  # metres need run lengths


def test_reconciliation_checks_pass(result):
    c = _c(result)
    assert c["chk-elec-demandmath"]["status"] == "pass"
    assert c["chk-elec-grand"]["status"] == "pass"
    for b in ("DB-1", "DB-2", "MSB"):
        assert c[f"chk-elec-board-{b}"]["status"] == "pass"


def test_phase_imbalance_flags(result):
    assert _c(result)["chk-elec-phase"]["status"] == "flag"


def test_shed_unaffected_by_electrical_pack():
    """The electrical pack must not fire on the shed (no schedule) — regression."""
    shed = engine.run(str(REPO / "fixtures" / "shed-manners-aline.pdf"))
    assert not any(x["trade"] == "electrical" for x in shed["quantities"])
    assert any(x["id"] == "qty-frames" for x in shed["quantities"])
