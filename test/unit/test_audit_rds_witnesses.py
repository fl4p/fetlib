"""apps/audit_rds_witnesses.py -- the external-witness audit.

The tests that matter here are the ones pinning what the audit REFUSES to do: decode an
uncalibrated MPN family, call a near-decade ratio a scale error when the digits differ, or
accept a non-finite catalog value. Each corresponds to a way the audit could quietly assert
something it has not established.
"""
import math

import pytest

from apps.audit_rds_witnesses import (CONFIRMED_MECHANISM, MPN_FAMILIES, MPN_REJECTED,
                                      _digits, catalog_milliohm, classify, mpn_milliohm)


# ------------------------------------------------------------------ decoder families
@pytest.mark.parametrize('mfr,mpn,expect', [
    ('infineon', 'IPW60R024CFD7', 24.0),
    ('infineon', 'IPW60R120C7XKSA1', 120.0),
    ('nce', 'NCES075P042D7', 42.0),
    ('vishay', 'SQD50N10-8M9L_GE3', 8.9),
    ('vishay', 'SQM120N10-3M8_GE3', 3.8),
])
def test_accepted_families_decode(mfr, mpn, expect):
    assert mpn_milliohm(mfr, mpn) == expect


@pytest.mark.parametrize('mfr,mpn', [
    # TSM089N08 "decodes" to 89 but the part is 8.9 mOhm -- the family encodes
    # deci-milliohm. All 25 checkable records sit at ratio 0.100 with no spread. Accepting
    # it would inject a systematic x10 into the tool built to find x10 errors.
    ('ts', 'TSM089N08LCR RLG'),
    ('ts', 'TSM160N10LCR'),
    # BUK7Y3R1-80MX is 3.1 mOhm / 80 V; the Vishay pattern matches the '-80M' VOLTAGE.
    ('nxp', 'BUK7Y3R1-80MX'),
    # xnrusemi has one decodable MPN and no catalog entry, so the family cannot be
    # calibrated at all. XR65R110T stays a hand-verified singleton.
    ('xnrusemi', 'XR65R110T'),
    ('xnrusemi', 'XR65R36H'),
    # never seen -> never guessed
    ('some-new-vendor', 'ABC60R024XYZ'),
])
def test_rejected_and_unknown_families_never_decode(mfr, mpn):
    assert mpn_milliohm(mfr, mpn) is None


def test_rejections_are_documented_not_merely_absent():
    """A family missing from MPN_FAMILIES with no recorded reason gets re-added by the next
    person who notices the pattern. The reason IS the guard."""
    for mfr in ('ts', 'xnrusemi', 'nxp'):
        assert mfr not in MPN_FAMILIES
        assert MPN_REJECTED.get(mfr), 'no recorded reason for rejecting %s' % mfr


# ------------------------------------------------------------------ classification
@pytest.mark.parametrize('parsed,ref,cls,decade', [
    # scale-like: exact digits, clean decade
    (0.019, 19.0, 'scale-like', -3),
    (0.14, 140.0, 'scale-like', -3),
    (88000.0, 88.0, 'scale-like', 3),
    (0.125, 125.0, 'scale-like', -3),
    (11.0, 0.11, 'scale-like', 2),          # XR65R110T's shape
    # near a decade but the digits are NOT the same number
    (49.0, 5.4, 'non-scale disagreement (near-decade, digits differ)', 1),
    (49.0, 5.7, 'non-scale disagreement (near-decade, digits differ)', 1),
    (99.0, 7.8, 'non-scale disagreement (near-decade, digits differ)', 1),
    # nowhere near a decade
    (180.0, 3.7, 'non-scale disagreement', 0),
    (10.0, 2.3, 'non-scale disagreement', 0),
])
def test_classification(parsed, ref, cls, decade):
    got_cls, got_k, _ = classify(parsed, ref)
    assert got_cls == cls
    assert got_k == decade


def test_digit_equality_is_exact_not_a_prefix():
    """The bug this closes: a two-character prefix rule accepted 12xxx vs 129xxx, which is
    the wrong-capture shape the classifier exists to exclude."""
    assert _digits(0.11) == _digits(11.0) == '11'
    assert _digits(88000.0) == _digits(88.0) == '88'
    assert _digits(129.0) != _digits(12000.0)
    cls, _, equal = classify(12000.0, 129.0)
    assert not equal and cls.startswith('non-scale')


def test_scale_like_requires_BOTH_decade_and_digits():
    assert classify(0.11, 11.0)[0] == 'scale-like'          # both
    assert classify(49.0, 5.4)[0].startswith('non-scale')   # decade only
    assert classify(11.0, 13.0)[0].startswith('non-scale')  # neither


# ------------------------------------------------------------------ catalog refusal
class _Specs:
    def __init__(self, v):
        self.Rds_on_10v_max = v


