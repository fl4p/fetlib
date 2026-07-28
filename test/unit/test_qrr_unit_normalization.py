"""Pin the Qrr micro-unit normalization in Field.__init__ (2026-07-28) — both
directions, per the guard checklist: the known-bad inputs must convert/refuse, AND
known-good inputs must pass through untouched. The mangled spellings are each backed
by a real record verified against its printed PDF (docs/qrr-open-fixes-brief.md §2,
apps/repair_qrr_units.py docstring): 'PC' IRFB38N20D, 'PSC' IXFN150N10, 'WC'
SUM85N15-19, whitespace-μC IXFN300N10P, 'UC' SPW55N80C3FKSA1."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from dslib.field import Field  # noqa: E402

nan = math.nan


@pytest.mark.parametrize('unit,typ,max_,want_typ,want_unit', [
    # mangled micro spellings -> x1000, canonical 'nC' (unit-proven, band irrelevant)
    ('PC', 1.3, 2.0, 1300.0, 'nC'),        # IRFB38N20D: was stored 1.3 -> 1000x low
    ('PSC', 0.6, nan, 600.0, 'nC'),        # IXFN150N10: sheet prints 0.6 µC
    ('WC', 0.52, 1.2, 520.0, 'nC'),        # SUM85N15-19
    ('mC', 1.1, nan, 1100.0, 'nC'),        # Symbol-font µ renders as 'm'
    ('UC', 43.0, nan, 43000.0, 'nC'),      # SPW55N80C3: out of the 0.1-0.9 band too
    ('µC', 1.3, 2.0, 1300.0, 'nC'),        # micro sign U+00B5 (old set had only U+03BC)
    ('μ C', 0.71, nan, 710.0, 'nC'),       # greek mu + stray whitespace (IXFN300N10P)
    ('uc', 0.5, nan, 500.0, 'nC'),
    # trustworthy units and the unitless convention: NO change
    ('nC', 35.0, 70.0, 35.0, 'nC'),
    ('nc', 35.0, 70.0, 35.0, 'nc'),
    (None, 120.0, nan, 120.0, None),       # unitless out of band: nC by convention
    (None, 0.44, nan, 440.0, None),        # unitless in band: the original 0.1-0.9 fix
    # bare 'C', values >= 100: identical under lost-'n' and lost-'µ' readings -> keep
    ('C', nan, 600.0, nan, 'C'),           # IXFN150N10's band-converted sibling
    ('C', 0.35, 0.5, 350.0, 'C'),          # bare 'C' in band: convert, unit NOT upgraded
    # whitespace-padded bare 'C' is the same mangle (review 2026-07-28: it used to
    # bypass the whole three-band block — silent pass-through of ambiguous values)
    (' C', 0.35, 0.5, 350.0, ' C'),        # padded, in band: convert like 'C'
    ('C ', nan, 600.0, nan, 'C '),         # padded, >= 100: keep like 'C'
])
def test_qrr_unit_scale(unit, typ, max_, want_typ, want_unit):
    f = Field('Qrr', min=nan, typ=typ, max=max_, unit=unit)
    if math.isnan(want_typ):
        assert math.isnan(f.typ)
    else:
        assert f.typ == pytest.approx(want_typ)
    assert f.unit == want_unit


@pytest.mark.parametrize('unit', ['C', 'C ', ' C', 'c '])
@pytest.mark.parametrize('typ,max_', [
    (1.3, 2.0),    # IRFB38N20D's raw text-layer values: nC and µC readings both plausible
    (35.0, nan),   # plausible as nC, absurd as µC-band -> still ambiguous vs lost-'n'
    (0.52, 1.2),   # mixed: one stat in the µ band, one outside
])
def test_qrr_bare_c_ambiguous_refuses(typ, max_, unit):
    """A bare 'C' whose scale cannot be established must REFUSE, not pass through:
    absence of evidence must never encode absence of the problem. A missing Qrr is
    recoverable; a plausible 1000x one is not. Whitespace-padded spellings included:
    ' C' used to slip past the raw-unit comparison and pass ambiguous values through
    silently (review 2026-07-28)."""
    with pytest.raises(ValueError, match='ambiguous-scale'):
        Field('Qrr', min=nan, typ=typ, max=max_, unit=unit)


def test_micro_mangle_claim_stays_qrr_specific():
    """'PC' on another charge symbol could be a genuine picocoulomb — the mangle
    evidence is Qrr-only and the conversion must not creep."""
    f = Field('Qg', min=nan, typ=200.0, max=nan, unit='PC')
    assert f.typ == 200.0 and f.unit == 'PC'
    # but the unambiguous micro spellings convert for any charge symbol
    f = Field('Qg', min=nan, typ=0.2, max=nan, unit='UC')
    assert f.typ == pytest.approx(200.0) and f.unit == 'nC'


def test_repair_classifier_in_lock_step_with_field():
    """apps/repair_qrr_units.py mirrors Field.__init__'s decision for records that
    bypass __init__ (pickled). If either side changes without the other, stored and
    freshly-parsed records diverge by 1000x again — compare them on a shared matrix."""
    from apps.repair_qrr_units import (
        classify, _bare_c_action, _F, MICRO, GOOD, BARE_C, C_CONVERT, C_KEEP, C_DROP)
    for unit in ('PC', 'PSC', 'WC', 'mC', 'UC', 'µC', 'μ C', 'uc'):
        assert classify('Qrr', unit) == MICRO, unit
        assert Field('Qrr', nan, 0.5, nan, unit=unit).unit == 'nC'
    for unit in ('nC', 'nc', None, ''):
        assert classify('Qrr', unit) == GOOD, unit
    for unit in ('C', ' C', 'C '):
        assert classify('Qrr', unit) == BARE_C, unit
        # and Field agrees the padded spellings are bare-C: ambiguous values refuse
        try:
            Field('Qrr', nan, 1.3, 2.0, unit=unit)
        except ValueError:
            pass
        else:
            raise AssertionError('%r must refuse ambiguous bare-C values' % unit)
    for stats, action in ((dict(typ=0.6), C_CONVERT), (dict(max=600.0), C_KEEP),
                          (dict(typ=1.3, max=2.0), C_DROP)):
        assert _bare_c_action(_F(**stats)) == action, stats
