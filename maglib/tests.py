from dslib import rel_err
from dslib.spec_models import DcDcLoadParams
from maglib import cores
from maglib.materials import KDM_SendustKS_60, MagInc_KoolMu_60, Micrometals_Sendust_60u


def test_mat():
    assert abs(rel_err(KDM_SendustKS_60.dc_bias(H_oe=10), 98 / 100)) < 0.05
    assert abs(rel_err(KDM_SendustKS_60.dc_bias(H_oe=60), 70 / 100)) < 0.05
    assert abs(rel_err(KDM_SendustKS_60.dc_bias(H_oe=100), 46 / 100)) < 0.05
    assert abs(rel_err(KDM_SendustKS_60.dc_bias(H_oe=200), 21 / 100)) < 0.05
    assert abs(rel_err(KDM_SendustKS_60.dc_bias(H_oe=1000), 1.5 / 100)) < 0.05

    assert abs(KDM_SendustKS_60.dc_magnetization(H_oe=10) - 0.05) < 0.012
    assert abs(KDM_SendustKS_60.dc_magnetization(H_oe=50) - 0.3) < 0.01
    assert abs(KDM_SendustKS_60.dc_magnetization(H_oe=100) - 0.53) < 0.01

    assert abs(Micrometals_Sendust_60u.dc_bias(H_oe=10) - .98) < 0.01
    assert abs(Micrometals_Sendust_60u.dc_bias(H_oe=100) - .5) < 0.01
    assert abs(Micrometals_Sendust_60u.dc_bias(H_oe=1000) - .01) < 0.01

    assert abs(Micrometals_Sendust_60u.core_loss_density(Bpk_tesla=400e-4, f_khz=50) - 50) < 1
    assert abs(Micrometals_Sendust_60u.core_loss_density(Bpk_tesla=1000e-4, f_khz=50) - 323) < 10  # from table
    assert abs(Micrometals_Sendust_60u.core_loss_density(Bpk_tesla=5000e-4, f_khz=50) - 7125) < 100
    assert abs(Micrometals_Sendust_60u.core_loss_density(Bpk_tesla=100e-4, f_khz=500) - 90) < 5
    assert abs(Micrometals_Sendust_60u.core_loss_density(Bpk_tesla=1000e-4, f_khz=500) - 9500) < 500

    assert abs(Micrometals_Sendust_60u.dc_magnetization(H_oe=50) - 2800e-4) < 100e-4
    assert abs(Micrometals_Sendust_60u.dc_magnetization(H_oe=100) - 4900e-4) < 100e-4

    assert abs(MagInc_KoolMu_60.core_loss_density(Bpk_tesla=0.06, f_khz=50) - 70) < 5
    assert abs(MagInc_KoolMu_60.core_loss_density(Bpk_tesla=0.1, f_khz=50) - 190) < 5  # pg 124
    assert abs(MagInc_KoolMu_60.core_loss_density(Bpk_tesla=0.06, f_khz=100) - 200) < 1

    assert abs(MagInc_KoolMu_60.dc_magnetization(H_oe=10) - 0.05) < 0.01
    assert abs(MagInc_KoolMu_60.dc_magnetization(H_oe=50) - 0.28) < 0.01  # pg 124
    assert abs(MagInc_KoolMu_60.dc_magnetization(H_oe=100) - 0.45) < 0.01  # pg 124


def test_power_loss():
    import maglib.cores as cores

    from dclib.powerloss import CoilSpecs
    coil = CoilSpecs(Rdc=0, turns=20, core=cores.MagInc_106_KoolMu60)

    # https://www.mag-inc.com/design/design-guides/powder-core-loss-calculation
    # method 1
    from maglib.powerloss import core_loss_from_dc_magnetization
    from maglib.powerloss import core_loss_from_dc_bias  # method 2

    # example 1: 20A DC, 2A ripple, 100 khz
    dcdc = DcDcLoadParams(85, 6.5, 100e3, io=20, iripple=2)
    assert abs(rel_err(dcdc.L, coil.L0)) < 0.1
    assert abs(rel_err(core_loss_from_dc_magnetization(dcdc, coil)[0], 44e-3)) < 0.05  # method 1
    assert abs(rel_err(core_loss_from_dc_bias(dcdc, coil)[0], 44e-3)) < 0.05  # method 2

    # example 2: 20A DC, 8A ripple, 100 khz
    dcdc = DcDcLoadParams(100, 60, 100e3, io=20, iripple=8)
    assert abs(rel_err(core_loss_from_dc_magnetization(dcdc, coil)[0], 692e-3)) < 0.05
    assert abs(rel_err(core_loss_from_dc_bias(dcdc, coil)[0], 708e-3)) < 0.05

    # example 3: 0A DC, 8A ripple, 100 khz
    dcdc = DcDcLoadParams(100, 60, 100e3, io=0, iripple=8)
    assert abs(rel_err(core_loss_from_dc_magnetization(dcdc, coil)[0], 1920e-3)) < 0.05
    assert abs(rel_err(core_loss_from_dc_bias(dcdc, coil)[0], 2062e-3)) < 0.05


