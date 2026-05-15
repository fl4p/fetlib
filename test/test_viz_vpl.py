"""
Validation for ``viz.find_vpl`` using the Vpl reference values that appear
in ``test/tests.py`` and ``dslib/manual_fields.py``.

Run::

    python3 test/test_viz_vpl.py
"""
from __future__ import annotations

import math
import os
import sys
from typing import List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from viz import find_vpl  # noqa: E402


# (pdf_path, reference_Vpl)
# References are copied from test/tests.py (test_pdf_parse / test_pdf_ocr /
# tests_failing) and dslib/manual_fields.reference_data.
SAMPLES: List[Tuple[str, float]] = [
    ('datasheets/infineon/BSB056N10NN3GXUMA2.pdf', 4.2), # chart title: "14 Typ. gate charge"
    ('datasheets/infineon/IPT025N15NM6ATMA1.pdf', 5.4),
    ('datasheets/infineon/BSC021N08NS5ATMA1.pdf', 4.4), #"Diagram 14 : Typ . gate charge"
    ('datasheets/infineon/BSC025N08LS5ATMA1.pdf', 2.8),
    ('datasheets/infineon/IPB019N08N3GATMA1.pdf', 4.6),
    ('datasheets/infineon/BSZ084N08NS5ATMA1.pdf', 4.7),
    ('datasheets/infineon/IPB033N10N5LFATMA1.pdf', 6.9),
    ('datasheets/infineon/BSZ150N10LS3GATMA1.pdf', 2.7),
    ('datasheets/infineon/IRF150DM115XTMA1.pdf', 5.7),
    ('datasheets/infineon/IPB072N15N3GATMA1.pdf', 5.5),
    ('datasheets/nxp/PSMN3R3-80BS,118.pdf', 6.1),
    ('datasheets/panjit/PSMP050N10NS2_T0_00601.pdf', 5.0),
    ('datasheets/infineon/IPP100N08N3GXKSA1.pdf', 5.2),
    ('datasheets/infineon/BSC050N10NS5ATMA1.pdf', 4.7),
    ('datasheets/vishay/SQJQ480E-T1_GE3.pdf', 3.9),
    ('datasheets/littelfuse/IXTT240N15X4HV.pdf', 5),
    #('datasheets/onsemi/NVCR4LS1D3N08M7A.pdf', 4.2),
]


def main():
    tol = float(os.environ.get('VPL_TOL', 0.5))
    enable_ocr = os.environ.get('VPL_OCR', '').lower() in ('1', 'true', 'yes')

    n_ok = 0
    n_ref = 0
    n_skip = 0
    rows: List[Tuple[str, Optional[float], float, str]] = []

    for path, ref in SAMPLES:
        if not os.path.exists(path):
            rows.append((path, None, ref, 'MISSING'))
            n_skip += 1
            continue
        n_ref += 1
        try:
            est = find_vpl(path, enable_ocr=enable_ocr)
        except Exception as e:
            rows.append((path, None, ref, f'ERROR: {type(e).__name__}: {e}'))
            continue

        if est is None:
            rows.append((path, None, ref, 'no chart'))
            continue

        ok = abs(est - ref) <= tol
        if ok:
            n_ok += 1
        rows.append((path, est, ref, 'OK' if ok else f'OFF ({est - ref:+.2f})'))

    width = max(len(r[0]) for r in rows)
    for path, est, ref, status in rows:
        est_s = f'{est:.2f}' if isinstance(est, float) else '   - '
        print(f'  {path.ljust(width)}  ref={ref:>5.2f}  est={est_s}  [{status}]')

    print()
    print(f'  matched within ±{tol} V: {n_ok} / {n_ref}'
          + (f'  ({n_skip} files missing)' if n_skip else ''))


if __name__ == '__main__':
    main()
