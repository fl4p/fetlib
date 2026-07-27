"""DatasheetFields.qrr_test_conditions — the parsed body-diode test point.

Every guard here is calibrated against a REAL part from the shipped DB that it was
written to reject, not against a synthetic near-miss. A guard nobody has watched fire
on the case it exists for is not a guard.

Run:  python3 -m pytest unit/test_qrr_parsed_conditions.py   (or execute directly)
"""
import math
import sys

sys.path.insert(0, ".")

from dslib.field import DatasheetFields, Field


def _ds(qrr_rows, trr_rows=(), mpn='TEST'):
    """qrr_rows/trr_rows: [(value, cond_dict), ...] -> a DatasheetFields carrying them."""
    fields = []
    for v, c in qrr_rows:
        fields.append(Field('Qrr', min=math.nan, typ=v, max=math.nan, unit='nC', cond=c))
    for v, c in trr_rows:
        fields.append(Field('trr', min=math.nan, typ=v, max=math.nan, unit='ns', cond=c))
    return DatasheetFields(mfr='infineon', mpn=mpn, fields=fields)


# IPTC020N13NM6: "VR=68 V, IF=71 A, diF/dt=500 A/us", Qrr 154 nC / trr 36 ns
GOOD_Q = [(154.0, {'VR': 68.0, 'IF': 71.0, 'diF/dt': 500.0})]
GOOD_T = [(36.0, {'VR': 68.0, 'IF': 71.0, 'diF/dt': 500.0})]


def test_reads_the_datasheet_test_point():
    c = _ds(GOOD_Q, GOOD_T).qrr_test_conditions()
    assert c is not None
    assert c['IF'] == 71.0 and c['didt'] == 500e6 and c['VR'] == 68.0
    assert c['Tj'] == 25.0
    assert c['source'] == 'parsed'      # provenance is not optional, see attach_qrr_registries


def test_negative_slew_is_a_sign_convention_not_a_reject():
    """Datasheets write "-diF/dt = 400 A/us" (IXKN45N80C) and negative source currents.
    Refusing the sign dropped 146 good parts in this corpus for a minus."""
    c = _ds([(45000.0, {'IF': -80.0, 'diF/dt': -400.0, 'VR': 480.0})],
            [(500.0, {})]).qrr_test_conditions()
    assert c is not None and c['IF'] == 80.0 and c['didt'] == 400e6


def test_conditions_come_from_the_row_that_supplied_the_scalar():
    """STW48NM60N quotes Qrr twice at ONE di/dt and IF: 10.5 uC at 25 C and 14 uC at
    150 C. The selected scalar is the cold row, but only the hot row carries a Tj — a
    di/dt-only guard sees no conflict and fits the cold charge at 150 C, inflating tau.
    Attribution must follow the VALUE."""
    ds = _ds([(10500.0, {'ISD': 44.0, 'di/dt': 100.0, 'VDD': 100.0}),
              (14000.0, {'ISD': 44.0, 'di/dt': 100.0, 'VDD': 100.0, 'Tj': 150.0})],
             [(472.0, {})])
    c = ds.qrr_test_conditions()
    assert c is not None
    assert c['Tj'] == 25.0, 'took the OTHER row\'s Tj'


def test_multi_didt_part_pairs_with_its_own_row():
    """IPP022N12NM6: 155.2 nC @ 300 A/us and 412.1 nC @ 1000. The scalar is the 300 row,
    so 300 is its test point -- not a reason to drop the part. Verified across the
    qrr_points dies in the DB (79 by exact key, 102 via the suffix lookup): the parsed
    triple matches a real datasheet row for every one, none mis-paired."""
    ds = _ds([(155.2, {'VR': 60.0, 'IF': 50.0, 'diF/dt': 300.0}),
              (412.1, {'VR': 60.0, 'IF': 50.0, 'diF/dt': 1000.0})],
             [(46.3, {})])
    c = ds.qrr_test_conditions()
    assert c is not None and c['didt'] == 300e6


def test_one_value_two_conditions_is_refused():
    """The genuinely ambiguous case the value-match cannot resolve: same number, two
    test points. Nothing can say which one produced it."""
    c, why = _ds([(155.2, {'IF': 50.0, 'diF/dt': 300.0}),
                  (155.2, {'IF': 50.0, 'diF/dt': 1000.0})],
                 [(46.3, {})]).qrr_test_conditions(detail=True)
    assert c is None and 'di/dt values' in why