def test_unusable_material_raises():
    """A curve that cannot be evaluated must refuse, not return nan.

    nan does not stay nan. dclib/powerloss.py combines the two core-loss
    methods with max(P_core1, P_core2), and max(0, nan) is 0 in CPython, so a
    material whose loss cannot be computed was reported as a core with NO LOSS
    -- the most favourable answer available -- and the run went on to claim
    'mthd: 1' because nan > 0 is False, naming a method that never ran.

    KDM_SendustKS_125 is written with literal nan exponents and backs
    KDM_KS184_125A in cores.py, so this is reachable, not hypothetical.
    """
    import pytest

    from maglib.materials import KDM_SendustKS_125, Micrometals_Sendust_60u

    with pytest.raises(ValueError):
        KDM_SendustKS_125.core_loss_density(Bpk_tesla=0.05, f_khz=100)

    # the same material's dc_bias HAS real coefficients and must be unaffected
    assert 0 < KDM_SendustKS_125.dc_bias(H_oe=50) < 1

    # and a healthy material must not be disturbed by the guard
    assert Micrometals_Sendust_60u.core_loss_density(
        Bpk_tesla=0.05, f_khz=100) > 0


def test_winding_bore():
    """A core without datasheet OD/ID must refuse by name, not AttributeError.

    dcdc_buck_coil needs the bore for the mean turn length b_eq =
    pi/2*(ID+OD). Reaching it through ``core.shape.ID`` gave
    "'NoneType' object has no attribute 'ID'" from inside the loss
    calculation, naming neither the core nor the missing quantity -- and every
    core defined with only l_e/A_e/Vol hit it, so the live coil-loss path was
    unreachable for most of the library.

    Three cores were passing ``**shape.values()``, which returns l_e/A_e/Vol
    and DROPS od/id, leaving shape=None on cores whose geometry is known and
    published. Those are pinned here: a regression to values() puts them back
    in the refusing set.
    """
    import pytest

    # geometry known -> real datasheet bore
    for core in (cores.Micrometals_MS_130_060, cores.Micrometals_MS_184_060,
                 cores.Micrometals_MS_184_090, cores.Micrometals_OE_184_060,
                 cores.Micrometals_MS_184_125):
        core_id, core_od = core.winding_bore()
        assert 0 < core_id < core_od < 0.1, (core.mpn, core_id, core_od)

    # geometry genuinely absent -> refuse, and say which core and why
    for core in (cores.MagInc_106_KoolMu60, cores.KDM_KS130_060A,
                 cores.Micrometals_OE_226_060):
        with pytest.raises(ValueError, match=core.mpn):
            core.winding_bore()


def test_dc_bias_suppression_is_not_silent():
    """no_raise=True may suppress the abort, not the fact.

    The design sweeps in apps/ walk past saturation on purpose, so the assert
    has to be suppressible. But it used to return a deeply-saturated
    permeability with no signal at all -- 0.283*mu_r for KDM_SendustKS_125 at
    H=1e5 -- and that number propagates into Ldc and every flux and loss figure
    downstream. The caller could not tell it apart from a validated one.
    """
    import warnings as _w

    from maglib.materials import KDM_SendustKS_125, MagInc_KoolMu_60

    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter('always')
        KDM_SendustKS_125.permeability_dc_bias(1e5, no_raise=True)
    assert caught, 'out-of-range dc bias was suppressed silently'

    # and an in-range point must stay quiet, or the warning means nothing
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter('always')
        MagInc_KoolMu_60.permeability_dc_bias(1e3, no_raise=True)
    assert not caught, [str(c.message) for c in caught]


