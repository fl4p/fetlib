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


def test_winding_fit():
    """Bore-limited strand count, pinned against the hand-checked T184 case.

    KDM KS184 (ID 24.11 mm), 1.8 mm G2 wire, 16 turns: one bore pass per
    strand-turn, 0.4 area fill max for stiff hand-wound wire.
    """
    import pytest

    from maglib.winding import (enameled_od, layer_fit, max_strands,
                                mean_turn_length, strand_cut_length,
                                window_fill)

    # IEC 60317-0-1 overall diameters, exact table rows
    assert abs(rel_err(enameled_od(1.8e-3, 2), 1.909e-3)) < 1e-6
    assert abs(rel_err(enameled_od(1.8e-3, 1), 1.872e-3)) < 1e-6
    assert abs(rel_err(enameled_od(1.0e-3, 3), 1.124e-3)) < 1e-6
    # interpolated size lands between its neighbours
    assert 1.706e-3 < enameled_od(1.65e-3, 2) < 1.809e-3
    # refusals: outside the table, and grade 3 has no build above 1.32 mm
    with pytest.raises(ValueError):
        enameled_od(5e-3, 2)
    with pytest.raises(ValueError):
        enameled_od(0.1e-3, 2)
    with pytest.raises(ValueError):
        enameled_od(1.8e-3, 3)

    # T184 case: 0.4*(24.11/1.9)^2 = 64.4 passes -> 64 -> 4 strands
    assert max_strands(24.11e-3, 1.9e-3, 16, 0.4) == 4
    assert max_strands(24.11e-3, 1.9e-3, 16, 0.33) == 3
    assert window_fill(24.11e-3, 1.9e-3, 64) < 0.4 < window_fill(
        24.11e-3, 1.9e-3, 65)

    # monotone: fatter wire never gains strands
    prev = 1000
    for od in (1.0e-3, 1.5e-3, 1.9e-3, 2.5e-3, 3.5e-3):
        s = max_strands(24.11e-3, od, 16, 0.4)
        assert s <= prev, (od, s, prev)
        prev = s
    # impossible fit refuses, never returns 0-meaning-fine
    with pytest.raises(ValueError):
        max_strands(24.11e-3, 5e-3, 16, 0.4)
    # garbage geometry raises ValueError, not assert (which dies under -O;
    # negative wire_od once made layer_fit loop unbounded there)
    with pytest.raises(ValueError):
        max_strands(24.11e-3, -1.9e-3, 16, 0.4)
    with pytest.raises(ValueError):
        layer_fit(24.11e-3, -1.9e-3, 64)

    # the KDM KS184 core carries its own datasheet bore (not the T184 clone)
    core_id, core_od = cores.KDM_KS184_125A.winding_bore()
    assert abs(rel_err(core_id, 24.11e-3)) < 1e-9 and abs(
        rel_err(core_od, 46.7e-3)) < 1e-9
    assert max_strands(core_id, enameled_od(1.8e-3, 2), 16, 0.4) == 3

    # layer 1 ideal capacity: floor(2*pi*11.105/1.9) = 36
    layers = layer_fit(24.11e-3, 1.9e-3, 36, packing=1.0)
    assert layers[0][1] == 36 and layers[0][2] == 36 and len(layers) == 1
    # 64 passes at practical packing spill into a third layer
    layers = layer_fit(24.11e-3, 1.9e-3, 64, packing=0.8)
    assert sum(l[2] for l in layers) == 64
    assert all(l[2] <= l[1] for l in layers)
    # hole shrinks monotonically and stays open
    holes = [l[3] for l in layers]
    assert all(a > b > 0 for a, b in zip(holes, holes[1:])) or len(holes) == 1
    # overstuffing the bore refuses rather than returning a short list
    with pytest.raises(ValueError):
        layer_fit(24.11e-3, 1.9e-3, 500, packing=1.0)

    # T184-S-125A: 46.7 x 24.11 x 18 mm -> ~70 mm/turn, ~1.4 m cut per strand
    mlt = mean_turn_length(46.7e-3, 24.11e-3, 18e-3, 1.9e-3, layers=2)
    assert 0.065 < mlt < 0.078, mlt
    cut = strand_cut_length(mlt, 16)
    assert 1.3 < cut < 1.6, cut


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


