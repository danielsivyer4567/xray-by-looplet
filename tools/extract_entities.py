"""
extract_entities.py — Stage 3+4 of the X-Ray by Looplet engine, run for real.

Per drawing page:
  * pull every embedded word + rect (lossless, no OCR)
  * grammar-classify: DIM / SCALE / TAG (Wxx,Dxx,WTxx) / STANDARD (AS xxxx) / NOTE
  * scale voting: title-block scale token + drawing-index cross-reference
  * chain reconciliation: band dimension tokens by row/column, test overall == sum(parts)
"""
import sys, re, json
from collections import defaultdict
import fitz

PDF = sys.argv[1]
PAGES = range(1, 14)  # drawing sheets

RE_DIM    = re.compile(r"^\d{2,3}(?:,\d{3})?$|^\d{4,6}$")          # 450 / 5,400 / 24000
RE_SCALE  = re.compile(r"^1:(\d{2,4})$")
RE_TAG    = re.compile(r"^(W|D|WT|DP|RWH?)-?\d{1,3}[A-Za-z]?$")     # W01, D04, WT02
RE_AS     = re.compile(r"^AS/?N?Z?S?\s?\d{3,5}")
RE_CHFC   = re.compile(r"^(CH|FC|DH|BH|FFL|RL|SSL|FCL)$", re.I)
RE_MINMAX = re.compile(r"^(MIN|MAX)\.?$", re.I)

doc = fitz.open(PDF)

def dimval(s):
    return int(s.replace(",", ""))

report = {}
for pno in PAGES:
    page = doc[pno - 1]
    W, H = page.rect.width, page.rect.height
    words = page.get_text("words")
    ents = defaultdict(list)
    for x0, y0, x1, y1, txt, *_ in words:
        t = txt.strip()
        if not t:
            continue
        if RE_SCALE.match(t):
            ents["SCALE"].append((t, round(x0), round(y0)))
        elif RE_DIM.match(t):
            v = dimval(t)
            if 40 <= v <= 99999:                      # plausible mm on 1:50–1:200 sheets
                ents["DIM"].append((v, x0, y0, x1, y1))
        elif RE_TAG.match(t):
            ents["TAG"].append((t, round(x0), round(y0)))
        elif RE_AS.match(t):
            ents["STD"].append(t)
        elif RE_CHFC.match(t):
            ents["HKEY"].append((t.upper(), round(x0), round(y0)))

    # --- scale: title block sits bottom-right; index page declares all ---
    tb_scales = [s for s in ents["SCALE"] if s[1] > W * 0.75 and s[2] > H * 0.80]
    all_scales = sorted({s[0] for s in ents["SCALE"]})

    # --- chain reconciliation ---
    dims = ents["DIM"]
    chains = []

    def bands(items, key_idx, tol):
        groups = defaultdict(list)
        for it in items:
            groups[round(it[key_idx] / tol)].append(it)
        return [g for g in groups.values() if len(g) >= 3]

    # horizontal chains: same y-band, sorted by x  |  vertical: same x-band, by y
    for axis, kidx, sidx in (("H", 2, 1), ("V", 1, 2)):
        for g in bands(dims, kidx, 8):
            vals = [it[0] for it in sorted(g, key=lambda it: it[sidx])]
            total, parts = max(vals), sorted(vals)[:-1]
            if len(parts) >= 2 and total == sum(parts):
                chains.append({"axis": axis, "parts": parts, "total": total, "ok": True})
            elif len(parts) >= 2 and abs(total - sum(parts)) <= max(20, total * 0.02):
                chains.append({"axis": axis, "parts": parts, "total": total,
                               "ok": False, "delta": total - sum(parts)})

    report[pno] = {
        "n_words": len(words),
        "n_dims": len(dims),
        "scales_on_sheet": all_scales,
        "titleblock_scale": [s[0] for s in tb_scales],
        "tags": sorted({t[0] for t in ents["TAG"]})[:40],
        "hkeys": sorted({t[0] for t in ents["HKEY"]}),
        "standards": sorted(set(ents["STD"]))[:15],
        "chains_ok": [c for c in chains if c["ok"]][:8],
        "chains_flag": [c for c in chains if not c["ok"]][:5],
        "dim_sample": sorted([d[0] for d in dims], reverse=True)[:15],
    }

for pno, r in report.items():
    print(f"\n===== SHEET {pno:02d} =====  words={r['n_words']} dims={r['n_dims']}")
    print(f" scales seen: {r['scales_on_sheet']}   title-block: {r['titleblock_scale']}")
    if r["tags"]:      print(f" tags: {r['tags']}")
    if r["hkeys"]:     print(f" height-keys: {r['hkeys']}")
    if r["standards"]: print(f" standards: {r['standards']}")
    if r["dim_sample"]:print(f" largest dims: {r['dim_sample']}")
    for c in r["chains_ok"]:
        print(f"  CHAIN {c['axis']} OK: {'+'.join(map(str, c['parts']))} = {c['total']}")
    for c in r["chains_flag"]:
        print(f"  CHAIN {c['axis']} FLAG: {'+'.join(map(str, c['parts']))} vs {c['total']} (d={c['delta']})")

with open("entities_report.json", "w") as f:
    json.dump(report, f, indent=1)
print("\nJSON -> entities_report.json")
