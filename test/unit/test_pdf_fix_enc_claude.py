"""Tests for dslib.pdf.fix_encoding using the sample PDFs from
docs/vibes/font-replacer.md.

The function under test repairs PDFs whose embedded fonts use scrambled,
custom encodings so plain text extraction yields gibberish. Tests below
verify:

  * detection — known-custom samples flag True, the clean sample flags False
  * structural invariants of the fix — output is a valid PDF with the same
    page count, written to the expected path
  * actual text recovery — for the samples where current matching produces
    readable output, distinctive keywords must appear after fixing AND must
    NOT appear before fixing

`HY1920W.pdf` is detected as custom-encoded but the visual matcher currently
produces a uniformly shifted alphabet for it; it's covered in detection /
structural tests only, not in the keyword-recovery test, so it doesn't gate
the suite on a known matcher limitation.
"""

import os
import pathlib

import pymupdf
import pytest

from dslib.pdf.fix_encoding import fix_pdf_font_encoding, has_custom_font_encoding

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# (relative path, distinctive substrings that must appear in extracted text
# AFTER fixing — picked from each datasheet's actual content so a regression
# in the matcher would flip the assertion).
POSITIVE_SAMPLES_WITH_KEYWORDS = [
    ('datasheets/huayi/HY3912W.pdf',
     ['MOSFET', 'Drain', 'Gate', 'Source']),
    ('datasheets/infineon/IPP057N08N3GHKSA1.pdf',
     ['OptiMOS', 'Drain', 'Gate', 'Power']),
    ('datasheets/infineon/BSC190N15NS3_G.pdf',
     ['OptiMOS', 'Drain', 'Gate', 'Power']),
    ('datasheets/infineon/IPP028N08N3_G.pdf',
     ['OptiMOS', 'Drain', 'Gate', 'Power']),
    ('datasheets/infineon/IPW60R041C6.pdf',
     ['Power', 'Transistor', 'drain', 'gate', 'source']),
]

# Detected as custom-encoded but currently not recovered into readable text.
DETECT_ONLY_POSITIVE_SAMPLES = [
    'datasheets/huayi/HY1920W.pdf',
]

ALL_POSITIVE_SAMPLES = (
    [s for s, _ in POSITIVE_SAMPLES_WITH_KEYWORDS]
    + DETECT_ONLY_POSITIVE_SAMPLES
)

NEGATIVE_SAMPLES = [
    'datasheets/huayi/HY0910D.pdf',
]


def _abs(rel: str) -> str:
    p = REPO_ROOT / rel
    if not p.is_file():
        pytest.skip(f'sample not available: {rel}')
    return str(p)


def _extract_all_text(pdf_path: str) -> str:
    doc = pymupdf.open(pdf_path)
    try:
        return ''.join(page.get_text() for page in doc)
    finally:
        doc.close()


def _page_count(pdf_path: str) -> int:
    doc = pymupdf.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


@pytest.fixture(scope='module')
def fix_sample(tmp_path_factory):
    """Fix a sample PDF at most once per test session and return the output
    path. Fixing involves rendering and matching every used glyph, which is
    slow — caching keeps the parametrized suite tractable."""
    cache: dict = {}
    out_dir = tmp_path_factory.mktemp('fixed')

    def _do(rel: str) -> str:
        if rel not in cache:
            src = _abs(rel)
            out = str(out_dir / (pathlib.Path(rel).stem + '.fixed.pdf'))
            cache[rel] = fix_pdf_font_encoding(src, out_path=out)
        return cache[rel]

    return _do


# ----- detection -------------------------------------------------------

@pytest.mark.parametrize('rel', ALL_POSITIVE_SAMPLES)
def test_detects_custom_encoding(rel):
    assert has_custom_font_encoding(_abs(rel)) is True


@pytest.mark.parametrize('rel', NEGATIVE_SAMPLES)
def test_does_not_flag_clean_pdf(rel):
    assert has_custom_font_encoding(_abs(rel)) is False


