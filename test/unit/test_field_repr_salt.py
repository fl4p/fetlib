"""Calibration for field_repr_salt: the cache key must move when anything that decides a
Field's STORED representation changes.

The failure this guards against, reproduced before the salt existed: a stale unpickled
Field(Rds_on, typ=.005, unit=':') merged with a fresh Field(Rds_on, max=.006, unit=':')
-- which the writer scales to max=6, 'mΩ' -- yields ONE Field holding typ=.005 and max=6.0
under unit=':', and get_resistance_milliohm(stat='max') then returns 6000 mΩ for a 6 mΩ
part. A 1000x error served from a cache HIT.

HISTORY, because it is the point of this file. The first salt fingerprinted the unit tables
by value plus `co_code` of the three converting functions, to keep comment edits from
rebuilding the corpus. It had three holes, and the tests passed anyway because they only
exercised what it could already see:

  1. `co_code` omits `co_consts`      -- swap 'mΩ' for 'Ω', bytecode identical
  2. `co_code` omits nested bodies    -- Field.__init__'s nested _unit_value was invisible
  3. three functions are not the closure -- parse_field_value / normalize_text / any_unit
     are reached from them and were unsalted; doubling parse_field_value's result moved
     stored values 1000x with the salt unchanged

TWO CONCERNS, TESTED SEPARATELY. Proving "every dependency moves every producer" by
perturbing files and reading producer keys conflated them, and the honest version is a
decomposition:

  (a) does each declared DEPENDENCY reach the signature?   -> perturb copies under tmp_path
  (b) does the SIGNATURE reach each producer's cache key?  -> monkeypatch _FIELD_REPR_SIG

(a) and (b) together give the matrix, and both are hermetic. The earlier version rewrote
five live production source files in place; a concurrent edit between its snapshot and its
restore would have been destroyed silently, which is not hypothetical in a worktree two
agents are editing. Nothing here writes to the repo any more.
"""
import math
import os
import shutil

import pytest

import dslib.field as F
from dslib.field import (Field, DatasheetFields, field_repr_salt, _FIELD_REPR_SOURCES,
                         _FIELD_REPR_SIG, _compute_field_repr_sig)

_DSLIB_DIR = os.path.dirname(os.path.abspath(F.__file__))
_IDS = [os.sep.join(r) for r in _FIELD_REPR_SOURCES]


def _dep_tree(tmp_path):
    """Copy the declared dependencies into tmp_path, preserving relative layout."""
    for rel in _FIELD_REPR_SOURCES:
        dst = tmp_path.joinpath(*rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(_DSLIB_DIR, *rel), dst)
    return str(tmp_path)


def test_salt_is_stable_across_calls():
    assert field_repr_salt() == field_repr_salt()


def test_salt_is_a_plain_string():
    assert isinstance(field_repr_salt(), str)
    assert field_repr_salt().startswith('field-repr:')


def test_copied_tree_reproduces_the_real_signature(tmp_path):
    """Guards the guard: if the copy did not reproduce the real signature, every
    perturbation test below would be measuring something other than production."""
    assert field_repr_salt(root=_dep_tree(tmp_path)) == _FIELD_REPR_SIG


@pytest.mark.parametrize('rel', _FIELD_REPR_SOURCES, ids=_IDS)
def test_every_dependency_reaches_the_signature(rel, tmp_path):
    """(a). A dependency that does not reach the signature is a silent hole: the conversion
    changes and every producer keeps serving pre-change Fields."""
    root = _dep_tree(tmp_path)
    before = field_repr_salt(root=root)
    target = tmp_path.joinpath(*rel)
    target.write_bytes(target.read_bytes() + b'\n# perturbed\n')
    assert field_repr_salt(root=root) != before, '%s does not reach the salt' % os.sep.join(rel)


def test_signature_reaches_every_producer(monkeypatch):
    """(b). A salt that is defined but absent from a given key is DEAD. This is what caught
    the v2 hole: dslib.v2's decorator carried only v2_code_salt, whose _V2_DEP_SOURCES omits
    dslib/__init__.py, conditions.py and pdf/pdf2txt -- so a normalize_text edit moved four
    producers and left v2 serving pre-change Fields."""
    from dslib.pdf.parse import extract_fields_from_text, parse_datasheet, tabula_read
    from dslib.pdf.sheet import read_sheet
    import dslib.v2

    pdf = str(tmp_pdf())
    producers = [
        ('extract_fields_from_text', extract_fields_from_text, ('some text', 'infineon')),
        ('parse_datasheet', parse_datasheet, (pdf,)),
        ('tabula_read', tabula_read, (pdf,)),
        ('read_sheet', read_sheet, (pdf,)),
        ('dslib.v2.parse_datasheet', dslib.v2.parse_datasheet, (pdf,)),
    ]

    def keys():
        return {name: fn.cache_key(*args) for name, fn, args in producers}

    before = keys()
    monkeypatch.setattr(F, '_FIELD_REPR_SIG', 'field-repr:PERTURBED')
    after = keys()

    stale = [n for n in before if before[n] == after[n]]
    assert not stale, 'the representation salt does not reach: %s' % ', '.join(stale)


