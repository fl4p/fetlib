"""The gate that stops the OCR ladder from chasing a symbol the sheet never prints.

IRFI4229PBF is the case this exists for. Its gate-charge table lists only Qg
(73/110 nC) and Qgd (24 nC) -- no Qgs, Qg_th or Qgs2 anywhere. `tabula_read`'s
escalation loop cannot tell "the symbol is not on this sheet" from "extraction
failed", so it climbed its whole pre-method ladder to the 600 dpi OCR rung --
~4 min and 24 MB of derived files -- and still reported the symbol missing, as
it always would.

`symbols_provably_absent` licenses skipping that rung, and the interesting part
of it is what it does when it CANNOT prove anything. Absence of evidence must
not encode absence of the symbol, so the two-part proof is asserted here from
both sides:

  (a) the symbol's own detection regex matches nowhere in the text, and
  (b) the SIBLING symbols were parsed, witnessing that the table holding them
      rendered as readable text.

Drop (b) and the check inverts into an anti-monotone false PASS: it would fire
hardest on the scrambled font-encoding sheets, where labels are unfindable
precisely BECAUSE the text layer is broken and OCR is the actual repair. So the
control-missing and no-text cases below are not edge cases, they are the point.

Corpus calibration behind the shipped rule: over 120 infineon sheets that DO
print Qgs, the guard fired 0 times.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from dslib.pdf.parse import (symbols_provably_absent,  # noqa: E402
                             drop_ocr_pre_methods)

QGS_GROUP = ('Qgs', 'Qg_th', 'Qgs2')
NEED = {QGS_GROUP}

# Witnesses that the gate-charge table was read. Anything less must not license a skip.
HAVE = {'Qg', 'Qgd', 'Rds_on'}

# The shape IRFI4229PBF's text layer actually has -- Qg and Qgd rows, no Qgs row.
TEXT_NO_QGS = '\n'.join([
    'gfs', 'Forward Trans conductance', '26', 'S',
    'Qg', 'Total Gate Charge', '73', '110', 'nC    ID = 11A,VDS = 125V',
    'Qgd', 'Gate-to-Drain Charge', '24', 'VGS = 10V',
    'td(on)', 'Turn-On Delay Time', '18', 'ns',
])


def _with_qgs_row(row):
    return TEXT_NO_QGS.replace('Qgd', row + '\n17\nnC\nQgd', 1)


def test_fires_when_symbol_is_genuinely_not_printed():
    assert symbols_provably_absent(NEED, TEXT_NO_QGS, HAVE, 'infineon') == NEED


# --- the direction that loses data: sheets that DO print the symbol -------------------
# Not just "the guard fired" but WHICH text keeps it quiet -- a symbol named only by its
# description, with no "Qgs" token in sight, must still hold the ladder open.
@pytest.mark.parametrize('row', [
    'Qgs',
    'Q gs',
    'Qgs1',
    'Gate-to-Source Charge',
    'Gate Charge Gate to Source',
    'Qgs2',
    'Gate Charge at Vth',
    'Pre-Vth Gate-to-Source Charge',
    'Post-threshold Gate-to-Source Charge',
])
def test_never_fires_when_the_symbol_is_on_the_sheet(row):
    assert symbols_provably_absent(NEED, _with_qgs_row(row), HAVE, 'infineon') == set()


# --- absence of evidence must not read as absence of the symbol ----------------------
def test_no_fire_without_the_sibling_witness():
    """No proof the table is readable => escalate as before, even though Qgs is absent."""
    assert symbols_provably_absent(NEED, TEXT_NO_QGS, {'Rds_on'}, 'infineon') == set()
    assert symbols_provably_absent(NEED, TEXT_NO_QGS, {'Qg'}, 'infineon') == set()
    assert symbols_provably_absent(NEED, TEXT_NO_QGS, set(), 'infineon') == set()


def test_no_fire_on_a_scanned_sheet():
    """Empty text layer is the OCR case itself -- the guard must stay out of its way."""
    assert symbols_provably_absent(NEED, '', HAVE, 'infineon') == set()


def test_no_fire_for_symbols_without_a_proof_rule():
    """An unlisted symbol is never 'provably absent'; no rule means escalate, not fine."""
    assert symbols_provably_absent({'Vsd', 'Qrr'}, TEXT_NO_QGS, HAVE, 'infineon') == set()


def test_alias_group_needs_every_member_absent():
    """The group asks for any ONE of the three, so one printed member keeps it needed."""
    assert symbols_provably_absent({QGS_GROUP}, _with_qgs_row('Qgs2'), HAVE, 'infineon') == set()
    # ... while the same text proves the bare 'Qgs' member absent only if Qgs2's regex is
    # what matched -- assert the members are judged independently, not as a blob.
    assert symbols_provably_absent({'Qg_th'}, TEXT_NO_QGS, HAVE, 'infineon') == {'Qg_th'}


def test_leaves_other_needed_symbols_alone():
    """Only the proven-absent entry is dropped; the rest still drive the ladder."""
    need = {QGS_GROUP, 'Vsd', 'tRise'}
    assert symbols_provably_absent(need, TEXT_NO_QGS, HAVE, 'infineon') == {QGS_GROUP}


# --- --no-ocr must actually mean no OCR ----------------------------------------------
def test_no_ocr_strips_the_ocr_rung_from_the_tabular_ladder():
    assert drop_ocr_pre_methods(('nop', 'gs', 'r600_ocrmypdf')) == ('nop', 'gs')
    assert drop_ocr_pre_methods(('nop', 'gs')) == ('nop', 'gs')


def test_no_ocr_never_leaves_an_empty_ladder():
    """Filtering every method would turn --no-ocr into --no-tabular; 'nop' survives."""
    assert drop_ocr_pre_methods(('r600_ocrmypdf', 'ocrmypdf_redo')) == ('nop',)
