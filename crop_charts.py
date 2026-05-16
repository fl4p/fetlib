"""
Crop the gate-charge chart from every part's datasheet PDF and save it as
``crops/<mfr>/<mpn>/qg.webp``.

For each ``Part`` in ``dslib.store.parts_db``:
  1. Locate the part's datasheet PDF via ``DiscoveredPart.get_ds_path()``.
  2. Try ``vpl_from_chart`` (vector-text-layer detection) first.
  3. Fall back to ``viz.find_in_pdf`` (vector + raster detection) on failure.
  4. Render the detected chart region and write it as a WebP image.

Existing crops are skipped unless ``--force`` is set.

Usage::

    python3 crop_charts.py                         # crop every part
    python3 crop_charts.py --mfr infineon          # restrict by manufacturer
    python3 crop_charts.py --mpn IRFB4110          # one specific part
    python3 crop_charts.py --limit 50              # first N parts only
    python3 crop_charts.py --force                 # re-render existing crops
    python3 crop_charts.py -j 8                    # 8-way parallelism
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Tuple

import numpy as np
import pymupdf as fitz

from dslib.store import Part, parts_db


# Where the crops land.  Tweak via the CLI if needed.
DEFAULT_OUT_ROOT = 'crops'


def _ds_path(part: Part) -> Optional[str]:
    """Locate the datasheet PDF for a Part, or None when unavailable."""
    disc = part.discovered
    if disc is None:
        return None
    try:
        path = disc.get_ds_path()
    except Exception:
        return None
    return path if path and os.path.isfile(path) else None


def _draw_arrow(draw, x1, y1, x2, y2, color, width=2, head=8):
    """Draw a line between two points with arrowheads at each end."""
    import math
    draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    spread = 0.45
    # head at (x2, y2)
    for off in (math.pi - spread, math.pi + spread):
        hx = x2 + head * math.cos(ang + off)
        hy = y2 + head * math.sin(ang + off)
        draw.line([(x2, y2), (hx, hy)], fill=color, width=width)
    # head at (x1, y1)
    for off in (-spread, spread):
        hx = x1 + head * math.cos(ang + off)
        hy = y1 + head * math.sin(ang + off)
        draw.line([(x1, y1), (hx, hy)], fill=color, width=width)


def _load_font(size: int):
    from PIL import ImageFont
    for cand in (
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
        '/Library/Fonts/Arial.ttf',
        'C:/Windows/Fonts/arial.ttf',
    ):
        if os.path.isfile(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def _annotate(png_bytes: bytes,
              plateau_px: Tuple[float, float, float],   # (x_lo, x_hi, y)
              baseline_px: Tuple[float, float],         # (x, y) of (Q=0, V=0)
              vpl: float,
              qgs_value: float,
              qgd_value: float) -> bytes:
    """Draw Vpl + Q_gs + Q_gd dimension lines on the crop and return WebP-
    ready PNG bytes.  All px coordinates are in the rasterised crop's
    coordinate system."""
    from io import BytesIO
    from PIL import Image, ImageDraw
    img = Image.open(BytesIO(png_bytes)).convert('RGB')
    W, H = img.size
    draw = ImageDraw.Draw(img)
    color = (200, 30, 30)        # red
    head = max(6, int(W * 0.012))
    font = _load_font(max(11, int(W * 0.025)))
    x_lo, x_hi, y_plateau = plateau_px
    base_x, base_y = baseline_px

    # 1) Vertical Vpl dimension line just left of the chart's left edge
    #    (or just inside if the left margin is too tight).
    vpl_x = base_x - max(10, int(W * 0.025))
    if vpl_x < 6:
        vpl_x = base_x + max(10, int(W * 0.025))
    if vpl is not None and y_plateau is not None and base_y is not None:
        _draw_arrow(draw, vpl_x, base_y, vpl_x, y_plateau, color, width=2, head=head)
        label = f'Vpl = {vpl:.2f} V'
        tx = vpl_x + 4 if vpl_x < base_x else vpl_x - 90
        ty = (base_y + y_plateau) / 2 - 8
        draw.text((tx, ty), label, fill=color, font=font)

    # 2) Horizontal Q_gs + Q_gd dimension bars, drawn well *above* the plateau
    #    so they don't overlap the curve.  Use whichever gap is more generous:
    #    25 % of the plateau-to-baseline span, or a fixed minimum.  Both bars
    #    sit at the same y so they read as one continuous dimension chain.
    if x_hi > x_lo and qgs_value > 0:
        gap = max(int(W * 0.06), int((base_y - y_plateau) * 0.25))
        ann_y = int(y_plateau - gap)
        # Stay safely inside the visible area.
        ann_y = max(ann_y, int(H * 0.04))

        small = _load_font(max(10, int(W * 0.022)))

        # Q_gs bar from baseline x to plateau start x.
        _draw_arrow(draw, base_x, ann_y, x_lo, ann_y, color, width=2, head=head)
        qgs_label = f'Qgs ≈ {qgs_value:.0f} nC'
        tw = draw.textlength(qgs_label, font=small) if hasattr(draw, 'textlength') else len(qgs_label)*6
        tx = (base_x + x_lo) / 2 - tw / 2
        draw.text((tx, ann_y - int(W * 0.03)), qgs_label, fill=color, font=small)

        # Q_gd bar from plateau start to plateau end.
        _draw_arrow(draw, x_lo, ann_y, x_hi, ann_y, color, width=2, head=head)
        qgd_label = f'Qgd ≈ {qgd_value:.0f} nC'
        tw = draw.textlength(qgd_label, font=small) if hasattr(draw, 'textlength') else len(qgd_label)*6
        tx = (x_lo + x_hi) / 2 - tw / 2
        draw.text((tx, ann_y + 4), qgd_label, fill=color, font=small)

    buf = BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def _crop_via_vpc(pdf_path: str, dpi: int) -> Optional[Tuple[bytes, int, str]]:
    """Try ``vpl_from_chart`` to find the gate-charge chart and return a
    (png_bytes, page_num, 'vpc') tuple, or None when no chart is found.

    The crop is annotated with Vpl / Q_gs / Q_gd dimension lines when a
    plateau is detected.
    """
    import vpl_from_chart as vpc
    from vpl_from_chart import _pick_best

    doc = fitz.open(pdf_path)
    try:
        charts = vpc.find_gate_charge_charts(doc)
        if not charts:
            return None

        # Run the full pipeline so we can choose the best chart AND keep the
        # plateau coordinates of the chosen candidate for annotation.
        evaluated = []   # list of (ChartFrame, vpl, plateau_seg_pixels)
        for c in charts:
            page = doc[c.page_index]
            try:
                inner, tr, dbg = vpc.extract_curves(page, c, dpi=300)
                vpl = vpc.find_plateau_vpl(inner, tr, debug=dbg)
            except Exception:
                vpl, dbg = None, None
            seg = dbg.get('plateau_segment') if dbg else None  # (y, x_lo, x_hi) in inner-mask coords
            inner_off = dbg.get('inner_origin') if dbg else (0, 0)
            scale_render = dbg.get('scale', 300/72) if dbg else 300/72
            evaluated.append({
                'chart': c, 'vpl': vpl, 'seg': seg,
                'inner_off': inner_off, 'scale_render': scale_render,
                'render_x0_pdf': dbg['pdf_rect'][0] if dbg else None,
                'render_y0_pdf': dbg['pdf_rect'][1] if dbg else None,
            })

        # Pick the best the same way _pick_best does for refreshing specs.
        results = [{
            'vpl': e['vpl'], 'page': e['chart'].page_index + 1,
            'x_axis_values': e['chart'].x_axis.values,
            'y_axis_values': e['chart'].y_axis.values,
            'title': e['chart'].nearby_text,
        } for e in evaluated]
        best = _pick_best(results) if any(r['vpl'] is not None for r in results) else None
        if best is None:
            chosen = evaluated[0]
        else:
            chosen = next(
                (e for e in evaluated
                 if e['chart'].page_index + 1 == best['page']
                 and e['vpl'] == best['vpl']),
                evaluated[0],
            )
        chart = chosen['chart']
        vpl = chosen['vpl']
        seg = chosen['seg']
        page = doc[chart.page_index]

        # Axis transform: Qg = a_x * pdf_x + b_x;  Vgs = a_y * pdf_y + b_y
        xs = np.array(chart.x_axis.cx); xv = np.array(chart.x_axis.values)
        ys = np.array(chart.y_axis.cy); yv = np.array(chart.y_axis.values)
        # For P-channel parts the axis values are flipped to absolute by
        # _axis_arrays; mirror that so labels stay positive.
        if yv.max() <= 0:
            yv = -yv
        a_x, b_x = vpc._linear_fit(xs, xv)
        a_y, b_y = vpc._linear_fit(ys, yv)

        qg0, qg1 = float(np.min(xv)), float(np.max(xv))
        v0, v1 = float(np.min(yv)), float(np.max(yv))
        x_lo_pdf = min((qg0 - b_x) / a_x, (qg1 - b_x) / a_x)
        x_hi_pdf = max((qg0 - b_x) / a_x, (qg1 - b_x) / a_x)
        y_lo_pdf = min((v0 - b_y) / a_y, (v1 - b_y) / a_y)
        y_hi_pdf = max((v0 - b_y) / a_y, (v1 - b_y) / a_y)

        crop_rect = fitz.Rect(x_lo_pdf - 32, y_lo_pdf - 22,
                              x_hi_pdf + 22, y_hi_pdf + 32) & page.rect
        scale = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                              clip=crop_rect, alpha=False)
        png = pix.tobytes('png')

        # If we have a plateau segment, annotate.
        if vpl is not None and seg is not None:
            seg_y, seg_x_lo, seg_x_hi = seg
            inner_x, inner_y = chosen['inner_off']
            render_x0 = chosen['render_x0_pdf']
            render_y0 = chosen['render_y0_pdf']
            render_scale = chosen['scale_render']
            # plateau in PDF coords
            pl_pdf_y = (seg_y + inner_y) / render_scale + render_y0
            pl_pdf_x_lo = (seg_x_lo + inner_x) / render_scale + render_x0
            pl_pdf_x_hi = (seg_x_hi + inner_x) / render_scale + render_x0
            # baseline (Q=0, V=0) in PDF coords
            base_pdf_y = (0.0 - b_y) / a_y
            base_pdf_x = (0.0 - b_x) / a_x

            def to_px(p_pdf, axis):
                if axis == 'x':
                    return (p_pdf - crop_rect.x0) * scale
                return (p_pdf - crop_rect.y0) * scale

            pl_px = (to_px(pl_pdf_x_lo, 'x'),
                     to_px(pl_pdf_x_hi, 'x'),
                     to_px(pl_pdf_y, 'y'))
            base_px = (to_px(base_pdf_x, 'x'),
                       to_px(base_pdf_y, 'y'))
            qgs_value = a_x * pl_pdf_x_lo + b_x
            qgd_value = a_x * (pl_pdf_x_hi - pl_pdf_x_lo)
            png = _annotate(png, pl_px, base_px,
                            float(vpl), float(qgs_value), float(qgd_value))

        return png, chart.page_index + 1, 'vpc'
    finally:
        doc.close()


def _crop_via_viz(pdf_path: str, dpi: int) -> Optional[Tuple[bytes, int, str]]:
    """Fall back to ``viz.find_in_pdf`` for charts that vpc can't see (raster
    chart axes, title-anchored Infineon images, …).
    """
    try:
        from viz import find_in_pdf
    except Exception:
        return None
    try:
        hits = find_in_pdf(pdf_path, enable_raster=True, enable_ocr=False)
    except Exception:
        return None
    if not hits:
        return None

    valid = [(c, h, s) for c, h, s in hits if h is not None]
    pool = valid or hits
    if valid:
        chart, hit, source = max(valid, key=lambda t: t[1].score)
    else:
        chart, hit, source = pool[0]
        source = source or 'viz'

    doc = fitz.open(pdf_path)
    try:
        page = doc[chart.page_num]
        bbox = chart.bbox
        rect = fitz.Rect(bbox.x0 - 38, bbox.y0 - 28,
                         bbox.x1 + 28, bbox.y1 + 38) & page.rect
        scale = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
        png = pix.tobytes('png')

        # Annotate if we have a plateau hit and at least two tick anchors per axis.
        if (hit is not None and hit.segment is not None
                and len(chart.y_ticks) >= 2 and len(chart.x_ticks) >= 2):
            # Linear fit: value = a * pdf + b  using the tick (value, pdf) pairs.
            y_vals = np.array([v for v, _ in chart.y_ticks])
            y_pdf  = np.array([p for _, p in chart.y_ticks])
            x_vals = np.array([v for v, _ in chart.x_ticks])
            x_pdf  = np.array([p for _, p in chart.x_ticks])
            if y_vals.max() <= 0:
                y_vals = -y_vals
            ay = np.polyfit(y_pdf, y_vals, 1)
            ax = np.polyfit(x_pdf, x_vals, 1)
            a_y, b_y = float(ay[0]), float(ay[1])
            a_x, b_x = float(ax[0]), float(ax[1])

            seg = hit.segment
            pl_pdf_x_lo = min(seg.x0, seg.x1)
            pl_pdf_x_hi = max(seg.x0, seg.x1)
            pl_pdf_y = hit.y_pdf
            base_pdf_y = (0.0 - b_y) / a_y if a_y != 0 else bbox.y1
            base_pdf_x = (0.0 - b_x) / a_x if a_x != 0 else bbox.x0

            def to_px(p_pdf, axis):
                if axis == 'x':
                    return (p_pdf - rect.x0) * scale
                return (p_pdf - rect.y0) * scale

            pl_px = (to_px(pl_pdf_x_lo, 'x'),
                     to_px(pl_pdf_x_hi, 'x'),
                     to_px(pl_pdf_y, 'y'))
            base_px = (to_px(base_pdf_x, 'x'),
                       to_px(base_pdf_y, 'y'))
            qgs_value = a_x * pl_pdf_x_lo + b_x
            qgd_value = a_x * (pl_pdf_x_hi - pl_pdf_x_lo)
            png = _annotate(png, pl_px, base_px,
                            float(hit.v_pl), float(qgs_value), float(qgd_value))

        return png, chart.page_num + 1, source or 'viz'
    finally:
        doc.close()


def _save_webp(png_bytes: bytes, out_path: str, quality: int) -> None:
    """Convert a PNG byte buffer to WebP via Pillow and write it to disk."""
    from io import BytesIO
    from PIL import Image
    img = Image.open(BytesIO(png_bytes))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, 'WEBP', quality=quality, method=4)


def _process_one(mfr: str, mpn: str, ds_path: str,
                 out_root: str, dpi: int, quality: int,
                 force: bool) -> Tuple[str, List[str]]:
    """Worker: returns (status, log_lines).

    ``status`` is one of:
      'saved-vpc', 'saved-viz', 'skipped-existing', 'no-chart', or 'error'.
    """
    log: List[str] = []
    out_path = os.path.join(out_root, mfr, mpn, 'qg.webp')

    if not force and os.path.exists(out_path):
        return 'skipped-existing', log

    if not os.path.isfile(ds_path):
        log.append(f'  · datasheet missing: {ds_path}')
        return 'error', log

    # Try the vector pipeline first.
    try:
        crop = _crop_via_vpc(ds_path, dpi)
    except Exception as exc:  # noqa: BLE001
        crop = None
        log.append(f'  · vpc error: {type(exc).__name__}: {exc}')

    if crop is None:
        # Fall back to viz (covers rasterised charts + title-anchored cases).
        try:
            crop = _crop_via_viz(ds_path, dpi)
        except Exception as exc:  # noqa: BLE001
            crop = None
            log.append(f'  · viz error: {type(exc).__name__}: {exc}')

    if crop is None:
        log.append('  · no chart detected by either extractor')
        return 'no-chart', log

    png_bytes, page_num, source = crop
    try:
        _save_webp(png_bytes, out_path, quality)
    except Exception as exc:  # noqa: BLE001
        log.append(f'  · WebP write failed: {type(exc).__name__}: {exc}')
        return 'error', log

    log.append(f'  + saved (page {page_num}, via {source}) → {out_path}')
    return 'saved-vpc' if source == 'vpc' else 'saved-viz', log


def _filter_parts(parts: dict,
                  mfr: Optional[str], mpn: Optional[str]) -> List[Part]:
    out = list(parts.values())
    if mfr:
        out = [p for p in out if p.mfr == mfr]
    if mpn:
        out = [p for p in out if p.mpn == mpn]
    return out


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--out-root', default=DEFAULT_OUT_ROOT,
                   help=f'output directory (default: {DEFAULT_OUT_ROOT}/)')
    p.add_argument('--mfr', help='only parts with this manufacturer')
    p.add_argument('--mpn', help='only this exact MPN')
    p.add_argument('--limit', type=int, default=0,
                   help='process at most N parts (0 = all)')
    p.add_argument('--force', action='store_true',
                   help='overwrite existing qg.webp files')
    p.add_argument('--dpi', type=int, default=200,
                   help='rasterisation DPI for the crop (default: 200)')
    p.add_argument('--quality', type=int, default=85,
                   help='WebP quality 0-100 (default: 85)')
    p.add_argument('-j', '--jobs', type=int, default=1,
                   help='number of parts to process in parallel '
                        '(1 = serial; >1 uses main.run_parallel)')
    args = p.parse_args()

    print('loading parts_db...')
    parts_map = parts_db.load()
    print(f'loaded {len(parts_map)} parts')

    candidates = _filter_parts(parts_map, args.mfr, args.mpn)
    print(f'after mfr/mpn filter: {len(candidates)} candidates')

    # Pre-filter parts that have a datasheet on disk.
    todo: List[Tuple[str, str, str]] = []   # (mfr, mpn, ds_path)
    for part in candidates:
        ds = _ds_path(part)
        if ds is None:
            continue
        todo.append((part.mfr, part.mpn, ds))

    print(f'parts with a datasheet PDF: {len(todo)} / {len(candidates)}')
    if args.limit and len(todo) > args.limit:
        todo = todo[:args.limit]
        print(f'  --limit applied: processing first {len(todo)}')

    if not todo:
        print('nothing to do.')
        return

    counts = {'saved-vpc': 0, 'saved-viz': 0, 'skipped-existing': 0,
              'no-chart': 0, 'error': 0}

    if args.jobs > 1:
        from main import run_parallel
        jobs = {
            (mfr, mpn): (_process_one, mfr, mpn, ds,
                         args.out_root, args.dpi, args.quality, args.force)
            for mfr, mpn, ds in todo
        }
        results = run_parallel(jobs, args.jobs, 'multiprocessing', verbose=0)
        for (mfr, mpn), result in results.items():
            if result is None:
                counts['error'] += 1
                print(f'[{mfr}/{mpn}] worker returned None')
                continue
            status, log_lines = result
            counts[status] = counts.get(status, 0) + 1
            if log_lines and status != 'skipped-existing':
                print(f'[{mfr}/{mpn}]')
                for line in log_lines:
                    print(line)
    else:
        for i, (mfr, mpn, ds) in enumerate(todo, 1):
            print(f'[{i}/{len(todo)}] {mfr}/{mpn}')
            status, log_lines = _process_one(
                mfr, mpn, ds, args.out_root, args.dpi, args.quality, args.force)
            counts[status] = counts.get(status, 0) + 1
            for line in log_lines:
                print(line)

    print()
    print('summary:')
    for status in ('saved-vpc', 'saved-viz', 'skipped-existing', 'no-chart', 'error'):
        print(f'  {status:>18s}: {counts.get(status, 0)}')


if __name__ == '__main__':
    main()
