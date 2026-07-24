"""packs_survey.py — read a site survey / terrain model.

A survey DXF is not a takeoff of parts; it is a description of the GROUND. The
numbers a builder needs from it are the ones every other trade sits on top of:

  * how many spot levels were shot (the survey's raw evidence),
  * the site's elevation range and total fall (max RL - min RL),
  * how many contours and breaklines describe the surface.

These come straight from POINT entities (spot levels) and old-style POLYLINE
entities (terrain mesh vertices, contour lines, breaklines) — the exact things
the DXF adapter now turns into `SurveyPoint`s and elevation-carrying `Measure`s.
Nothing here is invented: every figure is min/max/count over numbers read off
the file, and each quantity cites the entity ids it was computed from.

Law #1 holds: this pack never prices anything and never estimates cut/fill
volume (that needs a design surface to compare against — a human decision, not a
number the drawing states). It reports what the ground IS, and flags the rest.
"""
from __future__ import annotations

import re

from xray.quantify import Quantity
from xray.packs import Pack, register

# Layer-name hints. A contour sits at one RL (planar polyline with an elev); a
# breakline's z varies (elev is None). We classify by BOTH the layer name and the
# geometry so a mislabelled layer can't masquerade as something it isn't.
RE_CONTOUR = re.compile(r"CONTOUR", re.I)
RE_BREAKLINE = re.compile(r"BREAK.?LINE|RIDGE|TOP.?OF.?BANK|TOE", re.I)


def _survey_points(points):
    """Spot levels — POINT entities the surveyor shot in the field."""
    return [p for p in points or [] if getattr(p, "kind", "") == "survey"]


def _mesh_points(points):
    """Terrain-mesh vertices — the surface, not field shots."""
    return [p for p in points or [] if getattr(p, "kind", "") == "mesh"]


def _elevated_polys(geometry):
    """Polylines that carry an elevation (contours) vs. ones that don't."""
    contours, breaklines = [], []
    for g in geometry or []:
        if getattr(g, "kind", None) != "polyline":
            continue
        layer = getattr(g, "layer", "") or ""
        elev = getattr(g, "elev", None)
        if elev is not None and (RE_CONTOUR.search(layer) or not RE_BREAKLINE.search(layer)):
            contours.append(g)
        elif RE_BREAKLINE.search(layer) or elev is None:
            breaklines.append(g)
    return contours, breaklines


class SurveyPack(Pack):
    name = "survey"
    trade = "survey"

    def detect(self, ctx) -> bool:
        pts = getattr(ctx, "points", [])
        return bool(_survey_points(pts) or _mesh_points(pts))

    def quantify(self, ctx):
        points = getattr(ctx, "points", [])
        geometry = getattr(ctx, "geometry", [])
        quants = []

        spots = _survey_points(points)
        mesh = _mesh_points(points)

        # --- spot-level count -------------------------------------------------
        # An exact count of POINT entities; there is nothing to estimate.
        if spots:
            quants.append(Quantity(
                id="q-survey-spot-levels",
                trade="survey", item="survey spot levels", qty=float(len(spots)),
                unit="ea", tier="reconciled",
                formula=f"count of survey POINT entities = {len(spots)}",
                evidence=[p.id for p in spots if getattr(p, "id", "")],
                notes="each shot is one field-measured level (x, y, RL)"))

        # --- site fall (elevation range) -------------------------------------
        # max RL - min RL over the spot levels. This is a difference of two read
        # numbers, so it is exact and unit-free (both RLs are in drawing z). It is
        # `reconciled` because it is derived purely from measured points; the
        # evidence lists the lowest and highest shot so the figure is re-derivable.
        if len(spots) >= 2:
            lo = min(spots, key=lambda p: p.z)
            hi = max(spots, key=lambda p: p.z)
            fall = round(hi.z - lo.z, 2)
            quants.append(Quantity(
                id="q-survey-fall",
                trade="survey", item="site fall (survey points)", qty=fall,
                unit="m", tier="reconciled",
                formula=(f"max RL - min RL = {round(hi.z, 2)} - {round(lo.z, 2)} "
                         f"= {fall}"),
                evidence=[i for i in (getattr(lo, "id", ""), getattr(hi, "id", "")) if i],
                notes=(f"lowest shot RL {round(lo.z, 2)}, highest RL {round(hi.z, 2)}; "
                       "z is in the drawing's own units")))

        # --- surface described by the terrain mesh ---------------------------
        if mesh:
            quants.append(Quantity(
                id="q-survey-mesh-vertices",
                trade="survey", item="terrain mesh vertices", qty=float(len(mesh)),
                unit="ea", tier="single-source",
                formula=f"count of surface-mesh vertices = {len(mesh)}",
                evidence=[p.id for p in mesh[:1] if getattr(p, "id", "")],
                notes="vertices of the surveyed ground surface (polygon mesh)"))

        # --- contours & breaklines -------------------------------------------
        contours, breaklines = _elevated_polys(geometry)
        if contours:
            levels = sorted({round(g.elev, 3) for g in contours
                             if getattr(g, "elev", None) is not None})
            quants.append(Quantity(
                id="q-survey-contours",
                trade="survey", item="contour lines", qty=float(len(contours)),
                unit="ea", tier="single-source",
                formula=f"count of planar (single-RL) polylines = {len(contours)}",
                evidence=[g.id for g in contours if getattr(g, "id", "")],
                notes=(f"RLs present: {', '.join(str(l) for l in levels)}"
                       if levels else "each polyline sits at one RL")))
        if breaklines:
            quants.append(Quantity(
                id="q-survey-breaklines",
                trade="survey", item="breaklines", qty=float(len(breaklines)),
                unit="ea", tier="single-source",
                formula=f"count of variable-z polylines = {len(breaklines)}",
                evidence=[g.id for g in breaklines if getattr(g, "id", "")],
                notes="a breakline's z varies along its length (ridge / toe / bank)"))

        return quants, []


register(SurveyPack())
