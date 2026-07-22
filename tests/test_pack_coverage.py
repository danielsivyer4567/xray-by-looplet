"""An empty takeoff has to explain itself.

"No trade pack recognised this drawing" and "the pack that recognised it broke"
produce the identical empty quantities list, and they mean opposite things to
whoever opens the result. A builder told nothing was found moves on; a builder
told the steel pack failed looks again. Before this, both were silence.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from xray import engine, packs  # noqa: E402
from xray.quantify import Quantity  # noqa: E402

WAREHOUSE = REPO / "fixtures" / "warehouse-design21.pdf"
SHED = REPO / "fixtures" / "shed-manners-aline.pdf"


@pytest.fixture
def registry():
    """Register throwaway packs without leaking them into other tests."""
    saved = packs.iter_packs()
    try:
        yield packs
    finally:
        packs._registry[:] = saved


def _ctx():
    return packs.PackContext(entities=[], checks=[], tables=[], pages=[])


class BrokenDetect(packs.Pack):
    name, trade = "broken-detect", "demolition"

    def detect(self, ctx):
        raise RuntimeError("detect blew up")


class BrokenQuantify(packs.Pack):
    name, trade = "broken-quantify", "plumbing"

    def detect(self, ctx):
        return True

    def quantify(self, ctx):
        raise ValueError("bad dimension table")


class Working(packs.Pack):
    name, trade = "working", "carpentry"

    def detect(self, ctx):
        return True

    def quantify(self, ctx):
        return [Quantity(id="q-ok", trade="carpentry", item="stud", qty=1.0,
                         unit="ea", formula="1", tier="reconciled", evidence=[])], []


# --- run_packs: failures become visible, not silent -----------------------------

def test_failing_quantify_becomes_a_flagged_check(registry):
    registry._registry[:] = [BrokenQuantify()]

    quantities, checks = registry.run_packs(_ctx())

    assert quantities == []
    assert len(checks) == 1
    assert checks[0].kind == "pack-error"
    assert checks[0].status == "flag"
    # The message must name the pack and carry the original error, or it is
    # just a different flavour of silence.
    assert "broken-quantify" in checks[0].detail
    assert "bad dimension table" in checks[0].detail


def test_failing_detect_becomes_a_flagged_check(registry):
    registry._registry[:] = [BrokenDetect()]

    quantities, checks = registry.run_packs(_ctx())

    assert quantities == []
    assert [c.kind for c in checks] == ["pack-error"]
    assert "detect blew up" in checks[0].detail


def test_one_broken_pack_does_not_cost_the_others_their_quantities(registry):
    """One broken trade must not take the whole takeoff down with it."""
    registry._registry[:] = [BrokenQuantify(), Working()]

    quantities, checks = registry.run_packs(_ctx())

    assert [q.id for q in quantities] == ["q-ok"]
    assert [c.kind for c in checks] == ["pack-error"]


def test_a_pack_that_does_not_apply_is_not_an_error(registry):
    class NotMine(packs.Pack):
        name, trade = "not-mine", "roofing"

        def detect(self, ctx):
            return False

    registry._registry[:] = [NotMine()]
    quantities, checks = registry.run_packs(_ctx())

    assert (quantities, checks) == ([], [])


# --- engine: the empty result says which kind of empty it is --------------------

@pytest.fixture(scope="module")
def warehouse():
    return engine.run(str(WAREHOUSE))


def test_unrecognised_drawing_says_so(warehouse):
    assert warehouse["quantities"] == []

    coverage = [c for c in warehouse["checks"] if c["kind"] == "pack-coverage"]
    assert len(coverage) == 1
    assert coverage[0]["status"] == "flag"


def test_the_explanation_names_what_x_ray_can_measure(warehouse):
    """Telling someone "nothing matched" without saying what WOULD match
    leaves them unable to judge whether that is expected."""
    detail = next(c["detail"] for c in warehouse["checks"]
                  if c["kind"] == "pack-coverage")

    for trade in sorted({p.trade for p in packs.iter_packs()}):
        assert trade in detail


def test_the_explanation_reaches_review(warehouse):
    """review[] is what a host surfaces; a check nobody reads is not an
    explanation."""
    assert any(r["ref"] == "chk-pack-coverage" for r in warehouse["review"])


def test_the_evidence_is_not_discarded_with_the_quantities(warehouse):
    """Nothing was quantified, but the drawing was still read and
    cross-checked — that work is still worth something to a human."""
    assert len(warehouse["entities"]) > 0
    assert any(c["kind"] == "cross-sheet" for c in warehouse["checks"])


def test_a_drawing_that_does_quantify_gets_no_such_check():
    shed = engine.run(str(SHED))

    assert len(shed["quantities"]) > 0
    assert not [c for c in shed["checks"] if c["kind"] == "pack-coverage"]
