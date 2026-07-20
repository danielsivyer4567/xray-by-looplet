"""packs_electrical.py — electrical Schedule-of-Loads trade pack.

Consumes tables (from tables.extract_tables) rather than dimension geometry.
Reconciles the schedule against a board summary (if present) and produces the
BOM: breakers by rating/poles, cable by size (metres need run lengths), boards,
and total connected/demand loads (unit VA, pack-declared).
"""
from __future__ import annotations

import collections
import re

from xray.chains import Check
from xray.quantify import Quantity
from xray.packs import Pack, register, register_units

register_units("VA")

CANON = {
    "board": "board", "circuit": "circuit", "ckt": "circuit",
    "description": "description", "desc": "description",
    "connectedva": "connected", "connva": "connected",
    "connectedload": "connected", "connload": "connected", "connloadva": "connected",
    "demandfactor": "factor", "df": "factor", "demandva": "demand", "demand": "demand",
    "poles": "poles", "breakerat": "breaker", "breaker": "breaker",
    "cablemm2": "cable", "cable": "cable", "phase": "phase",
    "boarddemandsum": "boardsum", "mainbreakerat": "main", "feedermm2": "feeder",
}


def _norm(h):
    return re.sub(r"[^a-z0-9]", "", str(h).lower())


def _ck(h):
    return CANON.get(_norm(h))


def _canon(d):
    o = {}
    for k, v in d.items():
        c = _ck(k)
        if c and c not in o:
            o[c] = v
    return o


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return None


def _is_schedule(headers):
    keys = {_ck(h) for h in headers if _ck(h)}
    return (("circuit" in keys or "board" in keys) and "connected" in keys
            and "demand" in keys and ("breaker" in keys or "cable" in keys))


def _is_board_summary(headers):
    keys = {_ck(h) for h in headers if _ck(h)}
    return ("board" in keys and "connected" in keys and "demand" in keys
            and "circuit" not in keys and ("main" in keys or "feeder" in keys))


class ElectricalPack(Pack):
    name = "electrical"
    trade = "electrical"

    def detect(self, ctx):
        return any(_is_schedule(t.headers) for t in (ctx.tables or []))

    def quantify(self, ctx):
        sched = summ = None
        for t in ctx.tables or []:
            if sched is None and _is_schedule(t.headers):
                sched = t
            elif summ is None and _is_board_summary(t.headers):
                summ = t
        if sched is None:
            return [], []
        rows = [_canon(d) for d in sched.as_dicts()]
        checks, quants = [], []

        bad = 0
        for r in rows:
            cn, fa, de = _num(r.get("connected")), _num(r.get("factor")), _num(r.get("demand"))
            if None in (cn, fa, de):
                continue
            if abs(round(cn * fa, 2) - round(de, 2)) > 0.05:
                bad += 1
        checks.append(Check(
            id="chk-elec-demandmath", kind="schedule-match",
            status="pass" if bad == 0 else "flag",
            detail=(f"per-circuit demand = connected x factor: "
                    f"{'all ' + str(len(rows)) + ' correct' if bad == 0 else str(bad) + ' mismatched'}"),
            delta=float(bad) if bad else None, evidence=[]))

        byb = collections.defaultdict(list)
        for r in rows:
            byb[r.get("board", "?")].append(r)
        summ_rows = {}
        if summ:
            for d in summ.as_dicts():
                cd = _canon(d)
                if cd.get("board"):
                    summ_rows[cd["board"]] = cd
        gc = gd = 0.0
        for b, rs in byb.items():
            cs = sum(_num(r.get("connected")) or 0 for r in rs)
            ds = sum(_num(r.get("demand")) or 0 for r in rs)
            gc += cs
            gd += ds
            if b in summ_rows:
                sc, sd = _num(summ_rows[b].get("connected")), _num(summ_rows[b].get("demand"))
                ok = (sc is not None and abs(cs - sc) < 0.5) and (sd is not None and abs(ds - sd) < 0.5)
                checks.append(Check(
                    id=f"chk-elec-board-{b}", kind="cross-sheet",
                    status="pass" if ok else "flag",
                    detail=f"{b}: circuits connected {cs:.0f}/demand {ds:.2f} vs summary {sc}/{sd}",
                    delta=None if ok else round(ds - (sd or 0), 2), evidence=[]))
        if summ_rows:
            sgc = sum(_num(v.get("connected")) or 0 for v in summ_rows.values())
            sgd = sum(_num(v.get("demand")) or 0 for v in summ_rows.values())
            ok = abs(gc - sgc) < 1 and abs(gd - sgd) < 1
            checks.append(Check(
                id="chk-elec-grand", kind="cross-sheet",
                status="pass" if ok else "flag",
                detail=f"grand totals schedule {gc:.0f}/{gd:.2f} vs summary {sgc:.0f}/{sgd:.2f}",
                delta=None if ok else round(gd - sgd, 2), evidence=[]))

        ph = collections.defaultdict(float)
        for r in rows:
            d = _num(r.get("demand"))
            if r.get("phase") and d:
                ph[r["phase"]] += d
        if len(ph) >= 2:
            imb = (max(ph.values()) - min(ph.values())) / max(ph.values()) * 100
            checks.append(Check(
                id="chk-elec-phase", kind="cross-sheet",
                status="pass" if imb <= 15 else "flag",
                detail=("phase demand " + ", ".join(f"{k}={v:.0f}" for k, v in sorted(ph.items()))
                        + f" | imbalance {imb:.1f}%"),
                delta=round(imb, 1) if imb > 15 else None, evidence=[]))

        recon = all(c.status == "pass" for c in checks if not c.id.startswith("chk-elec-phase"))
        tt = "reconciled" if recon else "single-source"

        brk = collections.Counter((r.get("breaker"), r.get("poles")) for r in rows if r.get("breaker"))
        for (at, po), n in sorted(brk.items(), key=lambda k: (str(k[0][1]), str(k[0][0]))):
            quants.append(Quantity(
                id=f"q-elec-brk-{at}-{po}", trade="electrical", item=f"breaker {at}A {po}",
                qty=float(n), unit="ea", formula=f"count of {at}A {po} breakers = {n}",
                tier=tt, evidence=[], notes=""))
        cab = collections.Counter(r.get("cable") for r in rows if r.get("cable"))
        for sz, n in sorted(cab.items(), key=lambda k: _num(k[0]) or 0):
            quants.append(Quantity(
                id=f"q-elec-cable-{sz}", trade="electrical", item=f"cable {sz}mm2",
                qty=float(n), unit="ea", formula=f"{n} circuits @ {sz}mm2",
                tier="needs-human", evidence=[],
                notes="metres need run lengths from riser/floor plan"))
        quants.append(Quantity(
            id="q-elec-boards", trade="electrical", item="distribution boards",
            qty=float(len(byb)), unit="ea", formula=f"{len(byb)} boards in schedule",
            tier=tt, evidence=[], notes=""))
        quants.append(Quantity(
            id="q-elec-conn", trade="electrical", item="total connected load",
            qty=round(gc, 1), unit="VA", formula=f"sum connected across {len(rows)} circuits",
            tier=tt, evidence=[], notes=""))
        quants.append(Quantity(
            id="q-elec-dem", trade="electrical", item="total demand load",
            qty=round(gd, 1), unit="VA", formula=f"sum demand across {len(rows)} circuits",
            tier=tt, evidence=[], notes=""))
        return quants, checks


register(ElectricalPack())