def test_captured_multiplier_is_refused_by_the_physics_check():
    """IXYS/Littelfuse state "IF = 0.5 * ID25"; the regex captures the 0.5 and the test
    point becomes 0.5 A on a 60 A part -- a 65x charge error reported as a confident fit.

    Caught WITHOUT reference to the part's rating: Qrr=550 nC with trr=118 ns implies
    IRRM ~ 9.6 A, 19x the forward current that supposedly stored the charge. The triple
    is self-inconsistent, which is a stronger statement than "small relative to ID_25"."""
    ds = _ds([(550.0, {'IF': 0.5, 'di/dt': 100.0, 'Vgs': 0.0})], [(118.0, {})])
    c, why = ds.qrr_test_conditions(detail=True)
    assert c is None and 'IRRM' in why
    # the SAME part at its true current is unremarkable -- direction, not just firing
    ok = _ds([(550.0, {'IF': 30.0, 'di/dt': 100.0})], [(118.0, {})]).qrr_test_conditions()
    assert ok is not None and ok['IF'] == 30.0


def test_a_genuine_low_current_test_is_not_mistaken_for_a_multiplier():
    """The false-positive direction, which a rating-ratio guard got wrong.

    Vishay/AO/Diodes characterise body diodes at ~10 A regardless of a 200-400 A rating
    -- SiRS5100DP really does say "IF = 10 A, di/dt = 100 A/us" on a 241 A part. A guard
    that refused anything under 5% of ID_25 rejected 36 such parts across the shipped DB
    and caught ZERO captured multipliers this physics check does not already reject, so
    it was removed. Calibrating a guard only against its known-BAD input is half the job;
    this pins the known-GOOD one."""
    ds = _ds([(160.0, {'IF': 10.0, 'di/dt': 100.0})], [(80.0, {})])   # SiRS5100DP
    c = ds.qrr_test_conditions()
    assert c is not None and c['IF'] == 10.0 and c['didt'] == 100e6


def test_no_trr_is_refused_so_the_physics_check_is_never_skipped():
    """trr is required, which is what makes the IRRM check unconditional -- there is no
    longer a class of parts whose only defence is the deliberately-wide physical band.

    It costs nothing: the Lauritzen-Ma fit consumes the (Qrr, trr) PAIR, so a test point
    without trr fails at qrr_op time regardless. Refusing here turns a generic downstream
    LMFitError into a stated reason."""
    for rows, what in (([(550.0, {'IF': 0.5, 'di/dt': 100.0})], 'implausible IF'),
                       ([(550.0, {'IF': 30.0, 'di/dt': 100.0})], 'plausible IF')):
        c, why = _ds(rows).qrr_test_conditions(detail=True)
        assert c is None and 'no trr' in why, what
    # supplying trr re-enables it
    assert _ds([(550.0, {'IF': 30.0, 'di/dt': 100.0})],
               [(118.0, {})]).qrr_test_conditions() is not None


def test_conflicting_tj_rows_are_refused_but_absent_tj_defaults():
    """Tj disagreement among rows carrying the SAME Qrr is unresolvable and must refuse,
    like IF/di-dt. No Tj at all is a different case and defaults to the 25 C these tables
    are quoted at -- a documented convention, not a stand-in for an unread value."""
    c, why = _ds([(154.0, {'IF': 71.0, 'diF/dt': 500.0, 'Tj': 25.0}),
                  (154.0, {'IF': 71.0, 'diF/dt': 500.0, 'Tj': 150.0})],
                 GOOD_T).qrr_test_conditions(detail=True)
    assert c is None and 'disagree on Tj' in why
    assert _ds(GOOD_Q, GOOD_T).qrr_test_conditions()['Tj'] == 25.0
    # a single stated hot Tj is carried through, not silently replaced by the default
    hot = _ds([(154.0, {'IF': 71.0, 'diF/dt': 500.0, 'Tj': 150.0})],
              GOOD_T).qrr_test_conditions()
    assert hot is not None and hot['Tj'] == 150.0


