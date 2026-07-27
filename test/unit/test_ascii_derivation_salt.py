"""The nested pdf_to_ascii cache must track every Row-producing dependency.

Invalidating read_sheet alone is not enough: on the resulting miss it calls
pdf_to_ascii, whose own disk cache used to be keyed by only the decorated
function plus ``pdf_blocks_pdfminer_six.__code__.co_code``.  Helper changes in
ascii.py, tree.py or fonts.py could therefore make the outer cache miss and
then immediately serve stale Row objects from the inner cache.
"""
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import dslib.pdf.derivation as derivation_mod                         # noqa: E402
from dslib.pdf.ascii import pdf_to_ascii                              # noqa: E402
from dslib.pdf.derivation import (                                   # noqa: E402
    _ASCII_DERIVATION_PACKAGES,
    _ASCII_DERIVATION_SOURCES,
    _compute_ascii_derivation_sig,
    ascii_derivation_salt,
)
from dslib.pdf.fonts import (                                         # noqa: E402
    find_good_unicodes_for_name,
    get_font_default_enc,
    get_symbol_font_unicode,
)

PDF_DIR = os.path.dirname(os.path.abspath(derivation_mod.__file__))


@pytest.fixture()
def pdf_copy(tmp_path):
    dst = tmp_path / 'pdf'
    dst.mkdir()
    for rel in _ASCII_DERIVATION_SOURCES:
        src = os.path.join(PDF_DIR, *rel)
        out = dst.joinpath(*rel)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    return dst


@pytest.mark.parametrize('rel', _ASCII_DERIVATION_SOURCES,
                         ids=lambda r: '/'.join(r))
def test_every_ascii_source_moves_the_salt(pdf_copy, rel):
    before = _compute_ascii_derivation_sig(str(pdf_copy))
    target = pdf_copy.joinpath(*rel)
    original = target.read_bytes()
    target.write_bytes(original + b'\n# perturbation\n')
    after = _compute_ascii_derivation_sig(str(pdf_copy))
    target.write_bytes(original)
    assert after != before, '%s is invisible to the ASCII salt' % '/'.join(rel)
    assert _compute_ascii_derivation_sig(str(pdf_copy)) == before


@pytest.mark.parametrize('package', _ASCII_DERIVATION_PACKAGES)
def test_every_external_version_moves_the_salt(pdf_copy, monkeypatch, package):
    import importlib.metadata as metadata

    real_version = metadata.version
    before = _compute_ascii_derivation_sig(str(pdf_copy))

    def changed(name):
        value = real_version(name)
        return value + '.PERTURBED' if name == package else value

    monkeypatch.setattr(metadata, 'version', changed)
    after = _compute_ascii_derivation_sig(str(pdf_copy))
    assert after != before, '%s version is invisible to the ASCII salt' % package


def test_pdf_to_ascii_key_includes_the_ascii_salt(monkeypatch):
    pdf = os.path.abspath(os.path.join(PDF_DIR, '..', '..', 'README.md'))
    assert os.path.exists(pdf)

    before = pdf_to_ascii.cache_key(pdf)
    monkeypatch.setattr(derivation_mod, '_ASCII_DERIVATION_SIG',
                        'pdf-ascii:PERTURBED')
    after = pdf_to_ascii.cache_key(pdf)
    assert after != before


@pytest.mark.parametrize('cached,args', [
    (find_good_unicodes_for_name, ('NOT-A-REAL-GLYPH',)),
    (get_symbol_font_unicode, ()),
    (get_font_default_enc, ('Symbol',)),
])
def test_nested_font_cache_keys_include_the_ascii_salt(
        monkeypatch, cached, args):
    before = cached.cache_key(*args)
    monkeypatch.setattr(derivation_mod, '_ASCII_DERIVATION_SIG',
                        'pdf-ascii:PERTURBED')
    after = cached.cache_key(*args)
    assert after != before


def test_salt_is_snapshotted_but_test_root_recomputes(pdf_copy, monkeypatch):
    before = ascii_derivation_salt()
    monkeypatch.setattr(derivation_mod, '_ASCII_DERIVATION_SIG',
                        'pdf-ascii:PERTURBED')
    assert ascii_derivation_salt() == 'pdf-ascii:PERTURBED'
    assert ascii_derivation_salt(str(pdf_copy)) != 'pdf-ascii:PERTURBED'
    assert before.startswith('pdf-ascii:')
