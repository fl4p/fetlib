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

from dslib.viz.chart_finder import ChartLocation


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


def _polylines_from_drawing(d: dict) -> List[List[Tuple[float, float]]]:
    """Reconstruct connected polylines (lists of (x, y) points) from a drawing.

    A chart's gate-charge curve is typically drawn as one path with many
    short ``l`` or ``c`` ops in a chain — each op's start point equals the
    previous op's end. We walk the items in order, splitting whenever the
    chain is broken (gap, ``m`` move-to, ``re`` rect, etc.).

    Curves drawn as densely-sampled bezier polylines (e.g. AO/Vishay) end
    up as hundreds of ~1 px segments that the per-segment chrome filter
    rejects as ticks, so we need to consider the polyline as a single
    object when looking for a plateau.
    """
    polylines: List[List[Tuple[float, float]]] = []
    cur: Optional[List[Tuple[float, float]]] = None
    last: Optional[Tuple[float, float]] = None

    def _flush():
        nonlocal cur
        if cur is not None and len(cur) >= 2:
            polylines.append(cur)
        cur = None

    for it in d['items']:
        op = it[0]
        if op == 'l':
            p0, p1 = it[1], it[2]
            if cur is None or last is None \
                    or abs(p0.x - last[0]) > 0.5 or abs(p0.y - last[1]) > 0.5:
                _flush()
                cur = [(p0.x, p0.y), (p1.x, p1.y)]
            else:
                cur.append((p1.x, p1.y))
            last = (p1.x, p1.y)
        elif op == 'c':
            p0 = it[1]
            p3 = it[4]
            if cur is None or last is None \
                    or abs(p0.x - last[0]) > 0.5 or abs(p0.y - last[1]) > 0.5:
                _flush()
                cur = [(p0.x, p0.y), (p3.x, p3.y)]
            else:
                cur.append((p3.x, p3.y))
            last = (p3.x, p3.y)
        else:
            _flush()
            last = None
    _flush()
    return polylines


def _polyline_plateau(points: List[Tuple[float, float]],
                      max_dy: float
                      ) -> Optional[Tuple[float, float, float, float]]:
    """Longest x-stretch of the polyline where y stays within ``max_dy``.

    Returns ``(dx, y_center, y_range, length_idx)`` or None when no useful
    plateau exists. Uses a monotonic-deque sliding window in O(n).
    """
    from collections import deque
    n = len(points)
    if n < 3:
        return None
    max_q: 'deque[int]' = deque()  # y-decreasing
    min_q: 'deque[int]' = deque()  # y-increasing
    best: Optional[Tuple[float, float, float, float]] = None
    i = 0
    for j in range(n):
        y = points[j][1]
        while max_q and points[max_q[-1]][1] < y:
            max_q.pop()
        max_q.append(j)
        while min_q and points[min_q[-1]][1] > y:
            min_q.pop()
        min_q.append(j)
        while points[max_q[0]][1] - points[min_q[0]][1] > max_dy:
            i += 1
            if max_q[0] < i:
                max_q.popleft()
            if min_q[0] < i:
                min_q.popleft()
        # window points[i..j]; assume curve is mostly x-monotonic, so x extent
        # is bounded by the endpoints.
        dx = abs(points[j][0] - points[i][0])
        if best is None or dx > best[0]:
            yc = sum(points[k][1] for k in range(i, j + 1)) / (j - i + 1)
            yr = points[max_q[0]][1] - points[min_q[0]][1]
            best = (dx, yc, yr, float(j - i + 1))
    return best


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


