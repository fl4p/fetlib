"""
Extract the gate-charge curve from a located chart and find the Miller
plateau voltage.

The plateau is a flat-ish horizontal stretch of the V_GS(Q_G) curve. We
pick it out of the page's vector drawings (pymupdf ``get_drawings``):

  1. take every stroked path whose bounding rect intersects the chart bbox
  2. break each path into its underlying line segments
  3. discard segments belonging to the chart border, ticks, gridlines (long
     near-axis-aligned strokes that span most of the plot width/height)
  4. among the remaining segments, find the *longest horizontal stretch*
     (small |dy| over a meaningful dx) — that's the Miller plateau
  5. map its y coordinate to V via the y-tick calibration on the chart
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pymupdf

from viz.chart_finder import ChartLocation


@dataclass
class Segment:
    """A 2-point line segment in PDF coordinates."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def dx(self) -> float:
        return self.x1 - self.x0

    @property
    def dy(self) -> float:
        return self.y1 - self.y0

    @property
    def length(self) -> float:
        return math.hypot(self.dx, self.dy)

    @property
    def slope(self) -> float:
        if abs(self.dx) < 1e-9:
            return math.inf
        return self.dy / self.dx

    @property
    def cy(self) -> float:
        return 0.5 * (self.y0 + self.y1)


@dataclass
class PlateauHit:
    """A candidate Miller-plateau segment, including the converted voltage."""
    segment: Segment
    y_pdf: float
    v_pl: float
    score: float
    rel_position: float  # 0.0 (top of plot) → 1.0 (bottom of plot)


# ---------- vector drawing helpers ----------


def _segments_from_drawing(d: dict) -> List[Segment]:
    """Convert a pymupdf drawing dict into a flat list of line segments."""
    segs: List[Segment] = []
    last: Optional[Tuple[float, float]] = None
    for it in d['items']:
        op = it[0]
        if op == 'l':
            p0, p1 = it[1], it[2]
            segs.append(Segment(p0.x, p0.y, p1.x, p1.y))
            last = (p1.x, p1.y)
        elif op == 'c':
            # cubic bezier: approximate with start→end
            p0 = it[1]
            p3 = it[4]
            segs.append(Segment(p0.x, p0.y, p3.x, p3.y))
            last = (p3.x, p3.y)
        elif op == 're':
            r = it[1]
            segs.append(Segment(r.x0, r.y0, r.x1, r.y0))
            segs.append(Segment(r.x1, r.y0, r.x1, r.y1))
            segs.append(Segment(r.x1, r.y1, r.x0, r.y1))
            segs.append(Segment(r.x0, r.y1, r.x0, r.y0))
            last = None
        # 'm' / move-to and others don't produce visible strokes
    return segs


def _segments_from_drawing_filtered(d: dict) -> List[Segment]:
    """Like ``_segments_from_drawing`` but discards drawings that look
    like legend rectangles or other chart annotations.

    A rectangle drawing — either a single ``re`` op or four axis-aligned
    line segments forming a closed quadrilateral — contributes zero
    segments. The Miller plateau lives in a stroked path with at least one
    oblique stroke.
    """
    items = d['items']
    # Single rect op is always an annotation, never the curve.
    if len(items) == 1 and items[0][0] == 're':
        return []
    raw = _segments_from_drawing(d)
    # Closed 4-segment quadrilaterals: same.
    if len(raw) == 4:
        h = [s for s in raw if abs(s.dy) < 1.5]
        v = [s for s in raw if abs(s.dx) < 1.5]
        if len(h) == 2 and len(v) == 2:
            return []
    return raw


def _drawings_in_bbox(page: pymupdf.Page, bbox: pymupdf.Rect) -> List[dict]:
    out = []
    for d in page.get_drawings():
        r = d['rect']
        # accept drawings entirely contained in the chart bbox plus a small
        # tolerance for stroke width
        if bbox.x0 - 2 <= r.x0 and r.x1 <= bbox.x1 + 2 \
                and bbox.y0 - 2 <= r.y0 and r.y1 <= bbox.y1 + 2:
            out.append(d)
    return out


