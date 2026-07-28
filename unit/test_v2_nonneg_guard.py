"""v2's physical-domain guard: negative charges/times/caps/resistances/currents are
tokenization junk and must be REFUSED (NaN + warning), never abs()'d or shipped.

The observed class (2026-07-28): an OCR'd text layer prints the min/typ/max cells as
'- 54 -' and the placeholder dash fuses onto the value, so BSZ123N08NS3GATMA1 (and
five siblings) carried Qrr typ = -54 nC in the DB — a negative P_rr downstream, and
a wrong-sign entry the layout registry's value cross-check can never match again.

Direction pins, per the guard checklist: WHICH value survives (nothing from the
corrupt cell — the field vanishes so a cleaner stage wins), and the exemption
boundary (P-channel Vgs_th stays negative; a mixed row keeps its clean stats).
"""
import math
import os
import sys
import warnings
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dslib.v2 import _make_field


def _ex(symbol, mn=None, typ=None, mx=None, unit="nC"):
    row = SimpleNamespace(text="%s %s %s %s" % (symbol, mn, typ, mx),
                          bbox=SimpleNamespace(y2=600.0))
    return SimpleNamespace(symbol=symbol, row=row,
                           values={"min": mn, "typ": typ, "max": mx},
                           unit=unit, cond=None, page_num=4, cond_src=None)


def test_fused_placeholder_dash_is_refused_not_sign_flipped():
    # the verbatim shape: '- 54 -' with the dash fused onto the value
    with pytest.warns(UserWarning, match="negative typ for Qrr"):
        f = _make_field(_ex("Qrr", mn="-", typ="-54", mx="-"))
    assert f is None          # nothing survives; a cleaner stage fills the symbol


def test_clean_stats_on_the_same_row_survive_the_refusal():
    with pytest.warns(UserWarning, match="negative min for Qrr"):
        f = _make_field(_ex("Qrr", mn="-54", typ="54", mx="108"))
    assert f is not None
    assert math.isnan(f.min) and f.typ == 54.0 and f.max == 108.0


def test_voltage_symbols_are_exempt_from_the_guard():
    # The guard must not fire for V-symbols (P-channel Vgs_th is legitimately
    # negative). Whether dslib.field.Field's own invariants then accept the stats
    # is that constructor's business — it currently asserts on this input — so the
    # pin here is only that OUR refusal never triggers.
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _make_field(_ex("Vgs_th", mn="-3.5", typ="-2.5", mx="-1.5", unit="V"))
    assert not any("refusing the stat" in str(x.message) for x in w)


@pytest.mark.parametrize("sym", ["trr", "Coss", "Rg", "Qgs"])
def test_guard_covers_the_whole_nonnegative_domain(sym):
    with pytest.warns(UserWarning, match="negative typ for %s" % sym):
        assert _make_field(_ex(sym, typ="-12", unit="ns")) is None


def test_p_channel_drain_current_is_exempt():
    # 233 negative-Id ratings in the corpus are REAL P-channel parts (SP010P40TH,
    # XRS80P10H, ... — negative Vds and Vgs_th corroborate). A guard that covered
    # I* would have refused known-good data across every P-FET.
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _make_field(_ex("Id", typ="-49", unit="A"))
    assert not any("refusing the stat" in str(x.message) for x in w)
