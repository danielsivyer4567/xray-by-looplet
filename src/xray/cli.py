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
    run_p.add_argument("--report", action="store_true",
                       help="also write a deterministic HTML quote (no LLM)")
    run_p.add_argument("--ocr", action="store_true",
                       help="OCR raster/scanned pages (needs an OCR engine "
                            "installed, e.g. pytesseract + tesseract)")
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

    from xray.preflight import InputError
    try:
        result = engine.run(str(pdf), ocr=args.ocr or None)
    except InputError as e:
        # a clear, one-line reason — never a parser traceback
        print(f"error: {e.detail}", file=sys.stderr)
        return 1 if e.kind == "not-found" else 2
    except RuntimeError as e:  # e.g. --ocr but no engine installed
        print(f"error: {e}", file=sys.stderr)
        return 2

    json_path = out_dir / f"{pdf.stem}.xray.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    # The marked-up copy overlays evidence boxes on the ORIGINAL PDF pages, so it
    # only exists for a PDF source. A CAD source (DXF/SVG) has no PDF to draw on —
    # its evidence is the entity ids in the takeoff JSON — so the markup step is
    # skipped rather than crashing the whole run on a non-PDF input.
    marked_path = out_dir / f"{pdf.stem}.marked.pdf"
    is_pdf = pdf.suffix.lower() == ".pdf"
    if is_pdf:
        write_marked_pdf(str(pdf), str(marked_path), result)

    print(_summary(result))
    from xray.advisor import assess_input
    adv = assess_input(result)
    print(f"input    : [{adv['grade']}] {adv['verdict']}")
    print(f"           {adv['guidance']}")
    print(f"wrote    : {json_path}")
    if is_pdf:
        print(f"wrote    : {marked_path}")
    else:
        print(f"note     : marked-up PDF skipped ({pdf.suffix} source has no PDF "
              f"pages; evidence is the entity ids in the takeoff JSON)")

    if args.report:
        from xray.report import render_quote_html
        report_path = out_dir / f"{pdf.stem}.quote.html"
        report_path.write_text(render_quote_html(result), encoding="utf-8")
        print(f"wrote    : {report_path}")
    return 0