def test_copper_resistivity_tempco():
    """rho(T) = rho20 * (1 + tc*(T-20)); tc is fractional (1/K), so it scales.

    It was being added to the resistivity -- a dimensionless number in series
    with ohm-metres -- returning 0.0786 ohm*m at 100 degC against a true
    2.208e-8. Copper read as an insulator, seven orders out.
    """
    from maglib.wire import MaterialResistivity, copper_resistivity_tempco

    r20 = MaterialResistivity.Copper.value
    assert copper_resistivity_tempco(r20, 20) == r20
    assert abs(rel_err(copper_resistivity_tempco(r20, 100), 2.208e-8)) < 0.01
    assert abs(rel_err(copper_resistivity_tempco(r20, 40), 1.812e-8)) < 0.01
    # must stay in the ballpark of a metal, which the additive form did not
    assert 1e-8 < copper_resistivity_tempco(r20, 150) < 1e-7


def test_bpk_sinusoidal():
    """Oliver/Ridley p.3, Bpk = Vrms x 10^1 / (4.44 x Area[cm2] x N x f[kHz]).

    ``vrms`` was hardcoded to 0, so this returned 0 T at every operating point
    -- and zero flux is zero core loss, the one answer that makes any core look
    perfect. Asserting non-zero alone would not catch a units error, so the
    value is pinned against two closed forms:

    * the same equation rebuilt in SI, Bpk = Vrms / (4.44 * f * N * A_e), which
      fails if the cm2/kHz/10^1 conversions do not cancel exactly;
    * the exact volt-second flux of the square wave the inductor actually sees,
      Bpk = Vo*(1 - D)/(2*f*N*A_e), times the analytic sine/square form-factor
      ratio (2/4.44)/sqrt(D*(1 - D)).

    CORRECTION: an earlier version called those two INDEPENDENT. They are not.
    Whenever D = Vo/Vi the second reduces algebraically to the first, so it
    adds one proposition (that D_buck is Vo/Vi) and no separate check of the
    units, the 4.44, or the half-swing convention. The mutation coverage is
    real -- vrms=0, dropping (1-D)Vo^2, D<->1-D, missing Hz->kHz, missing
    m2->cm2, 4.44->4.0, dropping x10, peak-to-peak, dropping turns all fail --
    but they fail via the FIRST assertion. Calling it independent corroboration
    was the kind of claim this file exists to stop.
    """
    import math

    from dclib.powerloss import CoilSpecs
    from maglib.powerloss import Bpk_sinusoidal

    coil = CoilSpecs(Rdc=0, turns=20, core=cores.MagInc_106_KoolMu60)
    N, A_e = coil.turns, coil.core.A_e

    for vi, vo in [(100, 90), (100, 60), (100, 50), (100, 40), (100, 10)]:
        dcdc = DcDcLoadParams(vi, vo, 100e3, io=20, iripple=8)
        D, f = dcdc.D_buck, dcdc.f
        got = Bpk_sinusoidal(dcdc, coil)

        assert got > 0, (vi, vo, got)

        vrms = math.sqrt(D * (vi - vo) ** 2 + (1 - D) * vo ** 2)
        assert abs(rel_err(got, vrms / (4.44 * f * N * A_e))) < 1e-12, (vi, vo)

        exact = vo * (1 - D) / (2 * f * N * A_e)
        ratio = (2 / 4.44) / math.sqrt(D * (1 - D))
        assert abs(rel_err(got, exact * ratio)) < 1e-12, (vi, vo, got, exact)

    # the flux a real core sees is bounded; a units slip lands orders out
    dcdc = DcDcLoadParams(100, 50, 100e3, io=20, iripple=8)
    assert 0.01 < Bpk_sinusoidal(dcdc, coil) < 1.0


def test_coil():
    from dclib.powerloss import CoilSpecs
    coil = CoilSpecs(Rdc=0, turns=20, core=cores.MagInc_106_KoolMu60, wire_awg=15, wire_strands=10)
    assert abs(rel_err(coil.wire_diameter, 1.45e-3)) < 0.01
    assert abs(rel_err(coil.bundle_diameter, 4.59e-3)) < 0.01


