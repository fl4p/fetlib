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


def test_captured_multiplier_is_refused_via_the_rating():
    """IXYS/Littelfuse state "IF = 0.5 * ID25"; the regex captures the 0.5 and the test
    point becomes 0.5 A on a 60 A part -- a 65x charge error reported as a confident fit."""
    ds = _ds([(550.0, {'IF': 0.5, 'di/dt': 100.0, 'Vgs': 0.0})], [(118.0, {})])
    c, why = ds.qrr_test_conditions(Id=60.0, detail=True)
    assert c is None and 'multiplier' in why


def test_captured_multiplier_is_refused_without_a_rating_too():
    """Same part with NO parsed ID_25 -- the rating guard cannot fire, so the physics
    check must: Qrr=550 nC with trr=118 ns implies IRRM ~ 9.6 A, 19x the claimed 0.5 A
    forward current that supposedly stored the charge. Absence of the rating must not
    become absence of the problem."""
    ds = _ds([(550.0, {'IF': 0.5, 'di/dt': 100.0})], [(118.0, {})])
    c, why = ds.qrr_test_conditions(Id=None, detail=True)
    assert c is None and 'IRRM' in why
    # and the SAME part at its true current is unremarkable
    ok = _ds([(550.0, {'IF': 30.0, 'di/dt': 100.0})], [(118.0, {})]).qrr_test_conditions()
    assert ok is not None and ok['IF'] == 30.0


def test_neither_trr_nor_rating_is_refused_not_waved_through():
    """The INTERSECTION of the two guards' preconditions, which each of the two tests
    above leaves covered by the other. Both anti-multiplier checks are conditional --
    the rating check needs Id, the IRRM check needs trr -- so a part with neither was
    protected only by the deliberately-wide 0.05 A physical band, i.e. the guard vanished
    exactly where the evidence was thinnest. 153 parts in the shipped DB reach this state.
    """
    ds = _ds([(550.0, {'IF': 0.5, 'di/dt': 100.0})])          # no trr rows at all
    c, why = ds.qrr_test_conditions(Id=None, detail=True)
    assert c is None and 'neither trr nor a current rating' in why
    # a plausible IF with the same missing evidence is refused too -- the point is that
    # nothing can CHECK it, not that this particular number looks wrong
    ds2 = _ds([(550.0, {'IF': 30.0, 'di/dt': 100.0})])
    assert ds2.qrr_test_conditions(Id=None) is None
    # ... and either piece of evidence is enough to re-enable it
    assert ds2.qrr_test_conditions(Id=60.0) is not None
    assert _ds([(550.0, {'IF': 30.0, 'di/dt': 100.0})],
               [(118.0, {})]).qrr_test_conditions(Id=None) is not None


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
