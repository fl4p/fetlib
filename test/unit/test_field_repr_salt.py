"""Calibration for field_repr_salt: the cache key must move when anything that decides a
Field's STORED representation changes.

The failure this guards against, reproduced before the salt existed: a stale unpickled
Field(Rds_on, typ=.005, unit=':') merged with a fresh Field(Rds_on, max=.006, unit=':')
-- which the writer scales to max=6, 'mΩ' -- yields ONE Field holding typ=.005 and max=6.0
under unit=':', and get_resistance_milliohm(stat='max') then returns 6000 mΩ for a 6 mΩ
part. A 1000x error served from a cache HIT.

HISTORY, because it is the point of this file. The first version of the salt fingerprinted
the unit tables by value plus `co_code` of the three converting functions, to keep comment
edits from rebuilding the corpus. It had three holes, and the tests here passed anyway
because they only exercised what it could see:

  1. `co_code` omits `co_consts`      -- swap 'mΩ' for 'Ω', bytecode identical
  2. `co_code` omits nested bodies    -- Field.__init__'s nested _unit_value was invisible
  3. three functions are not the closure -- parse_field_value / normalize_text / any_unit
     are reached from them and were unsalted; doubling parse_field_value's result moved
     stored values 1000x with the salt unchanged

So the tests now pin the property that actually holds -- the salt is a function of the
CONTENT of the files listed in _FIELD_REPR_SOURCES -- and one of them asserts the cost
(prose is NOT free) so nobody "optimises" it back into a mute button without reading why.

KNOWN LIMITATION of `_perturb`: it rewrites production source files in place, restoring in
`finally` with a byte-for-byte check. That survives assertion failures but NOT a SIGKILL
mid-test, and it needs a writable checkout. It would also race under pytest-xdist, since
several tests here touch field.py -- there is no xdist config today, so this is a caveat
rather than a defect. A hermetic version would copy the declared dependencies under
tmp_path and have field_repr_salt resolve them from an injectable base directory; that is a
change to the salt's signature, deliberately not bundled with a cache-correctness fix.
"""
import math
import os

import pytest

import dslib.field as F
from dslib.field import Field, DatasheetFields, field_repr_salt, _FIELD_REPR_SOURCES

_DSLIB_DIR = os.path.dirname(os.path.abspath(F.__file__))
_DEP_PATHS = [os.path.join(_DSLIB_DIR, *rel) for rel in _FIELD_REPR_SOURCES]


def _perturb(path, suffix=b'\n# field_repr_salt calibration scratch\n'):
    """Append to `path`, yield, then restore byte-exactly. The restore is in `finally` and
    verified, because a test that corrupts a source file is worse than no test."""
    with open(path, 'rb') as f:
        original = f.read()
    try:
        with open(path, 'wb') as f:
            f.write(original + suffix)
        yield
    finally:
        with open(path, 'wb') as f:
            f.write(original)
        with open(path, 'rb') as f:
            assert f.read() == original, 'FAILED TO RESTORE %s' % path


def test_salt_is_stable_across_calls():
    assert field_repr_salt() == field_repr_salt()


def test_salt_is_a_plain_string():
    # Goes into a cache key, so it must be trivially serialisable and order-free.
    assert isinstance(field_repr_salt(), str)
    assert field_repr_salt().startswith('field-repr:')


@pytest.mark.parametrize('path', _DEP_PATHS, ids=[os.sep.join(r) for r in _FIELD_REPR_SOURCES])
def test_salt_moves_for_every_dependency(path):
    """The closure test. A dependency that does not move the salt is a silent hole: the
    conversion changes and every producer keeps serving pre-change Fields."""
    assert os.path.exists(path), 'declared dependency does not exist: %s' % path
    before = field_repr_salt()
    gen = _perturb(path)
    next(gen)
    try:
        after = field_repr_salt()
    finally:
        next(gen, None)
    assert after != before, '%s does not reach the salt' % path
    assert field_repr_salt() == before, 'salt did not return to baseline'


