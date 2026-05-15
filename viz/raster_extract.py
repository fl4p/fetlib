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

from viz.chart_finder import ChartLocation


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


def _trace_curve(bin_img: np.ndarray) -> np.ndarray:
    """For each column, return the median y of dark pixels (NaN if none).

    The median is robust against the few stray pixels from anti-aliased
    text / annotations inside the plot.
    """
    h, w = bin_img.shape
    trace = np.full(w, np.nan, dtype=np.float64)
    for x in range(w):
        ys = np.where(bin_img[:, x] > 0)[0]
        if ys.size == 0:
            continue
        trace[x] = float(np.median(ys))
    return trace


def _find_plateau_run(trace: np.ndarray,
                      flatness_px: float,
                      min_run_px: int) -> Optional[Tuple[int, int, float]]:
    """Return (x_start, x_end, plateau_y) for the longest x-span where the
    trace's local variation stays within ``flatness_px``.
    """
    n = trace.shape[0]
    best: Optional[Tuple[int, int, float]] = None

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
            if best is None or (j - i) > (best[1] - best[0]):
                best = (i, j, plateau_y)
        i = j if j > i else i + 1
    return best


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
                        dark_threshold: int = 128,
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

    def _pick_bounds(groups: List[List[int]], max_v: int,
                     counts: np.ndarray, opposite_dim: int
                     ) -> Tuple[int, int]:
        # discard runs glued to the very edge: those are usually page
        # borders, not the plot frame
        groups = [g for g in groups if (g[0] > 1 and g[-1] < max_v - 2)]
        # discard runs that span the *full* opposite dimension — the plot
        # frame has small margins on each side, so its width is < image
        # width. A 100%-wide line is a page-level horizontal rule.
        def is_full(g):
            mean_c = sum(int(counts[i]) for i in g) / len(g)
            return mean_c >= 0.97 * opposite_dim
        groups = [g for g in groups if not is_full(g)]
        if not groups:
            return -1, -1
        top = int(sum(groups[0]) / len(groups[0]))
        bot = int(sum(groups[-1]) / len(groups[-1]))
        return top, bot

    top, bot = _pick_bounds(_group_runs(h_hits), h, row_counts, w)
    left, right = _pick_bounds(_group_runs(v_hits), w, col_counts, h)
    if top < 0 or left < 0 or bot - top < 20 or right - left < 20:
        return None
    return top, bot, left, right


def find_plateau_raster(page: pymupdf.Page,
                        chart: ChartLocation,
                        dpi: int = 300) -> Optional[RasterPlateauHit]:
    """Image-based fallback when ``viz.curve_extract.find_plateau`` finds
    no vector strokes inside the chart."""
    if not chart.has_calibration():
        return None

    bbox = _plot_interior_bbox(chart)
    arr, sx, sy = _render_chart(page, bbox, dpi=dpi)
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

    # strip long horizontal / vertical lines (grid, border, axis)
    bin_no_grid = _mask_grid_lines(bin_img)

    trace = _trace_curve(bin_no_grid)
    if np.isnan(trace).all():
        return None

    flatness_px = max(2.0, 0.005 * h)
    min_run_px = max(10, int(0.07 * w))

    run = _find_plateau_run(trace, flatness_px=flatness_px,
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
