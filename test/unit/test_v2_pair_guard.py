"""_pair_split_rows guards against cross-parameter value theft (fetlib#43).

A symbol row with no numbers gets its values from a neighbouring row. Two
huayi ("WPS 文字") layouts broke that repair the same way: the RDS(ON) line
is split by ~0.4 pt into a label fragment (description + cond + unit) and a
value fragment (symbol + numbers). The label fragment, seeing no numbers of
its own and refusing the value fragment (it names its own symbol), reached
past it and pulled in the IGSS row above — booking the ±100 nA gate leakage
as a plausible-looking Rds_on max=100 mΩ.

Two independent guards close the class:

1. co-baseline: a symbol row that vertically overlaps a numbered row is a
   fragment of that same printed line, not a centred label — its values are
   there and nowhere else.
2. unit coherence: a neighbour whose own unit cell names a unit of another
   dimension (nA on an Rds_on pairing) measures another parameter.

Both are calibrated here in BOTH directions: the theft cases fail closed
AND the repair the pairing exists for (centred label over condition rows,
split value rows with no unit of their own) still works.
"""
import os
import sys
from types import SimpleNamespace

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from dslib.v2.chars import BBox, TextRow, Word                     # noqa: E402
from dslib.v2.tables import _pair_split_rows, _row_unit_conflicts  # noqa: E402

COLS = {"min": (400.0, 430.0), "typ": (440.0, 470.0),
        "max": (480.0, 515.0), "unit": (520.0, 550.0)}

SYM = SimpleNamespace(symbol="Rds_on")


def _row(y1, y2, *words):
    ws = [Word(t, BBox(x1, y1, x2, y2), font_size=y2 - y1)
          for t, x1, x2 in words]
    r = TextRow(words=ws, bbox=BBox(min(w.bbox.x1 for w in ws), y1,
                                    max(w.bbox.x2 for w in ws), y2))
    r.build_text()
    return r


def _igss_row(y1=194.7, y2=204.7):
    return dict(row=_row(y1, y2, ("IGSS", 62, 90), ("Leakage", 104, 160),
                         ("+-100", 482, 510), ("nA", 525, 540)),
                sym=None, values={"max": "+-100"}, has_num=True)


def _label_row(y1=178.6, y2=188.8):
    # description + condition + unit, numbers absent — the pairing trigger
    return dict(row=_row(y1, y2, ("Drain-Source", 104, 165),
                         ("Resistance", 209, 260), ("V=10V,I=50A", 281, 350),
                         ("mΩ", 525, 545)),
                sym=SYM, values={}, has_num=False)


def _value_fragment(sym, y1=178.2, y2=188.5):
    return dict(row=_row(y1, y2, ("RDS(ON)*", 53, 100), ("-", 414, 418),
                         ("4.3", 450, 465), ("5.5", 489, 505)),
                sym=sym, values={"typ": "4.3", "max": "5.5"}, has_num=True)


def test_cobaseline_fragment_with_own_symbol_blocks_all_pairing():
    """The HY3810NA2P layout: value fragment names RDS(ON) itself.

    It owns its values (and yields them as its own scan row), so the label
    fragment must pair with NOTHING — before the guard it stole the IGSS
    row above instead.
    """
    scan = [_igss_row(), _label_row(), _value_fragment(SYM)]
    assert _pair_split_rows(scan, 1, COLS) == []


def test_cobaseline_fragment_without_symbol_is_the_only_value_row():
    """Same split, but the fragment carries only numbers (HY3010B shape:
    the label fragment holds symbol+description+cond+unit, the value
    fragment just '- 10 12'). Only the fragment may be returned — the
    numbered IGSS row above must not ride along, because 'return both,
    merge picks topmost' would put the leakage values on top."""
    frag = _value_fragment(None)
    scan = [_igss_row(), _label_row(), frag]
    assert _pair_split_rows(scan, 1, COLS) == [frag["row"]]


