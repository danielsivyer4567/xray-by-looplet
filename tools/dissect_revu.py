"""
dissect_revu.py — dump everything Bluebeam Revu hides inside a PDF.

Usage: python dissect_revu.py <file.pdf> [--json out.json]

Walks every page, dumps every annotation dictionary, and flags:
  * BSI-prefixed custom keys (Bluebeam Software Inc.) anywhere in the tree
  * measurement metadata (scale, depth, area/length values)
  * Spaces, viewports, custom-column definitions
  * grouping (/RT /Group, /IRT), subjects/labels/status
  * document-level Bluebeam objects (column defs, page scales)
"""
import sys, json, argparse
from collections import defaultdict

import pikepdf
from pikepdf import Name, Dictionary, Array, String


MAX_STREAM_PREVIEW = 400


def jsonable(obj, depth=0, max_depth=8):
    """Convert a pikepdf object tree to JSON-safe structures."""
    if depth > max_depth:
        return "<max-depth>"
    try:
        if isinstance(obj, Dictionary):
            out = {}
            for k, v in obj.items():
                if str(k) in ("/Parent", "/P", "/Popup", "/Dest"):  # avoid cycles / noise
                    out[str(k)] = f"<ref {type(v).__name__}>"
                else:
                    out[str(k)] = jsonable(v, depth + 1, max_depth)
            if hasattr(obj, "read_bytes"):  # stream
                try:
                    raw = obj.read_bytes()
                    out["<stream>"] = raw[:MAX_STREAM_PREVIEW].decode("latin-1", "replace")
                    out["<stream-len>"] = len(raw)
                except Exception as e:
                    out["<stream>"] = f"<unreadable: {e}>"
            return out
        if isinstance(obj, Array):
            return [jsonable(x, depth + 1, max_depth) for x in obj]
        if isinstance(obj, Name):
            return str(obj)
        if isinstance(obj, String):
            return str(obj)
        if isinstance(obj, (int, float, bool)) or obj is None:
            return obj
        if isinstance(obj, pikepdf.Object):
            return str(obj)
        return str(obj)
    except Exception as e:
        return f"<error: {e}>"


def find_bsi_keys(node, path, hits, depth=0, seen=None):
    """Recursively locate every key containing 'BSI' or 'Bluebeam' (case-insensitive)."""
    if depth > 12:
        return
    if seen is None:
        seen = set()
    try:
        objgen = node.objgen if isinstance(node, pikepdf.Object) and node.is_indirect else None
        if objgen and objgen in seen:
            return
        if objgen:
            seen.add(objgen)
    except Exception:
        pass
    if isinstance(node, Dictionary):
        for k, v in node.items():
            ks = str(k)
            if "bsi" in ks.lower() or "bluebeam" in ks.lower():
                hits.append({"path": f"{path}{ks}", "value": jsonable(v, max_depth=4)})
            if ks not in ("/Parent", "/P", "/Popup"):
                find_bsi_keys(v, f"{path}{ks}/", hits, depth + 1, seen)
    elif isinstance(node, Array):
        for i, v in enumerate(node):
            find_bsi_keys(v, f"{path}[{i}]/", hits, depth + 1, seen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--full", action="store_true", help="dump full annot dicts, not summaries")
    args = ap.parse_args()

    pdf = pikepdf.open(args.pdf)
    report = {"file": args.pdf, "pages": [], "bsi_hits": [], "docinfo": {}, "root_keys": []}

    # Document info
    try:
        if pdf.docinfo:
            report["docinfo"] = {str(k): str(v) for k, v in pdf.docinfo.items()}
    except Exception:
        pass
    report["root_keys"] = [str(k) for k in pdf.Root.keys()]

    # Root-level BSI hunt (column defs etc. often hang off /Root)
    find_bsi_keys(pdf.Root, "/Root/", report["bsi_hits"])

    subtype_counts = defaultdict(int)

    for pno, page in enumerate(pdf.pages, 1):
        pinfo = {"page": pno, "keys": [str(k) for k in page.keys()], "annots": []}
        # page-level BSI (scales/viewports live here if anywhere)
        find_bsi_keys(page.obj, f"/Page{pno}/", report["bsi_hits"])
        annots = page.get("/Annots")
        if annots:
            for i, a in enumerate(annots):
                try:
                    subtype = str(a.get("/Subtype", "?"))
                    subtype_counts[subtype] += 1
                    entry = {
                        "idx": i,
                        "subtype": subtype,
                        "subject": str(a.get("/Subj", "")),
                        "contents": str(a.get("/Contents", ""))[:120],
                        "it": str(a.get("/IT", "")),           # intent: PolygonDimension etc.
                        "measure": jsonable(a.get("/Measure"), max_depth=5) if "/Measure" in a else None,
                        "keys": [str(k) for k in a.keys()],
                        "custom_keys": {
                            str(k): jsonable(v, max_depth=4)
                            for k, v in a.items()
                            if "bsi" in str(k).lower() or str(k) not in (
                                "/Type", "/Subtype", "/Rect", "/Contents", "/P", "/NM", "/M",
                                "/F", "/AP", "/AS", "/Border", "/C", "/IC", "/CA", "/T",
                                "/Popup", "/RC", "/CreationDate", "/Subj", "/IT", "/Measure",
                                "/Vertices", "/InkList", "/L", "/LE", "/BS", "/QuadPoints",
                                "/DA", "/Q", "/RD", "/OC", "/Open", "/Name", "/State",
                                "/StateModel", "/IRT", "/RT", "/GroupNesting",
                            )
                        },
                    }
                    if args.full:
                        entry["full"] = jsonable(a, max_depth=6)
                    pinfo["annots"].append(entry)
                except Exception as e:
                    pinfo["annots"].append({"idx": i, "error": str(e)})
        report["pages"].append(pinfo)

    report["annot_subtype_counts"] = dict(subtype_counts)

    # ---- human summary ----
    print(f"=== {args.pdf} ===")
    print(f"Producer: {report['docinfo'].get('/Producer', '?')}  Creator: {report['docinfo'].get('/Creator', '?')}")
    print(f"Pages: {len(report['pages'])}   Annots by subtype: {dict(subtype_counts)}")
    print(f"Root keys: {report['root_keys']}")
    print(f"\nBSI/Bluebeam custom keys found: {len(report['bsi_hits'])}")
    for h in report["bsi_hits"][:60]:
        val = json.dumps(h["value"], default=str)
        print(f"  {h['path']} = {val[:200]}")
    for p in report["pages"]:
        for a in p["annots"]:
            if a.get("custom_keys") or a.get("measure"):
                print(f"\n[p{p['page']} #{a['idx']}] {a['subtype']} subj='{a['subject']}' IT={a['it']}")
                if a.get("measure"):
                    print(f"    /Measure: {json.dumps(a['measure'], default=str)[:300]}")
                for k, v in (a.get("custom_keys") or {}).items():
                    print(f"    {k} = {json.dumps(v, default=str)[:200]}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, default=str)
        print(f"\nFull JSON → {args.json_out}")


if __name__ == "__main__":
    main()
