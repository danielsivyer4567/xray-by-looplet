"""packs_residential.py — residential / architectural (houses, renovations).

v1 is deliberately conservative: it only quantifies what the reconciled
dimension chains actually support on a residential drawing set —

  * building envelope  -> gross floor area (m2) + external wall run (lm),
    both tiered needs-human because an envelope assumes a rectangular
    footprint (an L-shaped plan overstates), and on a renovation the
    proposed-works scope is narrower than the whole envelope;
  * construction signature -> stud (≈90) vs masonry (≈230/250) wall
    thicknesses counted straight out of the passing chains;
  * scope items -> "PROPOSED ..." labels surfaced with evidence.

What it will NOT do in v1: room-by-room areas, internal wall lengths, or
anything that needs wall-trace geometry (that is the dimension-line
associator's job). Those show up as flagged checks so the gap is visible
in review[] instead of silently missing.
"""
from __future__ import annotations

import re

from xray.chains import Check
from xray.packs import Pack, PackContext, register
from xray.quantify import Quantity

# Strong residential vocabulary. Deliberately excludes bare "RESIDENTIAL":
# commercial sets cite "AS 2870 ... RESIDENTIAL SLABS AND FOOTINGS" in their
# general notes (the warehouse fixture does), and a standards citation must
# never make a warehouse read as a house.
RE_RES = re.compile(
    r"\b(RENOVATION|DWELLING|RESIDENCE|DUPLEX|GRANNY\s*FLAT|BEDROOM|BED\s?[1-6]\b|"
    r"ENSUITE|ALFRESCO|RUMPUS|WIR)\b", re.I)
RE_RES_EXCLUDE = re.compile(r"SLAB|FOOTING|\bAS\s?\d", re.I)

RE_SCOPE = re.compile(r"^PROPOSED\s+(.{3,60})$", re.I)
# sheet titles ("PROPOSED GROUND FLOOR PLAN", "PROPOSED FLOOR AREAS") are
# drawing names, not works — keep them out of the scope list
RE_SCOPE_TITLE = re.compile(
    r"(PLANS?|DETAILS?|AREAS?|ELEVATIONS?|SECTIONS?|NOTES?|SCHEDULES?)\s*$", re.I)

# chain-check parsing (our own emitters in chains.py — format locked by tests)
RE_CHK_PAGE = re.compile(r"-p(\d+)-")
RE_CHK_AXIS = re.compile(r"\((H|V)\s+(?:band|chain)")
RE_CHK_SUM = re.compile(r"^([\d,+\s]+)=\s*([\d,]+)\s+(?:matches overall|vs stated)")

# wall-thickness census bands (mm)
STUD = (70, 110)          # 70/90 stud walls incl. plasterboard rounding
MASONRY = (220, 270)      # brick veneer / cavity / block

# envelope plausibility for a house footprint side (mm)
ENV_MIN, ENV_MAX = 6000, 30000


def _labels(entities):
    for e in entities:
        if getattr(e, "type", None) == "LABEL":
            yield e


def _has_shed_spec(entities) -> bool:
    return any(getattr(e, "type", None) == "SPEC" for e in entities)


def _residential_labels(entities):
    hits = []
    for e in _labels(entities):
        raw = str(getattr(e, "raw", ""))
        if RE_RES.search(raw) and not RE_RES_EXCLUDE.search(raw):
            hits.append(e)
    return hits


def _parse_pass_chains(checks):
    """[(page, axis, [segments], total)] from passing chain/cross checks."""
    out = []
    for c in checks:
        if getattr(c, "status", "") != "pass":
            continue
        if getattr(c, "kind", "") not in ("chain-sum", "cross-sheet"):
            continue
        m_page = RE_CHK_PAGE.search(getattr(c, "id", "") or "")
        m_axis = RE_CHK_AXIS.search(getattr(c, "detail", "") or "")
        m_sum = RE_CHK_SUM.match(getattr(c, "detail", "") or "")
        if not (m_page and m_axis and m_sum):
            continue
        segs = [int(s.replace(",", "")) for s in m_sum.group(1).split("+") if s.strip()]
        total = int(m_sum.group(2).replace(",", ""))
        out.append((int(m_page.group(1)), m_axis.group(1), segs, total, c))
    return out


