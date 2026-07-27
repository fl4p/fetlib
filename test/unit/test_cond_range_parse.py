"""Swept-range conditions: "VGS = 0 to 10 V" means 10 V, not 0 V.

Two layers parse conditions and they must not disagree:

  dslib/pdf/sheet.parse_cond_str   the shared parser (case-insensitive, and it
                                   already handled units on both endpoints)
  dslib/v2._parse_cond_text        v2's per-statement wrapper, which finds the
                                   statements with _COND_ITEM_RE before handing
                                   each one to the shared parser

befbb355 fixed the unspaced lowercase spelling and shipped no tests. It left
_COND_ITEM_RE case-SENSITIVE and unable to accept a unit on the lower endpoint,
so "VGS=0 TO 10 V", "VGS=0To10V", "VGS=0V to 10V" and "VGS=0 V to 10 V" still
returned 0.0 from v2 while the shared parser returned 10.0 -- the identical
failure that commit set out to close.

Why it matters beyond tidiness: gate-drive loss goes as Qg * Vgs * f. A sheet
that separates its two total-gate-charge rows only by the swing (0-to-4.5 V vs
0-to-10 V) collapses both onto Vgs=0, so a request for the 10 V charge can
return the 4.5 V one -- a 2x error in a quantity this tool ranks on. And Vgs=0
is false on its face: no gate charge is measured at zero drive.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from dslib.pdf.sheet import parse_cond_str                      # noqa: E402
from dslib.v2 import _parse_cond_text                           # noqa: E402


def _v2(text):
    return _parse_cond_text(text, parse_cond_str)


# Every spelling of the same sweep seen in the corpus, plus the case variants
# the shared parser accepts. All must yield the ENDPOINT.
RANGE_SPELLINGS = [
    'VGS=0to10V',
    'VGS=0 to 10 V',
    'VGS=0 TO 10 V',
    'VGS=0To10V',
    'VGS=0V to 10V',
    'VGS=0 V to 10 V',
    'VGS=0V TO 10V',
]


@pytest.mark.parametrize('text', RANGE_SPELLINGS)
def test_v2_reads_the_endpoint(text):
    assert _v2(text) == {'Vgs': 10.0}, text


@pytest.mark.parametrize('text', RANGE_SPELLINGS)
def test_shared_parser_reads_the_endpoint(text):
    assert parse_cond_str(text) == {'Vgs': 10.0}, text


@pytest.mark.parametrize('text', RANGE_SPELLINGS)
def test_both_layers_agree(text):
    """The property that actually failed: one layer fixed, the other not."""
    assert _v2(text) == parse_cond_str(text), text


def test_negative_range_endpoint():
    assert _v2('VGS=-20to20V') == {'Vgs': 20.0}


# --- negative controls: the range clause must not widen the value match -----

def test_row_measurements_are_not_swallowed():
    """_parse_cond_text exists for this: the row's own numbers follow the cond.

    The shared parser repeats its value group and lets the LAST number win, so
    it answers 9.5 here -- the right key with the wrong value. v2 must stop at
    the first number. If a range fix ever relaxes that, this is what breaks.
    """
    assert _v2('VGS=10V 7.8 9.5') == {'Vgs': 10.0}


def test_trailing_word_is_not_eaten():
    """The exact regression of the obvious implementation.

    Making the lower-endpoint unit a free-standing optional group -- rather
    than putting it INSIDE the range group, where a literal "to" plus a digit
    must follow -- captures "5V tot" here, because the trailing unit class eats
    "tot" once "V" has been consumed. Measured, not hypothesised.
    """
    assert _v2('VDS=5V total') == {'Vds': 5.0}


def test_micro_scaling_still_applies():
    assert _v2('ID=250uA') == {'Id': 0.00025}


@pytest.mark.parametrize('text,expect', [
    ('VGS=10V', {'Vgs': 10.0}),
    ('VDS=5V', {'Vds': 5.0}),
    ('VGS=4.5V', {'Vgs': 4.5}),
])
def test_plain_conditions_unchanged(text, expect):
    assert _v2(text) == expect


def test_multiple_statements_in_one_cell():
    got = _v2('VDS=40V, VGS=0 to 10 V, ID=20A')
    assert got.get('Vgs') == 10.0 and got.get('Vds') == 40.0 and got.get('Id') == 20.0