def test_wire():
    from dslib import rel_err


    from maglib.wire import d2awg, awg2d
    for i in range(1000):
        import random
        x = random.random() * 10

        assert abs(rel_err(awg2d(d2awg(x)), x)) < 1e-9
        assert abs(rel_err(d2awg(awg2d(x)), x)) < 1e-9


    from maglib.wire import skin_depth, dc_resistance, ac_resistance, ac_resistance_factor

    assert abs(rel_err(skin_depth(1.72e-8, f=50), 9.335e-3)) < 1e-4
    assert abs(rel_err(skin_depth(1.72e-8, f=50, mu_r=2), 6.601e-3)) < 1e-4

    from maglib.wire import MaterialResistivity
    res = MaterialResistivity.Copper.value
    from maglib.wire import awg2d
    d = awg2d(14)

    rdc = dc_resistance(res, 1, d)
    assert abs(rel_err(rdc, 8.1e-3)) < 0.01

    rac = ac_resistance(res, 1, d, 50e3)[0]
    assert abs(rel_err(rac, 13.7e-3)) < 0.01

    acf, sd = ac_resistance_factor(res, d, 50e3)
    assert abs(rel_err(rac, acf * rdc)) < 0.01

    # example from https://s3.amazonaws.com/micrometals-production/filer_public/7c/72/7c728863-9c0e-40b3-ba86-a3f94d5ad1c1/acresistance_rev0_110123.pdf
    #
    # acr_factor_micrometals returns the EXCESS factors: Rac = Rdc * (1 + Fs + Fp),
    # with the +1 deliberately removed (see wire.py). The app note's 2.5060 is the
    # TOTAL ratio, so it must be compared against 1 + the sum. Comparing it to the
    # bare sum asserted 2.5060 == 1.5060 and failed by exactly 1.0 -- the DC term.
    # With the conventions aligned the model reproduces the app note to 1.7e-5,
    # and 1 + f_skin tracks the exact Kelvin-function solution to <= 0.19% over
    # the whole grid below, which is what settles the direction: bare f_skin is
    # ~100% low at low frequency, where the true ratio tends to 1.
    #
    # CORRECTION: an earlier version of this comment called Winding.Rac_sepe the
    # "only production consumer". That was false and it mattered -- asserting it
    # instead of checking is why a live double-count went unnoticed. There are
    # three call sites, and dclib/powerloss.py is the one on the shipped path.
    from maglib.wire import acr_factor_micrometals
    assert abs(rel_err(2.5060, 1 + sum(
        acr_factor_micrometals(23e-9, 1e-3, 100e3, 1, 32, 14.1e-3, 27.69e-3)))) < 1e-4

    # Cross-check the two skin-effect models. Same convention fix:
    # ac_resistance_factor returns the TOTAL ratio (>= 1, it is Rac/Rdc for a
    # hollow cylinder) while acr_factor_micrometals returns the excess.
    #
    # Restricted to where ac_resistance_factor is defined: its own assert is
    # sd/diameter < 0.3 (ac_resistance() uses 0.25 for the same approximation),
    # and 8 of the 20 points below violate it, so the loop used to die at its
    # first iteration rather than compare anything.
    #
    # Read what this actually measures. Against the exact Kelvin-function
    # solution the micrometals model is accurate to 0.02% on the EXCLUDED
    # points and 0.19% on the included ones -- it is best exactly where this
    # loop refuses to look. So the spread below is almost entirely
    # ac_resistance_factor's own error against a near-exact reference, not two
    # models independently agreeing. The tolerance is also one-sided: the
    # baseline disagreement is already +5.35%, so a downward error in
    # ac_resistance_factor of 7% passes here (it is caught by the reference
    # assertions above, not by this loop).
    #
    # And both models are pure functions of zeta = d/sd, so a multiplicative
    # error in skin_depth slides both along the same curve and CANNOT be seen
    # here at all -- measured: skin_depth x1.10 leaves this loop green. Its
    # only sensitivity to sd is the sample count, which is why n_compared is
    # asserted below; do not remove that believing the tolerance covers it.
    n_compared = 0
    for d in [0.7e-3, 1.0e-3, 1.2e-3, 1.5e-3, 2e-3]:
        for f in [20e3, 40e3, 100e3, 200e3]:
            if skin_depth(23e-9, f) / d >= 0.3:
                continue
            a = ac_resistance_factor(23e-9, d, f)[0]
            b = acr_factor_micrometals(23e-9, d, f, 1, 32, 14.1e-3, 27.69e-3)[0]
            assert abs(rel_err(a, 1 + b)) < 0.07, (d, f, a, 1 + b)
            n_compared += 1
    # A skip-guarded loop that skips everything passes while testing nothing.
    assert n_compared == 12, n_compared