def test_wrong_dimension_unit_vetoes_a_distant_neighbour():
    """No co-baseline split: a genuinely centred label still must not pair
    with a row whose own unit cell says nA."""
    label = _label_row(190.0, 200.0)
    below = dict(row=_row(175.0, 185.0, ("VGS=10V", 281, 340),
                          ("-", 414, 418), ("10", 450, 465), ("12", 489, 505)),
                 sym=None, values={"typ": "10", "max": "12"}, has_num=True)
    scan = [_igss_row(205.0, 215.0), label, below]
    assert _pair_split_rows(scan, 1, COLS) == [below["row"]]


def test_centred_label_repair_still_works_both_sides():
    """The repair _pair_split_rows exists for (diodes/mcc): a centred label
    between two condition rows, no unit or a SAME-dimension unit on the
    value rows. Both neighbours must still come back, above first."""
    above = dict(row=_row(205.0, 215.0, ("VGS=10V", 281, 340),
                          ("3.1", 450, 465), ("4.0", 489, 505),
                          ("mΩ", 525, 545)),
                 sym=None, values={"typ": "3.1", "max": "4.0"}, has_num=True)
    label = _label_row(190.0, 200.0)
    below = dict(row=_row(175.0, 185.0, ("VGS=6V", 281, 340),
                          ("4.4", 450, 465), ("5.7", 489, 505)),
                 sym=None, values={"typ": "4.4", "max": "5.7"}, has_num=True)
    scan = [above, label, below]
    assert _pair_split_rows(scan, 1, COLS) == [above["row"], below["row"]]


def test_unit_conflict_needs_positive_evidence():
    """Absence of a readable unit must not veto (checklist: absence of
    evidence never encodes absence of the problem — but this guard's job
    is refusing theft, and its safe degradation is the pre-existing
    pairing, not a new refusal)."""
    bare = _row(175.0, 185.0, ("4.4", 450, 465), ("5.7", 489, 505))
    assert not _row_unit_conflicts(bare, COLS, "Rds_on")
    # two words in the unit column = mis-captured cell, not evidence
    messy = _row(175.0, 185.0, ("V", 522, 526), ("=10V,I", 528, 549))
    assert not _row_unit_conflicts(messy, COLS, "Rds_on")
    # untracked dimension: cannot judge, must not veto
    na = _row(175.0, 185.0, ("nA", 525, 540))
    assert not _row_unit_conflicts(na, COLS, "IS")
    # and the positive case does fire
    assert _row_unit_conflicts(na, COLS, "Rds_on")
    assert not _row_unit_conflicts(
        _row(175.0, 185.0, ("mΩ", 525, 545)), COLS, "Rds_on")


DS = os.path.join(REPO, "datasheets")


@pytest.mark.skipif(not os.path.isdir(os.path.join(DS, "huayi")),
                    reason="needs the datasheets repo")
@pytest.mark.parametrize("pdf,typ,max_", [
    ("HY3810NA2P.pdf.gs.pdf", 4.3, 5.5),   # label/value split w/o symbol on label
    ("HY3010B.pdf", 10.0, 12.0),           # symbol on label, bare value fragment
])
def test_huayi_igss_row_is_not_rds_on(pdf, typ, max_):
    path = os.path.join(DS, "huayi", pdf)
    if not os.path.exists(path):
        pytest.skip("missing " + pdf)
    from dslib.v2 import extract_pages_with_rows
    from dslib.v2.tables import find_headers, parse_rows_for_page
    rds = []
    for pg in extract_pages_with_rows(path):
        for ex in parse_rows_for_page("huayi", pg, find_headers(pg.rows)):
            if ex.symbol != "Rds_on":
                continue
            assert "IGSS" not in ex.row.text, \
                "leakage row booked as Rds_on: %r" % ex.row.text
            rds.append(ex)
    # direction check: the guard must kill the theft, not the real value
    def _f(s):
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    assert any(_f(ex.values.get("typ")) == typ and
               _f(ex.values.get("max")) == max_ and ex.unit == "mΩ"
               for ex in rds), [(ex.values, ex.unit) for ex in rds]