@pytest.mark.parametrize('rel', _FIELD_REPR_SOURCES, ids=[os.sep.join(r) for r in _FIELD_REPR_SOURCES])
def test_every_dependency_moves_every_producer(rel, tmp_path):
    """The dependency x producer MATRIX, and the reason it is a matrix.

    An earlier probe perturbed only field.py, saw all five producers move, and concluded
    the closure was shut. field.py happens to be in BOTH field_repr_salt's list and v2's
    _V2_DEP_SOURCES, so that was one row generalised without warrant. The other rows were
    not shut: dslib/__init__.py, conditions.py and pdf/pdf2txt/__init__.py are absent from
    _V2_DEP_SOURCES, so a pdf2txt-only normalize_text edit moved four producers and left v2
    serving pre-change Fields. Three real holes.

    One row of a matrix is not the matrix. Keep this parametrised over every dependency and
    asserting every producer, or the next added dependency reopens the same gap silently.
    """
    from dslib.pdf.parse import extract_fields_from_text, parse_datasheet, tabula_read
    from dslib.pdf.sheet import read_sheet
    import dslib.v2

    # A dummy file, NOT an LFS fixture. cache_key only needs `file_dependencies` to exist
    # so it can hash the path's content; it never parses the PDF. Pointing this at a real
    # datasheet would make the calibration fail wherever LFS is not fetched — and a guard
    # that only runs in one environment is a guard that stops running.
    pdf = str(tmp_path / 'dummy.pdf')
    with open(pdf, 'wb') as f:
        f.write(b'%PDF-1.4 not a real pdf\n')

    producers = [
        ('extract_fields_from_text', extract_fields_from_text, ('some text', 'infineon')),
        ('parse_datasheet', parse_datasheet, (pdf,)),
        ('tabula_read', tabula_read, (pdf,)),
        ('read_sheet', read_sheet, (pdf,)),
        ('dslib.v2.parse_datasheet', dslib.v2.parse_datasheet, (pdf,)),
    ]

    def keys():
        return {name: fn.cache_key(*args) for name, fn, args in producers}

    path = os.path.join(_DSLIB_DIR, *rel)
    before = keys()
    gen = _perturb(path)
    next(gen)
    try:
        after = keys()
    finally:
        next(gen, None)

    stale = [n for n in before if before[n] == after[n]]
    assert not stale, '%s does not reach: %s' % (os.sep.join(rel), ', '.join(stale))
    assert keys() == before, 'keys did not return to baseline'


def test_prose_is_deliberately_not_free():
    """Records the accepted COST, so the tradeoff is not silently reversed.

    A comment edit DOES rebuild these caches. The precision optimisation that avoided this
    was abandoned because it could not see co_consts, nested bodies, or anything outside
    the three functions it named -- three holes, the last of which is unbounded. If you are
    here to make prose free again, you must first make the key cover the whole derivation,
    not a proxy for it."""
    before = field_repr_salt()
    gen = _perturb(_DEP_PATHS[0], b'\n# a pure comment, nothing semantic\n')
    next(gen)
    try:
        after = field_repr_salt()
    finally:
        next(gen, None)
    assert after != before, 'salt ignored a content change; it is a proxy again'


def test_unidecode_version_component_is_live_not_inert():
    """unidecode maps Ω -> 'O' and 'O' is in _OHM_BODY, so its version decides what counts
    as an ohm unit.

    Calibrated, not just described. The first version read `unidecode.__version__` with a
    getattr default -- and this package does NOT define that attribute, so it recorded the
    string 'unknown' on every run. The component looked present and did nothing, which is
    the same anti-monotone shape as the bug the salt exists for."""
    import unidecode
    from importlib.metadata import version

    # If this ever starts passing via __version__, the getattr form would have been fine --
    # but it is absent, which is exactly why the metadata form is required.
    assert not hasattr(unidecode, '__version__'), \
        'unidecode now exposes __version__; the comment in field_repr_salt is stale'
    assert version('Unidecode')

    # And the version must actually REACH the salt.
    import importlib.metadata as md
    before = field_repr_salt()
    saved = md.version
    try:
        md.version = lambda name: '9.9.9-probe' if name == 'Unidecode' else saved(name)
        after = field_repr_salt()
    finally:
        md.version = saved
    assert after != before, 'the unidecode version does not reach the salt (inert component)'
    assert field_repr_salt() == before, 'salt did not return to baseline'


def test_unreadable_dependency_raises_rather_than_narrowing_the_key():
    """Absence of evidence must not encode absence of the problem. Skipping a file that
    cannot be read would quietly shrink the key."""
    original = F._FIELD_REPR_SOURCES
    try:
        F._FIELD_REPR_SOURCES = original + (('does_not_exist_xyz.py',),)
        with pytest.raises(Exception):
            field_repr_salt()
    finally:
        F._FIELD_REPR_SOURCES = original
    assert isinstance(field_repr_salt(), str), 'salt broken after restore'


def test_writer_canonicalises_only_the_three_electrical_symbols():
    """Rth* also starts with 'R' and is quoted in °C/W or K/W; the old `symbol[0] == 'R'`
    gate only looked safe because 'K'/'C' are not mkM prefixes, so a bare 'W' capture on a
    thermal row would have become milliohms."""
    assert Field('Rg', math.nan, 1.2, 1.8, 'Q').typ == 1200.0
    assert Field('Rg', math.nan, 1.2, 1.8, 'Q').unit == 'mΩ'

    thermal = Field('RthJC', math.nan, 1.2, math.nan, 'W')
    assert thermal.typ == 1.2, 'thermal resistance scaled as an electrical resistance'
    assert thermal.unit == 'W'


def test_the_1000x_this_salt_exists_to_prevent():
    """Pins the defect the salt gates, so that if fill() is ever made unit-aware this
    records what the old behaviour was."""
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
