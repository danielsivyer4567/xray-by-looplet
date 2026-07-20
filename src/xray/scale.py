"""scale.py — Stage 4 of the X-Ray by Looplet engine: per-page scale voting.

Combines three evidence sources into one winning ratio:
  1. a declared scale string (drawing-index / caller-supplied), weight 3.0
  2. SCALE entities found on the page — title-block region (bottom-right band,
     as proven in tools/extract_entities.py) weighted 2.0, elsewhere 1.0
  3. paper-size inference: an ISO-A-series sheet adds a weak 1:100 prior (0.5)

mmPerPt for the winner: 1 pt = 25.4/72 mm of paper, times the ratio.
So 1:100 -> 25.4/72*100 = 35.2777... mm of real world per PDF point.

Duck-typed: entities only need .type, .raw (or .value), .bbox — no import of
grammar required, so this module stands alone while siblings are built.
"""
from __future__ import annotations

import re

MM_PER_PT = 25.4 / 72.0

RE_RATIO = re.compile(r"1\s*:\s*(\d{1,4})")

# ISO A sizes in mm (long, short)
_A_SIZES = {
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
    "A4": (297.0, 210.0),
}
_PAPER_TOL_MM = 7.0
# Weak prior: AU architectural sheets on A-series paper most commonly 1:100.
_PAPER_PRIOR_RATIO = 100

W_DECLARED = 3.0
W_TITLEBLOCK = 2.0
W_ONPAGE = 1.0
W_PAPER = 0.5

# Title-block band (empirical, tools/extract_entities.py): bottom-right corner.
TB_X_FRAC = 0.70
TB_Y_FRAC = 0.78


def _page_wh(page_rect) -> tuple[float, float]:
    """Accept (w,h), (x0,y0,x1,y1), or a fitz.Rect-like with .width/.height."""
    if hasattr(page_rect, "width") and hasattr(page_rect, "height"):
        return float(page_rect.width), float(page_rect.height)
    seq = tuple(page_rect)
    if len(seq) == 2:
        return float(seq[0]), float(seq[1])
    if len(seq) == 4:
        return float(seq[2]) - float(seq[0]), float(seq[3]) - float(seq[1])
    raise ValueError(f"unsupported page_rect: {page_rect!r}")


def infer_paper_size(width_pt: float, height_pt: float) -> str | None:
    """Return 'A0'..'A4' if the page matches an ISO A size (either orientation)."""
    long_mm = max(width_pt, height_pt) * MM_PER_PT
    short_mm = min(width_pt, height_pt) * MM_PER_PT
    for name, (lo, sh) in _A_SIZES.items():
        if abs(long_mm - lo) <= _PAPER_TOL_MM and abs(short_mm - sh) <= _PAPER_TOL_MM:
            return name
    return None


def _ratio_of(entity) -> int | None:
    for text in (getattr(entity, "raw", None), str(getattr(entity, "value", ""))):
        if not text:
            continue
        m = RE_RATIO.search(str(text))
        if m:
            return int(m.group(1))
    return None


def _in_titleblock(bbox, w: float, h: float) -> bool:
    try:
        x0, y0 = float(bbox[0]), float(bbox[1])
    except (TypeError, ValueError, IndexError):
        return False
    return x0 > w * TB_X_FRAC and y0 > h * TB_Y_FRAC


def calibrate(p0, p1, known_mm) -> dict:
    """Manual scale from two points (PDF points) + the real distance (mm)
    between them. Wins over auto-voting; confidence 1.0, verified True."""
    import math
    dist = math.hypot(float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1]))
    known = float(known_mm)
    if dist <= 0 or known <= 0:
        return {"value": None, "mmPerPt": None, "methods": [],
                "confidence": 0.0, "verified": False}
    mmpp = known / dist
    return {"value": f"1:{mmpp / MM_PER_PT:.0f}", "mmPerPt": mmpp,
            "methods": ["manual-calibration"], "confidence": 1.0, "verified": True}


def vote_scale(entities, page_rect, declared: str | None,
               calibration=None) -> dict:
    """Vote on the page scale.

    A manual `calibration` (dict with p0/p1/known_mm, or {"mmPerPt": ...}) wins
    outright. Returns {"value","mmPerPt","methods","confidence","verified"};
    `verified` is False when the winner rests only on the weak paper-size prior.
    With zero evidence returns value None, confidence 0.0.
    """
    if calibration:
        if calibration.get("mmPerPt"):
            mmpp = float(calibration["mmPerPt"])
            return {"value": f"1:{mmpp / MM_PER_PT:.0f}", "mmPerPt": mmpp,
                    "methods": ["manual-calibration"], "confidence": 1.0,
                    "verified": True}
        if all(k in calibration for k in ("p0", "p1", "known_mm")):
            return calibrate(calibration["p0"], calibration["p1"],
                             calibration["known_mm"])
    w, h = _page_wh(page_rect)
    votes: dict[int, float] = {}
    methods: dict[int, list[str]] = {}

    def _vote(ratio: int, weight: float, method: str):
        votes[ratio] = votes.get(ratio, 0.0) + weight
        methods.setdefault(ratio, [])
        if method not in methods[ratio]:
            methods[ratio].append(method)

    if declared:
        m = RE_RATIO.search(declared)
        if m:
            _vote(int(m.group(1)), W_DECLARED, "declared")

    for ent in entities or []:
        if getattr(ent, "type", None) != "SCALE":
            continue
        ratio = _ratio_of(ent)
        if ratio is None:
            continue
        if _in_titleblock(getattr(ent, "bbox", None), w, h):
            _vote(ratio, W_TITLEBLOCK, "titleblock-scale")
        else:
            _vote(ratio, W_ONPAGE, "onpage-scale")

    if infer_paper_size(w, h) is not None:
        _vote(_PAPER_PRIOR_RATIO, W_PAPER, "paper-size")

    if not votes:
        return {"value": None, "mmPerPt": None, "methods": [],
                "confidence": 0.0, "verified": False}

    winner = max(votes, key=lambda r: (votes[r], -r))
    total = sum(votes.values())
    confidence = round(min(1.0, votes[winner] / total), 3) if total else 0.0
    return {
        "value": f"1:{winner}",
        "mmPerPt": MM_PER_PT * winner,
        "methods": methods[winner],
        "confidence": confidence,
        "verified": any(m != "paper-size" for m in methods[winner]),
    }
