"""Audit parsed Rds_on against INDEPENDENT witnesses. Reports; changes nothing.

Two witness kinds, both external to the PDF parse:

  catalog  part.specs.Rds_on_10v_max, scraped by dslib/discovery from vendor parametric
           data. Independent of the parse: MosfetBasicSpecs is only ever constructed in
           dslib/discovery, and the DB's Rds_on comes from read_sheet/tabular/v2. The mass
           of exactly-1.0 ratios is genuine agreement (catalogs quote the datasheet max),
           not the DB agreeing with itself.

  mpn      resistance encoded in the part number. FAMILY-GATED, never applied by pattern
           similarity -- see MPN_FAMILIES for why that rule exists.

WHY THIS IS THE SOUND DETECTOR
    A self-inconsistency scan (compare the sheet against itself) was built and rejected: a
    fixed-line window with one unit applied to every number in it swallows `ID=120 A` and
    `Qg=65 nC` and calls them resistances -- it reproduces the wrong-cell failure it is
    meant to detect, and page separation does not restore cell association. Worse, even a
    correct hit cannot say WHICH of the two readings is wrong (IPP114N12N3GXKSA1 contradicts
    itself 11.4 vs 11400, and the STORED value is the right one). An external witness
    arbitrates; the sheet arguing with itself does not. Column geometry belongs in dslib/v2.

CLASSIFICATION -- digits, not ratio, and only two classes
    A near-decade ratio is a PRE-FILTER, not a classifier. A genuine dropped decimal or
    dropped SI prefix moves the point and preserves the digits EXACTLY: 0.11 -> 11,
    88 -> 88000. Five records here sit inside a +-0.17 log10 band of x10 yet read 49
    against 5.4, 49 against 5.7, 99 against 7.8 -- digits differ, so ratio alone would have
    mislabelled all five.

    The two classes are SCALE-LIKE and NON-SCALE DISAGREEMENT, and they are named for what
    the arithmetic proves rather than for a cause. Comparing two numbers cannot distinguish
    a wrong-cell capture from a wrong CATALOG entry, a typ-vs-max or condition mismatch, or
    OCR-mangled digits. Those are MECHANISMS and require reading the PDF, so they live in
    CONFIRMED_MECHANISM, one curated entry per part actually inspected. An earlier version
    of this file called all 13 non-scale rows "wrong-cell" on the strength of two that had
    been checked; that was a claim the code could not support.
"""
import math
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from dslib.store import datasheets_db  # noqa: E402

# Family -> (pattern, group->milliohm). Calibrated against catalog; see calibrate().
#
# GATED BY MANUFACTURER, and that is not caution for its own sake -- it has caught two
# systematic errors that pattern similarity would have introduced:
#   nexperia  BUK7Y3R1-80MX: the Vishay '-(\d+)M' pattern matches the '-80M' of the 80 V
#             RATING, reporting a correct 3.1 mOhm part as a 26x scale error.
#   ts        TSM089N08 decodes to 89 but is 8.9 mOhm -- that family encodes DECI-milliohms.
#             All 25 checkable records sit at ratio 0.100 with no spread. Adding it would
#             have injected a systematic x10 into the tool built to find x10 errors.
MPN_FAMILIES = {
    'infineon': (re.compile(r'^I[A-Z]{1,3}\d{2}[RT](\d{3})'), None),
    'nce': (re.compile(r'^NCE[SP]?\d{3}[PN](\d{3})'), None),
    'vishay': (re.compile(r'-(\d{1,3})M(\d)?'), 'decimal'),
}

# Families deliberately NOT used, recorded so nobody re-adds them from pattern shape.
MPN_REJECTED = {
    'ts': 'ratios pinned at 0.100 (n=25): encodes deci-milliohm, not milliohm',
    'xnrusemi': 'n=1 decodable and no catalog entry: CANNOT be calibrated. XR65R110T is a '
                'hand-verified singleton (PDF says 0.11/0.14 Ohm), not a family rule',
    'nxp': 'BUK7Y3R1-80MX: resistance is the 3R1 before the dash; the -80M is the voltage',
}