# ----- fix output structure --------------------------------------------

@pytest.mark.parametrize('rel', ALL_POSITIVE_SAMPLES)
def test_fix_writes_output_to_requested_path(rel, fix_sample):
    out = fix_sample(rel)
    assert os.path.isfile(out)
    assert out.endswith('.fixed.pdf')
    assert os.path.getsize(out) > 0


@pytest.mark.parametrize('rel', ALL_POSITIVE_SAMPLES)
def test_fix_preserves_page_count(rel, fix_sample):
    src = _abs(rel)
    assert _page_count(fix_sample(rel)) == _page_count(src)


def test_fix_default_output_path(tmp_path):
    """Without `out_path`, the fixed file is named `<stem>.unicoded.pdf`
    in the same directory as the source."""
    import shutil

    src_rel = POSITIVE_SAMPLES_WITH_KEYWORDS[0][0]
    src = tmp_path / 'sample.pdf'
    shutil.copy(_abs(src_rel), src)

    out = fix_pdf_font_encoding(str(src))
    assert out == str(tmp_path / 'sample.unicoded.pdf')
    assert os.path.isfile(out)


@pytest.mark.parametrize('rel', NEGATIVE_SAMPLES)
def test_clean_pdf_returns_original_path_unchanged(rel):
    """Fixing a PDF that doesn't need fixing must not produce a new file
    and must return the input path verbatim."""
    src = _abs(rel)
    out = fix_pdf_font_encoding(src)
    assert out == src


@pytest.mark.parametrize('rel', NEGATIVE_SAMPLES)
def test_raise_if_no_bad_fonts(rel):
    with pytest.raises(ValueError, match='no bad fonts'):
        fix_pdf_font_encoding(_abs(rel), raise_if_no_bad_fonts=True)


# ----- actual text recovery --------------------------------------------

@pytest.mark.parametrize('rel,keywords', POSITIVE_SAMPLES_WITH_KEYWORDS)
def test_fixed_pdf_contains_expected_keywords(rel, keywords, fix_sample):
    """After fixing, distinctive datasheet keywords must extract as proper
    text. Keywords are picked per sample because the datasheets cover
    different products (HuaYi vs Infineon OptiMOS vs Infineon CoolMOS)."""
    text = _extract_all_text(fix_sample(rel))
    missing = [k for k in keywords if k not in text]
    assert not missing, (
        f'{rel}: keywords missing from fixed text: {missing}. '
        f'First 400 chars: {text[:400]!r}'
    )


@pytest.mark.parametrize('rel,keywords', POSITIVE_SAMPLES_WITH_KEYWORDS)
def test_fix_recovers_new_text(rel, keywords, fix_sample):
    """The fix must genuinely recover text — at least one expected keyword
    must extract from the fixed PDF that did NOT extract from the original.
    Some Infineon samples mix properly-encoded text with custom-encoded
    text in the same file, so we don't require ALL keywords to be new, only
    that the fix yields net new content."""
    before = _extract_all_text(_abs(rel))
    after = _extract_all_text(fix_sample(rel))
    newly_recovered = [k for k in keywords if k in after and k not in before]
    assert newly_recovered, (
        f'{rel}: fix recovered no new keywords. '
        f'before contained: {[k for k in keywords if k in before]}, '
        f'after contained: {[k for k in keywords if k in after]}'
    )


# ----- post-fix invariants ---------------------------------------------

@pytest.mark.parametrize('rel', [s for s, _ in POSITIVE_SAMPLES_WITH_KEYWORDS])
def test_fixed_pdf_no_longer_flags_as_custom(rel, fix_sample):
    """Once fixed, detection should consider the PDF clean. (Restricted to
    samples that fully fix — `DETECT_ONLY_POSITIVE_SAMPLES` is excluded.)"""
    assert has_custom_font_encoding(fix_sample(rel)) is False