def _is_chart_chrome(seg: Segment, chart: ChartLocation,
                     axis_tol: float = 2.5,
                     tick_tol: float = 12.0) -> bool:
    """True if ``seg`` looks like axis / border / gridline / tick mark."""
    bx0, by0, bx1, by1 = chart.bbox.x0, chart.bbox.y0, chart.bbox.x1, chart.bbox.y1
    width = bx1 - bx0
    height = by1 - by0
    if width <= 0 or height <= 0:
        return True

    # 1. very short — likely a tick mark
    if seg.length < min(width, height) * 0.02:
        return True

    # 2. exactly along the chart border (top / bottom / left / right)
    if abs(seg.y0 - seg.y1) < axis_tol:
        if abs(seg.cy - by0) < axis_tol or abs(seg.cy - by1) < axis_tol:
            return True
    if abs(seg.x0 - seg.x1) < axis_tol:
        cx = 0.5 * (seg.x0 + seg.x1)
        if abs(cx - bx0) < axis_tol or abs(cx - bx1) < axis_tol:
            return True

    # 3. horizontal segment that spans most of the chart width — gridline
    if abs(seg.dy) < axis_tol and abs(seg.dx) > 0.8 * width:
        return True
    # 4. vertical segment that spans most of the chart height — gridline
    if abs(seg.dx) < axis_tol and abs(seg.dy) > 0.8 * height:
        return True

    # 5. short horizontal segment glued to the left/right axis — y-axis
    # tick mark (e.g. an 8-pt stub on the chart's left edge)
    if abs(seg.dy) < axis_tol and abs(seg.dx) < tick_tol:
        left_x = min(seg.x0, seg.x1)
        right_x = max(seg.x0, seg.x1)
        if abs(left_x - bx0) < tick_tol or abs(right_x - bx1) < tick_tol:
            return True
    # 6. short vertical segment glued to the bottom/top axis — x-tick mark
    if abs(seg.dx) < axis_tol and abs(seg.dy) < tick_tol:
        top_y = min(seg.y0, seg.y1)
        bot_y = max(seg.y0, seg.y1)
        if abs(bot_y - by1) < tick_tol or abs(top_y - by0) < tick_tol:
            return True

    return False


# ---------- plateau scoring ----------


def _segment_curve_score(seg: Segment, chart: ChartLocation) -> float:
    """How "plateau-like" is this segment?

    A perfect plateau: horizontal (dy ≈ 0), reasonably long (≥ ~10% of
    chart width).
    """
    bx0, by0, bx1, by1 = chart.bbox.x0, chart.bbox.y0, chart.bbox.x1, chart.bbox.y1
    width = bx1 - bx0
    height = by1 - by0
    if width <= 0 or height <= 0:
        return 0.0

    rel_dx = abs(seg.dx) / width
    rel_dy = abs(seg.dy) / height
    if rel_dx < 0.05:
        return 0.0
    if rel_dy > 0.05:
        return 0.0
    # bias: prefer flatter and longer segments
    flatness = 1.0 / (rel_dy + 0.005)
    return rel_dx * flatness


# ---------- y → V calibration ----------


