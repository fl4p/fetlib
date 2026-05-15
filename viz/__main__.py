"""CLI: ``python -m viz <pdf>`` prints the located Vpl per chart."""
from __future__ import annotations

import argparse
import sys

from viz import find_in_pdf


def main():
    p = argparse.ArgumentParser(description='Estimate Miller plateau voltage from a MOSFET datasheet PDF.')
    p.add_argument('pdfs', nargs='+')
    p.add_argument('--no-raster', action='store_true',
                   help="don't fall back to image-based extraction")
    args = p.parse_args()

    for path in args.pdfs:
        print(path)
        results = find_in_pdf(path, enable_raster=not args.no_raster)
        if not results:
            print('  no gate-charge chart found')
            continue
        for chart, hit, source in results:
            if hit is None:
                print(f'  p={chart.page_num + 1}  no plateau found  (chart bbox={tuple(round(v, 1) for v in chart.bbox)})')
                continue
            print(f'  p={chart.page_num + 1}  Vpl ≈ {hit.v_pl:.2f} V  via={source}  score={hit.score:.2f}')


if __name__ == '__main__':
    main()