def _segments_from_drawing_filtered(d: dict,
                                    fill_as_thick_stroke: bool = False
                                    ) -> List[Segment]:
    """Like ``_segments_from_drawing`` but discards drawings that look
    like legend rectangles or other chart annotations.

    A rectangle drawing — either a single ``re`` op or four axis-aligned
    line segments forming a closed quadrilateral — contributes zero
    segments. The Miller plateau lives in a stroked path with at least one
    oblique stroke.

    With ``fill_as_thick_stroke=True``, a 3-edge filled path (a thin
    triangle / parallelogram drawn to render a thick stroke) is reduced
    to a single dominant edge — useful for charts where the curve is
    drawn as filled polygons rather than stroked lines (some Infineon
    IRF datasheets).
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
    if fill_as_thick_stroke and d.get('type') == 'f':
        # A 3-edge fill is the chart-internal "thick stroke" idiom:
        # two parallel long edges + one short cap. Keep the average of
        # the two long edges so the segment represents the line itself.
        if len(raw) == 3:
            sorted_by_len = sorted(raw, key=lambda s: -s.length)
            long_a, long_b = sorted_by_len[0], sorted_by_len[1]
            if long_a.length > 3 * sorted_by_len[2].length:
                # average endpoints of the two long edges
                def midpt(a, b):
                    return ((a + b) * 0.5)
                # match endpoints by proximity
                ax0, ay0, ax1, ay1 = long_a.x0, long_a.y0, long_a.x1, long_a.y1
                bx0, by0, bx1, by1 = long_b.x0, long_b.y0, long_b.x1, long_b.y1
                # try the two pairings, pick the one with shorter cross-distances
                d_aa = (ax0 - bx0) ** 2 + (ay0 - by0) ** 2 + (ax1 - bx1) ** 2 + (ay1 - by1) ** 2
                d_ab = (ax0 - bx1) ** 2 + (ay0 - by1) ** 2 + (ax1 - bx0) ** 2 + (ay1 - by0) ** 2
                if d_aa <= d_ab:
                    p0 = (midpt(ax0, bx0), midpt(ay0, by0))
                    p1 = (midpt(ax1, bx1), midpt(ay1, by1))
                else:
                    p0 = (midpt(ax0, bx1), midpt(ay0, by1))
                    p1 = (midpt(ax1, bx0), midpt(ay1, by0))
                return [Segment(p0[0], p0[1], p1[0], p1[1])]
        # Other filled shapes (4-edge closed quads handled above,
        # legend swatches stripped) — keep as raw segments so the
        # chrome filter / scorer can reject them.
        return raw
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

    # 5. wide-ish horizontal segment landing exactly on a y-axis tick is
    # almost certainly a gridline rather than the Miller plateau —
    # plateaus naturally sit *between* the integer-volt ticks. Only
    # filter when the segment is at least ~40% of the bbox width so
    # short plateau segments (typically 5-15% of plot width) aren't
    # accidentally rejected just because they happen to align with a
    # tick. The 40% threshold also catches half-gridlines drawn as two
    # adjacent ~50% segments (onsemi convention).
    if abs(seg.dy) < axis_tol and abs(seg.dx) > 0.4 * width \
            and len(chart.y_ticks) >= 2:
        tick_ys = sorted(t[1] for t in chart.y_ticks)
        diffs = [tick_ys[i + 1] - tick_ys[i] for i in range(len(tick_ys) - 1)]
        positive = [d for d in diffs if d > 0.5]
        if positive:
            tick_spacing = min(positive)
            # Loose snap: only firing for wide horizontals, so be
            # generous (a gridline can drift up to ~25% of the tick
            # spacing because of pdfminer's path-stroke offset / fill
            # half-width). Plateaus that *also* happen to be wide
            # *and* fall right on a tick are extremely rare in
            # practice.
            snap_tol = max(2.0, 0.25 * tick_spacing)
            for _, ty in chart.y_ticks:
                if abs(seg.cy - ty) < snap_tol:
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


def _oblique_neighbor_count(seg: Segment,
                            all_segments: List[Segment],
                            tol: float = 2.0) -> int:
    """Return how many of ``seg``'s endpoints touch a non-h/v segment.

    The Miller plateau is connected to a rising tangent on *both* sides
    (one going into the plateau, one coming out) — so the canonical
    plateau scores 2. A horizontal gridline that happens to start /
    end at a curve endpoint touches at most one oblique stroke (the
    curve crosses the gridline at one point, not two).
    """
    p0 = (seg.x0, seg.y0)
    p1 = (seg.x1, seg.y1)
    hit0 = hit1 = False
    for s in all_segments:
        if s is seg:
            continue
        if abs(s.dx) < 1.0 or abs(s.dy) < 1.0:
            continue
        for sx, sy in ((s.x0, s.y0), (s.x1, s.y1)):
            if not hit0 and abs(p0[0] - sx) < tol and abs(p0[1] - sy) < tol:
                hit0 = True
            if not hit1 and abs(p1[0] - sx) < tol and abs(p1[1] - sy) < tol:
                hit1 = True
        if hit0 and hit1:
            break
    return int(hit0) + int(hit1)


def _has_oblique_neighbor(seg: Segment,
                          all_segments: List[Segment],
                          tol: float = 2.0) -> bool:
    """Backwards-compatible wrapper (>=1 oblique neighbour)."""
    return _oblique_neighbor_count(seg, all_segments, tol) >= 1


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
    bbox_h = chart.bbox.y1 - chart.bbox.y0
    bbox_w = chart.bbox.x1 - chart.bbox.x0

    all_segments: List[Segment] = []
    pre_candidates: List[Segment] = []
    for d in drawings:
        d_segs = _segments_from_drawing_filtered(d, fill_as_thick_stroke=True)
        if d.get('type') == 'f':
            # Filled drawings split into two kinds:
            #   1. legend boxes / annotations (closed quadrilateral
            #      rectangles) — already returned as [] by
            #      ``_segments_from_drawing_filtered``.
            #   2. three-edge "thick stroke" approximations of a curve
            #      segment — keep the dominant edge as a stroke.
            if not d_segs:
                continue
        for seg in d_segs:
            all_segments.append(seg)
            if _is_chart_chrome(seg, chart):
                continue
            pre_candidates.append(seg)

    # Polyline-plateau pass: gate-charge curves drawn as a densely-sampled
    # connected path (many tiny ``l``/``c`` ops) collapse into hundreds of
    # ~1 px segments that the per-segment chrome filter rejects as ticks,
    # so the segment-based scorer sees nothing. Walk each long polyline
    # and synthesize a horizontal "plateau segment" at the longest stretch
    # where y stays nearly constant — that segment then feeds the normal
    # scoring path (so it competes fairly with curves drawn as long
    # strokes). max_dy ≈ 2.5% of chart height ≈ 0.25 V for a 10 V chart.
    max_dy = max(2.0, 0.025 * bbox_h)
    for d in drawings:
        # Skip rectangles / annotation drawings outright — only paths.
        if d.get('type') == 'f' and len(d['items']) == 1 and d['items'][0][0] == 're':
            continue
        for poly in _polylines_from_drawing(d):
            if len(poly) < 8:
                # Short paths (axis tick-mark sequences, legend ticks) — let
                # the segment-based pipeline handle them; treating them as
                # polylines would produce noisy synthetic plateaus.
                continue
            result = _polyline_plateau(poly, max_dy=max_dy)
            if result is None:
                continue
            dx, y_c, y_range, _n = result
            if dx < 0.02 * bbox_w:
                continue
            if dx > 0.7 * bbox_w:
                # Spans most of the chart — almost certainly the x-axis or
                # a long gridline, not the Miller plateau.
                continue
            # Reject polylines that are basically a flat horizontal line
            # (an axis or gridline drawn as a polyline). A real
            # gate-charge polyline has rising/falling sections outside the
            # plateau window — the polyline's overall y-range should be
            # much larger than the plateau's y-range.
            poly_y_range = max(p[1] for p in poly) - min(p[1] for p in poly)
            if poly_y_range < 0.2 * bbox_h:
                continue
            # Locate the plateau window in x coordinates for the synthetic
            # segment endpoints.
            # The sliding window finds best (i, j) implicitly; reconstruct
            # by walking the polyline once more — small n, cost negligible.
            from collections import deque
            mq: 'deque[int]' = deque()
            nq: 'deque[int]' = deque()
            i = 0
            best_ij = (0, 0)
            best_dx = -1.0
            for j in range(len(poly)):
                y = poly[j][1]
                while mq and poly[mq[-1]][1] < y:
                    mq.pop()
                mq.append(j)
                while nq and poly[nq[-1]][1] > y:
                    nq.pop()
                nq.append(j)
                while poly[mq[0]][1] - poly[nq[0]][1] > max_dy:
                    i += 1
                    if mq[0] < i:
                        mq.popleft()
                    if nq[0] < i:
                        nq.popleft()
                d_curr = abs(poly[j][0] - poly[i][0])
                if d_curr > best_dx:
                    best_dx = d_curr
                    best_ij = (i, j)
            i, j = best_ij
            x0, x1 = poly[i][0], poly[j][0]
            if x0 > x1:
                x0, x1 = x1, x0
            # Synthesize a horizontal segment centred at y_c with a small
            # dy reflecting the actual y-range of the plateau window —
            # this makes the existing scorer (flatness = 1 / rel_dy) treat
            # tighter plateaus as stronger evidence.
            synth = Segment(x0, y_c - y_range * 0.5, x1, y_c + y_range * 0.5)
            all_segments.append(synth)
            if _is_chart_chrome(synth, chart):
                continue
            pre_candidates.append(synth)

    # Composite-gridline filter: when several horizontal segments at the
    # same y together span most of the chart width, they're a gridline
    # drawn in pieces (e.g. onsemi V_GS axis with the title text
    # "V_GS = 10 V" cutting the line in half). Filter them out so the
    # plateau scorer doesn't sum their scores into a stronger-than-
    # plateau cluster.
    bbox_width = chart.bbox.x1 - chart.bbox.x0
    cy_groups: dict = {}
    for seg in pre_candidates:
        if abs(seg.dy) >= 1.5:
            continue
        key = round(seg.cy / 1.5) * 1.5
        cy_groups.setdefault(key, []).append(seg)
    composite_gridline_ids = set()
    for _key, segs in cy_groups.items():
        if len(segs) < 2:
            continue
        total_span = sum(abs(s.dx) for s in segs)
        if total_span > 0.7 * bbox_width:
            for s in segs:
                composite_gridline_ids.add(id(s))
    candidates = [s for s in pre_candidates
                  if id(s) not in composite_gridline_ids]

    # Reject charts that don't show a rising curve at all. A real
    # gate-charge curve has rising tangents going into and out of the
    # plateau — oblique strokes. A chart that only contains horizontal
    # segments (e.g. a V_th-vs-temperature chart with a near-constant
    # line) has zero oblique segments, so the title-anchored finder
    # shouldn't mistake its flat curve for a Miller plateau.
    if not any(abs(s.dx) > 1 and abs(s.dy) > 1 for s in candidates):
        return None

    # score each candidate for plateau-likelihood
    scored: List[Tuple[float, Segment]] = []
    for seg in candidates:
        s = _segment_curve_score(seg, chart)
        if s <= 0:
            continue
        # Boost segments connected to oblique strokes — those are the
        # rising tangents that bracket a real Miller plateau. A
        # segment with oblique neighbours on **both** endpoints
        # (rising-in + rising-out) is the canonical plateau shape; one
        # endpoint is weaker evidence (could be the curve merely
        # crossing a gridline once). The two-sided boost is large
        # enough to beat full-width gridlines that share an endpoint
        # with the curve.
        n_ob = _oblique_neighbor_count(seg, all_segments)
        if n_ob >= 2:
            # Two oblique neighbours (rising tangent into AND out of
            # the plateau) is the canonical Miller-plateau shape; boost
            # generously so it beats full-width gridlines that happen
            # to share a single endpoint with the curve.
            s *= 20.0
        elif n_ob >= 1:
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
        # Dedupe *near-identical* segments within the group before summing.
        # Filled-polygon "thick stroke" curves and full-width gridlines
        # frequently produce stacks of segments with the same endpoints,
        # and a sum-based strength would let those triplicates outscore a
        # single-drawn plateau. A segment counts as a duplicate of an
        # earlier one only when **both endpoints** sit within ~2px of the
        # earlier segment's endpoints (matched either way) — that catches
        # true duplicates from fill triplicates without collapsing three
        # genuinely stacked curves at slightly different x/y (different
        # VDD conditions on the same chart).
        accepted: List[Segment] = []
        total = 0.0
        tol = 2.0
        for s, seg in sorted(g, key=lambda t: -t[0]):
            dup = False
            for prev in accepted:
                d_same = (abs(seg.x0 - prev.x0) + abs(seg.y0 - prev.y0)
                          + abs(seg.x1 - prev.x1) + abs(seg.y1 - prev.y1))
                d_swap = (abs(seg.x0 - prev.x1) + abs(seg.y0 - prev.y1)
                          + abs(seg.x1 - prev.x0) + abs(seg.y1 - prev.y0))
                if min(d_same, d_swap) < 4 * tol:
                    dup = True
                    break
            if not dup:
                accepted.append(seg)
                total += s
        return total

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
    from dslib.viz.raster_extract import find_plateau_raster
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


def _has_custom_font_encoding(pdf_path: str) -> bool:
    """Wrapper around ``dslib.pdf.fix_encoding.has_custom_font_encoding``
    that swallows import / parse errors and returns False so missing
    optional deps can't break the viz pipeline."""
    try:
        from dslib.pdf.fix_encoding import has_custom_font_encoding
        return has_custom_font_encoding(pdf_path)
    except Exception:
        return False


