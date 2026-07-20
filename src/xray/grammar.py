"""grammar.py — Stage 3 of the X-Ray by Looplet engine.

Tokens -> typed entities. Ported and hardened from tools/extract_entities.py.

Entity types produced (see CONTEXT.md + schema/takeoff.schema.json):
  DIM     millimetre integers (commas stripped), plausibility 40..99999
  SCALE   1:NNN ratio tokens
  TAG     window/door/wall-type tags (W|D|WT|DP|PF|WD prefixes), with the
          embedded-text confusable fix: lowercase l -> 1, O/o -> 0 inside the
          numeric tail (W0l -> W01)
  STD     Australian standards refs (AS / AS/NZS nnnn[.n]), single- or two-token
  LEVEL   RL / FFL + number (single token or two adjacent tokens)
  SPEC    title-block shed spec token <L>Lx<W>Wx<H>H|<pitch>deg|<bays>bays
  LABEL   uppercase multi-word room/element labels (baseline-grouped)
  NOTEKEY CH / DH / BH / FC / MIN / MAX

Input `words` may be:
  * reassemble.Word-like objects (attrs: text,x0,y0,x1,y1,page,source), or
  * raw PyMuPDF `page.get_text("words")` tuples (x0,y0,x1,y1,text,...).
No import of the reassemble module is required (duck-typed on purpose so this
module stands alone while sibling modules are built in parallel).

Entity ids: e{page}-{seq}. Confidence: 1.0 vector text, 0.9 reassembled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Entity:
    id: str
    page: int
    type: str  # DIM|TAG|SCALE|SPEC|LABEL|LEVEL|STD|NOTEKEY
    value: object
    raw: str
    bbox: tuple[float, float, float, float]
    confidence: float
    source: str  # "text" | "reassembled" | "ocr"


# ---------------------------------------------------------------- regexes

# 450 / 5,400 / 16,465 / 24000  (commas stripped before plausibility check)
RE_DIM = re.compile(r"^\d{1,3}(?:,\d{3})+$|^\d{2,6}$")
DIM_MIN, DIM_MAX = 40, 99999

RE_SCALE = re.compile(r"^1\s*:\s*(\d{1,4})$")

# Tag: prefix + optional hyphen + numeric tail (confusables allowed) + optional
# single alpha suffix. Tail must contain at least one real digit so words like
# DOOR / Do never classify as tags. Longest prefixes first.
RE_TAG = re.compile(r"^(WT|WD|DP|PF|RWH?|W|D)-?([0-9lO]{1,3})([A-HJ-KM-NP-Za-hj-km-np-z]?)$")

# Standards: single token "AS1684.2" / "AS/NZS4600", or prefix token "AS"|"AS/NZS"
RE_STD_ONE = re.compile(r"^AS(?:/NZS)?\s?(\d{3,5}(?:\.\d+)?)$", re.I)
RE_STD_PREFIX = re.compile(r"^AS(?:/NZS)?$", re.I)
RE_STD_NUM = re.compile(r"^\d{3,5}(?:\.\d+)?$")

# Levels: "RL12.500" single token, or "RL" + "12.500" pair
RE_LEVEL_ONE = re.compile(r"^(RL|FFL)\.?\s?(-?\d+(?:[.,]\d+)?)$", re.I)
RE_LEVEL_PREFIX = re.compile(r"^(RL|FFL)\.?$", re.I)
RE_LEVEL_NUM = re.compile(r"^-?\d+(?:[.,]\d+)?$")

RE_NOTEKEY = re.compile(r"^(CH|DH|BH|FC|MIN|MAX)\.?$", re.I)

# Title-block spec token, e.g. "16Lx9Wx4.2H|10°|4bays" (may be embedded inside
# a longer token like "Shed.16Lx9Wx4.2H|10°|4bays"). Degree sign may arrive as
# ° (\xb0), º (\xba), or a literal letter o/O.
RE_SPEC = re.compile(
    r"(\d+(?:\.\d+)?)\s*L\s*x\s*"
    r"(\d+(?:\.\d+)?)\s*W\s*x\s*"
    r"(\d+(?:\.\d+)?)\s*H\s*\|\s*"
    r"(\d+(?:\.\d+)?)\s*[°ºo]\s*\|\s*"
    r"(\d+)\s*bays",
    re.I,
)

# Candidate word for a LABEL group: >=2 chars, all-caps letters (&, /, - allowed)
RE_LABELWORD = re.compile(r"^[A-Z][A-Z&/\-\.']{1,}$")


# ---------------------------------------------------------------- helpers


class _Tok:
    __slots__ = ("text", "x0", "y0", "x1", "y1", "page", "source", "used")

    def __init__(self, text, x0, y0, x1, y1, page, source):
        self.text = text
        self.x0 = float(x0)
        self.y0 = float(y0)
        self.x1 = float(x1)
        self.y1 = float(y1)
        self.page = int(page)
        self.source = source
        self.used = False


def _coerce(w) -> _Tok | None:
    """Accept Word-like objects or raw fitz word tuples."""
    if hasattr(w, "text"):
        text = (w.text or "").strip()
        if not text:
            return None
        return _Tok(text, w.x0, w.y0, w.x1, w.y1,
                    getattr(w, "page", 0), getattr(w, "source", "text") or "text")
    # fitz tuple: (x0, y0, x1, y1, "text", block, line, word)
    seq = tuple(w)
    text = str(seq[4]).strip()
    if not text:
        return None
    return _Tok(text, seq[0], seq[1], seq[2], seq[3], 0, "text")


def _conf(source: str) -> float:
    return 0.9 if source == "reassembled" else 1.0


def _same_baseline(a: _Tok, b: _Tok, tol: float = 3.0) -> bool:
    return abs(a.y1 - b.y1) <= tol or abs((a.y0 + a.y1) - (b.y0 + b.y1)) / 2.0 <= tol


def _gap(a: _Tok, b: _Tok) -> float:
    return b.x0 - a.x1


def _merge_bbox(toks: list[_Tok]) -> tuple[float, float, float, float]:
    return (min(t.x0 for t in toks), min(t.y0 for t in toks),
            max(t.x1 for t in toks), max(t.y1 for t in toks))


def normalize_tag(text: str) -> str | None:
    """W0l -> W01. Returns the normalized tag string, or None if not a tag.

    Confusable mapping (embedded-CAD-text quirk, see CONTEXT.md): inside the
    numeric tail only, lowercase l -> 1 and O/o -> 0. The tail must contain at
    least one true digit, so purely alphabetic words never become tags.
    """
    m = RE_TAG.match(text.strip())
    if not m:
        return None
    prefix, tail, suffix = m.group(1), m.group(2), m.group(3)
    if not any(c.isdigit() for c in tail):
        return None
    tail = tail.replace("l", "1").replace("O", "0").replace("o", "0")
    return prefix.upper() + tail + suffix.upper()


def parse_spec_token(text: str) -> dict | None:
    """Parse a title-block shed spec token.

    "16Lx9Wx4.2H|10°|4bays" -> {"L":16.0,"W":9.0,"eave":4.2,"pitch":10.0,"bays":4}
    Degree sign may be ° / º / o. The pattern may be embedded in a longer token.
    """
    m = RE_SPEC.search(text)
    if not m:
        return None
    return {
        "L": float(m.group(1)),
        "W": float(m.group(2)),
        "eave": float(m.group(3)),
        "pitch": float(m.group(4)),
        "bays": int(m.group(5)),
    }


# ---------------------------------------------------------------- classify


def classify(words, page_rect) -> list[Entity]:
    """Grammar-classify a page's words into typed entities.

    `page_rect` is (width_pt, height_pt) — kept in the signature for parity
    with the pipeline (title-block-relative logic lives in scale/chains).
    """
    toks = [t for t in (_coerce(w) for w in words) if t is not None]
    pending: list[tuple[int, dict]] = []  # (order_key = first token index, kwargs)

    # ---- pass 1: two-token entities (STD "AS/NZS 4600", LEVEL "RL 12.500")
    for i, t in enumerate(toks):
        if t.used:
            continue
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if nxt is not None and not nxt.used and _same_baseline(t, nxt) \
                and 0 <= _gap(t, nxt) <= 4.0 * max(t.y1 - t.y0, 1.0):
            if RE_STD_PREFIX.match(t.text) and RE_STD_NUM.match(nxt.text):
                pair = [t, nxt]
                raw = f"{t.text} {nxt.text}"
                pending.append((i, dict(
                    type="STD", value=raw.upper().replace(" ", " "),
                    raw=raw, bbox=_merge_bbox(pair), page=t.page,
                    confidence=min(_conf(t.source), _conf(nxt.source)),
                    source="reassembled" if "reassembled" in (t.source, nxt.source) else t.source)))
                t.used = nxt.used = True
                continue
            lp = RE_LEVEL_PREFIX.match(t.text)
            if lp and RE_LEVEL_NUM.match(nxt.text):
                pair = [t, nxt]
                raw = f"{t.text} {nxt.text}"
                pending.append((i, dict(
                    type="LEVEL",
                    value={"kind": lp.group(1).upper(),
                           "value": float(nxt.text.replace(",", ""))},
                    raw=raw, bbox=_merge_bbox(pair), page=t.page,
                    confidence=min(_conf(t.source), _conf(nxt.source)),
                    source="reassembled" if "reassembled" in (t.source, nxt.source) else t.source)))
                t.used = nxt.used = True
                continue

    # ---- pass 2: single-token entities
    for i, t in enumerate(toks):
        if t.used:
            continue
        text = t.text
        base = dict(raw=text, bbox=(t.x0, t.y0, t.x1, t.y1), page=t.page,
                    confidence=_conf(t.source), source=t.source)

        spec = parse_spec_token(text)
        if spec is not None:
            pending.append((i, dict(type="SPEC", value=spec, **base)))
            t.used = True
            continue

        m = RE_SCALE.match(text)
        if m:
            pending.append((i, dict(type="SCALE", value=f"1:{int(m.group(1))}", **base)))
            t.used = True
            continue

        if RE_DIM.match(text):
            v = int(text.replace(",", ""))
            if DIM_MIN <= v <= DIM_MAX:
                pending.append((i, dict(type="DIM", value=v, **base)))
                t.used = True
                continue
            # implausible number: fall through (may still be part of a label? no) — skip
            t.used = True
            continue

        tag = normalize_tag(text)
        if tag is not None:
            pending.append((i, dict(type="TAG", value=tag, **base)))
            t.used = True
            continue

        m = RE_STD_ONE.match(text)
        if m:
            pending.append((i, dict(type="STD", value=text.upper(), **base)))
            t.used = True
            continue

        m = RE_LEVEL_ONE.match(text)
        if m:
            pending.append((i, dict(
                type="LEVEL",
                value={"kind": m.group(1).upper(),
                       "value": float(m.group(2).replace(",", ""))},
                **base)))
            t.used = True
            continue

        m = RE_NOTEKEY.match(text)
        if m:
            pending.append((i, dict(type="NOTEKEY", value=m.group(1).upper(), **base)))
            t.used = True
            continue

    # ---- pass 3: LABEL grouping of leftover uppercase words (multi-word only).
    # Handles both horizontal text (shared baseline, small x-gaps) and rotated
    # vertical text (shared x-column, small y-gaps) — e.g. the shed fixture's
    # "PORTAL RAFTER OVER" runs up the rafter lines as 90-degree text.
    leftovers = [(i, t) for i, t in enumerate(toks)
                 if not t.used and RE_LABELWORD.match(t.text)]

    def _is_vertical(t: _Tok) -> bool:
        w, h = t.x1 - t.x0, t.y1 - t.y0
        return len(t.text) >= 2 and h > 1.5 * w

    def _flush(g):
        if len(g) < 2:
            return
        # join in original word order (fitz emits reading order)
        g = sorted(g, key=lambda it: it[0])
        gtoks = [t for _, t in g]
        raw = " ".join(t.text for t in gtoks)
        pending.append((g[0][0], dict(
            type="LABEL", value=raw, raw=raw, bbox=_merge_bbox(gtoks),
            page=gtoks[0].page,
            confidence=min(_conf(t.source) for t in gtoks),
            source="reassembled" if any(t.source == "reassembled" for t in gtoks)
                   else gtoks[0].source)))

    horiz = [it for it in leftovers if not _is_vertical(it[1])]
    vert = [it for it in leftovers if _is_vertical(it[1])]

    # horizontal: band by baseline, chain on small x-gaps
    horiz.sort(key=lambda it: (round((it[1].y0 + it[1].y1) / 2.0 / 4.0), it[1].x0))
    group: list[tuple[int, _Tok]] = []
    for item in horiz:
        _, t = item
        if group:
            prev = group[-1][1]
            h = max(prev.y1 - prev.y0, 1.0)
            if _same_baseline(prev, t) and 0 <= _gap(prev, t) <= 1.8 * h:
                group.append(item)
                continue
            _flush(group)
        group = [item]
    _flush(group)

    # vertical: band by x-centre column, chain on small y-gaps
    vert.sort(key=lambda it: (round((it[1].x0 + it[1].x1) / 2.0 / 4.0), it[1].y0))
    group = []
    for item in vert:
        _, t = item
        if group:
            prev = group[-1][1]
            cw = max(prev.x1 - prev.x0, 1.0)  # char size for rotated text
            same_col = abs((prev.x0 + prev.x1) - (t.x0 + t.x1)) / 2.0 <= 3.0
            if same_col and 0 <= t.y0 - prev.y1 <= 1.8 * cw:
                group.append(item)
                continue
            _flush(group)
        group = [item]
    _flush(group)

    # ---- assign ids in document order
    pending.sort(key=lambda p: p[0])
    entities: list[Entity] = []
    seq_by_page: dict[int, int] = {}
    for _, kw in pending:
        page = kw.pop("page")
        seq = seq_by_page.get(page, 0)
        seq_by_page[page] = seq + 1
        entities.append(Entity(id=f"e{page}-{seq}", page=page, **kw))
    return entities
