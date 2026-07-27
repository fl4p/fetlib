"""The frame guard that lets non-fitz pages use fitz's ruling geometry.

`dslib/v2/rules.py:frame_matches` decides whether rulings read through fitz live
in the same coordinate space as baselines produced by another backend. Getting
it wrong is silent: bands and baselines in different frames attach plausible,
wrong conditions rather than none.

Two calibration failures are pinned here, both mine:

* The guard was first "calibrated" by handing `frame_matches` a raw
  origin-shifted box. `_pages_pdfminer` never supplies one -- pdfminer
  subtracts (x0, y0) and always reports (0, 0, w, h) -- so the test exercised
  an input the production path cannot produce and proved nothing. Every case
  here drives the real extractor and asserts on the bbox it actually emits.
* The first version of the unknown-backend test asserted `is None` on a fixture
  that returned None for an unrelated reason (no merged cell to find). It
  passed with the guard deleted. The table below is therefore built with a
  REAL merged conditions cell -- one column ruled per row, the conditions
  column ruled only at its outer edges -- and `test_fixture_is_live` asserts a
  condition IS produced. Without that positive control the refusal tests are
  vacuous.

Fixtures are built with fitz into tmp_path rather than taken from datasheets/,
which is Git LFS: a partial checkout would otherwise turn these into skips, and
a guard whose tests vanish with its fixtures is not a guard.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

fitz = pytest.importorskip("fitz")

from dslib.v2 import rules as R                                   # noqa: E402
from dslib.v2.chars import extract_pages_with_rows                # noqa: E402
from dslib.v2.tables import (_cond_from_cell, _values_for_row,    # noqa: E402
                             _detect_symbol_on_row, _is_numeric_token)

COLS = {'cond': (60.0, 300.0), 'typ': (350.0, 450.0)}
EXPECTED_COND = 'VGS = 10 V'


def _make_pdf(path, rotate=0, crop=None, mediabox=None):
    """A table whose conditions cell is MERGED across two value rows.

    The conditions column is ruled only at the table's outer edges while the
    typ column is ruled per row -- which is exactly the signal `cell_band` and
    `band_is_credible` exist to read: a missing ruling over one column while a
    neighbour is ruled at that y.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 120), EXPECTED_COND, fontsize=9)
    page.insert_text((360, 120), '73', fontsize=9)
    page.insert_text((360, 160), '20', fontsize=9)
    for y in (100, 180):                       # conditions column: outer only
        page.draw_line(fitz.Point(60, y), fitz.Point(300, y), width=0.5)
    for y in (100, 140, 180):                  # typ column: per row
        page.draw_line(fitz.Point(350, y), fitz.Point(450, y), width=0.5)
    if mediabox is not None:
        page.set_mediabox(mediabox)
    if crop is not None:
        page.set_cropbox(crop)
    if rotate:
        page.set_rotation(rotate)
    doc.save(str(path))
    doc.close()
    return str(path)


def _page(path, backend):
    pages = extract_pages_with_rows(path, 1, backend=backend)
    assert pages, f"{backend} produced no pages for the fixture"
    return pages[0]


def _scan(page):
    out = []
    for row in page.rows:
        if not row.text:
            continue
        values = _values_for_row(row, COLS)
        out.append(dict(row=row,
                        sym=_detect_symbol_on_row('ao', row, COLS),
                        values=values,
                        has_num=any(_is_numeric_token(v) for v in values.values())))
    return out


def _conds(path, backend):
    page = _page(path, backend)
    scan = _scan(page)
    return page, scan, [_cond_from_cell(page, scan, i, COLS) for i in range(len(scan))]


def test_fixture_is_live(tmp_path):
    """The positive control. Without it every refusal assertion below is vacuous."""
    _p, _s, got = _conds(_make_pdf(tmp_path / "t.pdf"), 'fitz')
    assert got and all(c == EXPECTED_COND for c in got), got


def test_pdfminer_matches_fitz_end_to_end(tmp_path):
    """The property the guard exists to protect: same conditions, either backend."""
    p = _make_pdf(tmp_path / "t.pdf")
    _a, _b, by_fitz = _conds(p, 'fitz')
    _c, _d, by_pdfminer = _conds(p, 'pdfminer')
    assert by_pdfminer == by_fitz == [EXPECTED_COND, EXPECTED_COND]


def test_pdfminer_normalises_the_origin(tmp_path):
    """The invariant frame_matches' docstring now relies on.

    If this fails, the origin branch stops being a dead assertion and becomes a
    live requirement -- which is exactly when someone needs to know.
    """
    p = _make_pdf(tmp_path / "shifted.pdf", mediabox=fitz.Rect(50, 50, 645, 892))
    page = _page(p, 'pdfminer')
    assert page.mediabox.x1 == 0 and page.mediabox.y1 == 0


def test_frame_matches_accepts_a_real_pdfminer_page(tmp_path):
    p = _make_pdf(tmp_path / "normal.pdf")
    page = _page(p, 'pdfminer')
    mb = page.mediabox
    assert R.frame_matches(p, page.page_num, (mb.x1, mb.y1, mb.x2, mb.y2))


def test_origin_shift_is_normalised_not_refused(tmp_path):
    """The commit that added this guard claimed the opposite. Pin the correction."""
    p = _make_pdf(tmp_path / "shifted2.pdf", mediabox=fitz.Rect(50, 50, 645, 892))
    page = _page(p, 'pdfminer')
    mb = page.mediabox
    assert R.frame_matches(p, page.page_num, (mb.x1, mb.y1, mb.x2, mb.y2))


@pytest.mark.parametrize("kwargs,label", [
    (dict(rotate=90), "rotated90"),
    # 180 is the case the rotation check ALONE catches: it preserves width and
    # height, so the dimension comparison passes while every coordinate is
    # flipped. Deleting the rotation guard leaves the 90 case still failing
    # (its dimensions swap) -- measured -- so without this row the guard could
    # be removed with the suite green.
    (dict(rotate=180), "rotated180"),
    (dict(crop=fitz.Rect(20, 20, 575, 822)), "cropped"),
])
def test_frame_matches_refuses_real_divergence(tmp_path, kwargs, label):
    p = _make_pdf(tmp_path / f"{label}.pdf", **kwargs)
    page = _page(p, 'pdfminer')
    mb = page.mediabox
    assert not R.frame_matches(p, page.page_num, (mb.x1, mb.y1, mb.x2, mb.y2))


def test_frame_matches_refuses_an_unreadable_file(tmp_path):
    assert not R.frame_matches(str(tmp_path / "nope.pdf"), 0, (0, 0, 595, 842))


def test_cond_from_cell_refuses_unknown_backend(tmp_path):
    """Page.backend == "" must refuse rather than be routed through frame_matches.

    frame_matches asks whether FITZ's page is ordinary; for an unidentified
    producer that is not the question, and answering it would dress a
    non-answer as evidence. `test_fixture_is_live` proves this same fixture
    yields a condition when the backend IS known, so a None here is the guard.
    """
    p = _make_pdf(tmp_path / "unknown.pdf")
    page = _page(p, 'pdfminer')
    page.backend = ""
    scan = _scan(page)
    got = [_cond_from_cell(page, scan, i, COLS) for i in range(len(scan))]
    assert got and all(c is None for c in got), got
