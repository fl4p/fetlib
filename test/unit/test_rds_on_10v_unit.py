"""Rds_on_10v carries a real unit from its producer instead of a guessed default.

`_RESISTANCE_UNITLESS_TO_MILLI` used to map Rds_on_10v -> 1e3, and since every one of the
10908 fields of that symbol in the shipped DB was unitless, the guess WAS the scale for all
of them. `MosfetBasicSpecs.fields()` -- the only constructor -- now states 'Ω', which it can
do with certainty because `ensure_ohm` has already forced the attribute to ohms.

The tests here pin the three things that make that safe rather than merely different:
the value does not move, a unitless field is now refused instead of guessed, and a unitless
field cannot be merged with a united one under either representation.
"""
import math
import warnings

import pytest

from dslib.discovery import MosfetBasicSpecs
from dslib.field import (_RESISTANCE_UNITLESS_TO_MILLI, _WRITER_CANONICAL_SYMBOLS,
                         DatasheetFields, Field, expected_dimension)


def _specs(rds_ohm, vds=100.0, id25=50.0):
    return MosfetBasicSpecs(
        Vds_max=vds, Rds_on_10v_max=rds_ohm, ID_25=id25,
        Vgs_th_min=math.nan, Vgs_th_typ=math.nan, Vgs_th_max=3.0,
        Qg_typ=30.0, Qg_max=40.0, source=['test'])


def _field_of(specs, symbol='Rds_on_10v'):
    return next(f for f in specs.fields() if f.symbol == symbol)


# ------------------------------------------------------------------ the producer
@pytest.mark.parametrize('ohms', [0.16, 0.0057, 0.0011])
def test_producer_states_ohms_and_writer_canonicalises(ohms):
    f = _field_of(_specs(ohms))
    assert f.unit == 'mΩ'
    assert f.max == pytest.approx(ohms * 1e3)


@pytest.mark.parametrize('ohms', [0.16, 0.0057, 0.0011])
def test_read_value_is_unchanged_by_the_migration(ohms):
    """The whole change has to be value-preserving: the old path stored ohms and
    multiplied by the 1e3 default at read time, the new one stores mΩ and multiplies
    by 1. Same number out, one fewer assumption in."""
    ds = DatasheetFields('mfr', 'mpn', fields=[_field_of(_specs(ohms))])
    assert ds.get_resistance_milliohm('Rds_on_10v', stat='max') == pytest.approx(ohms * 1e3)


def test_a_whole_ohm_part_also_round_trips():
    """The low end of the range is the easy case for a 1000x bug to hide in, because
    both scales look plausible. A 1.2 Ω part is unambiguous: 1200 mΩ or nothing.
    (ID_25 has to match, or MosfetBasicSpecs' own plausibility assert rejects the part.)
    """
    ds = DatasheetFields('mfr', 'mpn',
                         fields=[_field_of(_specs(1.2, vds=100.0, id25=5.0))])
    assert ds.get_resistance_milliohm('Rds_on_10v', stat='max') == pytest.approx(1200.0)


def test_qg_and_vds_are_untouched():
    """Scope check -- only the resistance field's unit was meant to change."""
    specs = _specs(0.016)
    by_sym = {f.symbol: f for f in specs.fields()}
    assert by_sym['Qg'].unit == 'nC'
    assert by_sym['Vds'].unit is None
    assert by_sym['ID_25'].unit is None


# ------------------------------------------------------------------ the default is gone
def test_no_unitless_default_remains_for_the_symbol():
    assert 'Rds_on_10v' not in _RESISTANCE_UNITLESS_TO_MILLI
    # ...and the ones that legitimately still have a documented default keep it.
    assert _RESISTANCE_UNITLESS_TO_MILLI == {'Rds_on': 1.0, 'Rg': 1e3}


def test_unitless_is_refused_and_says_so():
    """Absence of a unit must not silently become a scale. It must also not silently
    become NaN: downstream, a bare NaN reads as 'the datasheet does not give this',
    which is a different claim from 'we cannot tell what scale this is on'."""
    ds = DatasheetFields('mfr', 'mpn',
                         fields=[Field('Rds_on_10v', math.nan, math.nan, 0.016)])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        got = ds.get_resistance_milliohm('Rds_on_10v', stat='max')
    assert math.isnan(got)
    assert any('no documented unitless scale' in str(w.message) for w in caught)


