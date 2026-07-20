"""report.py — deterministic formatted quote from a takeoff result. NO LLM.

Renders the dict that ``engine.run()`` returns into a self-contained HTML quote
using pure string templating. **Nothing here computes or invents a number** —
every quantity, unit, formula, tier, and coverage figure is copied verbatim out
of the structured result. That is the whole point: the formatted quote is
exactly as auditable as the JSON it came from, because it *is* the JSON with a
layout. No interpreter sits between the engine and the page.

Public API:
    render_quote_html(result: dict) -> str        # a complete HTML document
    quote_rows(result: dict) -> list[dict]        # the rows, if you want CSV/xlsx instead

Pure-Python, standard library only (``html.escape``). Deterministic: the same
result dict always renders byte-identical output.
"""
from __future__ import annotations

from html import escape

TIER_LABEL = {
    "reconciled": ("Reconciled", "reconciled"),
    "single-source": ("Single source", "single-source"),
    "needs-human": ("Needs review", "needs-human"),
}


def quote_rows(result: dict) -> list:
    """One dict per quote line, fields copied verbatim from the result."""
    rows = []
    for q in result.get("quantities", []) or []:
        rows.append({
            "id": q.get("id", ""),
            "trade": q.get("trade", ""),
            "item": q.get("item", ""),
            "qty": q.get("qty", ""),
            "unit": q.get("unit", ""),
            "formula": q.get("formula", ""),
            "tier": q.get("tier", ""),
            "evidence": list(q.get("evidence", []) or []),
            "notes": q.get("notes", ""),
        })
    return rows


def _fmt_qty(v) -> str:
    """Render a quantity number without inventing precision it doesn't have."""
    if isinstance(v, (int, float)):
        # strip a trailing .0 but keep genuine decimals; never round the value
        return f"{v:g}"
    return escape(str(v))


def _tier_badge(tier: str) -> str:
    label, cls = TIER_LABEL.get(tier, (tier or "—", "unknown"))
    return f'<span class="tier tier-{escape(cls)}">{escape(label)}</span>'


def _rows_html(result: dict) -> str:
    out = []
    for r in quote_rows(result):
        ev = ", ".join(escape(e) for e in r["evidence"]) or "—"
        note = f'<div class="note">{escape(r["notes"])}</div>' if r["notes"] else ""
        out.append(
            "<tr>"
            f'<td>{escape(r["trade"])}</td>'
            f'<td class="item">{escape(r["item"])}{note}</td>'
            f'<td class="num">{_fmt_qty(r["qty"])}</td>'
            f'<td>{escape(r["unit"])}</td>'
            f'<td class="basis"><code>{escape(r["formula"])}</code></td>'
            f'<td>{_tier_badge(r["tier"])}</td>'
            f'<td class="ev">{ev}</td>'
            "</tr>"
        )
    return "\n".join(out)


def _coverage_line(result: dict) -> str:
    cov = (result.get("document", {}) or {}).get("coverage") or {}
    if not cov:
        return ""
    pct = round((cov.get("overallRatio") or 0) * 100)
    low = cov.get("lowPages") or []
    low_txt = (f" · low-coverage pages: {', '.join(map(str, low))}"
               if low else " · no low-coverage pages")
    return (f'<p class="coverage">Coverage: <strong>{pct}%</strong> of readable '
            f'text turned into structured output{escape(low_txt)}.</p>')


def _review_html(result: dict) -> str:
    review = result.get("review", []) or []
    if not review:
        return '<p class="clean">No items flagged for review.</p>'
    items = "\n".join(
        f'<li><code>{escape(str(r.get("ref", "")))}</code> — '
        f'{escape(str(r.get("reason", "")))}</li>'
        for r in review
    )
    return (f'<h2>Flagged for review ({len(review)})</h2>\n'
            f'<ul class="review">{items}</ul>')


def render_quote_html(result: dict) -> str:
    """A complete, self-contained HTML quote document. Deterministic. No LLM."""
    engine = result.get("engine", {}) or {}
    doc = result.get("document", {}) or {}
    name = escape(str(engine.get("name", "xray-by-looplet")))
    version = escape(str(engine.get("version", "")))
    path = escape(str(doc.get("path", "")))
    n_pages = len(doc.get("pages", []) or [])
    rows = _rows_html(result)
    coverage = _coverage_line(result)
    review = _review_html(result)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Draft takeoff quote — {path}</title>
<style>
  :root {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; color: #1a1a1a; }}
  body {{ max-width: 960px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 .25rem; }}
  .meta {{ color: #555; font-size: .9rem; margin: 0 0 1rem; }}
  .coverage {{ background: #f4f6f8; border-left: 3px solid #2d6cdf; padding: .5rem .75rem; font-size: .9rem; }}
  .provenance {{ font-size: .82rem; color: #666; border-top: 1px solid #e2e2e2; margin-top: 2rem; padding-top: .75rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .9rem; margin: 1rem 0; }}
  th, td {{ text-align: left; padding: .45rem .55rem; border-bottom: 1px solid #ececec; vertical-align: top; }}
  th {{ background: #fafafa; font-size: .78rem; text-transform: uppercase; letter-spacing: .03em; color: #666; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }}
  td.basis code {{ font-size: .82rem; color: #333; }}
  td.ev {{ font-size: .78rem; color: #777; font-family: ui-monospace, monospace; }}
  .item {{ font-weight: 500; }}
  .note {{ font-weight: 400; font-size: .8rem; color: #c0392b; margin-top: .2rem; }}
  .tier {{ color: #fff; font-size: .72rem; padding: .12rem .45rem; border-radius: 3px; white-space: nowrap; }}
  .tier-reconciled {{ background: #0a7d33; }}
  .tier-single-source {{ background: #b5820a; }}
  .tier-needs-human {{ background: #c0392b; }}
  .tier-unknown {{ background: #555; }}
  ul.review li {{ margin: .3rem 0; }}
  .clean {{ color: #0a7d33; }}
  code {{ font-family: ui-monospace, SFMono-Regular, monospace; }}
</style>
</head>
<body>
  <h1>Draft takeoff quote</h1>
  <p class="meta">{path} · {n_pages} page(s) · generated by {name} {version}</p>
  {coverage}
  <table>
    <thead>
      <tr><th>Trade</th><th>Item</th><th>Qty</th><th>Unit</th><th>Basis</th><th>Confidence</th><th>Evidence</th></tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>
  {review}
  <p class="provenance">
    Every figure above is produced by the {name} engine (deterministic Python)
    and copied verbatim into this document — no language model reads, computes,
    or phrases any number here. Each line carries the formula it was derived from
    and the evidence IDs that prove it; the full machine-readable takeoff is the
    engine's <code>takeoff.json</code> and is embedded in the marked PDF. Re-run
    the same plan through the same engine version to reproduce these figures
    byte-for-byte.
  </p>
</body>
</html>
"""