def test_mismatched_qrr_trr_rows_are_refused():
    """ISC014N08NM6: Qrr 65 nC at 100 A/us, but the trr scalar (25 ns) belongs to the
    1000 A/us row. The LM pair is then two different measurements; the fit is
    unrepresentable and must fail here rather than silently produce a tau."""
    c, why = _ds([(65.0, {'VR': 40.0, 'IF': 25.0, 'diF/dt': 100.0})],
                 [(25.0, {})]).qrr_test_conditions(detail=True)
    assert c is None and 'not LM-representable' in why


def test_explicit_trr_condition_conflict_is_refused():
    c, why = _ds(GOOD_Q, [(36.0, {'IF': 71.0, 'diF/dt': 1000.0})]).qrr_test_conditions(detail=True)
    assert c is None and 'trr di/dt' in why


def test_absent_data_never_invents_a_point():
    """Each missing-input path must return None, never a default test point."""
    for rows, trr, what in (([], (), 'no Qrr at all'),
                            ([(154.0, {})], GOOD_T, 'Qrr row with no conditions'),
                            ([(154.0, {'IF': 71.0})], GOOD_T, 'IF but no di/dt'),
                            ([(154.0, {'diF/dt': 500.0})], GOOD_T, 'di/dt but no IF')):
        assert _ds(rows, trr).qrr_test_conditions() is None, what


def test_out_of_band_values_are_refused():
    for cond, what in (({'IF': 71.0, 'diF/dt': 0.2}, 'di/dt far too slow'),
                       ({'IF': 71.0, 'diF/dt': 5e5}, 'di/dt far too fast'),
                       ({'IF': 9000.0, 'diF/dt': 500.0}, 'IF beyond any real part')):
        assert _ds([(154.0, cond)], GOOD_T).qrr_test_conditions() is None, what


def test_layout_registry_sits_between_curated_and_parsed():
    """Four tiers, and each must be distinguishable downstream: qrr_points > hand-read
    conditions > layout-read conditions > keyed parse. The layout entries are MACHINE-read
    from the datasheet's table geometry, so they must never displace a human's reading,
    and must never be mistaken for one in the CSV."""
    from dslib.mosfet import attach_qrr_registries
    from types import SimpleNamespace
    parsed = dict(IF=1.0, didt=1e6, VR=None, Tj=25.0, source='parsed')

    # a die that IS hand-curated: the human entry wins over both lower tiers
    s = SimpleNamespace(qrr_cond=None, qrr_points=None)
    attach_qrr_registries(s, 'infineon', 'IPP019N08NF2S', parsed_qrr_cond=parsed)
    assert s.qrr_cond['source'] == 'curated' and s.qrr_cond['IF'] == 100.0

    # a die in the generated layout registry but NOT hand-curated: layout beats parsed
    from dslib.qrr_layout_conditions import QRR_LAYOUT_CONDITIONS
    from dslib.qrr_conditions import QRR_CONDITIONS
    only_layout = next((k for k in QRR_LAYOUT_CONDITIONS if k not in QRR_CONDITIONS), None)
    assert only_layout, 'the generated registry should hold non-curated dies'
    s2 = SimpleNamespace(qrr_cond=None, qrr_points=None)
    attach_qrr_registries(s2, only_layout[0], only_layout[1], parsed_qrr_cond=parsed)
    assert s2.qrr_cond['source'] == 'layout'
    assert s2.qrr_cond['IF'] == QRR_LAYOUT_CONDITIONS[only_layout]['IF']

    # nothing curated and nothing in the layout registry -> the keyed parse fills it
    s3 = SimpleNamespace(qrr_cond=None, qrr_points=None)
    attach_qrr_registries(s3, 'nobody', 'NO-SUCH-PART', parsed_qrr_cond=parsed)
    assert s3.qrr_cond['source'] == 'parsed'


