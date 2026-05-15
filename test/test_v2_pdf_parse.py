"""
Reference-based validation for ``dslib.v2.parse_datasheet``.

Each entry is (relative_pdf_path, reference_DatasheetFields). Reference data is
copied verbatim from ``test/tests.py::test_pdf_parse`` (and a couple of
neighbouring tests) — the values were hand-verified against the real
datasheets.

Run with::

    python3 test/test_v2_pdf_parse.py
"""
from __future__ import annotations

import math
import os
import sys
from typing import List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dslib.field import DatasheetFields, Field  # noqa: E402
from dslib.v2 import parse_datasheet  # noqa: E402

nan = math.nan

# A reference sample is one of:
#   ('pdf', reference_DatasheetFields, err_threshold)
#   ('pdf', {'symbol': (min, typ, max), ...}, err_threshold)
SAMPLES: List[Tuple[str, object, float]] = [

    # straightforward onsemi sheet, used as a smoke test
    ('datasheets/onsemi/FDD86367.pdf',
     {
         'Qg': (nan, 68.0, 88.0),
         'Qg_th': (nan, 8.8, nan),
         'Qgs': (nan, 22.0, nan),
         'Qgd': (nan, 14.0, nan),
     },
     1e-3),

    # onsemi/FDP047N10 (from test_pdf_parse)
    ('datasheets/onsemi/FDP047N10.pdf',
     {
         'Qg': (nan, 160.0, 210.0),
         'Qgs': (nan, 56.0, nan),
         'Qgd': (nan, 36.0, nan),
     },
     1e-3),

    # nxp/PSMN5R5-100YSFX
    ('datasheets/nxp/PSMN5R5-100YSFX.pdf',
     {
         'Qg': (32.0, 64.0, 95.0),
         'Qgs': (10.3, 17.1, 24.0),
         'Qg_th': (nan, 12.0, nan),
         'Qgs2': (nan, 4.8, nan),
         'Qgd': (3.5, 11.8, 27.1),
     },
     1e-3),

    # infineon/BSB056N10NN3GXUMA2 - from inline ref in test_pdf_parse
    ('datasheets/infineon/BSB056N10NN3GXUMA2.pdf',
     DatasheetFields("infineon", "BSB056N10NN3GXUMA2",
                     fields=[Field("Qg",  nan, 56.0, 74.0, "nC"),
                             Field("Qgs", nan, 17.0, nan,  "nC"),
                             Field("Qgd", nan, 9.7,  nan,  "nC"),
                             Field("Qrr", nan, 174.0, nan, "nC"),
                             Field("trr", nan, 64.0, nan,  "ns"),
                             Field("Coss", nan, 750.0, 1000.0, "pF"),
                             Field("Ciss", nan, 4100.0, 5500.0, "pF"),
                             Field("Vpl", nan, 4.2, nan, "V"),
                             Field("Vsd", nan, 0.9, 1.2, "V"),
                             ]),
     1e-3),

    # infineon/IPT025N15NM6ATMA1
    ('datasheets/infineon/IPT025N15NM6ATMA1.pdf',
     {
         'Qg':    (nan, 105.0, 137.0),
         'Qgd':   (nan, 23.0, 35.0),
         'Qgs':   (nan, 41.0, 53.0),
         'Qg_th': (nan, 26.0, nan),
         'Coss':  (nan, 2300.0, 3000.0),
         'tRise': (nan, 16.0, nan),
         'tFall': (nan, 19.0, nan),
         'Vsd':   (nan, 0.86, 1.0),
     },
     1e-3),

    # vishay/SIR680ADP-T1-RE3
    ('datasheets/vishay/SIR680ADP-T1-RE3.pdf',
     {
         'Qrr': (nan, 70.0, 140.0),
         'Coss': (nan, 614.0, nan),
         'Qgs': (nan, 17.0, nan),
         'Qgd': (nan, 10.0, nan),
         'tRise': (nan, 8.0, 16.0),
         'tFall': (nan, 9.0, 18.0),
     },
     1e-3),

    # ao/AOT66811L
    ('datasheets/ao/AOT66811L.pdf',
     {
         'Vsd': (nan, 0.7, 1.0),
         'Coss': (nan, 1580.0, nan),
         'Qg':  (nan, 77.0, 110.0),
         'Qgs': (nan, 21.0, nan),
         'Qgd': (nan, 15.0, nan),
         'tRise': (nan, 7.0, nan),
         'tFall': (nan, 10.0, nan),
     },
     1e-3),

    # infineon/AUIRF7759L2TR — has split rows
    ('datasheets/infineon/AUIRF7759L2TR.pdf',
     {
         'Qgd': (nan, 62.0, 93.0),
         'Vsd': (nan, nan, 1.3),
     },
     1e-3),

    # ti/CSD19532KTTT
    ('datasheets/ti/CSD19532KTTT.pdf',
     {
         'Qgd': (nan, 5.6, nan),
         'Qgs': (nan, 17.0, nan),
         'Qg_th': (nan, 9.6, nan),
     },
     1e-3),

    # infineon/IPF015N10N5ATMA1
    ('datasheets/infineon/IPF015N10N5ATMA1.pdf',
     {
         'Qg_th': (nan, 36.0, nan),
         'Qgs': (nan, 53.0, nan),
         'Qgd': (nan, 34.0, 51.0),
     },
     1e-3),

    # additional samples derived from test_pdf_parse assertions
    #
    # NOTE: datasheets/infineon/IPI072N10N3G.pdf is excluded — its embedded
    # fonts use a custom encoding that pdfminer can't decode without going
    # through ghostscript (the existing parser falls back to `pdf2pdf
    # method='gs'` for that case; v2 is pure-text and skips it).

    ('datasheets/onsemi/FDP027N08B.pdf',
     {
         'tRise': (nan, 66.0, 142.0),
         'tFall': (nan, 41.0, 92.0),
         'Qgs': (nan, 56.0, nan),
         'Qgs2': (nan, 25.0, nan),
         'Qgd': (nan, 28.0, nan),
     },
     1e-3),

    ('datasheets/st/STL120N8F7.pdf',
     {
         'tRise': (nan, 16.8, nan),
         'tFall': (nan, 15.4, nan),
         'Qrr': (nan, 65.6, nan),
     },
     1e-3),

    ('datasheets/onsemi/NTMFSC004N08MC.pdf',
     {
         'tRise': (nan, 21.5, nan),
         'tFall': (nan, 5.4, nan),
     },
     1e-3),

    ('datasheets/onsemi/FDBL0150N80.pdf',
     {
         'tRise': (nan, 73.0, nan),
         'tFall': (nan, 48.0, nan),
     },
     1e-3),

    ('datasheets/infineon/IRF100B202.pdf',
     {
         'tRise': (nan, 56.0, nan),
         'tFall': (nan, 58.0, nan),
     },
     1e-3),
]


