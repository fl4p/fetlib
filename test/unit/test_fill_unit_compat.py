"""Field.fill: transactional, unit-aware merge.

Two defects are pinned here, both measured on the shipped DB rather than imagined.

1. CROSS-DIMENSION CONTAMINATION. A Field carries ONE unit, but fill() used to copy stats
   in from candidates quoted in another, and get_resistance_milliohm keys on the FIELD's
   unit rather than the stat's -- so it scaled them. Real cases:
     vishay/SUM60N10-17              Rds_on.min from an AMPERE cell (100 A) beside a
                                     genuine 13-16.5 mΩ typ/max
     infineon/FF4000UXTR33T2M1BPSA1  Rg.min from a MICROSECOND cell (0.26 μs)
   Those stats are not resistances at all.

2. THE GUARD THAT ATE THE GOOD VALUE. A post-hoc "discard the impossible max" check ran
   AFTER fill() had mutated, so the only thing left to sacrifice was a stat that might be
   the correct one. On ao/AOB66515L text's correct max=1180 arrives first and v2's wrong
   typ=1.18 merges second, and the guard discarded the max -- worse than the incoherent
   field it was written for.

Every test here asserts WHICH value survived and, where it matters, its source. "The guard
fired" is not an assertion: it passes identically when the guard destroys the correct data,
which is exactly how (2) shipped. Several tests are run in BOTH arrival orders for the same
reason -- ordering is part of the input.
"""
import math

import pytest

from dslib.field import (Field, DatasheetFields, unit_dimensions,
                         units_provably_incompatible)

NA = math.nan


# --- the unit classifier -------------------------------------------------------------

def test_unit_dimensions_uses_exprs_tables():
    assert 'R' in unit_dimensions('mΩ')
    assert 'R' in unit_dimensions('Ω')
    assert 'I' in unit_dimensions('A')
    assert 't' in unit_dimensions('μs')
    assert 'C' in unit_dimensions('pF')
    assert 'Q' in unit_dimensions('nC')


@pytest.mark.parametrize('unit,dimension', [
    ('nS', 't'),
    ('PF', 'C'),
    ('nc', 'Q'),
    ('a', 'I'),
    ('v', 'V'),
])
def test_unit_dimensions_uses_the_parsers_case_insensitive_semantics(unit, dimension):
    assert dimension in unit_dimensions(unit)


def test_unit_dimensions_covers_the_wider_ohm_body():
    """_OHM_BODY is deliberately wider than expr's R unit_regex; those spellings must not
    classify as unknown or the merge guard goes blind on exactly the corrupt units."""
    for u in (':', 'o', 'OQ', 'm:', '|mQ'):
        assert 'R' in unit_dimensions(u), u


def test_unknown_and_empty_units_are_not_a_dimension_claim():
    assert unit_dimensions('') == frozenset()
    assert unit_dimensions(None) == frozenset()
    assert unit_dimensions('Unit') == frozenset()


def test_incompatibility_is_one_directional():
    # provable mismatches
    assert units_provably_incompatible('mΩ', 'A')
    assert units_provably_incompatible('mΩ', 'μs')
    assert units_provably_incompatible('nC', 'pF')
    # NOT claimed for unknown/unitless -- unitless is the norm for Rds_on_10v
    assert not units_provably_incompatible('mΩ', '')
    assert not units_provably_incompatible('', 'A')
    assert not units_provably_incompatible('mΩ', 'Ω')     # same dimension, different scale
    assert not units_provably_incompatible('mΩ', 'Unit')


# --- (1) cross-dimension contamination ------------------------------------------------

