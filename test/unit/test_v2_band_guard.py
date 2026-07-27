"""_INTERIOR_EPS: the ruling-band guard that a corpus sweep cannot exercise.

`band_is_credible` accepts a merged conditions cell only when some NEIGHBOURING
column is ruled strictly inside the band -- evidence that the producer draws
per-row boundaries here and omitted this one deliberately. `_INTERIOR_EPS` is
how far inside "strictly" means.

A 70-part sweep over 0.0, 0.25, 0.5, 1.0, 2.0, 4.0 and 8.0 produced BYTE-
IDENTICAL results at every setting (cond_cell=436, sel=275, unsel=7 throughout).
That is not evidence the constant is well chosen; it is evidence the corpus
never puts it in a deciding position. A guard never seen to fire is not a guard,
so the case it exists for is constructed here instead.

That case is a DOUBLE-RULED BORDER: producers routinely stroke a table edge
twice, ~0.5 pt apart. Without a margin the second stroke sits "inside" the band
and looks exactly like a per-row divider, so a table with no row separation at
all is read as a merged cell and every row inherits its neighbour's conditions.
Measured on the fixture below: eps 0.0 and 0.25 wrongly inherit, eps 1.0
(shipped) and 2.0 refuse.

The shipped 1.0 therefore sits above the ~0.5 pt duplicate-stroke offset and far
below the ~40 pt row spacing that real interior dividers have -- a wide margin
on both sides rather than a fitted value.
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


def _make_pdf(path, neighbour_ys):
    """Conditions column ruled at its outer edges only; neighbour as given."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 120), EXPECTED_COND, fontsize=9)
    page.insert_text((360, 120), '73', fontsize=9)
    page.insert_text((360, 160), '20', fontsize=9)
    for y in (100, 180):
        page.draw_line(fitz.Point(60, y), fitz.Point(300, y), width=0.5)
    for y in neighbour_ys:
        page.draw_line(fitz.Point(350, y), fitz.Point(450, y), width=0.5)
    doc.save(str(path))
    doc.close()
    return str(path)


def _conds(path):
    page = extract_pages_with_rows(path, 1, backend='fitz')[0]
    scan = []
    for row in page.rows:
        if not row.text:
            continue
        values = _values_for_row(row, COLS)
        scan.append(dict(row=row,
                         sym=_detect_symbol_on_row('ao', row, COLS),
                         values=values,
                         has_num=any(_is_numeric_token(v) for v in values.values())))
    return [_cond_from_cell(page, scan, i, COLS) for i in range(len(scan))]


# A genuine per-row divider at 140: real merged cell, must be accepted.
GENUINE = (100, 140, 180)
# Only a duplicate of the top border 0.5 pt away: no row separation at all.
DUPLICATE_ONLY = (100, 100.5, 180)


def test_genuine_divider_is_accepted():
    """Positive control. Without it the refusal test below could pass vacuously."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        got = _conds(_make_pdf(os.path.join(td, 'g.pdf'), GENUINE))
    assert got == [EXPECTED_COND, EXPECTED_COND], got


def test_double_ruled_border_is_refused_at_shipped_eps(tmp_path):
    """The case the constant exists for, at the shipped value."""
    got = _conds(_make_pdf(tmp_path / 'd.pdf', DUPLICATE_ONLY))
    assert got == [None, None], got


@pytest.mark.parametrize('eps,should_refuse', [
    (0.0, False),      # no margin: the duplicate stroke passes as a divider
    (0.25, False),     # still under the 0.5 pt offset
    (1.0, True),       # shipped
    (2.0, True),
])
def test_eps_threshold_direction(tmp_path, eps, should_refuse):
    """Pin the DIRECTION, not just that the guard fires.

    Too-small values must inherit (the bug), the shipped value must refuse.
    Asserting only "refuses at 1.0" would still pass if the guard refused
    everything, which would silently disable merged-cell inheritance.
    """
    p = _make_pdf(tmp_path / f'e{eps}.pdf', DUPLICATE_ONLY)
    base = R._INTERIOR_EPS
    try:
        R._INTERIOR_EPS = eps
        got = _conds(p)
    finally:
        R._INTERIOR_EPS = base
    if should_refuse:
        assert got == [None, None], (eps, got)
    else:
        assert got == [EXPECTED_COND, EXPECTED_COND], (eps, got)
