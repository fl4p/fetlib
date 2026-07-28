"""Field.__init__'s plausibility checks must JUDGE a zero, not crash on it.

Two guards divided by a stat that can legitimately be 0 in garbage input:

  * the max/typ ratio assert (field.py ~560): typ=0 raised ZeroDivisionError instead of
    AssertionError. Same outcome in callers that catch Exception (parse_field, v2's
    _make_field) -- a crash in any future caller that catches AssertionError/ValueError,
    the natural types for validation.
  * the Vsd min/typ-swap heuristic (~549): max=0 raised instead of concluding "typ/0 is
    inf, not a swap".

Found by the 2026-07-28 corpus sweep: chart-axis text globs (VSD / ISD(A) tick labels
ending in 0) are fed to parse_field as rows on every ST sheet with a body-diode plot, so
the wrong exception fired hundreds of times per sweep. The rejection OUTCOME was already
correct in both live paths; these tests pin the channel, and that the guards still accept
and still swap what they should.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dslib.field import Field  # noqa: E402

nan = math.nan


def test_zero_typ_is_rejected_not_a_crash():
    """The known-bad input, reduced from the sweep logs. Must be an AssertionError --
    the pair IS implausible -- never a ZeroDivisionError."""
    with pytest.raises(AssertionError):
        Field('Vsd', min=nan, typ=0.0, max=0.7, unit='V')


def test_zero_max_vsd_is_rejected_not_a_crash():
    """max=0 < typ used to divide typ/0 in the swap heuristic. 'Not a swap' is the right
    reading of an infinite ratio; the pair then fails the ratio assert as implausible."""
    with pytest.raises(AssertionError):
        Field('Vsd', min=nan, typ=0.7, max=0.0, unit='V')


def test_legitimate_vsd_swap_still_happens():
    """Direction: the guard must keep doing its job for the case it exists for.
    A real Vsd row with typ/max transposed (1.2 > 1.0, ratio < 1.5) swaps them."""
    f = Field('Vsd', min=nan, typ=1.2, max=1.0, unit='V')
    assert f.typ == 1.0 and f.max == 1.2


def test_legitimate_ratio_still_accepted():
    f = Field('Rds_on', min=nan, typ=10.0, max=16.0, unit='mOhm')
    assert f.typ == 10.0 and f.max == 16.0