def _ref_to_ds(ref) -> DatasheetFields:
    if isinstance(ref, DatasheetFields):
        return ref
    assert isinstance(ref, dict)
    ds = DatasheetFields("ref", "ref")
    for sym, mtm in ref.items():
        mn, t, mx = mtm
        if all(math.isnan(v) for v in (mn, t, mx)):
            continue
        ds.add(Field(sym, mn, t, mx, "None"))
    return ds


def _format_mtm(f: Field) -> str:
    def s(v):
        return "  nan" if math.isnan(v) else f"{v:>5g}"
    return f"({s(f.min)},{s(f.typ)},{s(f.max)})"


def run_sample(pdf_path: str, ref, err_threshold: float) -> Tuple[int, int, list]:
    """Returns (n_ok, n_expected, missing_symbols)."""
    ref_ds = _ref_to_ds(ref)
    n_expected = len(ref_ds)

    print(f"\n>>> {pdf_path}")
    if not os.path.exists(pdf_path):
        print("    SKIP: file missing")
        return 0, n_expected, list(ref_ds.keys())

    ds = parse_datasheet(pdf_path)
    if not ds:
        print("    no fields extracted")
        return 0, n_expected, list(ref_ds.keys())

    # show every reference symbol and whether we got it right
    n_ok = 0
    missing = []
    for sym in ref_ds.keys():
        ref_f = ref_ds[sym]
        got = ds.fields_filled.get(sym)
        if got is None:
            missing.append(sym)
            print(f"    MISS {sym:<7} ref={_format_mtm(ref_f)}")
            continue
        # compare each of min/typ/max within err_threshold (relative)
        ok = True
        for k in ("min", "typ", "max"):
            rv = getattr(ref_f, k)
            gv = getattr(got, k)
            if math.isnan(rv):
                continue
            if math.isnan(gv):
                ok = False
                break
            if rv == 0:
                if abs(gv) > err_threshold:
                    ok = False
                    break
            else:
                if abs((gv - rv) / rv) > err_threshold:
                    ok = False
                    break
        if ok:
            n_ok += 1
            print(f"    OK   {sym:<7} ref={_format_mtm(ref_f)} got={_format_mtm(got)}")
        else:
            print(f"    BAD  {sym:<7} ref={_format_mtm(ref_f)} got={_format_mtm(got)}")

    return n_ok, n_expected, missing


def main():
    total_ok = 0
    total_exp = 0
    misses_summary = []
    for pdf, ref, eth in SAMPLES:
        ok, exp, miss = run_sample(pdf, ref, eth)
        total_ok += ok
        total_exp += exp
        if miss:
            misses_summary.append((pdf, miss))

    print("\n" + "=" * 60)
    print(f"TOTAL  {total_ok} / {total_exp} reference values matched")
    if misses_summary:
        print(f"\nMissing symbols:")
        for pdf, ms in misses_summary:
            print(f"  {pdf}: {ms}")


if __name__ == "__main__":
    main()