def test_toroid_packing():
    # T184 reference case (2026-08 FEMMT study): 1.9 mm-OD wire in the bore.
    # Repo T184 ID is 24.13 mm (the study used a 24.11 mm datasheet reading;
    # layer-1 capacity is 29 either way).
    from maglib.cores import MicrometalsT184
    from maglib.fem.toroid_packing import assign_layers, layer_capacity

    core_id = MicrometalsT184.ID
    assert abs(core_id - 24.13e-3) < 1e-6
    wire_od = 1.9e-3
    assert layer_capacity(1, core_id, wire_od) == 29
    assert layer_capacity(2, core_id, wire_od) == 24
    assert assign_layers(16, core_id, wire_od) == [16]
    assert assign_layers(32, core_id, wire_od) == [29, 3]
    assert assign_layers(48, core_id, wire_od) == [29, 19]
    assert assign_layers(64, core_id, wire_od) == [29, 24, 11]
    try:
        assign_layers(2000, core_id, wire_od)
        raise AssertionError('2000 wires must not fit')
    except ValueError as e:
        assert '2000' in str(e)


def test_toroid_column_geometry():
    from maglib.fem.toroid_packing import column_geometry, fem_sim_configs

    core_id, wire_od = 24.13e-3, 1.9e-3
    # single layer: pitch spreads over the full layer-1 circumference
    g1 = column_geometry(16, core_id, wire_od)
    assert g1.n_layers == 1 and g1.conductors_per_column == 16
    assert 4e-3 < g1.pitch < 5e-3
    assert abs(g1.window_h - g1.conductors_per_column * g1.pitch) < 1e-12

    # divisible: one exact config
    (w, g), = fem_sim_configs(48, core_id, wire_od)
    assert w == 1.0 and g.n_layers == 2 and g.conductors_per_column == 24

    # indivisible (64 wires, 3 layers): a short column skews the WHOLE model
    # (measured 0.45 rel asymmetry for 22/22/20) -> column_geometry refuses,
    # fem_sim_configs brackets with two all-full configs 63=3x21 / 66=3x22
    try:
        column_geometry(64, core_id, wire_od)
        raise AssertionError('indivisible count must raise')
    except ValueError as e:
        assert 'fem_sim_configs' in str(e)
    cfgs = fem_sim_configs(64, core_id, wire_od)
    assert [g.n_wires for _, g in cfgs] == [63, 66]
    assert [g.conductors_per_column for _, g in cfgs] == [21, 22]
    assert all(g.n_layers == 3 for _, g in cfgs)
    ws = [w for w, _ in cfgs]
    assert abs(sum(ws) - 1.0) < 1e-12 and abs(ws[0] - 2 / 3) < 1e-12
    assert all(g.pitch >= wire_od for _, g in cfgs)

    # 53 wires (2-layer capacity is exactly 29+24=53): the upper bracket 54
    # does NOT fit 2 layers — simulating 2x27 anyway would be a plausible Fr
    # for a fictitious geometry (review finding). Expect capacity refusal
    # from column_geometry and a single truncated-bracket config (52 = 2x26)
    # from fem_sim_configs.
    try:
        column_geometry(54, core_id, wire_od, n_layers=2)
        raise AssertionError('54 wires must not pack into 2 layers')
    except ValueError as e:
        assert 'capacity' in str(e)
    (w, g), = fem_sim_configs(53, core_id, wire_od)
    assert w == 1.0 and g.n_wires == 52 and g.n_layers == 2


