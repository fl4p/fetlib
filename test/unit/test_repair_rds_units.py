"""Value-anchored unit recovery (apps/repair_rds_units.py).

The whole point of these tests is the near-miss they encode. A first implementation looked
up "the unit near an RDS(on) row" and was wrong on 120 of 121 checkable parts, because
Infineon sheets state the SAME parameter twice with units that differ by 1000x -- an
advertised 'RDS(on),max' '120' 'mΩ' on the front page, and '0.103' ... 'Ω' in the
characteristics table. Both look like perfectly good evidence in isolation.

So the property under test is not "it finds a unit" but "it finds the unit belonging to the
value it was asked about", plus: it refuses rather than guesses.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from apps.repair_rds_units import (gate_agrees, gate_rejects_scale_error,  # noqa: E402
                                   mpn_nominal_milliohm, recover_unit)
from dslib.field import ohm_unit_to_milli_mul  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

# Front page: 'RDS(on),max' '120' 'mΩ'.  Page 5 table: '0.103' '0.231' '0.120' ... 'Ω'.
DUAL_UNIT_PDF = os.path.join(REPO, 'datasheets/infineon/IPW60R120C7XKSA1.pdf')

pytestmark = pytest.mark.skipif(
    not os.path.exists(DUAL_UNIT_PDF),
    reason='datasheets/ is a separate LFS repo; skip when not checked out')


def test_picks_the_unit_of_the_block_holding_the_value():
    """The regression that matters: the same PDF yields DIFFERENT units for different
    values, and both answers must be the one co-located with the number."""
    # table value -> the table's ohm unit, NOT the front page's mΩ
    assert ohm_unit_to_milli_mul(recover_unit(DUAL_UNIT_PDF, 0.103)) == 1e3
    assert ohm_unit_to_milli_mul(recover_unit(DUAL_UNIT_PDF, 0.120)) == 1e3
    # front-page summary value -> that block's mΩ
    assert ohm_unit_to_milli_mul(recover_unit(DUAL_UNIT_PDF, 120)) == 1.0


def test_recovered_scale_reproduces_the_part_number():
    """Calibrate against a known-good value: the MPN says 120 mΩ max, and the stored typ of
    0.103 must come back as ~103 mΩ -- not 0.103, and not 103000."""
    mul = ohm_unit_to_milli_mul(recover_unit(DUAL_UNIT_PDF, 0.103))
    assert mul * 0.103 == pytest.approx(103.0)
    nom = mpn_nominal_milliohm('IPW60R120C7XKSA1', 'infineon')
    assert nom == 120.0
    assert 0.5 < (mul * 0.103) / nom < 1.6


def test_refuses_a_value_that_appears_in_no_block():
    """Absence of evidence must not produce a unit. A value that is not in any RDS(on)
    block is unrecoverable, even though the PDF is full of perfectly valid ohm units."""
    assert recover_unit(DUAL_UNIT_PDF, 0.0417) is None
    assert recover_unit(DUAL_UNIT_PDF, 12345.6) is None


def test_refuses_an_unreadable_pdf():
    assert recover_unit(os.path.join(REPO, 'datasheets/infineon/__nope__.pdf'), 0.1) is None
    assert recover_unit('/dev/null', 0.1) is None


@pytest.mark.parametrize('got,nom,ok', [
    # exact, typ-vs-max, and hot-vs-cold spread must all PASS -- the gate is not trying to
    # distinguish those. IPL65R130C7AUMA1 really does store 276 mΩ (Tj=150°C) against an
    # MPN nominal of 130 mΩ (25°C max); a [0.5,1.6] band blocked the entire run over it.
    (130.0, 130.0, True),
    (103.0, 120.0, True),
    (276.0, 130.0, True),    # Tj=150°C / Tj=25°C
    (19.0, 24.0, True),      # typ vs max
    # the error class the gate exists for: 1000x in either direction must FAIL
    (0.130, 130.0, False),
    (130000.0, 130.0, False),
    (0.019, 24.0, False),
])
def test_gate_band_separates_scale_error_from_physical_spread(got, nom, ok):
    assert gate_agrees(got, nom) is ok


@pytest.mark.parametrize('got,nom', [(130.0, 130.0), (103.0, 120.0), (276.0, 130.0),
                                     (19.0, 24.0), (8.9, 8.9), (3.8, 3.8)])
def test_gate_is_never_blind_to_a_1000x_error(got, nom):
    """For every value the gate accepts, it must still reject that value mis-scaled by
    1000x. This is what stops the band being widened until it passes everything."""
    assert gate_agrees(got, nom), 'precondition: this value should pass'
    assert gate_rejects_scale_error(got, nom)


def test_gate_calibration_would_catch_a_widened_band():
    """Sanity-check the calibration itself: if the band were widened past the error class,
    gate_rejects_scale_error must start returning False rather than quietly agreeing."""
    import apps.repair_rds_units as m
    lo, hi = m.GATE_LO, m.GATE_HI
    try:
        m.GATE_LO, m.GATE_HI = 1e-9, 1e9      # a band that passes anything
        assert not m.gate_rejects_scale_error(130.0, 130.0)
    finally:
        m.GATE_LO, m.GATE_HI = lo, hi
    assert m.gate_rejects_scale_error(130.0, 130.0)


def test_mpn_nominal_is_a_gate_not_a_parser():
    """The gate must decline on part numbers that do not encode a resistance, rather than
    inventing a nominal that would then wave a bad repair through."""
    assert mpn_nominal_milliohm('SQD50N10-8M9L_GE3', 'vishay') == 8.9
    assert mpn_nominal_milliohm('SQM120N10-3M8_GE3', 'vishay') == 3.8
    assert mpn_nominal_milliohm('IPW60R024CFD7', 'infineon') == 24.0
    assert mpn_nominal_milliohm('IPQC60T022S7', 'infineon') == 22.0
    for mpn, mfr in [('IXTX46N50L', 'littelfuse'), ('IRFP4768PBF', 'infineon'),
                     ('HY5012W', 'huayi'), ('SiR5808DP', 'vishay'), ('', 'vishay')]:
        assert mpn_nominal_milliohm(mpn, mfr) is None, mpn
    # no mfr -> decline, never guess
    assert mpn_nominal_milliohm('IPW60R024CFD7') is None
    assert mpn_nominal_milliohm('SQD50N10-8M9L_GE3') is None


def test_mpn_nominal_does_not_read_a_voltage_as_a_resistance():
    """Nexperia BUK7Y3R1-80MX is 3.1 mΩ / 80 V. Applied blindly, the Vishay pattern matched
    the '-80M' of the VOLTAGE rating and reported the correct 3.1 mΩ record as a 26x scale
    error -- a gate that invents false alarms is as bad as one that never fires."""
    assert mpn_nominal_milliohm('BUK7Y3R1-80MX', 'nxp') is None
    assert mpn_nominal_milliohm('BUK7Y3R1-80MX') is None


def test_vishay_fractional_code_is_not_truncated():
    """Regression on my own fix: an earlier attempt to exclude Nexperia bolted a negative
    lookahead onto RE_VISHAY, which let '-8M9L' backtrack to '-8M' and report 8.0 mΩ for an
    8.9 mΩ part. Narrowing a gate must not quietly coarsen the values it does accept."""
    assert mpn_nominal_milliohm('SQD50N10-8M9L_GE3', 'vishay') == 8.9
    assert mpn_nominal_milliohm('SUM90N10-8M2P-E3', 'vishay') == 8.2
    assert mpn_nominal_milliohm('SQM120N10-3M8_GE3', 'vishay') == 3.8


@pytest.mark.parametrize('cell,expect', [
    ('Â', 1e3),      # bare ohm as rendered by the broken Infineon font
    ('mÂ', 1.0),     # ...with its SI prefix intact -- must NOT collapse to bare ohm
    ('kÂ', 1e6),
    ('nA', None), ('', None), ('A', None), ('0.048', None), ('R‡»ñÓÒò', None),
])
def test_mojibake_ohm_keeps_the_prefix(cell, expect):
    from apps.repair_rds_units import _mojibake_ohm
    got = _mojibake_ohm(cell)
    assert (ohm_unit_to_milli_mul(got) if got else None) == expect
