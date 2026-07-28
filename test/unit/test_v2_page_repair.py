"""The auto backend's per-page repair: when is a pdfminer page accepted?

`extract_pages_with_rows(backend='auto')` reads with fitz, then re-reads ONLY
the pages carrying glyphs fitz could not name and splices those in. Deciding
which replacements to accept is a data-quality gate, and it had no test at all:
every other test in the suite passes an explicit backend, so the splicing path
was never executed.

Two failure modes, opposite directions:

* Accept too much. The first version asked only `if page.char_count` -- that is
  "non-empty" standing in for "at least as good", so a page where fitz lost one
  glyph in 500 would be replaced by a 1-glyph pdfminer page, silently throwing
  away 499 good ones.
* Accept too little. The obvious repair, `>= pages[i].char_count`, deletes the
  feature: measured over 16 real repaired pages, pdfminer returns FEWER glyphs
  than fitz on 11 of them (by 1-15, ratio 0.99-1.00), because the libraries
  split glyphs slightly differently. Equality rejects two thirds of genuine
  repairs.

Hence a ratio. These tests pin BOTH directions, because a guard that only
refuses is indistinguishable from a broken feature.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import dslib.v2.chars as C                                    # noqa: E402
from dslib.v2.chars import BBox, Page, RawChar                # noqa: E402

UNDECODABLE = C._UNDECODABLE


def _fitz_page_with_a_lost_glyph(n_good=80):
    """chars for one page: n_good real glyphs on row 1, an undecodable on row 2.

    Two rows, so scrubbing the bad row still leaves a page with content --
    which is the realistic case the repair exists for.

    n_good is 80 rather than a token handful because the auto backend only
    reaches the per-page repair when the document is READABLE
    (MIN_CHARS_READABLE = 50 on the best page); below that it takes the
    whole-document fallback instead and none of this is exercised. A fixture
    too small to reach the code under test is the failure this docstring
    exists to prevent repeating.
    """
    chars = [RawChar('A', (5.0 * i, 100.0, 5.0 * i + 4, 110.0), 10.0, 100.0)
             for i in range(n_good)]
    chars.append(RawChar(UNDECODABLE, (5.0, 50.0, 9.0, 60.0), 10.0, 50.0))
    return chars


@pytest.fixture()
def auto_with_one_bad_page(monkeypatch):
    """Make fitz report exactly one page that needs repair."""
    def fake_fitz(pdf_path, max_pages):
        yield _fitz_page_with_a_lost_glyph(), BBox(0, 0, 595, 842), 1

    monkeypatch.setattr(C, '_pages_fitz', fake_fitz)
    return None


def _repair_of(n_chars):
    """A pdfminer replacement page carrying n_chars glyphs."""
    def fake_repair(pdf_path, indices):
        rows = C._build_rows([
            RawChar('B', (5.0 * i, 100.0, 5.0 * i + 4, 110.0), 10.0, 100.0)
            for i in range(n_chars)])
        return {0: Page(page_num=0, mediabox=BBox(0, 0, 595, 842), rows=rows,
                        char_count=n_chars, n_undecoded=0,
                        pdf_path=pdf_path, backend='pdfminer')}
    return fake_repair


def _run(monkeypatch, repair_chars):
    monkeypatch.setattr(C, '_pages_for_indices', _repair_of(repair_chars))
    return C.extract_pages_with_rows('/nonexistent/x.pdf', 0, backend='auto')


def test_the_page_is_flagged_for_repair_at_all(auto_with_one_bad_page, monkeypatch):
    """Positive control for the FIXTURE.

    If fitz's page did not report n_undecoded, nothing below would exercise the
    splice and every assertion would pass vacuously.
    """
    monkeypatch.setattr(C, '_pages_for_indices', lambda p, i: {})
    pages = C.extract_pages_with_rows('/nonexistent/x.pdf', 0, backend='auto')
    assert pages[0].n_undecoded > 0, 'fixture does not trigger the repair path'
    assert pages[0].backend == 'fitz'


def test_comparable_repair_is_accepted(auto_with_one_bad_page, monkeypatch):
    """The feature. A pdfminer page of similar size replaces fitz's."""
    pages = _run(monkeypatch, 81)
    assert pages[0].backend == 'pdfminer'
    assert pages[0].char_count == 81


def test_slightly_smaller_repair_is_still_accepted(auto_with_one_bad_page,
                                                   monkeypatch):
    """Measured reality: pdfminer is often 1-15 glyphs short of fitz.

    A >= rule would reject this, and with it two thirds of real repairs.
    """
    pages = _run(monkeypatch, 79)
    assert pages[0].backend == 'pdfminer', 'a 1-glyph shortfall must not be refused'


def test_catastrophically_smaller_repair_is_refused(auto_with_one_bad_page,
                                                    monkeypatch):
    """The reviewer's case: non-empty, but a collapse. Keep fitz's page."""
    with pytest.warns(UserWarning, match='keeping fitz'):
        pages = _run(monkeypatch, 1)
    assert pages[0].backend == 'fitz', 'a 1-glyph page replaced an 81-glyph page'
    assert pages[0].char_count == 81


def test_empty_repair_is_refused(auto_with_one_bad_page, monkeypatch):
    pages = _run(monkeypatch, 0)
    assert pages[0].backend == 'fitz'


def test_failed_repair_leaves_fitz_pages(auto_with_one_bad_page, monkeypatch):
    """_pages_for_indices raising must not lose the document."""
    def boom(pdf_path, indices):
        raise RuntimeError('pdfminer exploded')
    monkeypatch.setattr(C, '_pages_for_indices', boom)
    pages = C.extract_pages_with_rows('/nonexistent/x.pdf', 0, backend='auto')
    assert pages[0].backend == 'fitz' and pages[0].char_count == 81


@pytest.mark.parametrize('n,expect', [
    (81, 'pdfminer'),   # equal
    (79, 'pdfminer'),   # -2, the measured real-world shortfall
    (73, 'pdfminer'),   # just inside the 0.9 ratio
    (72, 'fitz'),       # just outside it
    (40, 'fitz'),       # -50%
    (1, 'fitz'),        # collapse
])
def test_ratio_is_monotone(auto_with_one_bad_page, monkeypatch, n, expect):
    """As the replacement gets worse the verdict must move one way only.

    No region may flip back to accepting -- the far tail is tested, not just
    the near miss.
    """
    import warnings as _w
    with _w.catch_warnings():
        _w.simplefilter('ignore')
        pages = _run(monkeypatch, n)
    assert pages[0].backend == expect, f'{n} glyphs -> {pages[0].backend}'