def test_generated_layout_entries_are_physically_bounded():
    """Every generated entry passed a fit and an IRRM bound at emit time. Re-assert the
    cheap invariants here so a hand-edit of the GENERATED file, or a regeneration with a
    loosened extractor, cannot quietly ship a nonsense operating point."""
    from dslib.qrr_layout_conditions import QRR_LAYOUT_CONDITIONS as Q
    assert len(Q) > 100, 'registry looks truncated'
    for (mfr, mpn), c in Q.items():
        assert 0.05 <= c['IF'] <= 3000, (mpn, c['IF'])
        assert 1e6 <= c['didt'] <= 1e11, (mpn, c['didt'])
        assert -60 <= c['Tj'] <= 200, (mpn, c['Tj'])
        assert c['VR'] is None or 0 < c['VR'] <= 2000, (mpn, c['VR'])
    # di/dt must look like a TEST CONDITION rather than a number scraped off a table.
    #
    # Asserted as a distribution, not an allowlist. An enumerated set of "canonical"
    # values ({100,300,500,1000}) was tried first and was simply wrong about the corpus:
    # infineon IQEH50NE2LM7UCGSC really does quote "diF/dt=400 A/us" and the siliup
    # SP75N65CTF/SP95N65CTO really do quote "di/dt=3000A/us" (and state an Irrm that
    # corroborates the fit). Rejecting those would have been the test asserting its
    # author's expectation over the datasheets. The concentration check still fails loudly
    # if the extractor starts pulling arbitrary numbers, which is the actual risk.
    # The CHARGE must be physical against its own test current, not just the conditions.
    #
    # This assertion exists because its absence shipped six wrong entries. IRFB38N20D and
    # five siblings print "1.3 2.0 C" -- the micro glyph dropped -- so the DB holds
    # Qrr=1.3 nC where the datasheet means 1.3 uC, and the layout reader agreed with it
    # because both read the same un-normalised text. Two readings of one corrupted source
    # are not a cross-check. They sat at Qrr/IF = 0.05 nC/A against a corpus minimum of
    # 0.58, and passed every gate because the only plausibility bound was one-sided
    # (IRRM too HIGH), so a 1000x-too-small charge produced IRRM ~ 0 and looked fine.
    from dslib.store import datasheets_db
    dss = datasheets_db.load()
    by = {k[1]: ds for k, ds in dss.items()}
    ratios = []
    for (mfr, mpn), c in Q.items():
        ds = by.get(mpn)
        if ds is None:
            continue
        fq = ds.fields_filled.get('Qrr')
        if not fq:
            continue
        try:
            v = fq.typ_or_max_or_min
        except ValueError:
            continue
        if v and not math.isnan(v):
            ratios.append((v / c['IF'], mfr, mpn))
    assert ratios, 'could not cross-check any entry against the DB'
    low = [r for r in ratios if r[0] < 0.2]
    assert not low, ('Qrr/IF below any physical recovery time -- likely a lost unit '
                     'prefix: %s' % low[:5])

    didts = [c['didt'] / 1e6 for c in Q.values()]
    assert all(10 <= d <= 20000 for d in didts), 'di/dt outside any real test range'
    common = sum(1 for d in didts if round(d) in (100, 300, 500, 1000))
    assert common / len(didts) > 0.9, (
        'only %.0f%% of di/dt values are standard test points -- the extractor is '
        'probably matching arbitrary table numbers' % (100 * common / len(didts)))


def test_curated_entries_outrank_parsed_ones():
    """attach_qrr_registries owns the precedence: hand-read beats parsed, and the
    survivor must say which it is."""
    from dslib.mosfet import attach_qrr_registries
    from types import SimpleNamespace
    parsed = dict(IF=1.0, didt=1e6, VR=None, Tj=25.0, source='parsed')
    s = SimpleNamespace(qrr_cond=None, qrr_points=None)
    attach_qrr_registries(s, 'infineon', 'IPP019N08NF2S', parsed_qrr_cond=parsed)
    assert s.qrr_cond['IF'] == 100.0            # the curated value, not the parsed 1.0
    assert s.qrr_cond['source'] == 'curated'
    # no curated entry -> parsed fills the slot, still labelled
    s2 = SimpleNamespace(qrr_cond=None, qrr_points=None)
    attach_qrr_registries(s2, 'nobody', 'NO-SUCH-PART', parsed_qrr_cond=parsed)
    assert s2.qrr_cond['source'] == 'parsed'


if __name__ == "__main__":
    for nm, fn in sorted(globals().items()):
        if nm.startswith("test_"):
            fn()
            print(f"{nm}: OK")