class ResidentialPack(Pack):
    name = "residential"
    trade = "residential"

    def detect(self, ctx: PackContext) -> bool:
        if _has_shed_spec(ctx.entities):        # shed pack owns spec-token sets
            return False
        return len(_residential_labels(ctx.entities)) >= 1

    def quantify(self, ctx: PackContext):
        quants: list[Quantity] = []
        checks: list[Check] = []
        chains = _parse_pass_chains(ctx.checks)

        # ---- envelope from the page with the most reconciled chains ----
        by_page: dict[int, list] = {}
        for row in chains:
            by_page.setdefault(row[0], []).append(row)
        plan_page, env_l, env_w, ev_l, ev_w = None, None, None, [], []
        for page in sorted(by_page, key=lambda p: -len(by_page[p])):
            h = [r for r in by_page[page] if r[1] == "H" and ENV_MIN <= r[3] <= ENV_MAX]
            v = [r for r in by_page[page] if r[1] == "V" and ENV_MIN <= r[3] <= ENV_MAX]
            if h and v:
                bh = max(h, key=lambda r: r[3])
                bv = max(v, key=lambda r: r[3])
                plan_page, env_l, env_w = page, bh[3], bv[3]
                ev_l, ev_w = list(bh[4].evidence), list(bv[4].evidence)
                break

        if plan_page is not None:
            gfa = round(env_l * env_w / 1e6, 1)
            perim = round(2 * (env_l + env_w) / 1000, 1)
            note = ("envelope from the largest reconciled H x V chains on "
                    f"page {plan_page}; assumes a rectangular footprint — an "
                    "L-shaped plan overstates. On a renovation, confirm how "
                    "much of the envelope is actually in scope.")
            quants.append(Quantity(
                id="qty-res-gfa", trade=self.trade, item="floor area (envelope)",
                qty=gfa, unit="m2",
                formula=f"{env_l} x {env_w} mm = {gfa} m2",
                tier="needs-human", evidence=ev_l + ev_w, notes=note))
            quants.append(Quantity(
                id="qty-res-ext-wall", trade=self.trade,
                item="external wall run (envelope)", qty=perim, unit="lm",
                formula=f"2 x ({env_l} + {env_w}) mm = {perim} lm",
                tier="needs-human", evidence=ev_l + ev_w, notes=note))
        else:
            checks.append(Check(
                id="chk-res-envelope", kind="count", status="flag",
                detail=("residential drawing recognised, but no page carried "
                        "reconciled H and V dimension chains inside a plausible "
                        f"house envelope ({ENV_MIN}-{ENV_MAX} mm), so no floor "
                        "area was derived. Check the flagged chains — one "
                        "corrected digit usually unlocks the envelope.")))

        # ---- construction signature from chain segments ----
        studs = masonry = 0
        seg_ev: list[str] = []
        for _, _, segs, _, c in chains:
            for s in segs:
                if STUD[0] <= s <= STUD[1]:
                    studs += 1
                elif MASONRY[0] <= s <= MASONRY[1]:
                    masonry += 1
                else:
                    continue
                seg_ev.extend(c.evidence)
        if studs or masonry:
            checks.append(Check(
                id="chk-res-construction", kind="count", status="pass",
                detail=(f"construction signature from reconciled chains: "
                        f"{studs} stud-wall segment(s) ({STUD[0]}-{STUD[1]} mm), "
                        f"{masonry} masonry segment(s) ({MASONRY[0]}-{MASONRY[1]} mm)"),
                evidence=sorted(set(seg_ev))))
        if studs >= 3:
            checks.append(Check(
                id="chk-res-internal-walls", kind="count", status="flag",
                detail=(f"{studs} internal stud-wall crossings sit in the "
                        "reconciled chains, but internal wall lengths need "
                        "wall-trace geometry (not in this pack yet) — "
                        "quantify internal walls manually for now.")))

        # ---- scope items ----
        seen: dict[str, list] = {}
        for e in _labels(ctx.entities):
            m = RE_SCOPE.match(str(getattr(e, "raw", "")).strip())
            if m and not RE_SCOPE_TITLE.search(m.group(1)):
                seen.setdefault(m.group(1).upper(), []).append(e)
        for i, (scope, ents) in enumerate(sorted(seen.items()), 1):
            quants.append(Quantity(
                id=f"qty-res-scope-{i}", trade=self.trade,
                item=f"scope: proposed {scope.lower()}", qty=1, unit="ea",
                formula=f"'PROPOSED {scope}' labelled {len(ents)}x on the drawings",
                tier="single-source",
                evidence=[getattr(e, "id", "") for e in ents],
                notes="scope item read from the drawing labels — confirm inclusions"))

        return quants, checks


register(ResidentialPack())
