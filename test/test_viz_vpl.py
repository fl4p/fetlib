"""
Validation for ``viz.find_vpl`` using the Vpl reference values that appear
in ``test/tests.py`` and ``dslib/manual_fields.py``.

Run::

    python3 test/test_viz_vpl.py
"""
from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

sys.path.insert(0, '/opt/homebrew/bin') # PATH="$PATH:/opt/homebrew/bin"

from dslib.viz import find_vpl  # noqa: E402


def find_vpl_(pdf, enable_ocr=False):
    from apps.vpl_from_chart import vpl_from_pdf, _pick_best
    vpl = _pick_best(vpl_from_pdf(pdf, enable_ocr=enable_ocr))
    if vpl is None:
        return None
    return vpl['vpl']


# (pdf_path, reference_Vpl)
# References are copied from test/tests.py (test_pdf_parse / test_pdf_ocr /
# tests_failing) and dslib/manual_fields.reference_data.
SAMPLES: List[Tuple[str, float]] = [
    ('datasheets/infineon/BSB056N10NN3GXUMA2.pdf', 4.2),  # chart title: "14 Typ. gate charge"
    ('datasheets/infineon/IPT025N15NM6ATMA1.pdf', 5.4),
    ('datasheets/infineon/BSC021N08NS5ATMA1.pdf', 4.4),  # "Diagram 14 : Typ . gate charge"
    ('datasheets/infineon/BSC025N08LS5ATMA1.pdf', 2.8),
    ('datasheets/infineon/IPB019N08N3GATMA1.pdf', 4.6),
    ('datasheets/infineon/BSZ084N08NS5ATMA1.pdf', 4.7),
    #('datasheets/infineon/IPB033N10N5LFATMA1.pdf', 6.9),  # needs OCR
    #('datasheets/infineon/BSZ150N10LS3GATMA1.pdf', 2.7),  # needs OCR
    #('datasheets/infineon/BSC050N10NS5ATMA1.pdf', 4.7),  # needs OCR
    ('datasheets/infineon/IRF150DM115XTMA1.pdf', 5.7),
    ('datasheets/infineon/IPB072N15N3GATMA1.pdf', 5.5),
    ('datasheets/nxp/PSMN3R3-80BS,118.pdf', 6.1),
    ('datasheets/panjit/PSMP050N10NS2_T0_00601.pdf', 5.0),
    ('datasheets/infineon/IPP100N08N3GXKSA1.pdf', 5.2),
    ('datasheets/vishay/SQJQ480E-T1_GE3.pdf', 3.9),
    ('datasheets/littelfuse/IXTT240N15X4HV.pdf', 5),
    ('datasheets/onsemi/FDA032N08.pdf', 5.5),
    ('datasheets/onsemi/NVCR4LS1D3N08M7A.pdf', 4.2),
    ('datasheets/ti/CSD19501KCS.pdf', 4.25),
    ('datasheets/ti/CSD19532KTT.pdf', 4.8),
    ('datasheets/mcc/MCAC100N08Y-TP.pdf', 5.1),
    ('datasheets/mcc/MCP75N10Y-BP.pdf', 4.05),
    ('datasheets/ti/TPS1100.pdf', 3.1),
    ('datasheets/infineon/IPW60R060C7.pdf', 5.0),
    ('datasheets/infineon/IPI65R190CFD.pdf', 6.4),
    ('datasheets/infineon/IPT013N08NM5LFATMA1.pdf', 9.25),
    ('datasheets/epc_space/EPC7018GSH.pdf', 2.6),
    ('datasheets/infineon/IRFS4310TRRPBF.pdf', 6.5),
    ('datasheets/vishay/SIJ482DP-T1-GE3.pdf', 2.9),
    ('datasheets/infineon/IRFH7110.pdf', 4.6),
    ('datasheets/vishay/SUP85N15-21.pdf', 5.7),
    ('datasheets/ao/AOLF66910.pdf', 4.2),
    ('datasheets/huayi/HY3912W.pdf', 5.35),
    ('datasheets/goford/G200N10K.pdf', 4.5),
    ('datasheets/nxp/PSMN6R7-40MSD.pdf', 4.75),
    ('datasheets/st/STB55NF06LT4.pdf', 3),
    ('datasheets/agmsemi/AGM035N10D.pdf', 4.3),

    #AOTF288L
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