def test_femmt_acr_result_conventions():
    # fr_total is TOTAL (Rac = Rdc * fr_total); fr_excess is the
    # acr_factor_micrometals F_se+F_pe convention. Interp anchors at
    # (100 Hz, 1.0) and extrapolates flat.
    from maglib.fem.femmt_toroid import AcrResult, F_DC_REF

    r = AcrResult(freqs=(40e3, 120e3), fr_total=(2.0, 4.0), p_dc_ref=1e-3,
                  layers=(16,), n_layers=1, conductors_per_column=16,
                  pitch=4.4e-3)
    assert r.fr_excess == (1.0, 3.0)
    assert abs(r.fr_at(F_DC_REF) - 1.0) < 1e-12
    assert abs(r.fr_at(40e3) - 2.0) < 1e-12
    assert abs(r.fr_at(120e3) - 4.0) < 1e-12
    assert abs(r.fr_at(1e6) - 4.0) < 1e-12  # flat beyond last point
    assert abs(r.fr_excess_at(40e3) - 1.0) < 1e-12
    mid = r.fr_at(80e3)
    assert 2.0 < mid < 4.0


def test_femmt_config_golden():
    from maglib.fem.femmt_toroid import _build_config, PROXY_LEG_DIAMETER

    cfg = _build_config(wire_r_um=900, n_cond=16, conductors_per_column=16,
                        n_layers=1, pitch_um=4363, freqs_hz=(40000, 120000),
                        temp_c=60, mu_r=20000, leg_d_um=24000, yoke_um=6000,
                        working_directory='/wd')
    assert cfg == {
        'schema': 1, 'wire_r': 900e-6, 'n_cond': 16,
        'conductors_per_column': 16, 'n_layers': 1, 'pitch': 4363e-6,
        'mu_r': 20000.0, 'temperature': 60.0,
        'freqs': [100.0, 40000.0, 120000.0], 'working_directory': '/wd',
        'core_inner_diameter': 24e-3, 'yoke': 6e-3,
    }
    assert abs(PROXY_LEG_DIAMETER - 24e-3) < 1e-12  # what callers pass as leg_d_um


def test_femmt_tool_paths_missing():
    # env is read at CALL time; a bogus home must raise ONE error naming
    # every missing piece — never degrade to a silent no-FEM path.
    import os
    import tempfile
    from maglib.fem.femmt_toroid import _tool_paths

    prev = os.environ.get('FETLIB_FEMMT_HOME')
    os.environ['FETLIB_FEMMT_HOME'] = tempfile.mkdtemp()
    try:
        _tool_paths()
        raise AssertionError('empty FETLIB_FEMMT_HOME must raise')
    except RuntimeError as e:
        msg = str(e)
        assert 'bin/python' in msg and 'femmt' in msg
        assert 'FETLIB_FEMMT_HOME' in msg
    finally:
        if prev is None:
            del os.environ['FETLIB_FEMMT_HOME']
        else:
            os.environ['FETLIB_FEMMT_HOME'] = prev


def test_femmt_toroid_fem():
    # Real FEM run, ~seconds-to-minutes. Opt-in via FETLIB_RUN_FEM_TESTS=1.
    # When the flag IS set and the femmt venv is missing, the RuntimeError
    # propagates — skipping then would be the skip-guarded false PASS above.
    import os
    if os.environ.get('FETLIB_RUN_FEM_TESTS') != '1':
        import pytest
        pytest.skip('set FETLIB_RUN_FEM_TESTS=1 to run the femmt FEM test')

    from maglib.fem import femmt_toroid_acr
    from maglib.wire import acr_factor_micrometals, MaterialResistivity

    r = femmt_toroid_acr(core_id=24.13e-3, wire_d=1.8e-3, turns=16, strands=1,
                         freqs=[40e3, 120e3], wire_od=1.9e-3)
    assert r.fr_total[0] >= 1 and r.fr_total[1] >= r.fr_total[0]
    assert r.provenance['guards']['column_symmetry_rel_dev'] < 0.05
    f_se, f_pe = acr_factor_micrometals(
        MaterialResistivity.CopperAnnealed.value, 1.8e-3, 40e3, 1, 16,
        id=24.13e-3, od=46.74e-3)
    # session-validated: TOTAL Fr agrees within ~9% for 1 layer (the EXCESS
    # ratio is looser, ~17%, because the DC term is subtracted); 15% margin
    assert abs(rel_err(r.fr_total[0], 1 + f_se + f_pe)) < 0.15, \
        (r.fr_total[0], 1 + f_se + f_pe)
