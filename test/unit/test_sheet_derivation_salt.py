"""read_sheet's cache key must move when read_sheet's DERIVATION changes.

read_sheet is `@disk_cache(hash_func_code=False, salt=('v11', field_repr_salt,
ascii_derivation_salt, sheet_derivation_salt))`. The two derivation salts are
both required. The sheet salt covers table/symbol logic; the shared ASCII salt
covers the nested pdf_to_ascii cache that produces its Row objects.

The gap was live. befbb355 changed parse_cond_str in pdf/sheet/__init__.py so a
swept range reads its endpoint instead of its false lower bound of 0, and every
existing read_sheet entry stayed valid across it: a cached run kept serving
Vgs=0. Gate-drive loss goes as Qg*Vgs*f, so that is a 2x error in a ranked
quantity delivered by a cache HIT, with nothing looking wrong.

Everything here works on COPIES under tmp_path. Rewriting the live sources to
test them dirties the repo if interrupted, fails on a read-only checkout, and
races itself under pytest-xdist.
"""
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import dslib.pdf.sheet as sheet_mod                                   # noqa: E402
import dslib.pdf.derivation as derivation_mod                         # noqa: E402
from dslib.pdf.sheet import (_SHEET_DERIVATION_SOURCES,               # noqa: E402
                             _compute_sheet_derivation_sig,
                             sheet_derivation_salt)

PKG_DIR = os.path.dirname(os.path.abspath(sheet_mod.__file__))


@pytest.fixture()
def pkg_copy(tmp_path):
    """A copy of just the declared derivation sources."""
    dst = tmp_path / 'sheet'
    dst.mkdir()
    for rel in _SHEET_DERIVATION_SOURCES:
        src = os.path.join(PKG_DIR, *rel)
        out = dst.joinpath(*rel)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    return dst


def test_salt_is_stable_when_nothing_changes(pkg_copy):
    assert _compute_sheet_derivation_sig(str(pkg_copy)) == \
           _compute_sheet_derivation_sig(str(pkg_copy))


@pytest.mark.parametrize('rel', _SHEET_DERIVATION_SOURCES,
                         ids=lambda r: '/'.join(r))
def test_every_declared_source_moves_the_salt(pkg_copy, rel):
    """Per SOURCE, not one file standing in for the list.

    A single-file probe reads one row of the matrix as the whole matrix -- the
    exact mistake that hid three holes in field_repr_salt's closure.
    """
    before = _compute_sheet_derivation_sig(str(pkg_copy))
    target = pkg_copy.joinpath(*rel)
    original = target.read_bytes()
    try:
        target.write_bytes(original + b'\n# perturbation\n')
        after = _compute_sheet_derivation_sig(str(pkg_copy))
    finally:
        target.write_bytes(original)
    assert after != before, f'{"/".join(rel)} does not move the sheet salt'
    assert _compute_sheet_derivation_sig(str(pkg_copy)) == before, 'did not restore'


def test_parse_cond_str_lives_in_a_declared_source():
    """The salt must cover the function befbb355 actually changed.

    Declaring files is only half of it; if parse_cond_str moved to a module
    outside the list, the salt would keep passing its own tests while going
    blind to the change it exists for.
    """
    import inspect
    from dslib.pdf.sheet import parse_cond_str
    defined_in = os.path.abspath(inspect.getsourcefile(parse_cond_str))
    declared = {os.path.abspath(os.path.join(PKG_DIR, *rel))
                for rel in _SHEET_DERIVATION_SOURCES}
    assert defined_in in declared, (
        f'parse_cond_str is defined in {defined_in}, which no longer appears in '
        '_SHEET_DERIVATION_SOURCES -- the salt cannot see changes to it')


def test_detect_fields_lives_in_a_declared_source():
    """Symbol detection is a direct semantic input, not a transitive nicety."""
    import inspect
    from dslib.pdf.parse import detect_fields
    defined_in = os.path.abspath(inspect.getsourcefile(detect_fields))
    declared = {os.path.abspath(os.path.join(PKG_DIR, *rel))
                for rel in _SHEET_DERIVATION_SOURCES}
    assert defined_in in declared, (
        f'detect_fields is defined in {defined_in}, which does not appear in '
        '_SHEET_DERIVATION_SOURCES -- read_sheet can serve old symbols')


def test_read_sheet_key_includes_the_sheet_salt(monkeypatch):
    """End to end: the component reaches read_sheet's actual cache key."""
    from dslib.pdf.sheet import read_sheet
    pdf = os.path.join(os.path.dirname(PKG_DIR), '..', '..', 'README.md')
    pdf = os.path.abspath(pdf)
    if not os.path.exists(pdf):
        pytest.skip('need any existing file for file_dependencies')

    before = read_sheet.cache_key(pdf)
    monkeypatch.setattr(sheet_mod, '_SHEET_DERIVATION_SIG', 'sheet-deriv:PERTURBED')
    after = read_sheet.cache_key(pdf)
    assert after != before, 'sheet_derivation_salt does not reach read_sheet cache_key'


def test_read_sheet_key_includes_the_nested_ascii_salt(monkeypatch):
    """An outer miss must not be followed by a stale pdf_to_ascii hit."""
    from dslib.pdf.sheet import read_sheet
    pdf = os.path.abspath(os.path.join(PKG_DIR, '..', '..', '..', 'README.md'))
    assert os.path.exists(pdf)

    before = read_sheet.cache_key(pdf)
    monkeypatch.setattr(derivation_mod, '_ASCII_DERIVATION_SIG',
                        'pdf-ascii:PERTURBED')
    after = read_sheet.cache_key(pdf)
    assert after != before, 'ascii_derivation_salt does not reach read_sheet cache_key'


def test_salt_value_is_reported_not_placeholder():
    """A salt that silently degrades to a constant is worse than none."""
    sig = sheet_derivation_salt()
    assert sig.startswith('sheet-deriv:') and len(sig) > len('sheet-deriv:')
    assert 'unknown' not in sig
