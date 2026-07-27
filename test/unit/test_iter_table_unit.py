"""The `iter_table` fallback in extract_fields_from_dataframes must not drop the unit.

Background: 774 of 5667 Rds_on records reached the shipped DB with unit=None, all tagged
`iter_table`. That branch passed the STICKY table unit (carried down from the last row whose
unit cell parsed) and ignored the row's own unit cell -- the one that `_fill_unit` sits
directly above this branch reconstructing for vertically merged cells.

It matters because a unitless resistance is not stored as "unknown": it lands on the
reader's unitless default (`_RESISTANCE_UNITLESS_TO_MILLI['Rds_on'] = 1.0`, "already mΩ"),
so every sheet quoting ohms comes back 1000x too LOW -- and low is the direction that
survives a loss ranking and sorts to the top.

Shape below is Infineon CoolMOS (IPW60R024CFD7 p.5): one RDS(on) entry stating Tj=25°C and
Tj=150°C against a SINGLE merged 'Ω' cell.
"""


import pandas as pd
import pytest

from dslib.pdf.parse import extract_fields_from_dataframes


def _df(rows, name='test_table'):
    df = pd.DataFrame(rows)
    df.index.name = name
    return df


# Parameter | Symbol | Min | Typ | Max | Unit | Note
HEADER = ['Parameter', 'Symbol', 'Min.', 'Typ.', 'Max.', 'Unit', 'Note / Test Condition']


def _rds_table(unit_cell, merged_blank=False):
    """A table whose header IS detected, so col_idx['unit'] is known, but where the sticky
    `unit` is never set because the Rds_on row is the first one carrying a unit."""
    rows = [
        HEADER,
        ['Drain-source on-state resistance', 'RDS(on)', '-', '0.019', '0.024', unit_cell,
         'VGS=10V, ID=42.4A, Tj=25°C'],
    ]
    if merged_blank:
        # the vertically merged continuation sub-row: unit cell empty, ffill/bfill territory
        rows.append(['', '', '-', '0.043', '-', '', 'VGS=10V, ID=42.4A, Tj=150°C'])
    return _df(rows)


def _rds_on(dsf):
    return dsf.fields_filled.get('Rds_on')


def test_unit_is_taken_from_the_row_not_the_sticky_value():
    """The regression. Before the fix this Field came out with unit=None."""
    dsf = extract_fields_from_dataframes([_rds_table('Ω')], mfr='infineon')
    f = _rds_on(dsf)
    assert f is not None, 'Rds_on not extracted at all'
    assert (f.unit or '').strip(), 'unit dropped -- this is the 1000x bug'


def test_ohm_row_reads_back_as_milliohm_not_1000x_low():
    """Direction, not just presence. 0.019 Ω is 19 mΩ; the bug reported 0.019 mΩ, which is
    1000x BETTER than reality and therefore survives selection."""
    dsf = extract_fields_from_dataframes([_rds_table('Ω')], mfr='infineon')
    got = dsf.get_resistance_milliohm('Rds_on', stat='typ')
    assert got == pytest.approx(19.0), got
    assert got > 1.0, 'still on the unitless mΩ default -> 1000x low'


def test_milliohm_row_is_not_double_scaled():
    """The other direction: a sheet that already quotes mΩ must NOT be multiplied. A fix
    that only ever multiplies would break these instead."""
    dsf = extract_fields_from_dataframes([_rds_table('mΩ')], mfr='infineon')
    got = dsf.get_resistance_milliohm('Rds_on', stat='typ')
    assert got == pytest.approx(0.019), got


def test_merged_continuation_subrow_still_resolves():
    """The real Infineon layout: a second sub-row with an EMPTY unit cell under the merged
    'Ω'. It must not clobber the resolved unit back to None."""
    dsf = extract_fields_from_dataframes([_rds_table('Ω', merged_blank=True)], mfr='infineon')
    got = dsf.get_resistance_milliohm('Rds_on', stat='typ')
    assert got == pytest.approx(19.0), got


def test_non_resistance_unit_is_not_adopted():
    """Calibrate against a known-bad cell. A 'nA' in the unit column means the row was
    mis-captured, so the branch must NOT copy it into the Field as if it were the row's
    unit -- widening 'use the row's unit cell' into 'use whatever is in that column' would
    hand get_resistance_milliohm a cross-dimension unit to reason about.

    Note what this test does NOT claim: the resulting Field is unitless, and a unitless
    Rds_on still lands on _RESISTANCE_UNITLESS_TO_MILLI's "already mΩ" assumption rather
    than refusing. That is a separate hazard in the reader, not something this branch can
    fix, and it is why the value below is 0.019 instead of NaN.
    """
    dsf = extract_fields_from_dataframes([_rds_table('nA')], mfr='infineon')
    f = _rds_on(dsf)
    if f is not None:
        assert (f.unit or '').strip() != 'nA', 'cross-dimension cell laundered into unit'
