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


def _crop_via_vpc(pdf_path: str, dpi: int) -> Optional[Tuple[bytes, int, str]]:
    """Try ``vpl_from_chart`` to find the gate-charge chart and return a
    (png_bytes, page_num, 'vpc') tuple, or None when no chart is found.

    The chart bounding rectangle is derived from the detected axis tick
    positions (we already do this in ``extract_curves`` — we duplicate just
    the rectangle math here to avoid running the plateau detector when all
    we want is the crop).
    """
    import vpl_from_chart as vpc
    from vpl_from_chart import _pick_best

    doc = fitz.open(pdf_path)
    try:
        charts = vpc.find_gate_charge_charts(doc)
        if not charts:
            return None
        # Run the full pipeline so we can choose the best chart via _pick_best
        # (the title-keyword / axis-resolution scoring).  When a part has
        # several gate-charge-looking charts on different pages, we want the
        # same one the Vpl extractor would pick.
        results, lookup = [], {}
        for c in charts:
            page = doc[c.page_index]
            try:
                inner, tr, _ = vpc.extract_curves(page, c, dpi=300)
                vpl = vpc.find_plateau_vpl(inner, tr)
            except Exception:
                vpl = None
            r = {
                'vpl': vpl,
                'page': c.page_index + 1,
                'x_axis_values': c.x_axis.values,
                'y_axis_values': c.y_axis.values,
                'title': c.nearby_text,
            }
            results.append(r)
            lookup[(r['page'], r['vpl'])] = c
        best = _pick_best(results) if results else None
        if best is None:
            # No plateau was extractable — fall back to the first detected chart.
            chart = charts[0]
        else:
            chart = lookup.get((best['page'], best['vpl']), charts[0])
        page = doc[chart.page_index]

        xs = np.array(chart.x_axis.cx)
        xv = np.array(chart.x_axis.values)
        ys = np.array(chart.y_axis.cy)
        yv = np.array(chart.y_axis.values)
        ax, bx = vpc._linear_fit(xs, xv)
        ay, by = vpc._linear_fit(ys, yv)

        qg0, qg1 = float(np.min(xv)), float(np.max(xv))
        v0, v1 = float(np.min(yv)), float(np.max(yv))
        px0 = (qg0 - bx) / ax
        px1 = (qg1 - bx) / ax
        py0 = (v0 - by) / ay
        py1 = (v1 - by) / ay
        x_lo, x_hi = sorted([px0, px1])
        y_lo, y_hi = sorted([py0, py1])

        # Generous margin so axis labels are also captured.
        rect = fitz.Rect(x_lo - 32, y_lo - 22, x_hi + 22, y_hi + 32) & page.rect

        scale = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
        return pix.tobytes('png'), chart.page_index + 1, 'vpc'
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
    # Pick the highest-scoring plateau hit; if none has a score, fall back to
    # the first chart on the lowest page.
    if valid:
        chart, hit, source = max(valid, key=lambda t: t[1].score)
    else:
        chart, hit, source = pool[0]
        source = source or 'viz'

    doc = fitz.open(pdf_path)
    try:
        page = doc[chart.page_num]
        bbox = chart.bbox
        rect = fitz.Rect(bbox.x0 - 38, bbox.y0 - 28, bbox.x1 + 28, bbox.y1 + 38) & page.rect
        scale = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
        return pix.tobytes('png'), chart.page_num + 1, source or 'viz'
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
