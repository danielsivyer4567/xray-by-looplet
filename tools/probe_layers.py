"""Probe each page: vector text? drawings? images? Render sample pages to PNG."""
import sys, json, re
import fitz  # pymupdf

PDF = sys.argv[1]
RENDER = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else []

doc = fitz.open(PDF)
print(f"pages={len(doc)}  metadata={json.dumps(doc.metadata, default=str)[:400]}")

DIM = re.compile(r"^\d{1,3}(?:[ ,]\d{3})+$|^\d{2,6}$")  # metric mm dimension candidates

rows = []
for i, page in enumerate(doc):
    words = page.get_text("words")  # x0,y0,x1,y1,word,block,line,word_no
    n_words = len(words)
    n_dims = sum(1 for w in words if DIM.match(w[4]))
    drawings = page.get_drawings()
    n_lines = sum(1 for d in drawings for it in d["items"] if it[0] == "l")
    n_imgs = len(page.get_images(full=True))
    kind = "VECTOR" if n_words > 30 else ("RASTER" if n_imgs > 0 and n_words <= 30 else "SPARSE")
    rows.append((i + 1, kind, n_words, n_dims, n_lines, n_imgs))

# summary
from collections import Counter
kinds = Counter(r[1] for r in rows)
print("page kinds:", dict(kinds))
print(f"{'pg':>3} {'kind':7} {'words':>6} {'dims':>5} {'lines':>6} {'imgs':>4}")
for r in rows:
    print(f"{r[0]:>3} {r[1]:7} {r[2]:>6} {r[3]:>5} {r[4]:>6} {r[5]:>4}")

for pno in RENDER:
    page = doc[pno - 1]
    pix = page.get_pixmap(dpi=110)
    out = f"page_{pno:03d}.png"
    pix.save(out)
    print(f"rendered {out} ({pix.width}x{pix.height})")
