"""Calibration for field_repr_salt: the cache key must move when a Field's STORED
representation changes, and must not move when only prose changes.

The failure this guards against was reproduced before the salt existed: a stale unpickled
Field(Rds_on, typ=.005, unit=':') merged with a fresh Field(Rds_on, max=.006, unit=':')
-- which the new writer scales to max=6, 'mΩ' -- yields one Field holding typ=.005 and
max=6.0 under unit=':', and get_resistance_milliohm(stat='max') then returns 6000 mΩ for a
6 mΩ part. A 1000x error served from a cache HIT.

Both directions are asserted on purpose. A salt that changes on every edit is as useless as
one that never changes: it would rebuild ~6040 parts (tabular ~177 s/part) whenever someone
fixed a typo, and the pressure to stop bumping it is how these guards die.
"""
import math

import dslib.field as F
from dslib.field import Field, DatasheetFields, field_repr_salt


def test_salt_is_stable_across_calls():
    # Sets/dicts feed the key, so iteration order must not leak into it.
    assert field_repr_salt() == field_repr_salt()


def test_salt_moves_when_a_unit_table_changes():
    """A table edit changes no bytecode -- _OHM_BODY is a global, so only the LOAD_GLOBAL
    is in co_code. Hashing code alone would MISS this, which is why the tables are in the
    salt by value."""
    before = field_repr_salt()
    original = F._OHM_BODY
    try:
        F._OHM_BODY = original | {'ZZ_fake_omega'}
        after = field_repr_salt()
    finally:
        F._OHM_BODY = original
    assert after != before, 'editing _OHM_BODY did not move the salt'
    assert field_repr_salt() == before, 'salt did not return to baseline after restore'


def test_salt_moves_when_the_writer_scope_changes():
    before = field_repr_salt()
    original = F._WRITER_CANONICAL_SYMBOLS
    try:
        F._WRITER_CANONICAL_SYMBOLS = frozenset(original | {'RthJC'})
        after = field_repr_salt()
    finally:
        F._WRITER_CANONICAL_SYMBOLS = original
    assert after != before, 'widening the writer scope did not move the salt'


def test_salt_moves_when_the_unitless_default_changes():
    before = field_repr_salt()
    original = F._RESISTANCE_UNITLESS_TO_MILLI
    try:
        F._RESISTANCE_UNITLESS_TO_MILLI = {**original, 'Rg': 1.0}   # ohm-scale -> mOhm
        after = field_repr_salt()
    finally:
        F._RESISTANCE_UNITLESS_TO_MILLI = original
    assert after != before, 'changing a stored-scale default did not move the salt'


def test_salt_ignores_comments_and_docstrings():
    """co_code excludes docstrings and comments, so prose edits are free. Demonstrated on
    two functions that differ ONLY in docstring + comment."""

    def a(x):
        """One docstring."""
        return x + 1

    def b(x):
        """A completely different docstring, much longer than the other one."""
        # ...and a comment that the first one does not have.
        return x + 1

    assert a.__code__.co_code == b.__code__.co_code, \
        'co_code is sensitive to prose; the salt would rebuild the corpus on a typo fix'


def test_writer_canonicalises_only_the_three_electrical_symbols():
    """The scope fix. Rth* also starts with 'R' and is quoted in °C/W or K/W; the old
    `symbol[0] == 'R'` gate only looked safe because 'K'/'C' are not mkM prefixes, so a
    bare 'W' capture on a thermal row would have become milliohms."""
    assert Field('Rg', math.nan, 1.2, 1.8, 'Q').typ == 1200.0
    assert Field('Rg', math.nan, 1.2, 1.8, 'Q').unit == 'mΩ'

    thermal = Field('RthJC', math.nan, 1.2, math.nan, 'W')
    assert thermal.typ == 1.2, 'thermal resistance was scaled as an electrical resistance'
    assert thermal.unit == 'W'


def test_the_1000x_this_salt_exists_to_prevent():
    """Not a test of the salt itself but of the defect it gates: pin the exact merge, so
    that if fill() is ever made unit-aware this records what the old behaviour was."""
    stale = Field('Rds_on', math.nan, 0.005, math.nan, None)
    stale.unit = ':'                       # a pre-canonicalisation cache generation

    fresh = Field('Rds_on', math.nan, math.nan, 0.006, ':')
    assert fresh.max == 6.0 and fresh.unit == 'mΩ', 'writer no longer canonicalises ":"'

    ds = DatasheetFields()
    ds.add(stale)
    ds.add(fresh)
    merged = ds.fields_filled['Rds_on']

    # fill() copies stats between candidates without converting or comparing units, so the
    # merged Field carries one raw stat and one canonical stat under a single unit.
    assert merged.typ == 0.005 and merged.max == 6.0 and merged.unit == ':'
    assert ds.get_resistance_milliohm('Rds_on', stat='max') == 6000.0
