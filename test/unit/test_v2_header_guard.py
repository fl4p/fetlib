"""A DATA row must not be promoted to a table header (dslib/v2/tables.py).

THE BUG, from a real corpus record. st/STP50NF25 page 4 contains the IDSS leakage row

    current (VGS = 0) VDS = Max rating @125 C 10 uA

`head_re` is IGNORECASE and matches its groups ANYWHERE in a row, so inside the condition
text "VDS = Max rating" the word "Max" matched (?P<max>...) and "rating" matched
(?P<values>(Value|Rating)s?). Two ordinary words in a sentence became a table header with
columns max=(316,338), values=typ=(338,364).

Those bogus columns then governed every row BENEATH it, including

    R_DS(on) | Static drain-source on resistance | V_GS = 10 V, I_D = 22 A | 0.055 | 0.069 | Ohm

whose real values sit at x=436/470. `max` instead landed on the CONDITION cell and returned
"10 V" -> 10 Ohm -> 10000 mOhm, against a true 0.069 Ohm = 69 mOhm. The same "10" was
consumed twice: once correctly as cond={'Vgs': 10.0}, and once as the value.

Note this is NOT the documented case-sensitive `head_stop` hole -- none of head_stop's words
appear in that row in any casing. It is a separate hole in the same function.

DIRECTION IS ASSERTED, NOT JUST FIRING. A guard that rejects header rows is dangerous in
the opposite direction: over-reject and real tables silently vanish, trading one visible
wrong value for many invisible missing ones. So every test that pins a rejection is paired
with a genuine header that must still be ACCEPTED.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dslib.v2.chars import BBox, TextRow, Word  # noqa: E402
from dslib.v2.tables import (  # noqa: E402
    _candidate_header,
    _damerau_levenshtein_at_most_one,
    head_re,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _row(text, x0=100.0, y=300.0, w=7.0, h=9.0):
    """A TextRow whose words are laid out left-to-right at a fixed pitch."""
    words, x = [], x0
    for tok in text.split():
        words.append(Word(text=tok, bbox=BBox(x, y, x + w * len(tok), y + h), font_size=h))
        x += w * len(tok) + w
    row = TextRow(words=words, bbox=BBox(x0, y, x, y + h))
    row.build_text()
    return row


# ------------------------------------------------------------------ must be REJECTED
@pytest.mark.parametrize('text', [
    # the exact corpus row that caused the 10000 mOhm capture
    'current (VGS = 0) VDS = Max rating @125 C 10 uA',
    # a condition cell that happens to contain a header word
    'VDS = 25 V, ID = Max pulse current 10 A',
])
def test_condition_bearing_data_rows_are_not_headers(text):
    assert head_re.search(text), 'precondition: head_re must match, else this proves nothing'
    assert _candidate_header(_row(text)) is None, 'data row accepted as a table header'


@pytest.mark.parametrize('text', [
    '3 Safe operating area 4 Max. transient thermal impedance',
    'Tl Maximum lead temperature for soldering purpose 300 C',
])
def test_section_title_with_head_stop_word_is_not_a_header(text):
    assert head_re.search(text), 'precondition: loose header regex must match'
    assert _candidate_header(_row(text)) is None


@pytest.mark.xfail(strict=True, reason=(
    'KNOWN, NOT FIXED. These are prose/section-title rows with no "=", so the landed guard '
    '(which requires BOTH an "=" outside the match AND low coverage) deliberately does not '
    'fire. Rejecting them needs a coverage-only rule, and that was measured too blunt: 1132 '
    'of 2234 accepted header candidates over 120 datasheets (51%) sit below 0.5 coverage, '
    'so a coverage-only rule reshapes half the corpus. They appear harmless in practice -- '
    'downstream merging and _headers_that_explain_numbers drop them, and STP50NF25 extracts '
    'correctly with them still accepted -- but "appears harmless" is not "checked", which '
    'is why this is xfail(strict) rather than deleted. If a coverage rule is ever landed '
    'with an end-to-end A/B behind it, these should flip to passing.'))
@pytest.mark.parametrize('text', [
    'compliance with JEDEC Standard JESD97. The maximum ratings related to soldering',
])
def test_prose_rows_are_still_wrongly_accepted(text):
    assert _candidate_header(_row(text)) is None


# ------------------------------------------------------------------ must still be ACCEPTED
@pytest.mark.parametrize('text', [
    'Symbol Parameter Test conditions Min. Typ. Max. Unit',
    'Symbol Parameter Test conditions Min Typ Max Unit',
    'Symbol Parameter Value Unit',
    'Min Typ Max Min Typ Max',
    'Min Typ Max',
    'Symbol Parameter Conditions Min Typ Max Units',
])
def test_genuine_headers_still_accepted(text):
    """The direction that matters. Over-rejecting here deletes whole tables silently."""
    c = _candidate_header(_row(text))
    assert c is not None, 'real header rejected -- this drops an entire table'


def test_the_headers_that_governed_the_broken_sheet_still_parse():
    """The good header on that very page must survive the fix that kills the bad one."""
    c = _candidate_header(_row('Symbol Parameter Test conditions Min. Typ. Max. Unit'))
    assert c is not None
    _m, cols = c
    for k in ('min', 'typ', 'max'):
        assert k in cols
    # and its numeric columns are in ascending x, unlike the bogus header's
    assert cols['min'][0] < cols['typ'][0] < cols['max'][0]


def test_fuzzy_header_recovers_st_condictions_typo():
    """STP80NF10FP prints the typo; it must not erase the whole dynamic table."""
    c = _candidate_header(
        _row('Symbol Parameter Test condictions Min. Typ. Max. Unit'))
    assert c is not None
    _m, cols = c
    for k in ('sym', 'param', 'cond', 'min', 'typ', 'max', 'unit'):
        assert k in cols
    assert cols['min'][0] < cols['typ'][0] < cols['max'][0] < cols['unit'][0]


@pytest.mark.parametrize(('a', 'b'), [
    ('condictions', 'conditions'),  # deletion
    ('conditxons', 'conditions'),   # substitution
    ('conditios', 'conditions'),    # insertion
    ('conditinos', 'conditions'),   # adjacent transposition
])
def test_fuzzy_header_distance_accepts_one_damerau_edit(a, b):
    assert _damerau_levenshtein_at_most_one(a, b)


def test_fuzzy_header_distance_rejects_two_edits():
    assert not _damerau_levenshtein_at_most_one('condxxions', 'conditions')


def test_fuzzy_words_without_table_structure_are_not_headers():
    """One near-match in prose is not permission to reinterpret the row."""
    row = _row('current VDS = Mox rating at 125 C 10 uA')
    assert _candidate_header(row) is None


# ------------------------------------------------------------------ end-to-end, real sheet
@pytest.mark.skipif(not os.path.exists(os.path.join(REPO, 'datasheets/st/STP50NF25.pdf')),
                    reason='needs the datasheets repo')
def test_stp50nf25_reads_its_real_rds_on():
    """Ground truth, not a self-consistent re-derivation: the MPN decodes to 69 mOhm and the
    sheet prints 0.055 typ / 0.069 max. Before the fix v2 returned 10000.0 mOhm."""
    from dslib.v2 import parse_datasheet as v2parse
    ds = v2parse(os.path.join(REPO, 'datasheets/st/STP50NF25.pdf'), mfr='st', mpn='STP50NF25')
    f = ds.fields_filled.get('Rds_on')
    assert f is not None, 'Rds_on disappeared entirely -- the guard over-rejected'
    assert f.max == pytest.approx(69.0, rel=0.02), 'got %r (10000.0 was the bug)' % f.max


@pytest.mark.skipif(not os.path.exists(os.path.join(REPO, 'datasheets/st/STP80NF10FP.pdf')),
                    reason='needs the datasheets repo')
def test_stp80nf10fp_fuzzy_header_recovers_qgs():
    """Ground truth: the dynamic table explicitly prints Qgs typ = 23 nC."""
    from dslib.v2 import parse_datasheet as v2parse
    ds = v2parse(os.path.join(REPO, 'datasheets/st/STP80NF10FP.pdf'),
                 mfr='st', mpn='STP80NF10FP')
    f = ds.fields_filled.get('Qgs')
    assert f is not None
    assert f.typ == pytest.approx(23.0)