class _DS:
    def __init__(self, v):
        self.part = type('P', (), {'specs': _Specs(v)})()


@pytest.mark.parametrize('v', [
    None, float('nan'), float('inf'), float('-inf'), 0, -1.0, 'abc', object(),
])
def test_non_finite_or_nonpositive_catalog_is_refused(v):
    """isinstance(v, float) was the old gate, so a Decimal('NaN') or numpy NaN would reach
    log10/round. Usability is a property of the VALUE, not of its numeric class."""
    assert catalog_milliohm(_DS(v)) is None


def test_decimal_nan_is_refused_despite_not_being_a_float():
    from decimal import Decimal
    assert catalog_milliohm(_DS(Decimal('NaN'))) is None
    assert catalog_milliohm(_DS(Decimal('0.016'))) == pytest.approx(16.0)


def test_valid_catalog_converts_to_milliohm():
    assert catalog_milliohm(_DS(0.016)) == pytest.approx(16.0)
    assert catalog_milliohm(_DS(1)) == pytest.approx(1000.0)


# ------------------------------------------------------------------ mechanism honesty
def test_mechanisms_are_curated_never_inferred():
    """classify() returns no mechanism. Only parts whose PDF was actually read appear in
    CONFIRMED_MECHANISM, and absence there means 'not investigated', not 'no mechanism'."""
    assert len(classify(0.11, 11.0)) == 3          # (class, decade, digits_equal) only
    assert ('st', 'STF40N60M2') in CONFIRMED_MECHANISM
    # the motivating case, deliberately absent from the output table
    assert ('xnrusemi', 'XR65R110T') in CONFIRMED_MECHANISM
    # parts in the table that were NOT individually inspected must have no mechanism
    for key in (('huayi', 'HY1920P'), ('ti', 'CSD19506KTT'), ('hxy', 'IRF540N-HXY'),
                ('infineon', 'ISC0805NLS')):
        assert key not in CONFIRMED_MECHANISM


def test_mechanisms_are_keyed_by_mfr_and_mpn():
    """An mpn-only key would let a clone or vendor collision attach a mechanism derived
    from a DIFFERENT company's PDF -- a curated fact silently misattributed."""
    assert all(isinstance(k, tuple) and len(k) == 2 for k in CONFIRMED_MECHANISM)
    # the bare mpn must NOT resolve
    assert CONFIRMED_MECHANISM.get('STF40N60M2') is None


SCALE_LIKE = {
    ('infineon', 'IPB50R140CPATMA1'), ('infineon', 'IPP50R140CPXKSA1'),
    ('infineon', 'IPP60R099CPXKSA1'), ('infineon', 'IPP60R125CPXKSA1'),
    ('st', 'STF40N60M2'), ('st', 'STFW40N60M2'),
    ('vishay', 'SUM85N15-19'), ('vishay', 'SUM85N15-19-E3'),
}
ALL_REPORTED = SCALE_LIKE | {
    ('huayi', 'HY1920P'), ('huayi', 'HYG072N08NR1P'), ('hxy', 'IRF540N-HXY'),
    ('infineon', 'BSC037N08NS5T'), ('infineon', 'BSC0805LS'),
    ('infineon', 'IPB054N08N3 G'), ('infineon', 'IPB054N08N3GATMA1'),
    ('infineon', 'IPP057N08N3 G'), ('infineon', 'IPP057N08N3GXKSA1'),
    ('infineon', 'ISC0805NLS'), ('ti', 'CSD19506KTT'), ('ti', 'CSD19506KTTT'),
    ('xnrusemi', 'XR65R36H'),

    # Added 2026-07-27 when apps/recover_db_from_snapshot.py restored an Rds_on field this
    # record had lost. Stored 94140 mΩ against a catalog 94 mΩ: ratio 1001 but the digits
    # are NOT equal (94140 vs 94), so it classifies as a near-decade disagreement rather
    # than scale-like -- consistent with a digit concatenation ("94" and "140" from one row)
    # rather than a lost SI prefix. Not investigated further, hence no CONFIRMED_MECHANISM
    # entry; the audit surfacing it is the point.
    ('hxy', 'FCMT099N65S3-HXY'),
}