_TMP_PDF = []


def tmp_pdf():
    """A dummy file for `file_dependencies`. cache_key hashes the path's content but never
    parses it, so this must NOT be an LFS datasheet -- a calibration that only runs where
    LFS is fetched is one that stops running."""
    if not _TMP_PDF:
        import tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'dummy.pdf')
        with open(p, 'wb') as f:
            f.write(b'%PDF-1.4 not a real pdf\n')
        _TMP_PDF.append(p)
    return _TMP_PDF[0]


def test_the_salt_is_bound_to_the_imported_generation(tmp_path):
    """The inverse failure, and the more dangerous one. Reading disk per call would let a
    long-lived process that loaded the OLD Field code notice a new on-disk edit, compute the
    NEW salt, and write OLD-representation Fields under the new-generation key -- so the next
    process reads them as new. Staleness is recoverable; a new key filled with old values is
    not. Two agents edit this repo concurrently, so this is a live scenario.

    field_repr_salt() must therefore be a SNAPSHOT taken at import, immune to later edits,
    while _compute_field_repr_sig() still sees them (which is what proves the edit landed and
    keeps this test from being vacuous)."""
    root = _dep_tree(tmp_path)
    fresh_before = _compute_field_repr_sig(root)
    target = tmp_path.joinpath(*_FIELD_REPR_SOURCES[0])
    target.write_bytes(target.read_bytes() + b'\n# a peer agent edits mid-run\n')

    assert field_repr_salt() == _FIELD_REPR_SIG, 'salt is not pinned to the imported code'
    assert _compute_field_repr_sig(root) != fresh_before, 'perturbation did not land'


def test_prose_is_deliberately_not_free(tmp_path):
    """Records the accepted COST so the tradeoff is not silently reversed.

    A comment edit DOES rebuild these caches. The precision optimisation that avoided it was
    abandoned because it could not see co_consts, nested bodies, or anything outside the
    three functions it named -- three holes, the last unbounded. To make prose free again you
    must first make the key cover the whole derivation, not a proxy for it."""
    root = _dep_tree(tmp_path)
    before = field_repr_salt(root=root)
    target = tmp_path.joinpath(*_FIELD_REPR_SOURCES[0])
    target.write_bytes(target.read_bytes() + b'\n# a pure comment, nothing semantic\n')
    assert field_repr_salt(root=root) != before, 'salt ignored a content change'


def test_unreadable_dependency_raises_rather_than_narrowing_the_key(tmp_path):
    """Absence of evidence must not encode absence of the problem. Skipping a file that
    cannot be read would quietly shrink the key."""
    root = _dep_tree(tmp_path)
    original = F._FIELD_REPR_SOURCES
    try:
        F._FIELD_REPR_SOURCES = original + (('does_not_exist_xyz.py',),)
        with pytest.raises(Exception):
            field_repr_salt(root=root)
    finally:
        F._FIELD_REPR_SOURCES = original
    assert isinstance(field_repr_salt(), str), 'salt broken after restore'


def test_unidecode_version_component_is_live_not_inert():
    """unidecode maps Ω -> 'O' and 'O' is in _OHM_BODY, so its version decides what counts as
    an ohm unit.

    Calibrated, not just described. The first version read `unidecode.__version__` with a
    getattr default -- and this package does NOT define that attribute, so it recorded the
    string 'unknown' on every run: a component that looked present and did nothing, the same
    anti-monotone shape as the bug the salt exists for."""
    import unidecode
    from importlib.metadata import version

    assert not hasattr(unidecode, '__version__'), \
        'unidecode now exposes __version__; the comment in field_repr_salt is stale'
    assert version('Unidecode')

    import importlib.metadata as md
    before = _compute_field_repr_sig()
    saved = md.version
    try:
        md.version = lambda name: '9.9.9-probe' if name == 'Unidecode' else saved(name)
        after = _compute_field_repr_sig()
    finally:
        md.version = saved
    assert after != before, 'the unidecode version does not reach the salt (inert component)'
    assert _compute_field_repr_sig() == before, 'signature did not return to baseline'


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
    """Pins the defect the salt gates, so if fill() is ever made unit-aware this records
    what the old behaviour was."""
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
