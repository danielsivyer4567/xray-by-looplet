"""packs_shed.py — the shed (steel portal-frame) trade pack.

Wraps the existing quantify.shed_pack and reproduces the pre-registry behaviour
exactly: compute the trig check + PORTAL RAFTER count check, then call shed_pack
with the chain checks plus those two as evidence.
"""
from __future__ import annotations

import re

from xray.chains import Check, trig_check
from xray.quantify import shed_pack
from xray.hardening import harden
from xray.packs import Pack, register

RE_FRAME_LABEL = re.compile(r"PORTAL\s+RAFTER", re.I)


def _find_spec(entities):
    for e in entities:
        if e.type == "SPEC" and isinstance(e.value, dict):
            return e.value
    return None


def _count_checks(spec, entities):
    frames = int(spec["bays"]) + 1
    hits = [e for e in entities
            if e.type == "LABEL" and RE_FRAME_LABEL.search(str(e.raw))]
    if not hits:
        return []
    n = len(hits)
    return [Check(
        id=f"chk-count-portal-rafter-p{hits[0].page}",
        kind="count",
        status="pass" if n == frames else "flag",
        detail=(f"'PORTAL RAFTER' label appears {n}x; "
                f"expected frames = bays + 1 = {frames}"),
        delta=float(n - frames),
        evidence=[e.id for e in hits],
    )]


class ShedPack(Pack):
    name = "shed"
    trade = "structural steel"

    def detect(self, ctx):
        return _find_spec(ctx.entities) is not None

    def quantify(self, ctx):
        spec = _find_spec(ctx.entities)
        if not spec:
            return [], []
        extra = []
        tc = trig_check(spec, ctx.entities)
        if tc is not None:
            extra.append(tc)
        extra.extend(_count_checks(spec, ctx.entities))
        quants = shed_pack(spec, ctx.entities, list(ctx.checks) + extra)
        spec_ent = next((e for e in ctx.entities
                         if getattr(e, "type", None) == "SPEC"), None)
        base_ev = [spec_ent.id] if spec_ent is not None else []
        quants = harden(quants, spec, base_evidence=base_ev)
        return quants, extra


register(ShedPack())
