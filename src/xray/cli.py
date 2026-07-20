"""cli.py — python -m xray run <plan.pdf> [--out DIR]

Writes <plan>.xray.json + <plan>.marked.pdf (default: alongside the input)
and prints a one-screen summary. Exit code 0 on success.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from xray import ENGINE_NAME, __version__
from xray import engine
from xray.markup_writer import write_marked_pdf


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="xray",
        description="X-Ray by Looplet - sees through plans. PDF in, quantities out.",
    )
    ap.add_argument("--version", action="version",
                    version=f"{ENGINE_NAME} {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="run a takeoff on a plan PDF")
    run_p.add_argument("pdf", help="path to the plan PDF")
    run_p.add_argument("--out", default=None, metavar="DIR",
                       help="output directory (default: next to the PDF)")
    return ap


def _summary(result: dict) -> str:
    checks = result["checks"]
    quants = result["quantities"]
    n_pass = sum(1 for c in checks if c["status"] == "pass")
    n_flag = len(checks) - n_pass
    lines = [
        f"{ENGINE_NAME} {__version__}",
        f"document : {result['document']['path']} "
        f"({len(result['document']['pages'])} pages)",
        f"entities : {len(result['entities'])}",
        f"checks   : {n_pass} pass, {n_flag} flag",
    ]
    cov = result.get("document", {}).get("coverage")
    if cov:
        low = cov.get("lowPages") or []
        low_txt = f"; low pages: {', '.join(map(str, low))}" if low else ""
        lines.append(
            f"coverage : {cov.get('overallRatio', 0) * 100:.0f}% of readable "
            f"text structured{low_txt}")
    lines.append(f"quantities ({len(quants)}):")
    for q in quants:
        lines.append(f"  [{q['tier']:>13}] {q['item']:<28} "
                     f"{q['qty']:>8g} {q['unit']:<3} = {q['formula']}")
    review = result.get("review") or []
    if review:
        lines.append(f"review ({len(review)}):")
        for r in review:
            lines.append(f"  - {r['ref']}: {r['reason'][:100]}")
    return "\n".join(lines)


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd != "run":  # pragma: no cover - argparse enforces this
        return 2

    pdf = Path(args.pdf)
    if not pdf.is_file():
        print(f"error: no such file: {pdf}", file=sys.stderr)
        return 1
    out_dir = Path(args.out) if args.out else pdf.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    result = engine.run(str(pdf))

    json_path = out_dir / f"{pdf.stem}.xray.json"
    marked_path = out_dir / f"{pdf.stem}.marked.pdf"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_marked_pdf(str(pdf), str(marked_path), result)

    print(_summary(result))
    print(f"wrote    : {json_path}")
    print(f"wrote    : {marked_path}")
    return 0