# Mechanisms established by READING THE PDF, one entry per part actually checked. Absence
# here means "not investigated", never "no mechanism" -- the classifier above deliberately
# refuses to guess one.
# KEYED BY (mfr, mpn), because that is the audited identity. An mpn-only key lets a clone
# or a vendor collision attach a mechanism derived from a DIFFERENT company's PDF -- a
# curated fact silently misattributed, which is worse than having none.
CONFIRMED_MECHANISM = {
    ('st', 'STF40N60M2'): 'dropped SI prefix: p1 says "88 mOhm", p2 table says 78/88 "Ohm"',
    ('st', 'STFW40N60M2'): 'dropped SI prefix: p1 says "88 mOhm", p2 table says 78/88 "Ohm"',
    ('infineon', 'BSC037N08NS5T'): 'wrong cell: sheet only ever states 3.2/4.4/3.7/5.3 mOhm; 180 is absent',
    ('infineon', 'IPB50R140CPATMA1'): 'unitless Rds_on hitting the mOhm default; sheet quotes ohms',
    ('infineon', 'IPP60R125CPXKSA1'): 'unitless Rds_on hitting the mOhm default; sheet quotes ohms',
    ('infineon', 'IPP60R099CPXKSA1'): 'unitless Rds_on hitting the mOhm default; sheet quotes ohms',
    ('infineon', 'IPP50R140CPXKSA1'): 'unitless Rds_on hitting the mOhm default; sheet quotes ohms',
    # XR65R110T is the one confirmed dropped DECIMAL (font maps 0 and . to control glyphs,
    # so 0.11 parses as 11) but it has no catalog entry and xnrusemi cannot be calibrated,
    # so it never reaches this table. Recorded here because it is the case that motivated
    # the whole pass, and its absence from the output is the actual finding.
    ('xnrusemi', 'XR65R110T'): 'dropped decimal via mojibake: cell reads \x13\x1111 for 0.11 (no catalog)',
}

DISAGREE_RATIO = 3.0     # report threshold
NEAR_DECADE_TOL = 0.17   # log10; pre-filter only. Calibrated: true-decade candidates
                         # deviate <=0.149, wrong-cell >=0.199, so the band sits in a gap.


def mpn_milliohm(mfr, mpn):
    """Resistance encoded in the part number, or None. Unknown family -> None, always."""
    fam = MPN_FAMILIES.get(mfr)
    if not fam:
        return None
    pat, kind = fam
    g = pat.search(mpn)
    if not g:
        return None
    if kind == 'decimal':
        return float(g.group(1) + ('.' + g.group(2) if g.group(2) else ''))
    return float(g.group(1))


def catalog_milliohm(ds):
    """Catalog value in mOhm, or None. Rejects anything not FINITE and POSITIVE.

    The finiteness test is deliberately on the number, not on `isinstance(v, float)`: a
    Decimal('NaN') or numpy.float64('inf') would sail past a float-gated check and reach
    log10/round, crashing the audit -- or worse, ranking. Whether a value is usable is a
    property of the value, never of which numeric class happens to carry it.
    """
    sp = getattr(getattr(ds, 'part', None), 'specs', None)
    v = getattr(sp, 'Rds_on_10v_max', None) if sp else None
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v * 1000.0


def _digits(x):
    """Significant digits with the point and leading/trailing zeros removed, so 0.11 and 11
    compare equal -- that is exactly the invariant a decimal shift preserves."""
    s = ('%.6g' % x).replace('.', '').replace('-', '').lstrip('0').rstrip('0')
    return s or '0'


def classify(parsed, ref):
    """(class, decade, digits_equal). Digits decide; the decade only pre-filters.

    The class names say SCALE-LIKE, not "scale error", and NON-SCALE DISAGREEMENT, not
    "wrong-cell". That is not hedging -- it is the limit of what this computation can
    support. It compares two numbers. It cannot tell a wrong-cell capture from a wrong
    CATALOG entry, from a typ-vs-max/condition mismatch, or from OCR-mangled digits; those
    are mechanisms, and a mechanism needs the PDF read. Curated, PDF-confirmed mechanisms
    live in CONFIRMED_MECHANISM and are attached separately, never inferred here.

    Digit equality is EXACT (dp == dr), not a prefix match. A two-character prefix rule
    would call 12xxx vs 129xxx a scale error, which is exactly the wrong-capture shape this
    is meant to exclude. All eight current scale-like rows satisfy exact equality, so the
    strict rule costs nothing and closes that hole.
    """
    r = parsed / ref
    e = math.log10(r)
    k = round(e)
    near = k != 0 and abs(e - k) < NEAR_DECADE_TOL
    equal = _digits(parsed) == _digits(ref)
    if near and equal:
        return 'scale-like', k, True
    if near:
        return 'non-scale disagreement (near-decade, digits differ)', k, False
    return 'non-scale disagreement', 0, False


