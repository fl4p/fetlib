"""
Validation for ``dslib.viz.find_vpl``

Run::

    VPL_REQUIRE_ALL=1 python3 test/test_viz_vpl.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from typing import Callable, List, Optional, Tuple



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


def find_vpl_enc(pdf, enable_ocr):
    from dslib.pdf.fix_encoding import fix_pdf_font_encoding
    pdf2 = fix_pdf_font_encoding(pdf)
    import dslib.viz
    return dslib.viz.find_vpl(pdf2, enable_ocr=enable_ocr)


# (pdf_path, reference_Vpl)
# References are copied from test/tests.py (test_pdf_parse / test_pdf_ocr /
# tests_failing) and dslib/manual_fields.reference_data.
SAMPLES: List[Tuple[str, float]] = [
    ('datasheets/st/STWA75N65DM6.pdf', 6.5), # double axis, a lot of annotations
    ('datasheets/ao/AON6220.pdf', 2.5),
    ('datasheets/mcc/MCAC60N15YA-TP.pdf', 4.7),
    ('datasheets/xnrusemi/XR150N04.pdf', 3.1),
    ('datasheets/hxy/AM9435SA-HXY.pdf', 3.5),
    ('datasheets/siliup/SP30N01AGHNP.pdf', 4.8),  # needs ocr

    ('datasheets/ti/CSD19532KTT.pdf', 4.8), # very soft plateau
    ('datasheets/diotec/DI110N15PQ.pdf', 3.2),
    ('datasheets/huayi/HYG009N06NS1C2.pdf', 4.9),
    ('datasheets/good_ark/GSFP1080.pdf', 5),


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
    ('datasheets/toshiba/XPQR8308QB.pdf', 5.5), # double axis, chart has 3 additional Vds curves overlapping the gate charge curve

    # Human-verified samples from docs/vibes/chart-extraction.md, checked with
    # full-curve overlays in ee/out/vpl_human_refs_first5_dsdig_fullcurve.
    ('datasheets/agmsemi/AGM15T13D.pdf', 4.2),  # bright blue curve
    ('datasheets/ao/AOMR62818.pdf', 3.0),  # smooth plateau start
    ('datasheets/ao/AOT286L.pdf', 4.2),  # noisy line
    ('datasheets/infineon/IPW65R019C7.pdf', 5.4),
    ('datasheets/infineon/IRF540NL.pdf', 4.6),  # overlapping test-condition box
    ('datasheets/onsemi/NVMFS5C468NLT1G.pdf', 3.5),  # Qgs/Qgd dimension lines
    ('datasheets/onsemi/NVMYS029N08LHTWG.pdf', 3.0),  # Qgs/Qgd dimension lines
    ('datasheets/onsemi/NVTFWS010N10MCLTAG.pdf', 2.6),  # Qgs/Qgd dimension lines
    ('datasheets/agmsemi/AGM025N13LL.pdf', 4.3),  # rasterized
    ('datasheets/agmsemi/AGM150P10AP.pdf', 3.1),  # rasterized
    ('datasheets/infineon/IAUC28N08S5L230ATMA1.pdf', 3.1),  # rasterized
    ('datasheets/infineon/F3L3MR12W3M1HH11BPSA1.pdf', 7.25),

    # Additional reviewed samples outside this 63-case list:
    # - PSMN1R2-55SLH is hard-gated upstream in datasheet-chart-digitizer after
    #   the local-axis repair.
    # - R6509KND3TL1-HXY and SIHD6N65ET4-GE3-HXY are still off/reference-disputed.

    # Human-verified samples from chart-extraction.md entries 16-40 that are
    # green in the full-curve overlay batch.
    ('datasheets/st/STL70N4LLF5.pdf', 3.0),  # rasterized in source table, vector-readable
    ('datasheets/ao/AOB284L.pdf', 3.95),  # noisy line
    ('datasheets/ao/AOTL66518Q.pdf', 5.5),  # smooth knee
    ('datasheets/nxp/PSMN1R0-30YLD.pdf', 2.6),
    ('datasheets/huayi/HYG016N04LS1B.pdf', 3.6),  # rasterized
    ('datasheets/hxy/SIS444DN-T1-GE3-HXY.pdf', 3.0),
    ('datasheets/crmicro/CRTT020N04N.pdf', 5.0),
    # GT085N10MH is green in the overlay harness but was observed to drift in
    # a clean review venv, so keep it out of the hard dslib.viz regression set.

    #AOTF288L
]

# SAMPLES = SAMPLES[:20]

EXPECTED_SAMPLE_COUNT = 63
Row = Tuple[str, Optional[float], float, str]


def _evaluate_samples(
    samples: List[Tuple[str, float]],
    *,
    estimator: Callable[[str], Optional[float]],
    tol: float,
    require_all: bool,
) -> Tuple[List[Row], int, int, int, int]:
    """Evaluate a corpus while keeping missing-fixture policy explicit."""

    n_ok = 0
    n_ref = 0
    n_skip = 0
    n_fail = 0
    rows: List[Row] = []

    for path, ref in samples:
        if not os.path.exists(path):
            rows.append((path, None, ref, 'MISSING'))
            n_skip += 1
            if require_all:
                n_fail += 1
            continue
        n_ref += 1
        try:
            est = estimator(path)
        except Exception as e:
            rows.append((path, None, ref, f'ERROR: {type(e).__name__}: {e}'))
            n_fail += 1
            continue

        if est is None:
            rows.append((path, None, ref, 'no chart'))
            n_fail += 1
            continue

        ok = abs(est - ref) <= tol
        if ok:
            n_ok += 1
        else:
            n_fail += 1
        rows.append((path, est, ref, 'OK' if ok else f'OFF ({est - ref:+.2f})'))

    return rows, n_ok, n_ref, n_skip, n_fail


def test_main():
    if len(SAMPLES) != EXPECTED_SAMPLE_COUNT:
        raise AssertionError(
            f'Vpl corpus size changed: {len(SAMPLES)} != {EXPECTED_SAMPLE_COUNT}'
        )
    tol = float(os.environ.get('VPL_TOL', 0.5))
    require_all = os.environ.get('VPL_REQUIRE_ALL', '').lower() in ('1', 'true', 'yes')
    rows, n_ok, n_ref, n_skip, n_fail = _evaluate_samples(
        SAMPLES,
        estimator=find_vpl,
        tol=tol,
        require_all=require_all,
    )

    width = max(len(r[0]) for r in rows)
    for path, est, ref, status in rows:
        est_s = f'{est:.2f}' if isinstance(est, float) else '   - '
        print(f'  {path.ljust(width)}  ref={ref:>5.2f}  est={est_s}  [{status}]')

    print()
    print(f'  matched within ±{tol} V: {n_ok} / {n_ref}'
          + (f'  ({n_skip} files missing)' if n_skip else ''))
    if n_fail:
        raise SystemExit(1)


class VplRegressionRunnerTests(unittest.TestCase):
    def test_missing_policy_and_unresolved_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = [(os.path.join(tmp, 'missing.pdf'), 4.0)]
            relaxed = _evaluate_samples(
                missing,
                estimator=lambda _path: 4.0,
                tol=0.5,
                require_all=False,
            )
            strict = _evaluate_samples(
                missing,
                estimator=lambda _path: 4.0,
                tol=0.5,
                require_all=True,
            )
        self.assertEqual(relaxed[3:], (1, 0))
        self.assertEqual(strict[3:], (1, 1))

        with tempfile.NamedTemporaryFile(suffix='.pdf') as pdf:
            unresolved = _evaluate_samples(
                [(pdf.name, 4.0)],
                estimator=lambda _path: None,
                tol=0.5,
                require_all=True,
            )
        self.assertEqual(unresolved[3:], (0, 1))


if __name__ == '__main__':
    test_main()