def test_symbol_is_still_a_resistance_everywhere_else():
    """The two sets answer different questions. Deriving the writer gate from the
    defaults table -- as it used to -- would have dropped Rds_on_10v out of unit
    canonicalisation and out of expected_dimension() the moment the default went,
    silently un-converting the unit that had just been made explicit."""
    assert 'Rds_on_10v' in _WRITER_CANONICAL_SYMBOLS
    assert expected_dimension('Rds_on_10v') == 'R'


# ------------------------------------------------------------------ the merge hole
def test_unitless_and_united_fields_do_not_merge_two_scales():
    """The mixed-generation case, and the 1000x it would cause.

    A DB record written before the producer stated 'Ω' holds an ohm-magnitude number
    with no unit; a fresh candidate holds mΩ. With no default for the symbol there is
    nothing to convert the unitless side with, so merging them under either unit would
    put two different scales in one Field -- and the reader applies one unit to both.
    """
    ds = DatasheetFields('mfr', 'mpn')
    ds.add(Field('Rds_on_10v', math.nan, math.nan, 0.016))            # pre-change: ohms
    ds.add(Field('Rds_on_10v', math.nan, 12.0, math.nan, unit='mΩ'))

    merged = ds.fields_filled['Rds_on_10v']
    assert not (merged.max == pytest.approx(0.016) and merged.typ == pytest.approx(12.0)), \
        'two scales merged into one Field'


@pytest.mark.parametrize('legacy_first', [True, False])
def test_the_readable_value_wins_regardless_of_order(legacy_first):
    """WHICH value survives, not merely that a guard fired.

    The first version of this only asserted `_rejected_fills >= 1`, and that passed while
    the aggregate kept the unitless 0.016 it could not read and discarded the perfectly
    good 16 mΩ candidate -- the guard fired and dropped the RIGHT value. Worse, the
    outcome depended purely on insertion order: legacy-first read NaN, fresh-first read 16.
    """
    legacy = Field('Rds_on_10v', math.nan, math.nan, 0.016)   # ohm-magnitude, no unit
    good = Field('Rds_on_10v', math.nan, math.nan, 16.0, unit='mΩ')

    ds = DatasheetFields('mfr', 'mpn')
    for f in ([legacy, good] if legacy_first else [good, legacy]):
        ds.add(f)

    assert ds.fields_filled['Rds_on_10v'].unit == 'mΩ'
    assert ds.get_resistance_milliohm('Rds_on_10v', stat='max') == pytest.approx(16.0)


def test_promotion_is_scoped_to_symbols_without_a_default():
    """Two-sided. `Rg`'s unitless default IS documented, so a unitless Rg base is
    readable and must keep gap-filling rather than being displaced."""
    ds = DatasheetFields('mfr', 'mpn')
    ds.add(Field('Rg', math.nan, math.nan, 0.1))               # unitless -> Ω by default
    ds.add(Field('Rg', math.nan, 3600.0, math.nan, unit='mΩ'))
    merged = ds.fields_filled['Rg']
    assert merged.max == pytest.approx(100.0) and merged.typ == pytest.approx(3600.0)


def test_symbols_that_kept_a_default_still_merge():
    """Two-sided: the new rejection is scoped to symbols with no default, so Rg -- whose
    unitless default is documented as ohms -- must still merge and convert."""
    base = Field('Rg', math.nan, math.nan, 0.1)                    # unitless -> Ω default
    fresh = Field('Rg', math.nan, 3600.0, math.nan, unit='mΩ')

    ds = DatasheetFields('mfr', 'mpn')
    ds.add(base)
    ds.add(fresh)
    merged = ds.fields_filled['Rg']
    assert merged.unit == 'mΩ'
    assert merged.max == pytest.approx(100.0)      # 0.1 Ω promoted to mΩ
    assert merged.typ == pytest.approx(3600.0)