def rows():
    out = []
    comparable = 0
    for (mfr, mpn), ds in datasheets_db.load().items():
        parsed = ds.get_resistance_milliohm('Rds_on')
        if math.isnan(parsed) or parsed <= 0:
            continue
        ref, src = catalog_milliohm(ds), 'catalog'
        if ref is None:
            ref, src = mpn_milliohm(mfr, mpn), 'mpn'
        if not ref:
            continue
        comparable += 1
        r = parsed / ref
        if r <= DISAGREE_RATIO and r >= 1 / DISAGREE_RATIO:
            continue
        cls, k, same = classify(parsed, ref)
        out.append(dict(mfr=mfr, mpn=mpn, parsed=parsed, ref=ref, ratio=r, witness=src,
                        decade=k, digits_equal=same, cls=cls,
                        mechanism=CONFIRMED_MECHANISM.get((mfr, mpn))))
    out.sort(key=lambda x: -abs(math.log10(x['ratio'])))
    return comparable, out


def calibrate():
    """Decoder soundness as a DISTRIBUTION, not a pass rate.

    A pass rate against any band is the wrong statistic: with a [0.1,10] gate a systematic
    x9 decoder scores 100%. What exposes a bad family is a tight cluster at a NON-UNITY
    decade, which is exactly what 'ts' shows.
    """
    db = datasheets_db.load()
    out = {}
    for mfr in list(MPN_FAMILIES) + ['ts']:
        pat = MPN_FAMILIES.get(mfr, (re.compile(r'^TSM(\d{3})N'), None))
        rs = []
        for (m, mpn), ds in db.items():
            if m != mfr:
                continue
            nom = mpn_milliohm(mfr, mpn) if mfr in MPN_FAMILIES else (
                float(pat[0].search(mpn).group(1)) if pat[0].search(mpn) else None)
            cat = catalog_milliohm(ds)
            if not nom or not cat:
                continue
            rs.append(cat / nom)
        if rs:
            rs.sort()
            # statistics.median, not rs[len//2] -- the latter is the UPPER middle for even
            # n. It happens not to move these printed values, which is exactly why it would
            # have survived unnoticed into a family where it did.
            out[mfr] = (len(rs), rs[0], statistics.median(rs), rs[-1],
                        max(abs(math.log10(x)) for x in rs))
    return out


def main():
    comparable, rs = rows()
    print('comparable records (catalog OR family-gated MPN): %d' % comparable)
    print('disagreeing beyond %gx: %d\n' % (DISAGREE_RATIO, len(rs)))
    print('%-9s %-22s %10s %10s %9s %-8s %-6s %s'
          % ('mfr', 'mpn', 'parsed', 'ref', 'ratio', 'witness', 'digits', 'class'))
    for x in rs:
        print('%-9s %-22s %10.5g %10.5g %9.4g %-8s %-6s %s'
              % (x['mfr'], x['mpn'], x['parsed'], x['ref'], x['ratio'], x['witness'],
                 'same' if x['digits_equal'] else 'diff', x['cls']))
    n_scale = sum(1 for x in rs if x['cls'] == 'scale-like')
    print('\nscale-like: %d   non-scale disagreement: %d' % (n_scale, len(rs) - n_scale))
    conf = [x for x in rs if x['mechanism']]
    print('\nmechanism CONFIRMED by reading the PDF (%d of %d rows); the rest are '
          'unclassified as to mechanism:' % (len(conf), len(rs)))
    for x in conf:
        print('   %-22s %s' % (x['mpn'], x['mechanism']))

    # Confirmed mechanisms whose part does NOT appear above. These are the cases the audit
    # cannot witness -- no catalog entry and no calibrated MPN family -- so without this
    # section running the artifact would silently omit them. XR65R110T is exactly that: the
    # one confirmed dropped DECIMAL, the case that motivated this entire pass, and its
    # ABSENCE from the table is the finding. A comment in the source is not the report.
    seen = {(x['mfr'], x['mpn']) for x in rs}
    outside = [(k, v) for k, v in sorted(CONFIRMED_MECHANISM.items()) if k not in seen]
    print('\nconfirmed mechanism but OUTSIDE the witnessed table (%d) -- no catalog entry '
          'and no calibrated MPN family, so this audit cannot witness them:' % len(outside))
    for (mfr, mpn), why in outside:
        print('   %-9s %-22s %s' % (mfr, mpn, why))

    print('\n-- MPN decoder calibration (catalog/decoded ratio; 1.0 = exact) --')
    print('%-9s %5s %8s %8s %8s %10s'
          % ('family', 'n', 'min', 'median', 'max', 'max|log10|'))
    for mfr, (n, lo, med, hi, worst) in sorted(calibrate().items()):
        print('%-9s %5d %8.4g %8.4g %8.4g %10.4f%s'
              % (mfr, n, lo, med, hi, worst, '   <- REJECTED' if mfr in MPN_REJECTED else ''))
    print('(a systematic x9 decoder would show max|log10| = 0.954)')
    for mfr, why in sorted(MPN_REJECTED.items()):
        print('   rejected %-9s %s' % (mfr, why))


if __name__ == '__main__':
    main()