def _calibrate_y(chart: ChartLocation) -> Tuple[float, float]:
    """Linear fit y_pdf → V_GS.

    Returns (a, b) such that V = a * y_pdf + b.
    """
    pts = chart.y_ticks
    if len(pts) < 2:
        raise ValueError("need >=2 y_ticks to calibrate")
    # least-squares fit; ticks are typically perfectly linear so this is
    # mostly an averaging exercise
    n = len(pts)
    sx = sum(p[1] for p in pts)
    sy = sum(p[0] for p in pts)
    sxx = sum(p[1] * p[1] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        raise ValueError("degenerate y_ticks")
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    return a, b


# ---------- public API ----------


def _has_oblique_neighbor(seg: Segment,
                          all_segments: List[Segment],
                          tol: float = 2.0) -> bool:
    """True if at least one of ``seg``'s endpoints touches a non-h/v
    segment in ``all_segments``.

    The Miller plateau connects to a rising curve on both sides; legend
    rectangle edges connect only to vertical edges. So presence of an
    oblique neighbour is a strong vote for "real plateau".
    """
    endpoints = [(seg.x0, seg.y0), (seg.x1, seg.y1)]
    for s in all_segments:
        if s is seg:
            continue
        # consider only diagonals
        if abs(s.dx) < 1.0 or abs(s.dy) < 1.0:
            continue
        for ex, ey in endpoints:
            for sx, sy in ((s.x0, s.y0), (s.x1, s.y1)):
                if abs(ex - sx) < tol and abs(ey - sy) < tol:
                    return True
    return False


def find_plateau(page: pymupdf.Page,
                 chart: ChartLocation) -> Optional[PlateauHit]:
    """Find the Miller plateau in the located chart on a page.

    Returns ``None`` if the chart has no extractable vector curve (e.g.
    the curve is an embedded raster image).
    """
    if not chart.has_calibration():
        return None

    try:
        a, b = _calibrate_y(chart)
    except ValueError:
        return None

    drawings = _drawings_in_bbox(page, chart.bbox)

    all_segments: List[Segment] = []
    candidates: List[Segment] = []
    for d in drawings:
        if d.get('type') == 'f':
            continue
        d_segs = _segments_from_drawing_filtered(d)
        for seg in d_segs:
            all_segments.append(seg)
            if _is_chart_chrome(seg, chart):
                continue
            candidates.append(seg)

    # score each candidate for plateau-likelihood
    scored: List[Tuple[float, Segment]] = []
    for seg in candidates:
        s = _segment_curve_score(seg, chart)
        if s <= 0:
            continue
        # boost segments connected to an oblique stroke — that's the rising
        # tangent of the curve into / out of the plateau, and what
        # distinguishes a real plateau from a legend rectangle edge
        if _has_oblique_neighbor(seg, all_segments):
            s *= 3.0
        scored.append((s, seg))

    if not scored:
        return None

    scored.sort(key=lambda t: -t[0])

    # Group near-equal-y segments — when several curves share the same
    # plateau (different VDD conditions), they pile up at the same y and
    # the cluster's combined score is the strongest signal.
    groups: List[List[Tuple[float, Segment]]] = []
    for score, seg in scored:
        for g in groups:
            if abs(g[0][1].cy - seg.cy) < 1.5:
                g.append((score, seg))
                break
        else:
            groups.append([(score, seg)])

    def group_strength(g):
        return sum(s for s, _ in g)

    groups.sort(key=group_strength, reverse=True)
    best = groups[0]
    s_best, seg_best = max(best, key=lambda t: t[0])

    y = seg_best.cy
    v_pl = a * y + b

    if not (1.0 < v_pl < 10.0):
        return None

    height = chart.bbox.y1 - chart.bbox.y0
    rel_pos = (y - chart.bbox.y0) / height if height > 0 else 0.5

    return PlateauHit(
        segment=seg_best,
        y_pdf=y,
        v_pl=round(v_pl, 2),
        score=s_best,
        rel_position=rel_pos,
    )


def _chart_bboxes_overlap(a: pymupdf.Rect, b: pymupdf.Rect,
                          min_overlap: float = 0.4) -> bool:
    """Approximate overlap check used to dedupe charts found by the two
    paths. Two bboxes count as the same chart when their intersection
    area exceeds ``min_overlap`` of the smaller rect."""
    inter = pymupdf.Rect(max(a.x0, b.x0), max(a.y0, b.y0),
                         min(a.x1, b.x1), min(a.y1, b.y1))
    iw = inter.width
    ih = inter.height
    if iw <= 0 or ih <= 0:
        return False
    smaller = min(a.width * a.height, b.width * b.height)
    return (iw * ih) >= min_overlap * smaller


def _vector_or_raster(page: pymupdf.Page,
                      chart: ChartLocation,
                      enable_raster: bool):
    """Try the vector pipeline first; on failure, fall back to raster."""
    hit = find_plateau(page, chart)
    if hit is not None:
        return hit, 'vector'
    if not enable_raster:
        return None, None
    from viz.raster_extract import find_plateau_raster
    rhit = find_plateau_raster(page, chart)
    if rhit is None:
        return None, None
    return rhit, 'raster'


def _looks_scanned(doc: pymupdf.Document) -> bool:
    """True if the PDF appears to be a scanned document.

    A "scanned" page has (almost) no extractable text but does contain an
    embedded image — that's the typical layout of an Infineon datasheet
    where every page is a single bitmap. We use this as the cue to fall
    back to OCR.
    """
    for page in doc.pages():
        text = page.get_text().strip()
        if len(text) > 80:
            return False
    # at least one page must carry an image, otherwise OCR is pointless
    for page in doc.pages():
        if page.get_images(full=False):
            return True
    return False


def find_in_pdf(pdf_path: str,
                enable_raster: bool = True,
                enable_ocr: bool = False,
                _ocr_attempted: bool = False
                ) -> List[Tuple[ChartLocation, Optional[object], Optional[str]]]:
    """Locate every gate-charge chart in a PDF and report its Vpl.

    Returns a list of ``(chart, plateau_hit_or_None, source_or_None)`` where
    ``source`` is ``'vector'``, ``'raster'``, or (after an OCR retry) one
    of those with ``'+ocr'`` appended.

    When ``enable_ocr`` is True and the PDF appears to be a scanned
    document (no extractable text on any page), the PDF is run through
    ``dslib.pdf.parse.ocr_pdf`` and this function is re-invoked on the
    resulting text-layer-augmented PDF. The OCR retry happens at most
    once per call chain.
    """
    from viz.chart_finder import (find_gate_charge_charts,
                                   _find_infineon_raster_charts)
    doc = pymupdf.open(pdf_path)
    out = []
    for page in doc.pages():
        text = page.get_text()
        if 'gate charge' not in text.lower() and 'qg' not in text.lower():
            continue
        charts = list(find_gate_charge_charts(page))
        # always also consider title-anchored charts — on OCRed pages the
        # standard tick-based finder often locks onto noisy fragments
        # and the title path produces a cleaner bbox.
        for c in _find_infineon_raster_charts(page):
            if not any(_chart_bboxes_overlap(c.bbox, x.bbox) for x in charts):
                charts.append(c)
        for chart in charts:
            hit, source = _vector_or_raster(page, chart, enable_raster)
            out.append((chart, hit, source))

    if out or not enable_ocr or _ocr_attempted:
        return out

    if not _looks_scanned(doc):
        return out

    # No text-layer cues anywhere; try OCR and retry on the augmented PDF.
    import os
    import shutil
    import warnings
    # Avoid re-running ocrmypdf (slow + requires tesseract) if a cached
    # variant from a previous run is already on disk.
    cached = pdf_path + '.r600_ocrmypdf.pdf'
    if os.path.isfile(cached):
        ocr_path = cached
    elif shutil.which('tesseract') is None:
        # ocrmypdf shells out to tesseract; without it the call would hang
        # / raise a MissingDependencyError.
        warnings.warn(f'viz: skipping OCR for {pdf_path} — tesseract not installed')
        return out
    else:
        try:
            from dslib.pdf.parse import ocr_pdf
            ocr_path = ocr_pdf(pdf_path)
        except Exception as e:
            warnings.warn(f'viz: ocr_pdf failed on {pdf_path}: {type(e).__name__}: {e}')
            return out

    retried = find_in_pdf(ocr_path, enable_raster=enable_raster,
                          enable_ocr=enable_ocr, _ocr_attempted=True)
    return [(c, h, (s + '+ocr') if s else s) for c, h, s in retried]


def find_vpl(pdf_path: str,
             enable_raster: bool = True,
             enable_ocr: bool = False) -> Optional[float]:
    """Convenience: return the most confident Vpl, or None if none found."""
    cands = []
    for _chart, hit, _src in find_in_pdf(pdf_path,
                                         enable_raster=enable_raster,
                                         enable_ocr=enable_ocr):
        if hit is None:
            continue
        cands.append(hit)
    if not cands:
        return None
    cands.sort(key=lambda h: -h.score)
    return cands[0].v_pl