def find_in_pdf(pdf_path: str,
                enable_raster: bool = True,
                enable_ocr: bool = False,
                _ocr_attempted: bool = False,
                _fix_attempted: bool = False,
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

    When ``enable_ocr`` is True and no charts are found on the first
    pass and the PDF carries a custom font encoding (e.g. some Huayi
    datasheets ship a font with a scrambled glyph map that turns "Qg"
    into "OG" and "(nC)" into "(nO)" for any text-layer reader), the
    PDF is first passed through ``fix_pdf_font_encoding`` to restore
    a sane ``ToUnicode`` map, then through ``ocr_pdf`` to rasterize
    and re-OCR — that pipeline produces a clean text layer with
    correct "Gate Charge"/"VGS" labels and chart-region tick values.
    """
    from dslib.viz.chart_finder import (find_gate_charge_charts,
                                        _find_infineon_raster_charts)
    doc = pymupdf.open(pdf_path)
    out = []
    for page in doc.pages():
        text = page.get_text()
        text_lower = text.lower()
        # Toshiba TPH/XPN/XPQR datasheets caption the V_GS-vs-Q_g plot
        # "Dynamic Input/Output Characteristics" and don't mention "gate
        # charge" anywhere on the page.
        if ('gate charge' not in text_lower
                and 'qg' not in text_lower
                and 'dynamic input/output' not in text_lower
                and 'dynamic input / output' not in text_lower):
            continue
        std_charts = list(find_gate_charge_charts(page))
        title_charts = list(_find_infineon_raster_charts(page))
        # Try the standard charts first; only fall back to title-
        # anchored charts when none of the standard ones yielded a
        # **vector** plateau hit. A standard chart that succeeds only
        # via the raster fallback is much less reliable (raster can
        # latch onto V=0 gridlines on flat-line plots), so we still try
        # the title-anchored chart in parallel and let ``find_vpl``
        # pick the higher-scoring candidate. This also recovers charts
        # the standard finder missed entirely (or returned a too-narrow
        # bbox for, leaving the trace's vertical span too small to
        # clear the ``find_plateau_raster`` sanity check).
        page_results = []
        any_vector_hit = False
        std_vector_hit_charts: List[ChartLocation] = []
        std_plausible_charts: List[ChartLocation] = []
        for chart in std_charts:
            hit, source = _vector_or_raster(page, chart, enable_raster)
            page_results.append((chart, hit, source))
            if hit is not None:
                if source == 'vector':
                    std_vector_hit_charts.append(chart)
                    any_vector_hit = True
                # A raster hit landing inside the canonical Miller-
                # plateau range (≈ 1.5..7 V) is much more trustworthy
                # than the wider-bbox title-anchored finder's hit on
                # the same chart, which tends to latch onto the
                # curve's high-V endpoint when the bbox includes the
                # x-axis title and gridlines outside the plot frame.
                # Treat these as "plausible" and use them to suppress
                # overlapping title-anchored alternates.
                v = getattr(hit, 'v_pl', None)
                if v is not None and 1.5 < v < 7.5:
                    std_plausible_charts.append(chart)
        if not any_vector_hit and title_charts:
            for chart in title_charts:
                # Skip the title chart when it overlaps a std chart
                # that already produced a trustworthy hit (vector, or
                # raster in the typical Miller-plateau voltage range).
                # An unreliable std-raster hit (e.g. V≈0 from a flat
                # mis-anchored chart) doesn't suppress the title-
                # anchored fallback — that's what saves SIJ482DP /
                # SUP85N15-style cases where std mis-anchors.
                if any(_chart_bboxes_overlap(chart.bbox, s.bbox)
                       for s in std_vector_hit_charts):
                    continue
                if any(_chart_bboxes_overlap(chart.bbox, s.bbox)
                       for s in std_plausible_charts):
                    continue
                hit, source = _vector_or_raster(page, chart, enable_raster)
                page_results.append((chart, hit, source))
        out.extend(page_results)

    # ``out`` may contain entries with hit=None (chart located but no
    # plateau extracted); fall through to OCR in that case too, because
    # OCR sometimes produces a cleaner tick column that lets the
    # plateau scan succeed.
    have_hit = any(h is not None for _c, h, _s in out)
    if have_hit or not enable_ocr or _ocr_attempted:
        return out

    is_scanned = _looks_scanned(doc)
    has_bad_fonts = (not _fix_attempted) and _has_custom_font_encoding(pdf_path)
    # If the caller already passed a fix-encoded PDF (its text reads as
    # garbled "Gate 0harge" / "(nO)" because fix_encoding's shape matcher
    # confuses C↔0 / Q↔O), neither is_scanned nor has_bad_fonts will be
    # true even though the page truly needs OCR. Detect that by looking
    # for any chart-keyword cue in the extracted text — if NONE of the
    # pages mention "gate charge", "qg", or "dynamic input/output",
    # the text layer can't anchor the chart finder and OCR is worth a
    # shot.
    if not is_scanned and not has_bad_fonts and out:
        # The text layer reads fine AND we already located at least one
        # chart — so the failure is in plateau extraction, not chart
        # discovery. OCR is unlikely to help, skip it.
        # When ``out`` is empty, the chart finder turned up nothing even
        # though one of the pages mentions "gate charge". That usually
        # means the chart sits on a different, image-only page (the
        # keyword we found is on the front-page summary). OCR'ing the
        # image pages can surface the chart's tick labels and unblock
        # the title-anchored finder.
        has_keyword = False
        for page in doc.pages():
            tl = page.get_text().lower()
            if ('gate charge' in tl or 'qg' in tl
                    or 'dynamic input/output' in tl
                    or 'dynamic input / output' in tl):
                has_keyword = True
                break
        if has_keyword:
            return out

    import os
    import shutil
    import warnings

    # Custom-encoded fonts: fix the ToUnicode map first, then OCR. OCR
    # alone misses the small per-tick digits on these charts (the
    # rasterized "1".."9" are too small for tesseract); the fix-encoded
    # PDF preserves the original text positions exactly, and the
    # subsequent rasterize-and-tesseract pass cleans up the title and
    # axis labels that fix_encoding misidentifies (C ↔ 0, Q ↔ O).
    fix_path = pdf_path
    if has_bad_fonts:
        try:
            from dslib.pdf.fix_encoding import fix_pdf_font_encoding
            fix_path = fix_pdf_font_encoding(
                pdf_path, raise_if_no_bad_fonts=False)
        except Exception as e:
            warnings.warn(
                f'viz: fix_pdf_font_encoding failed on {pdf_path}: '
                f'{type(e).__name__}: {e}')
            fix_path = pdf_path

    # Avoid re-running ocrmypdf (slow + requires tesseract) if a cached
    # variant from a previous run is already on disk.
    cached = fix_path + '.r600_ocrmypdf.pdf'
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
            ocr_path = ocr_pdf(fix_path)
        except Exception as e:
            warnings.warn(f'viz: ocr_pdf failed on {pdf_path}: {type(e).__name__}: {e}')
            return out

    retried = find_in_pdf(ocr_path, enable_raster=enable_raster,
                          enable_ocr=enable_ocr, _ocr_attempted=True,
                          _fix_attempted=True)
    return [(c, h, (s + '+ocr') if s else s) for c, h, s in retried]


def find_vpl(pdf_path: str,
             enable_raster: bool = True,
             enable_ocr: bool = False) -> Optional[float]:
    """Convenience: return the most confident Vpl, or None if none found.

    Within the candidate set, prefer plateau values in the canonical
    Miller-plateau range (1.5..7.5 V) before falling back to out-of-range
    hits. The high-end out-of-range hits are usually wrong — they latch
    onto the curve's V_drive saturation tail rather than the plateau —
    but the rare datasheets with V_drive ≳ 8 V have their plateau there,
    so out-of-range hits are still accepted as a fallback when no in-
    range candidate exists.
    """
    cands = []
    for _chart, hit, _src in find_in_pdf(pdf_path,
                                         enable_raster=enable_raster,
                                         enable_ocr=enable_ocr):
        if hit is None:
            continue
        cands.append(hit)
    if not cands:
        return None
    cands.sort(key=lambda h: (0 if 1.5 < h.v_pl < 7.5 else 1, -h.score))
    return cands[0].v_pl