@pytest.mark.parametrize('reverse', [False, True], ids=['ohm-first', 'amp-first'])
def test_ampere_stat_never_merges_into_a_resistance(reverse):
    """vishay/SUM60N10-17 shaped. Asserts the surviving VALUE, not just that something was
    dropped, and in both arrival orders."""
    ohms = Field('Rds_on', NA, 0.013, 0.0165, 'Ω')      # -> 13 / 16.5 mΩ
    amps = Field('Rds_on', 100.0, NA, NA, 'A')          # a current cell, not a resistance

    ds = DatasheetFields()
    for f in ([amps, ohms] if reverse else [ohms, amps]):
        ds.add(f)
    got = ds.fields_filled['Rds_on']

    assert got.unit == 'mΩ'
    assert got.typ == 13.0 and got.max == 16.5
    assert math.isnan(got.min), 'the 100 A cell was merged into Rds_on.min'


@pytest.mark.parametrize('reverse', [False, True], ids=['ohm-first', 'us-first'])
def test_microsecond_stat_never_merges_into_rg(reverse):
    """infineon/FF4000UXTR33T2M1BPSA1 shaped."""
    ohms = Field('Rg', NA, 1500.0, NA, 'mΩ')
    usec = Field('Rg', 0.26, NA, NA, 'μs')

    ds = DatasheetFields()
    for f in ([usec, ohms] if reverse else [ohms, usec]):
        ds.add(f)
    got = ds.fields_filled['Rg']

    assert got.unit == 'mΩ' and got.typ == 1500.0
    assert math.isnan(got.min), 'a 0.26 μs cell was merged into Rg.min'
    assert ds.get_resistance_milliohm('Rg', stat='typ_or_max_or_min') == 1500.0


def test_leakage_current_never_merges_into_vds():
    """onsemi/NVTFS8D1N08HTAG shaped, and the highest-volume case: 215 Vds stats change on
    the shipped DB. An I_DSS leakage row ('mA'/'nA') sat next to the 80 V rating and its
    value was eligible for Vds. Vds drives part SELECTION by voltage rating, so a 10 in
    Vds.max on an 80 V part is not cosmetic."""
    ds = DatasheetFields()
    ds.add(Field('Vds', 80.0, NA, NA, 'V'))
    ds.add(Field('Vds', NA, NA, 10.0, 'mA'))     # I_DSS @ Vds=80V
    ds.add(Field('Vds', NA, NA, 100.0, 'nA'))
    ds.add(Field('Vds', NA, NA, 80.0, 'V'))      # the genuine rating

    got = ds.fields_filled['Vds']
    assert got.max == 80.0, 'a leakage current reached Vds.max'
    assert got.min == 80.0
    assert got._rejected_fills == 2


def test_a_unitless_stat_still_merges():
    """The mirror case. A guard that also rejects the legitimate merge is a mute button:
    unitless is the NORM for several symbols, so this must survive untouched."""
    base = Field('Rds_on', NA, 3.2, NA, 'mΩ')
    more = Field('Rds_on', NA, NA, 10.0, None)          # ti/CSD19535KTTT shaped

    ds = DatasheetFields()
    ds.add(base)
    ds.add(more)
    got = ds.fields_filled['Rds_on']
    assert got.typ == 3.2 and got.max == 10.0, 'a legitimate unitless merge was rejected'


@pytest.mark.parametrize('reverse', [False, True], ids=['unitless-first', 'milliohm-first'])
def test_unitless_rg_and_explicit_milliohm_merge_in_one_scale(reverse):
    """onsemi/FDMS86150ET100 shaped.

    Rg's unitless compatibility default is Ω, unlike Rds_on's mΩ default. Merging a
    canonical-mΩ max into a unitless base without converting both sides makes the reader
    multiply the max by 1000 a second time.
    """
    unitless = Field('Rg', NA, 0.1, NA, None)
    explicit = Field('Rg', NA, NA, 3.6, 'Ω')  # canonicalized by the writer to 3600 mΩ

    ds = DatasheetFields()
    for f in ([explicit, unitless] if reverse else [unitless, explicit]):
        ds.add(f)

    got = ds.fields_filled['Rg']
    assert got.unit == 'mΩ'
    assert got.typ == 100.0 and got.max == 3600.0
    assert ds.get_resistance_milliohm('Rg') == 3600.0


