"""Unit-string -> milliohm scale resolution.

The omega glyph is very often a Symbol-font char with no ToUnicode mapping, so extractors
render it as nothing, ':', 'O', 'Q', 'QO' or 'W', and table extractors additionally glue
cell-border debris to the front. Recovering those is pure recall: the alternative is NaN.

The point of this file is the NEGATIVE half. Widening a unit matcher is exactly the kind of
change that turns "I cannot read this cell" into a believable wrong resistance on the
quantity the tool ranks on, so every widening here is pinned against a cross-dimension and
a mis-segmented case that MUST still refuse to resolve.
"""
import pytest

from dslib.field import ohm_unit_to_milli_mul

OHM = 'Ω'  # GREEK CAPITAL OMEGA
OHM_SIGN = 'Ω'  # OHM SIGN -- a distinct codepoint, both occur in real sheets


@pytest.mark.parametrize('unit,expect', [
    # --- canonical, must be unchanged by the OCR widening -----------------------------
    (OHM, 1e3), (OHM_SIGN, 1e3), ('Ohm', 1e3), ('ohm', 1e3), ('OHM', 1e3),
    ('m' + OHM, 1.0), ('mOhm', 1.0), ('k' + OHM, 1e6), ('M' + OHM, 1e9),
    # 'ohm' starts with 'o', which is also an omega rendering -- the noise-strip must not
    # eat it. This is the case that breaks if 'o'/'O' are ever added to _OHM_NOISE_PREFIX.
    ('mohm', 1.0), ('mOHM', 1.0),

    # --- OCR omega renderings ---------------------------------------------------------
    ('O', 1e3), ('Q', 1e3), ('QO', 1e3), ('OQ', 1e3), ('o', 1e3), ('W', 1e3),
    ('mO', 1.0), ('mQ', 1.0), ('mQO', 1.0), ('mo', 1.0), ('mW', 1.0),

    # --- ':' as omega. Ground truth is exact: Vishay SQD50N10-8M9L (8.9 mOhm) stores
    #     0.0089 with unit ':', SQM120N10-3M8 stores 0.0038, SUM90N10-8M2P 0.0082.
    (':', 1e3),
    #     'm:' checks out against IRFP4768PBF ("max 17.5m", DB 17.5) and HY5012W (3.6).
    ('m:', 1.0),

    # --- cell-border debris glued to the front ----------------------------------------
    ('|mQ', 1.0), ('ImQ', 1.0), ('JmQ', 1.0), ('}mQ', 1.0), ('|(mQ', 1.0),
    ('|JmQ', 1.0), ('|mQO', 1.0), ('|mOQ', 1.0), ('ImO', 1.0), ('|mO', 1.0),
    ('|Q', 1e3), ('JO', 1e3),

    # --- separator inside the cell ----------------------------------------------------
    ('m ' + OHM, 1.0), ('m ' + OHM, 1.0),

    # --- omega dropped entirely by the extractor --------------------------------------
    ('m', 1.0),
])
def test_resolves(unit, expect):
    assert ohm_unit_to_milli_mul(unit) == expect


@pytest.mark.parametrize('unit', [
    # Empty/missing: the caller must decide what a missing unit means, not this function.
    None, '', '   ',

    # --- cross-dimension. These are the whole reason the function returns None rather
    #     than assuming a scale: the cell was mis-captured, so the number is not a
    #     resistance at all (Rg=168 lifted out of a unit='ns' switching-time row).
    'V', 'V/°C', 'nA', 'nA nA', 'j|nA', 'A', '∝A', '°', 'm°',
    'mm', 'ns', 'pF', 'nC', 'mV',

    # 'm°' and 'mm' are the sharp ones: a valid prefix followed by a body that is NOT
    # omega must not be salvaged by the bare-'m' rule.

    # --- bare prefixes other than 'm' are ambiguous with a stray letter ---------------
    'k', 'M',

    # --- pure debris, nothing left after stripping ------------------------------------
    'l', '|', '}', '|(', 'Ij',

    # --- numbers that landed in the unit column ---------------------------------------
    '7.8', '6.0', '16',

    # --- mis-segmented cells: the condition text ran into the unit. The unit is probably
    #     mOhm, but the cell boundary is wrong, so the VALUE is suspect too -- refusing is
    #     the whole point. Do not "recover" these.
    'VGS = 10V, ID = 103A',
    'm: VGS = 10V, ID = 103A 4',
    'm: VGS = 10V, ID = 33A 3',
])
def test_refuses(unit):
    assert ohm_unit_to_milli_mul(unit) is None


def test_never_inspects_magnitude():
    """The scale must come from the unit alone. A guard that reads magnitude is how
    `if rds_on_max < 0.1: *= 1000` became anti-monotone."""
    assert ohm_unit_to_milli_mul('m:') == ohm_unit_to_milli_mul('m' + OHM)
    assert ohm_unit_to_milli_mul(':') == ohm_unit_to_milli_mul(OHM)


def test_prefix_and_body_compose_consistently():
    """Every recognised body must accept every recognised prefix, so a newly added OCR
    body cannot resolve bare but silently fail when prefixed (or vice versa)."""
    from dslib.field import _OHM_BODY
    for body in _OHM_BODY:
        assert ohm_unit_to_milli_mul(body) == 1e3, body
        assert ohm_unit_to_milli_mul('m' + body) == 1.0, body
        assert ohm_unit_to_milli_mul('k' + body) == 1e6, body


def test_calibrate_against_the_bug_this_fixes():
    """IXTX46N50L: 0.16 Ohm max. Before the fix the reader saw an unresolvable unit and
    returned NaN; a dropped unit instead lands on the unitless default (= already mOhm)
    and yields 0.16 mOhm, 1000x too LOW -- i.e. the part looks 1000x better and sorts to
    the top of a loss-ranked CSV. Assert the direction, not merely that something changed.
    """
    assert ohm_unit_to_milli_mul(':') * 0.16 == pytest.approx(160.0)
    assert ohm_unit_to_milli_mul('m:') * 17.5 == pytest.approx(17.5)
    # and the failure mode stays a refusal, never a plausible number
    assert ohm_unit_to_milli_mul('nA') is None
