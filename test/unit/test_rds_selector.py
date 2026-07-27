"""DatasheetFields.select_rds_on_milliohm: Rds_on_10v / Rds_on precedence in ONE place.

`get_resistance_milliohm` is the primitive and resolves one symbol's scale from that symbol's
own unit. Which SYMBOL wins is a separate decision that had been copied into five call sites
(get_row, get_mosfet_specs, both CSV generators, validate.py) -- which is how main.py and
field.py held OPPOSITE precedence for a while with nothing noticing.

The reason this matters is a scale clash: `Rds_on` is mΩ (or mΩ by default when unitless)
while `Rds_on_10v` is ohm-scale. A part storing the same raw number under both therefore reads
1000x apart. Six real parts do, confirmed against the resistance encoded in their MPNs.

`Rds_on_10v` now arrives with an EXPLICIT ohm unit from its producer
(MosfetBasicSpecs.fields -> ensure_ohm), so the fixtures here state it. It used to be emitted
unitless and read through a per-symbol default, which is why the clash existed at all; a
unitless one is refused now rather than defaulted.
"""
import math

import pytest

from dslib.field import Field, DatasheetFields

NA = math.nan


def _ds(rds_on=None, rds_on_10v=None):
    ds = DatasheetFields()
    if rds_on is not None:
        ds.add(rds_on)
    if rds_on_10v is not None:
        ds.add(rds_on_10v)
    return ds


def test_rds_on_10v_wins_when_both_present():
    """It is the vendor's parametric max-at-10V, from one of 13 vendor scrapers and 0%
    implausible in every one of them, where parsed Rds_on carries whatever the table cell
    held."""
    ds = _ds(Field('Rds_on', NA, NA, 7.7, 'mΩ'), Field('Rds_on_10v', NA, NA, 0.0062, 'Ω'))
    assert ds.select_rds_on_milliohm(stat='max') == pytest.approx(6.2)


def test_falls_back_to_rds_on_when_10v_absent():
    ds = _ds(rds_on=Field('Rds_on', NA, NA, 7.7, 'mΩ'))
    assert ds.select_rds_on_milliohm(stat='max') == pytest.approx(7.7)


def test_falls_back_when_10v_present_but_that_stat_is_nan():
    """Precedence is per REQUESTED STAT, not per symbol: an Rds_on_10v holding only typ must
    not shadow an Rds_on that actually has the max being asked for."""
    ds = _ds(Field('Rds_on', NA, NA, 7.7, 'mΩ'), Field('Rds_on_10v', NA, 0.005, NA, 'Ω'))
    assert ds.select_rds_on_milliohm(stat='max') == pytest.approx(7.7)


def test_nan_when_neither_is_readable():
    ds = _ds(rds_on=Field('Rds_on', NA, NA, 168.0, 'ns'))   # cross-dimension -> refused
    assert math.isnan(ds.select_rds_on_milliohm(stat='max'))


@pytest.mark.parametrize('mpn,raw,truth_milliohm', [
    ('IPB50R140CPATMA1', 0.14, 140.0),
    ('IPP50R140CPXKSA1', 0.14, 140.0),
    ('IPP60R125CPXKSA1', 0.125, 125.0),
    ('IPP60R099CPXKSA1', 0.099, 99.0),
    ('SUM85N15-19', 0.019, 19.0),
])
def test_the_thousandfold_convention_clash(mpn, raw, truth_milliohm):
    """The six real parts. The SAME raw value is stored under both symbols; `Rds_on` alone
    reads it 1000x low, the selector reads it correctly.

    Ground truth is external, not a plausibility band: the Infineon MPNs encode the
    resistance (50R140 -> 140 mΩ, 60R125 -> 125 mΩ, 60R099 -> 99 mΩ), and 19 mΩ is right for
    an 85 A / 150 V part where 0.019 mΩ is impossible.
    """
    # Rds_on_10v now carries an EXPLICIT ohm unit from its producer
    # (MosfetBasicSpecs.fields via ensure_ohm), so this is production shape. It used to be
    # emitted unitless and relied on a per-symbol default; a stated unit beats a defaulted
    # one, and the fixture follows the producer rather than the old convention.
    ds = _ds(Field('Rds_on', NA, NA, raw, None), Field('Rds_on_10v', NA, NA, raw, 'Ω'))

    assert ds.get_resistance_milliohm('Rds_on', stat='max') == pytest.approx(raw), \
        'the bare symbol should still read on its own mΩ convention'
    assert ds.select_rds_on_milliohm(stat='max') == pytest.approx(truth_milliohm), \
        '%s: selector did not resolve the 1000x convention clash' % mpn


