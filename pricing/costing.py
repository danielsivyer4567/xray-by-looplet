"""costing.py — turn a takeoff into a priced quote, with NO language model.

The whole job is a join and a multiply: each quantity carries a unit; a price
row carries item/alias + unit + a dated price; where the item matches and the
**units agree**, amount = qty x price. That is arithmetic, so a spreadsheet — or
this module — does it deterministically. An LLM is never in the path.

The laws it keeps (roadmap P2, templates/README):
  * **Unit is the join key.** A per-metre price never multiplies a per-each
    quantity. Unit incompatibility is a flag, not a fudge.
  * **Dated + freshness-gated.** A price older than the caller's window does not
    quietly cost a job — it flags `needs-human` and the rate stays null.
  * **Provenance on every costed line** — which supplier row, which date.
  * **Unmatched / ambiguous → flag.** A quantity with no confident single price
    match is surfaced, never priced from a guess.

`as_of` is an explicit argument, never "today" — so a run is reproducible and a
freshness decision is auditable rather than clock-dependent.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path

from pricing.mapping import tokens, units_compatible
from xray.htmlutil import esc


@dataclass
class PriceRow:
    item: str
    aliases: list[str]
    unit: str
    price: float | None      # None for POA / blank — never coerced to 0
    effective_date: str      # ISO yyyy-mm-dd, "" if absent
    region: str
    supplier: str
    notes: str = ""


def load_price_list(path: str | Path) -> list[PriceRow]:
    """Read a price-list CSV (templates/price-list.template.csv shape). Extra
    columns are ignored; only item/unit are required per row."""
    rows: list[PriceRow] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            item = (r.get("item") or "").strip()
            unit = (r.get("unit") or "").strip()
            if not item or not unit:
                continue
            raw_price = (r.get("price_aud") or r.get("price") or "").strip()
            try:
                price = float(raw_price.replace(",", "")) if raw_price else None
            except ValueError:
                price = None
            aliases = [a.strip() for a in (r.get("alias") or "").split(";")
                       if a.strip()]
            rows.append(PriceRow(
                item=item, aliases=aliases, unit=unit, price=price,
                effective_date=(r.get("effective_date") or "").strip(),
                region=(r.get("region") or "").strip(),
                supplier=(r.get("supplier") or "").strip(),
                notes=(r.get("notes") or "").strip()))
    return rows


def _match_score(qty_item: str, row: PriceRow) -> float:
    """How well a price row names this quantity's item. The row's own tokens
    (item or any alias) must be fully contained in the quantity's — a price for
    'fence posts' matches 'fence posts', not merely 'fence'. Score is the
    fraction of quantity tokens the match explains, so the most specific row
    wins a tie."""
    q = tokens(qty_item)
    if not q:
        return 0.0
    best = 0.0
    for name in [row.item, *row.aliases]:
        rt = tokens(name)
        if rt and rt <= q:                       # row tokens ⊆ quantity tokens
            best = max(best, len(rt) / len(q))
    return best


def _freshness(row: PriceRow, as_of: str | None,
               freshness_days: int | None) -> str:
    """Freshness verdict when a window is in force: 'ok' | 'stale' | 'unknown'.

    'unknown' covers a missing OR unparseable date — uncertain age must flag
    `needs-human`, never quietly price (law 2). With no window set, dates are
    irrelevant and everything is 'ok'."""
    if as_of is None or freshness_days is None:
        return "ok"
    if not row.effective_date:
        return "unknown"
    try:
        age = (date.fromisoformat(as_of) - date.fromisoformat(row.effective_date)).days
    except ValueError:
        return "unknown"
    return "stale" if age > freshness_days else "ok"


@dataclass
class CostLine:
    quantity_id: str
    item: str
    unit: str
    qty: float
    status: str                     # "priced" | "needs-human"
    rate: float | None = None
    amount: float | None = None
    provenance: str = ""
    reason: str = ""                # why needs-human, when it is
    supplier: str = ""
    price_date: str = ""


def cost_takeoff(quantities, price_rows, as_of=None, freshness_days=None,
                 region=None) -> dict:
    """Cost a takeoff's quantities against a price list. Deterministic.

    quantities: the takeoff's `quantities` list (dicts or objects with
    id/item/unit/qty). price_rows: from load_price_list. Returns
    {lines, summary} — every line either priced with provenance, or flagged.
    """
    def g(q, k):
        return q.get(k) if isinstance(q, dict) else getattr(q, k, None)

    lines: list[CostLine] = []
    for q in quantities:
        qid = g(q, "id") or ""
        item = g(q, "item") or ""
        unit = (g(q, "unit") or "")
        qty = float(g(q, "qty") or 0.0)

        # region filter first — a price for the wrong region is not this job's
        eligible = [r for r in price_rows
                    if region is None or not r.region or r.region == region]
        # candidates: unit-compatible rows whose name is contained in the item
        cands = [(r, _match_score(item, r)) for r in eligible
                 if units_compatible(unit, r.unit)]
        cands = [(r, s) for r, s in cands if s > 0.0]

        # was there a name match that only failed on the unit? that is the most
        # useful flag to give — "you priced this per ea but it measures lm".
        unit_only = [r for r in eligible
                     if not units_compatible(unit, r.unit)
                     and _match_score(item, r) > 0.0]

        if not cands:
            reason = ("no price row matches this item"
                      if not unit_only else
                      f"a price for {item!r} exists but in unit "
                      f"{unit_only[0].unit!r}, which cannot fulfil {unit!r}")
            lines.append(CostLine(qid, item, unit, qty, "needs-human",
                                  reason=reason))
            continue

        cands.sort(key=lambda rs: (-rs[1], rs[0].item))
        top_score = cands[0][1]
        winners = [r for r, s in cands if s == top_score]
        if len(winners) > 1:
            lines.append(CostLine(
                qid, item, unit, qty, "needs-human",
                reason=(f"{len(winners)} price rows match equally "
                        f"({', '.join(sorted(w.item for w in winners))}) — "
                        "confirm which applies")))
            continue

        row = winners[0]
        if row.price is None:
            lines.append(CostLine(qid, item, unit, qty, "needs-human",
                                  supplier=row.supplier, price_date=row.effective_date,
                                  reason="matched row is POA / has no price"))
            continue
        fresh = _freshness(row, as_of, freshness_days)
        if fresh == "stale":
            lines.append(CostLine(
                qid, item, unit, qty, "needs-human",
                supplier=row.supplier, price_date=row.effective_date,
                reason=(f"matched price dated {row.effective_date} is older than "
                        f"the {freshness_days}-day window (as of {as_of})")))
            continue
        if fresh == "unknown":
            lines.append(CostLine(
                qid, item, unit, qty, "needs-human",
                supplier=row.supplier, price_date=row.effective_date,
                reason=(f"a {freshness_days}-day freshness window is set but the "
                        f"matched row's date ({row.effective_date or 'missing'!r}) "
                        "cannot be read — age unknown, not priced")))
            continue

        amount = round(qty * row.price, 2)
        stamp = f"{row.supplier or 'price list'}"
        if row.effective_date:
            stamp += f" dated {row.effective_date}"
        lines.append(CostLine(
            qid, item, unit, qty, "priced", rate=row.price, amount=amount,
            provenance=f"priced from {stamp}", supplier=row.supplier,
            price_date=row.effective_date))

    priced = [ln for ln in lines if ln.status == "priced"]
    flagged = [ln for ln in lines if ln.status != "priced"]
    summary = {
        "total": round(sum(ln.amount or 0.0 for ln in priced), 2),
        "priced": len(priced),
        "needsHuman": len(flagged),
        "asOf": as_of,
        "freshnessDays": freshness_days,
        "region": region,
    }
    return {"lines": [asdict(ln) for ln in lines], "summary": summary}


# --------------------------------------------------------------------- exports

def to_csv(result: dict) -> str:
    """Costed lines as CSV text — opens straight in any spreadsheet."""
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["quantity_id", "item", "unit", "qty", "rate", "amount",
                "status", "provenance_or_reason"])
    for ln in result["lines"]:
        w.writerow([ln["quantity_id"], ln["item"], ln["unit"], ln["qty"],
                    "" if ln["rate"] is None else ln["rate"],
                    "" if ln["amount"] is None else ln["amount"],
                    ln["status"], ln["provenance"] or ln["reason"]])
    w.writerow([])
    w.writerow(["", "", "", "", "", result["summary"]["total"], "TOTAL (priced)", ""])
    return buf.getvalue()


_TIER = {"priced": "#1a7f37", "needs-human": "#cf222e"}


def quote_html(result: dict, title: str = "Quote draft") -> str:
    """A presentation layer prettier than a spreadsheet: self-contained, offline,
    light/dark. The numbers are exactly the costing result — nothing recomputed."""
    rows = []
    for ln in result["lines"]:
        col = _TIER.get(ln["status"], "#57606a")
        amt = "" if ln["amount"] is None else f"${ln['amount']:,.2f}"
        rate = "" if ln["rate"] is None else f"${ln['rate']:,.2f}"
        detail = esc(ln["provenance"] or ln["reason"])
        rows.append(
            f'<tr><td>{esc(ln["item"])}</td>'
            f'<td style="text-align:right">{ln["qty"]:g}</td>'
            f'<td>{esc(ln["unit"])}</td>'
            f'<td style="text-align:right">{rate}</td>'
            f'<td style="text-align:right">{amt}</td>'
            f'<td><span style="color:{col};font-weight:600">{esc(ln["status"])}</span>'
            f'<div style="color:#8b949e;font-size:11px">{detail}</div></td></tr>')
    s = result["summary"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:24px;
  color:#1f2328;background:#fff}} h1{{font-size:20px;margin:0 0 4px}}
 .sub{{color:#57606a;margin:0 0 20px}} table{{border-collapse:collapse;width:100%}}
 th,td{{border-bottom:1px solid #eaeef2;padding:7px 10px;text-align:left;font-size:13px}}
 th{{color:#57606a;font-weight:600}} tfoot td{{font-weight:700;font-size:15px}}
 @media(prefers-color-scheme:dark){{body{{background:#0d1117;color:#e6edf3}}
  th,td{{border-color:#21262d}} .sub,th{{color:#8b949e}}}}
</style></head><body>
<h1>{esc(title)}</h1>
<p class="sub">{s['priced']} priced · {s['needsHuman']} need review · engine does the
 arithmetic, no LLM{'' if not s.get('asOf') else ' · as of ' + esc(s['asOf'])}</p>
<table><thead><tr><th>item</th><th style="text-align:right">qty</th><th>unit</th>
 <th style="text-align:right">rate</th><th style="text-align:right">amount</th>
 <th>status / provenance</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
<tfoot><tr><td colspan="4">TOTAL (priced lines only)</td>
 <td style="text-align:right">${s['total']:,.2f}</td><td></td></tr></tfoot>
</table></body></html>"""


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="pricing.costing",
        description="Cost a takeoff.json against a price-list CSV. No LLM.")
    ap.add_argument("takeoff")
    ap.add_argument("prices", help="price-list CSV (see templates/)")
    ap.add_argument("--as-of", help="ISO date for the freshness gate")
    ap.add_argument("--freshness-days", type=int)
    ap.add_argument("--region")
    ap.add_argument("--out")
    a = ap.parse_args(argv)

    takeoff = json.loads(Path(a.takeoff).read_text(encoding="utf-8"))
    rows = load_price_list(a.prices)
    result = cost_takeoff(takeoff.get("quantities", []), rows,
                          as_of=a.as_of, freshness_days=a.freshness_days,
                          region=a.region)
    out_dir = Path(a.out) if a.out else Path(a.takeoff).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(a.takeoff).name.replace(".xray.json", "").replace(".json", "")
    (out_dir / f"{stem}.quote.csv").write_text(to_csv(result), encoding="utf-8")
    (out_dir / f"{stem}.quote.html").write_text(quote_html(result), encoding="utf-8")
    (out_dir / f"{stem}.quote.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    s = result["summary"]
    print(f"{stem}: ${s['total']:,.2f} priced, {s['needsHuman']} need review "
          f"-> {stem}.quote.csv / .html / .json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