def test_wrong_dimension_only_candidate_is_retained_but_cannot_seed_base():
    ds = DatasheetFields()
    bad = Field('Rg', 0.4, 0.8, 1.2, 'pF')
    ds.add(bad)

    assert 'Rg' not in ds.fields_filled
    assert ds.fields_lists['Rg'] == [bad]


def test_same_dimension_different_scale_is_converted_not_rejected():
    """An ohm-quoted candidate merging into an mΩ field must be SCALED, not dropped and not
    taken at face value. Field.__init__ canonicalises the three electrical symbols, so this
    covers legacy/unpickled candidates that bypassed it."""
    base = Field('Rds_on', NA, 3.2, NA, 'mΩ')
    # Built unitless (so __init__ does not canonicalise it) then stamped with 'Ω', which is
    # how an old pickle holds it: raw ohm magnitude, ohm unit, never through the new writer.
    legacy = Field('Rds_on', NA, NA, 0.0165, None)
    legacy.unit = 'Ω'

    ds = DatasheetFields()
    ds.add(base)
    ds.add(legacy)
    got = ds.fields_filled['Rds_on']
    assert got.typ == 3.2
    assert got.max == pytest.approx(16.5), 'ohm candidate was not converted to mΩ'


# --- (2) the transactional property ---------------------------------------------------

@pytest.mark.parametrize('reverse', [False, True], ids=['max-first', 'typ-first'])
def test_the_correct_stat_is_never_the_one_sacrificed(reverse):
    """ao/AOB66515L. The old post-hoc guard discarded max BECAUSE it had already mutated.
    Whatever this merge produces, it must never be the case that the correct 1180 was
    dropped while the wrong 1.18 was kept -- that was strictly worse than not guarding."""
    correct = Field('Qrr', NA, NA, 1180.0, 'nC')        # text, correct
    wrong = Field('Qrr', NA, 1.18, NA, 'nC')           # v2, 1000x low

    ds = DatasheetFields()
    for f in ([wrong, correct] if reverse else [correct, wrong]):
        ds.add(f)
    got = ds.fields_filled['Qrr']

    kept_wrong_dropped_right = (got.typ == 1.18 and math.isnan(got.max))
    assert not kept_wrong_dropped_right, \
        'the guard sacrificed the correct max and kept the 1000x-low typ'
    # and the correct value must still be reachable from the candidate list either way
    assert any(c.max == 1180.0 for c in ds.fields_lists['Qrr'])


def test_fill_does_not_mutate_when_it_rejects():
    """Transactional: a rejected candidate must leave self byte-identical, not half-merged."""
    base = Field('Rds_on', NA, 3.2, NA, 'mΩ')
    before = (base.min, base.typ, base.max, base.unit, dict(base._sources))
    base.fill(Field('Rds_on', 100.0, NA, NA, 'A'))
    assert (base.min, base.typ, base.max, base.unit, dict(base._sources)) == before


def test_rejections_are_counted_not_silent():
    """A guard that drops data without saying so is unauditable."""
    base = Field('Rds_on', NA, 3.2, NA, 'mΩ')
    assert getattr(base, '_rejected_fills', 0) == 0
    base.fill(Field('Rds_on', 100.0, NA, NA, 'A'))
    assert base._rejected_fills == 1


def test_candidates_are_still_retained_for_the_reader():
    """Rejecting a merge must not remove the candidate: fields_lists is what _get_by_cond
    and the audit tooling select over."""
    ds = DatasheetFields()
    ds.add(Field('Rds_on', NA, 0.013, 0.0165, 'Ω'))
    ds.add(Field('Rds_on', 100.0, NA, NA, 'A'))
    assert len(ds.fields_lists['Rds_on']) == 2
