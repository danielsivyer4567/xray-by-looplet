"""Fencing pack — the first geometry-driven trade pack.

End-to-end truths are proven against fixtures/cad/fencing-boundary.dxf, a fence
whose every number is exact by construction (see tools/make_fencing_fixture.py):
a single 48.0 lm run, 21 posts at 2.4 m centres, 1 gate. The reconciled-post case
lives there; the paths the fixture cannot show (a spacing ASSUMPTION with no posts
drawn, placed posts that disagree, an unresolved unit, non-detection) are proven
directly against the pack with hand-built context.
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

from xray.engine import run                       # noqa: E402
from xray.packs import PackContext                 # noqa: E402
from xray.packs_fencing import FencingPack, DEFAULT_POST_SPACING_M  # noqa: E402
from xray.sources.base import Measure, Symbol      # noqa: E402

FIXTURE = REPO / "fixtures" / "cad" / "fencing-boundary.dxf"


def _q(result, qid):
    return next((q for q in result["quantities"] if q["id"] == qid), None)


def _check(result, cid):
    return next((c for c in result["checks"] if c["id"] == cid), None)


# --------------------------------------------------------------- end-to-end

@pytest.fixture(scope="module")
def result():
    return run(str(FIXTURE))


def test_fence_length_is_the_drawn_run(result):
    """48000 mm run, resolved as mm, is 48.0 lineal metres — stated once by the
    drawing, so single-source (no independent dimension to reconcile against)."""
    q = _q(result, "q-fence-length")
    assert q is not None
    assert q["qty"] == 48.0
    assert q["unit"] == "lm"
    assert q["tier"] == "single-source"


def test_length_flags_that_the_fence_system_is_unspecified(result):
    """The geometry can't state paling vs Colorbond vs chainmesh, so panels/
    rails/footings are deliberately NOT invented — the note asks for the system."""
    q = _q(result, "q-fence-length")
    assert "system" in q["notes"].lower()


def test_posts_reconcile_placed_against_spacing(result):
    """21 placed POST blocks equal floor(48.0/2.4)+1 = 21, so the count is
    reconciled — two independent routes to the same number."""
    q = _q(result, "q-fence-posts")
    assert q is not None
    assert q["qty"] == 21.0
    assert q["unit"] == "ea"
    assert q["tier"] == "reconciled"

    chk = _check(result, "chk-fence-posts")
    assert chk is not None and chk["status"] == "pass"
    assert chk["delta"] in (None, 0.0)


def test_gates_counted_exactly(result):
    q = _q(result, "q-fence-gates")
    assert q is not None and q["qty"] == 1.0 and q["unit"] == "ea"


def test_reconciled_posts_do_not_reach_review(result):
    """A reconciled quantity carries no assumption, so it must not appear in the
    human-review list."""
    assert not any(r["ref"] == "q-fence-posts" for r in result["review"])


# ------------------------------------------------------ direct pack: hard paths

def _ctx(geometry=(), symbols=()):
    return PackContext(entities=[], checks=[], tables=[], pages=[],
                       symbols=list(symbols), geometry=list(geometry))


def _run(layer="FENCE", value=48.0, unit="m"):
    return Measure(kind="polyline", value=value, layer=layer, unit=unit)


def _post(i, layer="FENCE"):
    return Symbol(block_name="POST", layer=layer, x=float(i), y=0.0, id=f"post-{i}")


def test_geometry_quantities_cite_the_run_as_evidence(result):
    """The fence length is built from a drawn run, so it must cite that run's id
    — 'every number re-derives from evidence' has to hold for geometry too."""
    q = _q(result, "q-fence-length")
    assert q["evidence"], "fence length must cite the run it measured"


def test_derived_posts_formula_is_self_consistent_for_unequal_runs():
    """The stated formula must reproduce its own result, even for unequal runs —
    5 m + 7 m at 2.4 m centres = 3 + 3 = 6, and the string must say so."""
    a, b = _run(value=5.0), _run(value=7.0)
    a.id, b.id = "r1", "r2"
    quants, _ = FencingPack().quantify(_ctx(geometry=[a, b]))
    posts = next(q for q in quants if q.id == "q-fence-posts")
    assert posts.qty == 6.0
    assert posts.formula == "floor(5/2.4)+1 + floor(7/2.4)+1 = 6"
    assert posts.evidence == ["r1", "r2"]


def test_derived_posts_without_placements_are_needs_human():
    """No posts drawn: the count rests on a 2.4 m spacing ASSUMPTION, so it is
    needs-human and the assumption is stated in the notes."""
    quants, checks = FencingPack().quantify(_ctx(geometry=[_run()]))
    posts = next(q for q in quants if q.id == "q-fence-posts")
    assert posts.qty == 21.0
    assert posts.tier == "needs-human"
    assert f"{DEFAULT_POST_SPACING_M:g} m" in posts.notes
    # no reconciliation check when there is nothing placed to reconcile
    assert not any(c.id == "chk-fence-posts" for c in checks)


def test_placed_posts_that_disagree_flag_the_delta():
    """10 placed posts against a 21 estimate: not reconciled, and the mismatch
    is a flagged count check carrying the delta — never silently averaged."""
    posts_placed = [_post(i) for i in range(10)]
    quants, checks = FencingPack().quantify(
        _ctx(geometry=[_run()], symbols=posts_placed))
    posts = next(q for q in quants if q.id == "q-fence-posts")
    assert posts.qty == 10.0
    assert posts.tier == "single-source"
    chk = next(c for c in checks if c.id == "chk-fence-posts")
    assert chk.status == "flag"
    assert chk.delta == -11.0


def test_unresolved_unit_makes_length_needs_human():
    """A run whose unit never resolved can't be trusted as metres, so the length
    is needs-human rather than a fabricated number."""
    quants, _ = FencingPack().quantify(_ctx(geometry=[_run(unit="")]))
    length = next(q for q in quants if q.id == "q-fence-length")
    assert length.tier == "needs-human"


def test_does_not_detect_a_non_fence_drawing():
    """Geometry and blocks off any fence layer must not trip the pack."""
    pack = FencingPack()
    assert pack.detect(_ctx()) is False
    assert pack.detect(_ctx(geometry=[_run(layer="ROOF")])) is False
    assert pack.detect(_ctx(symbols=[_post(0, layer="STEEL")])) is False


def test_detects_from_runs_or_from_placed_symbols():
    pack = FencingPack()
    assert pack.detect(_ctx(geometry=[_run()])) is True
    assert pack.detect(_ctx(symbols=[_post(0)])) is True
