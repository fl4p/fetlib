"""
Raster-based plateau extraction fallback.

When the chart is an embedded image (so ``pymupdf.Page.get_drawings``
returns nothing for the plot area), we render the chart bbox at high DPI
and look for the plateau directly in pixel space:

  1. render the chart bbox region as a grayscale numpy array
  2. binarise dark ink, mask out grid + axis pixels using long-line
     detection (Hough-like row/column histograms)
  3. trace the curve as the densest column of remaining dark pixels per
     x column
  4. the plateau row is the y at which the curve's trace stays nearly
     constant for the longest span of x
  5. linearly interpolate back to VGS via the chart's y_ticks
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pymupdf

from dslib.viz.chart_finder import ChartLocation


@dataclass
class RasterPlateauHit:
    y_pdf: float
    v_pl: float
    score: float
    plateau_run: Tuple[int, int]  # (x_pixel_start, x_pixel_end)


def _render_chart(page: pymupdf.Page,
                  bbox: pymupdf.Rect,
                  dpi: int = 300) -> Tuple[np.ndarray, float, float]:
    """Render the chart bbox region. Returns (grayscale array, scale_x,
    scale_y) where scale_X is pixels-per-pdf-point.
    """
    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=bbox, colorspace=pymupdf.csGRAY)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return arr, zoom, zoom


def _mask_grid_lines(bin_img: np.ndarray,
                     min_extent_ratio: float = 0.7) -> np.ndarray:
    """Zero out pixels that belong to long horizontal or vertical lines.

    A row whose dark pixel count exceeds ``min_extent_ratio * width`` is
    treated as a gridline / axis line and stripped. Same for columns.
    """
    h, w = bin_img.shape
    out = bin_img.copy()

    row_counts = bin_img.sum(axis=1)
    bad_rows = np.where(row_counts > min_extent_ratio * w * 255)[0]
    out[bad_rows, :] = 0

    col_counts = bin_img.sum(axis=0)
    bad_cols = np.where(col_counts > min_extent_ratio * h * 255)[0]
    out[:, bad_cols] = 0

    return out


def _trace_curve(bin_img: np.ndarray,
                 max_gap: int = 2) -> np.ndarray:
    """For each column, return the centre y of the *largest* dark run.

    Splits the column's dark pixels into contiguous runs (separated by
    runs of ``max_gap`` or more light pixels) and reports the centre of
    the longest one. This is much more robust than a global median when
    the plot has legend boxes, annotations, or stacked curves: the
    largest connected dark stretch through that column is almost always
    the main curve itself.
    """
    h, w = bin_img.shape
    trace = np.full(w, np.nan, dtype=np.float64)
    for x in range(w):
        col = bin_img[:, x] > 0
        if not col.any():
            continue
        # find all dark runs in this column
        best_len = 0
        best_center: Optional[float] = None
        i = 0
        while i < h:
            if not col[i]:
                i += 1
                continue
            j = i
            while j < h and col[j]:
                j += 1
            # tolerate a small gap and merge runs
            k = j
            while k < h and not col[k] and (k - j) < max_gap:
                k += 1
            if k < h and col[k]:
                j = k
                while j < h and col[j]:
                    j += 1
            run_len = j - i
            if run_len > best_len:
                best_len = run_len
                best_center = 0.5 * (i + j - 1)
            i = j
        if best_center is not None:
            trace[x] = best_center
    return trace


def _find_plateau_run(trace: np.ndarray,
                      flatness_px: float,
                      min_run_px: int) -> Optional[Tuple[int, int, float]]:
    """Return (x_start, x_end, plateau_y) for the longest x-span where the
    trace's local variation stays within ``flatness_px``.

    A run is rejected when both endpoints sit at the chart's left/right
    edges with no rising-curve continuation — that pattern indicates a
    gridline extending past the curve (e.g. a V_GS = 8 V reference line
    drawn across the full plot width while the actual curve only covers
    the left half), not a Miller plateau bracketed by the rising curve.
    A real plateau has the curve approaching from below it on one side
    *and* continuing above it on the other.
    """
    n = trace.shape[0]
    candidates: List[Tuple[int, int, float]] = []

    i = 0
    while i < n:
        if math.isnan(trace[i]):
            i += 1
            continue
        j = i
        run_vals: List[float] = []
        while j < n and not math.isnan(trace[j]):
            cand = trace[j]
            if run_vals:
                center = float(np.median(run_vals))
                if abs(cand - center) > flatness_px:
                    break
            run_vals.append(cand)
            j += 1
        if (j - i) >= min_run_px:
            plateau_y = float(np.median(run_vals))
            candidates.append((i, j, plateau_y))
        i = j if j > i else i + 1

    if not candidates:
        return None

    # Probe just outside each candidate to decide whether it sits on a
    # real Miller plateau or on a tail-end gridline. A V_GS-vs-Q_g curve
    # rises monotonically, so the trace immediately before the plateau
    # should sit *at or below* the plateau's y (i.e. lower V → larger y)
    # and the trace immediately after should sit *at or above* it
    # (higher V → smaller y). A gridline drawn past the curve's right
    # edge fails this: the curve has already left the plot at a
    # *much lower* y (high V) before the gridline begins, so the
    # immediate-left sample is well *above* the plateau's y in the
    # "wrong direction".
    probe_span = max(min_run_px, 10)
    diff_tol = max(flatness_px * 2.0, 4.0)

    def is_plausible_plateau(run: Tuple[int, int, float]) -> bool:
        i_, j_, py = run
        # Sample the closest valid trace value on each side.
        left_y: Optional[float] = None
        for k in range(i_ - 1, max(-1, i_ - probe_span) - 1, -1):
            v = trace[k]
            if not math.isnan(v):
                left_y = float(v)
                break
        right_y: Optional[float] = None
        for k in range(j_, min(n, j_ + probe_span)):
            v = trace[k]
            if not math.isnan(v):
                right_y = float(v)
                break
        # If the curve never appears next to this run, it's at the
        # data's edge — accept (the plateau may genuinely hug the
        # left/right of the chart).
        if left_y is None and right_y is None:
            return True
        # Plateau-shape check: left side at *or below* (greater-or-
        # equal y in image coords), right side at *or above* (smaller-
        # or-equal y). Allow ``diff_tol`` slack for stroke-rounding.
        if left_y is not None and left_y < py - diff_tol:
            return False
        if right_y is not None and right_y > py + diff_tol:
            return False
        return True

    valid = [r for r in candidates if is_plausible_plateau(r)]
    if not valid:
        valid = candidates

    valid.sort(key=lambda r: r[1] - r[0], reverse=True)
    return valid[0]


def _calibrate_y(chart: ChartLocation,
                 bbox_y0: float, zoom: float) -> Tuple[float, float]:
    """y_pixel → V conversion (linear).

    The chart bbox we rendered starts at ``bbox_y0`` (pdf) → 0 (pixel).
    Pixel y maps back to pdf y via: y_pdf = bbox_y0 + y_pixel / zoom.
    Then the y_tick fit converts y_pdf → V.
    """
    pts_pdf_v = chart.y_ticks
    pixel_pts = [(v, (y - bbox_y0) * zoom) for v, y in pts_pdf_v]
    # least squares: V = a * y_px + b
    n = len(pixel_pts)
    sx = sum(p[1] for p in pixel_pts)
    sy = sum(p[0] for p in pixel_pts)
    sxx = sum(p[1] * p[1] for p in pixel_pts)
    sxy = sum(p[0] * p[1] for p in pixel_pts)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        raise ValueError("degenerate y_ticks")
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    return a, b


def _plot_interior_bbox(chart: ChartLocation) -> pymupdf.Rect:
    """Tight bbox around the plot interior (no captions / tick labels).

    Vertically: top of plot ≈ topmost y-tick; bottom of plot ≈ bottom
    y-tick (which is usually the 0-volt line).
    Horizontally: leftmost x-tick → rightmost x-tick.

    We rely on the chart having both tick families. If the x-ticks are
    missing, fall back to the chart's full bbox along that axis.
    """
    bx0, by0, bx1, by1 = chart.bbox.x0, chart.bbox.y0, chart.bbox.x1, chart.bbox.y1
    if chart.y_ticks:
        ys = [y for _, y in chart.y_ticks]
        by0 = min(ys) - 2
        by1 = max(ys) + 2
    if chart.x_ticks:
        xs = [x for _, x in chart.x_ticks]
        bx0 = min(xs) - 2
        bx1 = max(xs) + 2
    return pymupdf.Rect(bx0, by0, bx1, by1)


def _detect_plot_border(arr: np.ndarray,
                        dark_threshold: int = 200,
                        ratio: float = 0.55
                        ) -> Optional[Tuple[int, int, int, int]]:
    """Find the plot frame inside a rendered chart image.

    Returns ``(top_px, bottom_px, left_px, right_px)`` — the rows / cols
    where the chart's bordering rectangle sits. Returns ``None`` if no
    clear frame is detectable.

    Strategy:
      1. flag rows/cols whose dark-pixel count exceeds ``ratio`` of the
         opposite dimension
      2. cluster runs of consecutive flagged indices (a 4-pixel-thick
         frame counts as one)
      3. drop runs that touch the very edge of the image, or that span
         (nearly) the full opposite dimension — those are page borders /
         footer bleed-through, not the plot frame
      4. plot top = first surviving horizontal run, plot bottom = last;
         same for left/right columns
    """
    h, w = arr.shape
    if h < 20 or w < 20:
        return None

    dark = arr < dark_threshold
    row_counts = dark.sum(axis=1).astype(np.int32)
    col_counts = dark.sum(axis=0).astype(np.int32)

    h_hits = np.where(row_counts > ratio * w)[0]
    v_hits = np.where(col_counts > ratio * h)[0]

    if h_hits.size < 1 or v_hits.size < 1:
        return None

    def _group_runs(hits: np.ndarray) -> List[List[int]]:
        groups: List[List[int]] = []
        for h_ in hits:
            if groups and h_ - groups[-1][-1] <= 4:
                groups[-1].append(int(h_))
            else:
                groups.append([int(h_)])
        return groups

    def _is_page_rule(row_or_col_indices: List[int],
                      bin_orient: np.ndarray) -> bool:
        """A page-level horizontal rule has dark pixels that touch *both*
        ends of the perpendicular axis — i.e. it goes edge-to-edge. The
        chart frame has small margins so its dark stretch is bounded
        well inside the image."""
        # check the densest row/col in this group
        idxs = bin_orient.sum(axis=1) if bin_orient.ndim == 2 else None
        return False

    def _row_touches_edges(g: List[int], bin_img: np.ndarray) -> bool:
        """True if the merged darkness for rows ``g`` reaches both column
        ends of ``bin_img`` (= it's a page rule, not a chart frame)."""
        slab = bin_img[g[0]:g[-1] + 1, :].any(axis=0)
        return bool(slab[0]) and bool(slab[-1])

    def _col_touches_edges(g: List[int], bin_img: np.ndarray) -> bool:
        slab = bin_img[:, g[0]:g[-1] + 1].any(axis=1)
        return bool(slab[0]) and bool(slab[-1])

    def _pick_bounds_rows(groups: List[List[int]], max_v: int,
                          bin_img: np.ndarray) -> Tuple[int, int]:
        # Drop:
        #  * page-level horizontal rules (touch both column ends)
        #  * groups GLUED to the very image edge (rows 0..edge_pad) and
        #    not part of a clearly-defined chart frame; but when the
        #    image was clipped tight against the chart frame these edge
        #    rows ARE the frame, so we accept them if the slab doesn't
        #    touch the image's left/right edges.
        edge_pad = 1
        out = []
        for g in groups:
            if _row_touches_edges(g, bin_img):
                continue
            # row glued to the very edge — still accept if it doesn't
            # touch the column edges (= real chart frame, not artefact)
            if g[0] < edge_pad or g[-1] > max_v - 1 - edge_pad:
                if _row_touches_edges(g, bin_img):
                    continue
            out.append(g)
        groups = out
        if not groups:
            return -1, -1
        centers = [int(sum(g) / len(g)) for g in groups]
        return centers[0], centers[-1]

    def _pick_bounds_cols(groups: List[List[int]], max_v: int,
                          bin_img: np.ndarray) -> Tuple[int, int]:
        edge_pad = 1
        out = []
        for g in groups:
            if _col_touches_edges(g, bin_img):
                continue
            out.append(g)
        groups = out
        if not groups:
            return -1, -1
        top = int(sum(groups[0]) / len(groups[0]))
        bot = int(sum(groups[-1]) / len(groups[-1]))
        return top, bot

    top, bot = _pick_bounds_rows(_group_runs(h_hits), h, dark)
    left, right = _pick_bounds_cols(_group_runs(v_hits), w, dark)
    if top < 0 or left < 0 or bot - top < 20 or right - left < 20:
        return None
    return top, bot, left, right


def _doc_is_ocred(page: pymupdf.Page) -> bool:
    """Heuristic: is the underlying PDF the OCR output of ``ocr_pdf``?

    ``dslib.pdf.parse.ocr_pdf`` writes ``<orig>.r600_ocrmypdf.pdf``;
    tesseract scatters spurious "text" across curve regions in that
    output, so we don't want to use the OCR'd text-layer to mask the
    chart interior.
    """
    try:
        name = page.parent.name or ''
    except Exception:
        return False
    name = name.lower()
    return name.endswith('.r600_ocrmypdf.pdf') \
        or name.endswith('.r400_ocrmypdf.pdf') \
        or '_ocrmypdf' in name


def _mask_inchart_text(page: pymupdf.Page,
                       bbox: pymupdf.Rect,
                       arr: np.ndarray,
                       zoom: float) -> np.ndarray:
    """Erase text glyphs that sit *inside* the plot from the rendered
    bitmap.

    Charts often place curve labels (``"20 V"``, ``"40 V"``, etc.) right
    on top of the curves. Their dark pixels would otherwise leak into
    ``_trace_curve``'s per-column scan and pull the trace away from the
    actual line. We render a white box over every page word whose bbox
    falls inside the chart bbox so the curve trace sees the curve and
    nothing else.

    Skipped entirely on OCR'd PDFs: tesseract treats curve squiggles as
    text, so the "words" the text layer reports there *are* the curve
    pixels — masking them would erase the curve itself.

    Y-axis / x-axis tick labels at the very edges are preserved
    automatically: ``_detect_plot_border`` already crops to the plot
    interior before the trace runs.
    """
    if _doc_is_ocred(page):
        return arr
    try:
        words = page.get_text('words')
    except Exception:
        return arr
    arr = arr.copy()
    pad = max(1, int(zoom))
    for w in words:
        x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
        if x1 < bbox.x0 or x0 > bbox.x1:
            continue
        if y1 < bbox.y0 or y0 > bbox.y1:
            continue
        if x0 < bbox.x0 - 1 and x1 > bbox.x1 + 1:
            continue
        px0 = max(0, int((x0 - bbox.x0) * zoom) - pad)
        py0 = max(0, int((y0 - bbox.y0) * zoom) - pad)
        px1 = min(arr.shape[1], int((x1 - bbox.x0) * zoom) + pad)
        py1 = min(arr.shape[0], int((y1 - bbox.y0) * zoom) + pad)
        if px1 <= px0 or py1 <= py0:
            continue
        arr[py0:py1, px0:px1] = 255
    return arr


def _mask_grid_lines_strict(bin_img: np.ndarray,
                            ratio: float = 0.5,
                            thickness: int = 2) -> np.ndarray:
    """Like ``_mask_grid_lines`` but with a lower coverage threshold and
    a small thickness dilation. Toshiba "Dynamic Input/Output" charts
    draw a horizontal gridline every 1 V; the gridline crossing a curve
    boosts the row's coverage above the strict-mask threshold while the
    coverage of the pure curve segments stays well below it. The
    thickness pass extends each masked row/column by ``thickness`` px
    on each side so an anti-aliased gridline's faint shoulder pixels
    don't leak through and confuse the trace.
    """
    h, w = bin_img.shape
    out = bin_img.copy()
    rc = (bin_img > 0).sum(axis=1)
    bad_rows = rc > ratio * w
    bad_rows_d = bad_rows.copy()
    for d in range(1, thickness + 1):
        bad_rows_d[d:] |= bad_rows[:-d]
        bad_rows_d[:-d] |= bad_rows[d:]
    out[bad_rows_d, :] = 0
    cc = (bin_img > 0).sum(axis=0)
    bad_cols = cc > ratio * h
    bad_cols_d = bad_cols.copy()
    for d in range(1, thickness + 1):
        bad_cols_d[d:] |= bad_cols[:-d]
        bad_cols_d[:-d] |= bad_cols[d:]
    out[:, bad_cols_d] = 0
    return out


def _trace_rising_curve(bin_img: np.ndarray,
                        max_dy: int = 15,
                        seed_search_frac: float = 0.5,
                        seed_top_frac: float = 0.15,
                        seed_min_support: int = 3,
                        edge_skip: int = 2) -> np.ndarray:
    """Trace a monotonically-rising VGS-vs-Qg curve.

    Walks leftward from a top-right seed (where V_GS = V_drive at the
    curve's right end). At each step the chosen pixel must sit at or
    below the previous y (in image coords), so the trace cannot back-
    track upward into a horizontal gridline or text label above the
    curve. The seed is the first column from the right whose topmost
    dark stretch sits in the top ``seed_top_frac`` slice of the plot
    (V_GS ≳ 0.85·V_drive) — restrictive enough to skip an in-chart
    "V_DD ≈ 16, 32, 64 V" annotation that floats at V≈6 in the upper-
    right of Toshiba "Dynamic Input/Output" charts.

    Suitable for charts with multiple overlapping curves where the
    largest-dark-run trace gets distracted by V_DS curves crossing
    the V_GS curve.
    """
    h, w = bin_img.shape
    trace = np.full(w, np.nan, dtype=np.float64)
    seed_x = None
    seed_y = None
    for x in range(w - 1 - edge_skip,
                   max(0, w - int(seed_search_frac * w)) - 1, -1):
        col = bin_img[:, x] > 0
        ys = np.where(col)[0]
        if len(ys) == 0:
            continue
        top_y = int(ys[0])
        if top_y > seed_top_frac * h:
            continue
        support = 0
        i = top_y
        while i < h and col[i]:
            support += 1
            i += 1
        if support >= seed_min_support:
            seed_y = float(top_y)
            seed_x = x
            break
    if seed_x is None:
        return trace
    trace[seed_x] = seed_y
    cur_y = seed_y
    for x in range(seed_x - 1, -1, -1):
        ys = np.where(bin_img[:, x] > 0)[0]
        if len(ys) == 0:
            continue
        # only accept y >= cur_y (curve only descends as x decreases);
        # tolerate ~2 px of aliasing jitter
        ok = ys[ys >= cur_y - 2]
        if len(ok) == 0:
            continue
        diffs = np.abs(ok - cur_y)
        i = int(np.argmin(diffs))
        if diffs[i] > max_dy:
            continue
        trace[x] = float(ok[i])
        cur_y = max(cur_y, trace[x])
    return trace


def _fill_short_nan_gaps(trace: np.ndarray, max_gap: int = 4) -> np.ndarray:
    """Linearly interpolate across NaN runs of length ≤ ``max_gap``.

    Vertical-gridline masking leaves single-column NaN gaps in the
    trace that break ``_find_plateau_run``'s contiguous-run scan even
    when the surrounding samples sit at the same y. Filling short gaps
    lets the scan see the plateau as one run.
    """
    n = trace.shape[0]
    out = trace.copy()
    i = 0
    while i < n:
        if not math.isnan(out[i]):
            i += 1
            continue
        j = i
        while j < n and math.isnan(out[j]):
            j += 1
        gap_len = j - i
        if gap_len <= max_gap and i > 0 and j < n \
                and not math.isnan(out[i - 1]) and not math.isnan(out[j]):
            y0, y1 = out[i - 1], out[j]
            for k in range(i, j):
                t = (k - (i - 1)) / (j - (i - 1))
                out[k] = y0 + t * (y1 - y0)
        i = j
    return out


def _title_is_dual_axis(title: Optional[str]) -> bool:
    """Detect chart titles that flag a dual-y-axis V_GS / V_DS plot.

    Toshiba's "Dynamic Input/Output Characteristics" charts plot V_GS
    (right axis) and V_DS (left axis) against Q_g on the same frame
    with three V_DS curves at different V_DD values overlapping the
    single V_GS curve. The default per-column "largest dark run" trace
    can't separate them; a monotonic-descent trace can.
    """
    if not title:
        return False
    t = title.lower()
    return 'dynamic input/output' in t or 'dynamic input / output' in t


def find_plateau_raster(page: pymupdf.Page,
                        chart: ChartLocation,
                        dpi: int = 300) -> Optional[RasterPlateauHit]:
    """Image-based fallback when ``viz.curve_extract.find_plateau`` finds
    no vector strokes inside the chart."""
    if not chart.has_calibration():
        return None

    bbox = _plot_interior_bbox(chart)
    arr, sx, sy = _render_chart(page, bbox, dpi=dpi)
    # Wipe out in-chart text (curve labels like "20 V"/"40 V") before the
    # plateau scan — labels sit right on top of the curves and would pull
    # the per-column trace away from the actual line.
    arr = _mask_inchart_text(page, bbox, arr, sy)
    h, w = arr.shape

    if h < 30 or w < 30:
        return None

    # If the chart bbox is the full image (e.g. the Infineon raster
    # fallback hands us the bitmap bbox directly), snap to the actual plot
    # frame so the y-axis calibration aligns with the plot edges rather
    # than the image edges.
    border = _detect_plot_border(arr)
    crop_top_px = 0
    crop_left_px = 0
    if border is not None:
        top_px, bot_px, left_px, right_px = border
        # tight crop, but leave a 1-pixel pad so the curve isn't clipped
        crop_top_px = max(top_px + 1, 0)
        crop_left_px = max(left_px + 1, 0)
        crop_bot_px = min(bot_px - 1, h)
        crop_right_px = min(right_px - 1, w)
        if crop_bot_px > crop_top_px + 20 and crop_right_px > crop_left_px + 20:
            arr = arr[crop_top_px:crop_bot_px, crop_left_px:crop_right_px]
            # Realign the y-tick calibration to the detected plot frame:
            # top of plot = highest tick value, bottom = lowest.
            ymin = min(v for v, _ in chart.y_ticks)
            ymax = max(v for v, _ in chart.y_ticks)
            top_pdf = bbox.y0 + top_px / sy
            bot_pdf = bbox.y0 + bot_px / sy
            # rebuild ticks against the detected frame
            chart = ChartLocation(
                page_num=chart.page_num,
                bbox=chart.bbox,
                y_ticks=[(ymax, top_pdf), (ymin, bot_pdf)],
                x_ticks=chart.x_ticks,
                title=chart.title,
            )
            h, w = arr.shape

    # binarise: ink = dark pixels
    thresh = max(60, int(np.mean(arr) * 0.65))
    bin_img = ((arr < thresh).astype(np.uint8)) * 255

    dual_axis = _title_is_dual_axis(chart.title)

    if dual_axis:
        # Aggressive gridline masking (every 1 V on Toshiba charts) plus
        # a monotonic-descent trace from the top-right seed: the V_GS
        # curve is the only one that reaches V≈V_drive at the rightmost
        # extent and rises monotonically into the seed.
        bin_no_grid = _mask_grid_lines_strict(bin_img)
        trace = _trace_rising_curve(bin_no_grid)
    else:
        bin_no_grid = _mask_grid_lines(bin_img)
        trace = _trace_curve(bin_no_grid)
    if np.isnan(trace).all():
        return None

    # Reject charts whose curve hardly varies — they're not gate-charge
    # curves (probably a V_th-vs-something plot that happens to share
    # the 0..10 V y-axis). The real V_GS curve sweeps from ~0 V to the
    # drive voltage, so the trace spans nearly the full plot height.
    # Dual-axis Toshiba charts get a looser threshold because the strict
    # gridline mask carves out segments below the plateau where the
    # rising-curve trace can't bridge — the trace typically covers
    # V≈V_drive..V_plateau (~45-50% of plot height).
    valid_trace = trace[~np.isnan(trace)]
    min_span_frac = 0.4 if dual_axis else 0.5
    if valid_trace.size > 0:
        trace_span = float(valid_trace.max() - valid_trace.min())
        if trace_span / max(h, 1) < min_span_frac:
            return None

    # Tolerate ~0.5% of plot height of vertical wander; plateaus are
    # flat but aliased strokes jitter by a couple of pixels. Min run
    # length is ~3% of plot width — covers short Miller plateaus on
    # legend-cluttered charts.
    flatness_px = max(2.0, 0.005 * h)
    min_run_px = max(10, int(0.03 * w))

    # The strict gridline mask leaves single-column NaN gaps where
    # vertical gridlines were stripped; without bridging those gaps the
    # plateau-run scan splits one plateau into many short segments.
    scan_trace = _fill_short_nan_gaps(trace, max_gap=4) if dual_axis else trace
    run = _find_plateau_run(scan_trace, flatness_px=flatness_px,
                            min_run_px=min_run_px)
    if run is None and not dual_axis:
        # Default per-column "largest dark run" trace gets distracted
        # by in-chart text annotations ("Id=20A Vds=20V") whose dense
        # glyph strokes outscore the thin curve in their columns,
        # breaking the plateau into short fragments. Fall back to the
        # monotonic rising-curve walk used for Toshiba dual-axis
        # charts: it walks down the curve from a top-right seed and
        # rejects any column whose trace would jump upward into the
        # annotation, leaving the plateau intact.
        rising_trace = _trace_rising_curve(bin_no_grid)
        if not np.isnan(rising_trace).all():
            valid_r = rising_trace[~np.isnan(rising_trace)]
            if valid_r.size > 0 and (valid_r.max() - valid_r.min()) / h >= 0.5:
                rising_scan = _fill_short_nan_gaps(rising_trace, max_gap=4)
                run = _find_plateau_run(rising_scan,
                                        flatness_px=flatness_px,
                                        min_run_px=min_run_px)
    if run is None:
        return None
    x0, x1, plateau_y_px = run

    try:
        a, b = _calibrate_y(chart, bbox.y0, sy)
    except ValueError:
        return None
    # plateau_y_px is in the cropped image; convert back to the
    # rendered-image's pixel coordinates for calibration
    v_pl = a * (plateau_y_px + crop_top_px) + b
    if not (1.0 < v_pl < 10.0):
        return None

    score = (x1 - x0) / w
    return RasterPlateauHit(
        y_pdf=bbox.y0 + (plateau_y_px + crop_top_px) / sy,
        v_pl=round(v_pl, 2),
        score=round(score, 3),
        plateau_run=(x0 + crop_left_px, x1 + crop_left_px),
    )