def test_a_unitless_rds_on_10v_is_refused_not_defaulted():
    """The producer states the unit now, so a MISSING one means the value did not come from
    where we think it did. Refusing surfaces that as absent data instead of a number that
    happens to be right for the vendors that were checked.

    Consequence on the shipped DB, measured: all 5476 unitless Rds_on_10v records read NaN,
    the Rds_on fallback rescues 5137, and 339 parts have no on-resistance until the DB is
    re-derived from discovery. That is the intended trade, not a regression, but it is a real
    number and belongs next to the behaviour."""
    ds = _ds(rds_on_10v=Field('Rds_on_10v', NA, NA, 0.0062, None))
    assert math.isnan(ds.get_resistance_milliohm('Rds_on_10v', stat='max'))
    assert math.isnan(ds.select_rds_on_milliohm(stat='max')), \
        'a unitless Rds_on_10v was silently scaled by a default again'


def test_validate_no_longer_reports_a_value_no_consumer_reads():
    """The defect this fixes. validate.py read the bare `Rds_on` and reported all six parts as
    "Rds_on may be 1000x low" -- a finding about a number get_mosfet_specs and the CSV never
    saw, because both go through precedence. A check keyed on a proxy for the consumed value
    instead of the value itself."""
    from dslib.validate import _rds_milliohm
    ds = _ds(Field('Rds_on', NA, NA, 0.14, None), Field('Rds_on_10v', NA, NA, 0.14, 'Ω'))
    assert _rds_milliohm(ds) == pytest.approx(140.0), \
        'validate still disagrees with what the pipeline consumes'


def test_a_missing_reader_raises_instead_of_reporting_unchecked():
    """Calibrates the guard added alongside this refactor.

    `_rds_milliohm` used to swallow every Exception and return None, which the validator
    reports as `unchecked`. So renaming the reader switched the ID_25*Rds_on check off for the
    whole corpus while looking like missing data, and only three calibration tests noticed.
    A broken contract must be louder than absent data."""
    from dslib.validate import _rds_milliohm

    class NoReader:
        fields_filled = {}

    with pytest.raises(AttributeError):
        _rds_milliohm(NoReader())

    # ...and the mirror case: a reader that IS present but has no data still degrades quietly.
    class EmptyButValid:
        fields_filled = {}

        def select_rds_on_milliohm(self, **kw):
            return math.nan

    assert _rds_milliohm(EmptyButValid()) is None


def test_selector_is_used_and_not_reimplemented():
    """Guards the point of the change. If a call site grows its own precedence again, the two
    can drift apart silently -- which is exactly what happened between main.py and field.py.
    """
    import os
    import dslib.field

    needle = "get_resistance_milliohm('Rds_on_10v'"

    # PURE TEXT, deliberately. This used inspect.getsource on the bound method, which
    # resolves the body via the code object's co_firstlineno -- a line number fixed at IMPORT
    # -- while reading the file as it is NOW. In a worktree other agents edit during a 3
    # minute suite, any line-count change makes it return a DIFFERENT method's source: it
    # handed back get_resistance_milliohm and the test failed claiming the selector no longer
    # reads Rds_on_10v. It failed that way three times in the full suite while passing in
    # isolation, and a "consistent snapshot" fix did not help because the drift happens before
    # every read. Reading the file once and locating the method by text has no such coupling.
    field_path = os.path.abspath(dslib.field.__file__)
    main_path = os.path.join(os.path.dirname(os.path.dirname(field_path)), 'main.py')
    field_src = open(field_path, encoding='utf-8').read()
    main_src = open(main_path, encoding='utf-8').read()

    start = field_src.find('    def select_rds_on_milliohm(')
    assert start != -1, 'select_rds_on_milliohm is gone; this test is measuring nothing'
    end = field_src.find('\n    def ', start + 1)
    own_src = field_src[start:end if end != -1 else len(field_src)]

    assert own_src.count(needle) == 1, \
        'selector no longer reads Rds_on_10v; this test is measuring nothing'
    assert field_src.count(needle) == 1, \
        'dslib.field reimplements Rds precedence outside select_rds_on_milliohm'
    assert main_src.count(needle) == 0, \
        'main.py reimplements Rds precedence instead of calling select_rds_on_milliohm'
