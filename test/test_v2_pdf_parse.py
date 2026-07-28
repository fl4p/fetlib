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
from typing import List, Optional, Tuple

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

    # Littelfuse P-channel sheet: the VSD maximum is encoded as two PDF words
    # ("-" and "3.3").  V2 must join the leading sign rather than discard the
    # body-diode row as non-numeric.
    ('datasheets/littelfuse/IXTR170P10P.pdf',
     {
         'Vsd': (nan, nan, -3.3),
     },
     1e-3),

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

    # One logical row split across two baselines 1.6pt apart, with the unit on
    # the upper half and the numbers on the lower:
    #   y368.7  Qrr                                IF=20A, di/dt=500A/ms   uC
    #   y367.1  Body Diode Reverse Recovery Charge                       1.18
    # Both halves resolve to Qrr, so the lower one is taken as its own value
    # row and the uC above was never consulted -- emitting a bare 1.18 that
    # Field reads as nC, 1000x low. This pins the DIRECTION of the fix, not
    # merely that it runs: 1180 is the microcoulomb reading, 1.18 the bug.
    # Charge cannot be protected by a plausibility floor the way resistance is
    # (Qrr's real population reaches 0.18 nC, so 1.18 is not implausible), so
    # this reference value is the only thing standing between the corpus and a
    # silent 1000x here.
    ('datasheets/ao/AOB66515L.pdf',
     {
         'Qrr': (nan, 1180.0, nan),
     },
     1e-3),
]


# (pdf, symbol, stat, forbidden_value) -- values v2 must NOT produce.
#
# SAMPLES above can only check that expected symbols are right; it never looks
# at what else was extracted, so a whole class of damage is invisible to it.
# The chart-page false positives were exactly that: v2 read a graph's AXIS
# TICKS as a parameter table, and because DatasheetFields.fill merges stats
# across candidates, Id.typ=0.0 landed in the REAL Id rating field where a
# default consumer selects it. 65/65 passed throughout.
#
# 0.0 and 1.0 are axis origins -- that they are the values which appeared is
# the signature of the bug, not a coincidence.
NEGATIVE_SAMPLES = [
    ('datasheets/infineon/IPA65R110CFDXKSA1.pdf', 'Crss', 'typ', 1.0),
    ('datasheets/nxp/GAN3R2-100CBEAZ.pdf', 'Id', 'typ', 0.0),
    ('datasheets/nxp/GAN7R0-150LBEZ.pdf', 'Id', 'typ', 0.0),
]


def run_negative(pdf_path, symbol, stat, forbidden) -> Optional[bool]:
    """True if the forbidden value is absent, None if it could not be checked.

    The absent fixture must NOT read as a pass. Returning True there made a
    partial checkout print "3 / 3 negative checks passed" while running none of
    them -- absence of the PDF encoding absence of the bug. Unlike the positive
    SAMPLES, nothing else in this file opens these three files, so a rename or
    a shallow datasheets clone would retire all three guards silently.
    """
    if not os.path.exists(pdf_path):
        print(f"    UNVERIFIED: {pdf_path} missing -- guard did not run")
        return None
    ds = parse_datasheet(pdf_path)
    f = (ds.fields_filled or {}).get(symbol) if ds else None
    got = getattr(f, stat, math.nan) if f is not None else math.nan
    bad = (got is not None and not math.isnan(got)
           and abs(got - forbidden) <= 1e-9)
    label = "BAD " if bad else "OK  "
    print(f"    {label} {symbol}.{stat} must not be {forbidden} -- got {got}")
    return not bad


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


def main() -> int:
    total_ok = 0
    total_exp = 0
    misses_summary = []
    for pdf, ref, eth in SAMPLES:
        ok, exp, miss = run_sample(pdf, ref, eth)
        total_ok += ok
        total_exp += exp
        if miss:
            misses_summary.append((pdf, miss))

    neg_ok = 0
    neg_unverified = 0
    print("\n>>> negative checks (values v2 must NOT produce)")
    for pdf, sym, stat, bad in NEGATIVE_SAMPLES:
        verdict = run_negative(pdf, sym, stat, bad)
        if verdict is None:
            neg_unverified += 1
        elif verdict:
            neg_ok += 1

    print("\n" + "=" * 60)
    print(f"TOTAL  {total_ok} / {total_exp} reference values matched")
    print(f"       {neg_ok} / {len(NEGATIVE_SAMPLES)} negative checks passed"
          + (f"  ({neg_unverified} UNVERIFIED)" if neg_unverified else ""))
    if misses_summary:
        print(f"\nMissing symbols:")
        for pdf, ms in misses_summary:
            print(f"  {pdf}: {ms}")
    return 0 if (total_ok == total_exp
                 and neg_ok == len(NEGATIVE_SAMPLES)
                 and neg_unverified == 0) else 1


def test_v2_reference_values():
    """Fail-capable entry point.

    This file used to only print. A run where every value regressed still
    exited 0 and reported "TOTAL 3 / 65" to a log nobody reads, so the
    references here could not defend anything -- the same vacuous-assertion
    shape that let `field == 0.62` pass unconditionally elsewhere in this
    suite. Both pytest and the shell now see a real verdict.
    """
    assert main() == 0, "v2 reference values regressed (see output above)"


if __name__ == "__main__":
    sys.exit(main())
