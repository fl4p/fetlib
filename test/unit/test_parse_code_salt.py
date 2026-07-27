"""legacy_parse_code_salt: the cache key must cover the code that DERIVES the value.

The hole this closes. `disk_cache(hash_func_code=True)` hashes only the decorated function's
own source, and tabula_read does not even set it. extract_fields_from_dataframes -- which
decides the symbol a row is attributed to and the unit it carries -- is therefore invisible
to both keys, so a fix confined to that helper keeps serving the pre-fix cached value
indefinitely and looks exactly like a fix that did not work. That is not hypothetical: the
iter_table unit fix landed under precisely this hole.

These tests are mostly about SENSITIVITY. Asserting a salt exists proves nothing; a constant
would pass. Each dependency is mutated in a scratch tree and the salt must move.
"""
import os
import shutil

import pytest

from dslib.pdf.parse import (_PARSE_DERIVATION_SOURCES, _compute_parse_code_sig,
                             legacy_parse_code_salt)

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
DSLIB = os.path.join(PKG, 'dslib')


@pytest.fixture()
def tree(tmp_path):
    """A scratch copy of just the hashed dependencies."""
    for rel in _PARSE_DERIVATION_SOURCES:
        dst = tmp_path.joinpath(*rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(DSLIB, *rel), dst)
    return tmp_path


def test_is_deterministic():
    assert legacy_parse_code_salt() == legacy_parse_code_salt()
    assert legacy_parse_code_salt().startswith('parse-src:')


def test_production_value_is_the_import_snapshot_not_a_live_read():
    """The blocker this replaced.

    Computing the hash per call inverts the guarantee. A long-lived process still executing
    the OLD parse.py would see a concurrent on-disk edit, compute the NEW hash, and write its
    OLD results under the NEW generation key -- so every later process trusts entries
    produced by code that never ran. The key must describe the code that ACTUALLY produced
    the value, which is only what this process imported.

    Proved WITHOUT touching live sources: make a recomputation impossible, then require the
    production call to succeed anyway. An earlier version of this test appended to the real
    parse.py and restored it -- which is precisely the destructive pattern field_repr_salt's
    own comment warns about, since a concurrent edit landing inside that window is silently
    destroyed. Do not reintroduce it; the tree fixture exists for perturbation.
    """
    import dslib.pdf.parse as m

    assert legacy_parse_code_salt() is m._PARSE_CODE_SIG, 'not returning the import snapshot'

    def explode(root=None):
        raise AssertionError('production path recomputed the salt from disk')

    orig = m._compute_parse_code_sig
    m._compute_parse_code_sig = explode
    try:
        assert legacy_parse_code_salt() == m._PARSE_CODE_SIG
    finally:
        m._compute_parse_code_sig = orig

    # and the snapshot is a real hash of the real sources, not a placeholder
    assert legacy_parse_code_salt() == _compute_parse_code_sig()


@pytest.mark.parametrize('rel', _PARSE_DERIVATION_SOURCES, ids=lambda r: '/'.join(r))
def test_every_dependency_actually_moves_the_salt(tree, rel):
    """The calibration. One file changes, the salt must change -- otherwise that file is in
    the list for decoration only and edits to it would be served stale."""
    before = legacy_parse_code_salt(root=str(tree))
    p = tree.joinpath(*rel)
    p.write_text(p.read_text(encoding='utf-8') + '\n# touched\n', encoding='utf-8')
    after = legacy_parse_code_salt(root=str(tree))
    assert before != after, '%s does not affect the cache key' % '/'.join(rel)


def test_covers_the_helper_that_caused_the_bug(tree):
    """Specifically: an edit inside extract_fields_from_dataframes -- not the decorated
    entry point -- must move the key. This is the exact change that was invisible before."""
    p = tree.joinpath('pdf', 'parse.py')
    src = p.read_text(encoding='utf-8')
    assert 'def extract_fields_from_dataframes' in src
    before = legacy_parse_code_salt(root=str(tree))
    p.write_text(src.replace('def extract_fields_from_dataframes',
                             'def extract_fields_from_dataframes  # edited', 1), encoding='utf-8')
    assert legacy_parse_code_salt(root=str(tree)) != before


def test_unreadable_dependency_raises_rather_than_narrowing_the_key(tree):
    """Skipping a file that cannot be read would silently shrink the key and reintroduce the
    very staleness this guards -- so it must be LOUDER than a cache miss, not quieter."""
    os.remove(tree.joinpath('pdf', 'expr.py'))
    with pytest.raises(Exception):
        legacy_parse_code_salt(root=str(tree))


def test_wired_into_both_entry_points():
    """tabula_read and the outer parse_datasheet are the two functions whose keys were blind
    to the helper. Both must compose this salt."""
    import inspect

    import dslib.pdf.parse as m

    src = inspect.getsource(m)
    # NB the trailing '(' matters: a bare 'def tabula_read' also matches
    # tabula_read_pdf_cached, which caches the raw Tabula DataFrames -- the INPUT to the
    # derivation, not the derivation -- and correctly carries no derivation salt.
    for fn in ('def parse_datasheet(', 'def tabula_read('):
        i = src.index(fn)
        dec = src[max(0, i - 400):i]
        assert 'legacy_parse_code_salt' in dec, '%s is not salted with it' % fn


def test_raw_tabula_extraction_is_deliberately_not_salted():
    """tabula_read_pdf_cached caches Tabula's own DataFrame output, which depends on the PDF
    and Tabula's arguments -- not on any code in this repo that shapes a Field. Salting it
    with the derivation would throw away an expensive (~177 s/part) cache on every unrelated
    parser edit, for no correctness gain."""
    import inspect

    import dslib.pdf.parse as m

    src = inspect.getsource(m)
    i = src.index('def tabula_read_pdf_cached(')
    assert 'legacy_parse_code_salt' not in src[max(0, i - 300):i]


def test_field_repr_is_not_double_hashed():
    """field.py is covered by field_repr_salt, which is composed alongside this one. Listing
    it here too would hash it twice -- harmless but misleading about where coverage lives."""
    assert ('field.py',) not in _PARSE_DERIVATION_SOURCES
    assert not any(r[-1] == 'field.py' for r in _PARSE_DERIVATION_SOURCES)