def test_corpus_membership_is_stable():
    """Integration: needs the shipped DB.

    Asserts the exact MEMBER SETS, not just counts. A count is a proxy: members can swap
    silently and the total stay put -- the same proxy-vs-property hole fixed twice already
    in this work (the cache signature, and the errors-column source count).

    The 5282 -> 5308 bump on 2026-07-27 is a real corpus change, not a silenced failure.
    This assertion did its job first: a main.py run served a stale read_parts_datasheets
    cache and overwrote the DB, 1348 records lost 65631 fields, and this dropped to 5046.
    It was left RED until the data came back rather than being adjusted to match the
    damage. apps/recover_db_from_snapshot.py then merged the richer snapshot with the 1183
    fields only the newer DB had, which restored the 5282 AND gave 65 records an Rds_on
    they had never had -- hence 26 more comparable records than before the incident, and
    one new reported row. If this number moves again, find out which of those two things
    happened before touching it.

    STILL RED as of 2026-07-27 evening, ON PURPOSE. Read this before adjusting 5308.

    An attempt to re-pin this at 5562 was reverted, because the investigation behind it was
    wrong in the one direction that matters. Recording it so the next person does not
    repeat it:

      * Growth is real: vs the .bak-20260727-1419 snapshot, +295 records, 0 removed, and
        447 shared records gained a symbol.
      * The total field count fell 597389 -> 583106. That part IS benign: fields_lists
        holds one entry per extraction CANDIDATE, and a re-parse legitimately replaces a
        symbol's candidate list with fewer candidates. The merge guard is symbol-level and
        test_no_duplicate_candidates_for_a_symbol_fresh_already_has pins that deliberately.
      * BUT the records that lost Rds_on entirely (17 at first measurement, 26 an hour
        later) were NOT garbage being refused, which is what the reverted version claimed.
        Their unit was ':' -- and ':' is an explicitly recognised omega rendering, listed
        in dslib.field._OHM_BODY, so ohm_unit_to_milli_mul(':') == 1e3 and a stored 0.0375
        means 37.5 mOhm. Checked against the independent catalog witness: 0.0375 * 1000 ==
        37.5 == catalog, ratio 1.0000. Those were CORRECT values.
      * And they were not refused: fields_lists['Rds_on'] is now EMPTY for them, i.e. the
        parser produced zero candidates. That is an extraction-RECALL regression that
        destroyed known-good data, and it is invisible to this test's metrics because an
        absent symbol reports no disagreement -- exactly like a correct one.
      * Symbol-set diffing is not sufficient anyway: 82 shared records changed their
        get_resistance_milliohm('Rds_on') OUTPUT while keeping the symbol, several by ~2.09x
        (e.g. vishay/SUM45N25-58 58.0 -> 121.0 mOhm). None crosses DISAGREE_RATIO yet.
        Compare VALUES, not just symbol presence, before trusting any new number.

    Also: the count is not measurable right now. apps/reparse_all.py --apply is in flight
    and this has read 5562, 5463 and 5373 within one hour; it is only stable between
    batches. Re-measure once that finishes AND the recall regression above is understood.

    Per the paragraph above: left RED until the data comes back, rather than adjusted to
    match the damage.
    """
    from apps.audit_rds_witnesses import rows
    comparable, rs = rows()
    assert comparable == 5308
    got = {(x['mfr'], x['mpn']) for x in rs}
    assert got == ALL_REPORTED, ('added: %s  missing: %s'
                                 % (got - ALL_REPORTED, ALL_REPORTED - got))
    scale = {(x['mfr'], x['mpn']) for x in rs if x['cls'] == 'scale-like'}
    assert scale == SCALE_LIKE, ('added: %s  missing: %s'
                                 % (scale - SCALE_LIKE, SCALE_LIKE - scale))
    assert all(math.isfinite(x['ratio']) and x['ratio'] > 0 for x in rs)


def test_calibration_positive_control_ts_is_a_clean_decade():
    """The control that proves the calibration can SEE a bad decoder. ts sits at exactly
    0.1 with no spread -- a systematic decade, not noise -- which a pass-rate against a
    [0.1,10] band would have reported as 100% agreement."""
    from apps.audit_rds_witnesses import calibrate
    cal = calibrate()
    n, lo, med, hi, worst = cal['ts']
    assert n == 25
    assert 0.09 < med < 0.11 and 0.09 < lo <= hi < 0.12
    assert worst > 0.9, 'ts must read as a full decade off'
    for fam in ('infineon', 'nce', 'vishay'):
        assert cal[fam][4] < 0.3, '%s decoder drifted' % fam


def test_confirmed_mechanisms_outside_the_table_are_still_reported(capsys):
    """The audit must SHOW the cases it cannot witness.

    XR65R110T is the one confirmed dropped decimal and the case that motivated this whole
    pass, but it has no catalog entry and xnrusemi cannot be calibrated, so it is absent
    from the witnessed rows by construction. Printing only mechanisms attached to those
    rows meant running the artifact never mentioned it -- the finding lived in a source
    comment, and a source comment is not the audit report.
    """
    from apps.audit_rds_witnesses import main, rows

    main()
    out = capsys.readouterr().out
    assert 'OUTSIDE the witnessed table' in out
    assert 'XR65R110T' in out
    assert 'dropped decimal' in out

    # and it genuinely is outside the rows, so the section is load-bearing
    _, rs = rows()
    assert ('xnrusemi', 'XR65R110T') not in {(x['mfr'], x['mpn']) for x in rs}
