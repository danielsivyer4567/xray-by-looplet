"""chains.py — stage 5: chain-sum, cross-band and trig verification checks.

Pure geometry/arithmetic over Entity objects produced by grammar.classify.
Entities are duck-typed (attributes: id, page, type, value, raw, bbox,
confidence, source) so this module never imports grammar.

Empirical anchors (CONTEXT.md):
  * warehouse sheet 04: 29995 = 13530 + 16465 ; 3579 = 2289 + 90 + 1200 (pass)
    panel chain 2745*5 + 2742 = 16467 vs stated 16465 -> FLAG delta +2
  * shed page 1: three floorplan chains each sum to 16000 exactly
  * false positives to mask: phone "03 5452 2255" + postcode, copyright years,
    opening-schedule rows -> bottom-band mask + neighbor-text guards.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

# --- tunables (from CONTEXT.md empirical findings) -------------------------
TITLEBLOCK_BAND_FRAC = 0.22   # bottom fraction of the page masked out
BAND_TOL_PT = 6.0             # shared-baseline tolerance for banding
NEIGHBOR_RADIUS_PT = 30.0     # neighbor scan radius for false-positive guards
CHAIN_ABS_TOL = 20.0          # mm-equivalent absolute tolerance for near-miss
CHAIN_REL_TOL = 0.02          # 2% relative tolerance for near-miss
TRIG_TOL_MM = 2.0             # rise match tolerance

_STATE_RE = re.compile(r"^(VIC|NSW|QLD|SA|WA|TAS|NT|ACT)[.,]?$", re.I)
_FOUR_DIGIT_RE = re.compile(r"^\d{4}$")


@dataclass
class Check:
    id: str
    kind: str            # chain-sum|trig|cross-sheet|count
    status: str          # pass|flag
    detail: str
    delta: float | None = None
    evidence: list[str] = field(default_factory=list)  # entity ids


# --- geometry helpers -------------------------------------------------------

def _page_bounds(page_rect) -> tuple[float, float, float, float]:
    """Accept (W,H), (x0,y0,x1,y1) or a fitz.Rect-like; return x0,y0,x1,y1."""
    if hasattr(page_rect, "x0") and hasattr(page_rect, "y1"):
        return (float(page_rect.x0), float(page_rect.y0),
                float(page_rect.x1), float(page_rect.y1))
    t = tuple(page_rect)
    if len(t) == 2:
        return 0.0, 0.0, float(t[0]), float(t[1])
    if len(t) == 4:
        return float(t[0]), float(t[1]), float(t[2]), float(t[3])
    raise ValueError(f"unsupported page_rect: {page_rect!r}")


def titleblock_mask(page_rect) -> tuple:
    """Region tuple (x0, y0, x1, y1) covering the bottom 22% band of the page.

    PDF-points, origin top-left (PyMuPDF convention): the mask starts at
    78% of the page height and runs to the bottom edge, full width.
    """
    x0, y0, x1, y1 = _page_bounds(page_rect)
    height = y1 - y0
    return (x0, y1 - TITLEBLOCK_BAND_FRAC * height, x1, y1)


def _center(bbox) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _in_region(bbox, region) -> bool:
    cx, cy = _center(bbox)
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def _rect_gap(b1, b2) -> float:
    """Minimum distance between two bboxes (0 if they touch/overlap)."""
    dx = max(b1[0] - b2[2], b2[0] - b1[2], 0.0)
    dy = max(b1[1] - b2[3], b2[1] - b1[3], 0.0)
    return math.hypot(dx, dy)


def _dim_value(ent) -> float | None:
    """Numeric value of a DIM entity; falls back to parsing raw."""
    v = getattr(ent, "value", None)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    raw = str(getattr(ent, "raw", "") or "").replace(",", "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return float(raw)
    return None


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


# --- banding ----------------------------------------------------------------

def _bands(dims, axis: str, tol: float = BAND_TOL_PT, min_len: int = 3):
    """Cluster DIM entities sharing a baseline.

    axis 'H': shared y-center within tol, ordered by x0 (a horizontal
    dimension string). axis 'V': shared x-center within tol, ordered by y0
    (rotated text on a vertical dimension line).

    min_len=2 admits two-member bands: useless for in-band chain sums, but
    required for cross-stated overalls (warehouse: 29995 = 13530 + 16465,
    where 29995 sits on its own dimension line above the pair).
    """
    if not dims:
        return []
    key = (lambda e: _center(e.bbox)[1]) if axis == "H" else (lambda e: _center(e.bbox)[0])
    order = (lambda e: e.bbox[0]) if axis == "H" else (lambda e: e.bbox[1])
    items = sorted(dims, key=key)
    clusters, cur = [], [items[0]]
    for it in items[1:]:
        if key(it) - key(cur[-1]) <= tol:
            cur.append(it)
        else:
            clusters.append(cur)
            cur = [it]
    clusters.append(cur)
    return [sorted(c, key=order) for c in clusters if len(c) >= min_len]


# --- false-positive guards ----------------------------------------------------

def _guard_text_hit(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return ("P:" in t) or t.startswith("Ph") or ("©" in t) or ("copyright" in t.lower())


def _band_is_noise(band, page_entities) -> bool:
    """True when a band's neighbors mark it as phone / copyright / address
    furniture rather than a dimension chain (CONTEXT false-positive list)."""
    band_ids = {e.id for e in band}
    neighbors = [
        o for o in page_entities
        if o.id not in band_ids
        and any(_rect_gap(o.bbox, e.bbox) <= NEIGHBOR_RADIUS_PT for e in band)
    ]
    has_state = False
    for nb in neighbors:
        raw = str(getattr(nb, "raw", "") or "")
        if _guard_text_hit(raw):
            return True
        if _STATE_RE.match(raw.strip()):
            has_state = True
    if has_state:
        # state token followed by a 4-digit postcode-shaped token nearby,
        # or the band itself carries 4-digit members (postcode/phone chunks)
        for e in band:
            v = _dim_value(e)
            if v is not None and v.is_integer() and 1000 <= v <= 9999:
                return True
        for nb in neighbors:
            if _FOUR_DIGIT_RE.match(str(getattr(nb, "raw", "") or "").strip()):
                return True
    return False


# --- chain checks -------------------------------------------------------------

def find_chain_checks(entities, page_rect) -> list[Check]:
    """Band DIM entities per page, test overall == sum(parts).

    - only DIM entities OUTSIDE the title-block mask are considered
    - exact internal sum -> chain-sum pass
    - within max(20mm, 2%) -> chain-sum flag with delta = sum(parts) - stated
    - band sum matching a separately-stated overall elsewhere on the page
      -> cross-sheet pass
    """
    mask = titleblock_mask(page_rect)
    checks: list[Check] = []
    seen: set[frozenset] = set()
    n_chain = 0
    n_cross = 0

    by_page = defaultdict(list)
    for e in entities:
        by_page[getattr(e, "page", 0)].append(e)

    for page in sorted(by_page):
        page_ents = by_page[page]
        dims = [
            e for e in page_ents
            if getattr(e, "type", None) == "DIM"
            and not _in_region(e.bbox, mask)
            and _dim_value(e) is not None
        ]
        pending_cross = []

        for axis in ("H", "V"):
            for band in _bands(dims, axis, min_len=2):
                if _band_is_noise(band, page_ents):
                    continue
                key = frozenset(e.id for e in band)
                if key in seen:
                    continue
                vals = [_dim_value(e) for e in band]
                total = max(vals)
                parts = list(vals)
                parts.remove(total)          # remove one instance of the max
                psum = sum(parts)
                tol = max(CHAIN_ABS_TOL, CHAIN_REL_TOL * total)
                parts_txt = "+".join(_fmt(v) for v in parts)
                if len(parts) >= 2 and psum == total:
                    n_chain += 1
                    seen.add(key)
                    checks.append(Check(
                        id=f"chk-chain-p{page}-{n_chain}",
                        kind="chain-sum", status="pass",
                        detail=f"{parts_txt} = {_fmt(total)} ({axis} chain, page {page})",
                        delta=0.0,
                        evidence=[e.id for e in band],
                    ))
                elif len(parts) >= 2 and abs(psum - total) <= tol:
                    n_chain += 1
                    seen.add(key)
                    delta = psum - total
                    checks.append(Check(
                        id=f"chk-chain-p{page}-{n_chain}",
                        kind="chain-sum", status="flag",
                        detail=(f"{parts_txt} = {_fmt(psum)} vs stated {_fmt(total)} "
                                f"(delta {delta:+g}, {axis} chain, page {page})"),
                        delta=delta,
                        evidence=[e.id for e in band],
                    ))
                else:
                    pending_cross.append((axis, band))

        # a band of n tokens summing to an overall stated in another band
        for axis, band in pending_cross:
            band_ids = {e.id for e in band}
            bsum = sum(_dim_value(e) for e in band)
            # near-miss tier only for bands of >=3 (a 2-member near-miss is
            # far too easy to hit by chance); exact matches for any band size
            tol = max(CHAIN_ABS_TOL, CHAIN_REL_TOL * bsum) if len(band) >= 3 else 0.5
            best = None  # (absdiff, dim)
            for d in dims:
                if d.id in band_ids:
                    continue
                diff = abs(_dim_value(d) - bsum)
                if diff <= tol and (best is None or diff < best[0]):
                    best = (diff, d)
            if best is None:
                continue
            diff, overall = best
            key = frozenset(band_ids | {overall.id})
            if key in seen:
                continue
            seen.add(key)
            n_cross += 1
            parts_txt = "+".join(_fmt(_dim_value(e)) for e in band)
            if diff < 0.5:
                checks.append(Check(
                    id=f"chk-cross-p{page}-{n_cross}",
                    kind="cross-sheet", status="pass",
                    detail=(f"{parts_txt} = {_fmt(bsum)} matches overall "
                            f"{_fmt(_dim_value(overall))} "
                            f"stated separately ({axis} band, page {page})"),
                    delta=0.0,
                    evidence=[e.id for e in band] + [overall.id],
                ))
            else:
                delta = bsum - _dim_value(overall)
                checks.append(Check(
                    id=f"chk-cross-p{page}-{n_cross}",
                    kind="cross-sheet", status="flag",
                    detail=(f"{parts_txt} = {_fmt(bsum)} vs overall "
                            f"{_fmt(_dim_value(overall))} stated separately "
                            f"(delta {delta:+g}, {axis} band, page {page})"),
                    delta=delta,
                    evidence=[e.id for e in band] + [overall.id],
                ))

    return checks


# --- trig check ---------------------------------------------------------------

def trig_check(spec: dict, entities) -> Check | None:
    """rise = tan(pitch) * W/2 * 1000 (mm); pass if a DIM within +/-2mm exists.

    Shed fixture: tan(10deg) * 4.5m * 1000 = 793.4mm, and 793 is drawn on the
    elevations.
    """
    if not spec:
        return None
    W = spec.get("W")
    pitch = spec.get("pitch")
    if W is None or pitch is None:
        return None
    rise = math.tan(math.radians(float(pitch))) * (float(W) / 2.0) * 1000.0

    best = None  # (abs diff, entity, value)
    for e in entities:
        if getattr(e, "type", None) != "DIM":
            continue
        v = _dim_value(e)
        if v is None:
            continue
        d = abs(v - rise)
        if d <= TRIG_TOL_MM and (best is None or d < best[0]):
            best = (d, e, v)
    if best is None:
        return None
    _, ent, v = best
    delta = round(v - rise, 2)
    return Check(
        id=f"chk-trig-{ent.id}",
        kind="trig", status="pass",
        detail=(f"rise = tan({_fmt(float(pitch))}deg) x {_fmt(float(W))}/2 m x 1000 "
                f"= {rise:.0f} mm; drawn {_fmt(v)} matches (delta {delta:+.2f} mm)"),
        delta=delta,
        evidence=[ent.id],
    )
