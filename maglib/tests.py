import math

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


def test_micrometals_toroid_shapes():
    """Pin the catalogue toroid sizes, and the coated-vs-bare bore distinction.

    The library used to define exactly two toroid shapes with a bore (130 and
    184) out of the 48 sizes Micrometals publishes. That is not a neutral gap:
    winding fit is limited by BORE AREA, so a design sweep over the shapes
    maglib happened to know silently answered a narrower question than it was
    asked -- and answered it confidently, because ``winding_bore()`` refuses
    shape-less cores rather than guessing, so the missing sizes never appeared
    as failures. One size up (T250) beats three stacked T184s.

    Reference values are the catalogue "Physical/Magnetic Dimensions" blocks,
    cross-checked against the per-part datasheets. l_e/A_e/Vol are pinned
    loosely (self-consistency) but OD/ID/Ht exactly, since those are what the
    winding models consume.
    """
    import pytest

    # (size, OD, ID_bare, ID_coated_min, Ht) in mm
    catalogue = [
        (130, 33.02, 19.94, 19.30, 10.67), (132, 33.02, 19.94, 19.30, 11.18),
        (157, 39.88, 24.13, 23.32, 14.48), (184, 46.74, 24.13, 23.32, 18.03),
        (185, 46.74, 28.70, 27.89, 15.24), (200, 50.80, 31.75, 30.94, 13.46),
        (225, 57.15, 35.56, 34.75, 13.97), (226, 57.15, 26.39, 25.58, 15.24),
        (250, 63.50, 31.37, 30.48, 25.00), (292, 74.10, 45.30, 44.10, 35.00),
        (300, 77.80, 49.23, 47.96, 12.70), (301, 77.80, 49.23, 47.96, 15.88),
    ]
    for size, od, id_bare, id_coated, ht in catalogue:
        sh = cores.MicrometalsToroidShapes[size]
        assert abs(sh.OD - od * 1e-3) < 1e-9, (size, sh.OD)
        assert abs(sh.ID - id_bare * 1e-3) < 1e-9, (size, sh.ID)
        assert abs(sh.ID_coated - id_coated * 1e-3) < 1e-9, (size, sh.ID_coated)
        # The coating always costs bore and always adds envelope/height. The
        # bands are tight enough to matter: real deltas are 0.81-1.27 mm on OD
        # and 0.81-1.20 mm on Ht, so +1.4e-3 leaves little undetected slack.
        assert sh.OD < sh.OD_coated < sh.OD + 1.4e-3, (size, sh.OD_coated)
        assert sh.HT < sh.HT_coated < sh.HT + 1.4e-3, (size, sh.HT_coated)
        # ...and the three must stay distinguishable: a coated ID that exceeds
        # the coated Ht or OD means two of them were swapped
        assert sh.ID_coated < sh.OD_coated, size
        assert abs(sh.HT - ht * 1e-3) < 1e-9, (size, sh.HT)
        # the coating always costs bore, never adds it
        assert 0 < sh.ID_coated < sh.ID < sh.OD
        # A_e ~ (OD-ID)/2*Ht and l_e ~ pi*(OD+ID)/2, times a stacking factor.
        # The catalogue quotes EFFECTIVE values, so the ratios sit at 0.94-0.98
        # rather than 1.0; the point of the check is that an OD/ID/Ht mix-up in
        # the parse breaks both, and cannot break neither. Calibrated below.
        assert 0.93 < sh.A_e / ((sh.OD - sh.ID) / 2 * sh.HT) < 1.00, size
        assert 0.94 < sh.l_e / (math.pi * (sh.OD + sh.ID) / 2) < 1.00, size

    # Calibrate that pair against the failure it exists to catch: a shape whose
    # OD and ID were read in the wrong order. A guard never seen to fire is not
    # a guard, and this one is the only thing standing between a mis-parsed
    # catalogue column and a plausible-looking core.
    swapped = cores.ToroidShape('swapped', l_e=cores.MicrometalsT250.l_e,
                                A_e=cores.MicrometalsT250.A_e,
                                Vol=cores.MicrometalsT250.Vol,
                                od=cores.MicrometalsT250.ID,   # <- swapped
                                id=cores.MicrometalsT250.OD,
                                ht=cores.MicrometalsT250.HT)
    assert not (0.93 < swapped.A_e / ((swapped.OD - swapped.ID) / 2 * swapped.HT) < 1.00)
    # ...and an OD/Ht swap, which leaves OD > ID intact and so slips past a
    # naive ordering check
    od_ht = cores.ToroidShape('od_ht', l_e=cores.MicrometalsT250.l_e,
                              A_e=cores.MicrometalsT250.A_e,
                              Vol=cores.MicrometalsT250.Vol,
                              od=cores.MicrometalsT250.HT * 2.5,
                              id=cores.MicrometalsT250.ID * 0.5,
                              ht=cores.MicrometalsT250.OD)
    assert not (0.94 < od_ht.l_e / (math.pi * (od_ht.OD + od_ht.ID) / 2) < 1.00)

    # T130's Vol was T132's (5.69e-6). A_e*l_e disagreed by 3.8%, which is
    # INSIDE ToroidShape's 0.9..1.1 consistency assert -- the guard could not
    # see it. Pin the value itself, not just the ratio.
    assert abs(cores.MicrometalsT130.Vol - 5.48e-6) < 1e-9
    assert abs(cores.MicrometalsT132.Vol - 5.69e-6) < 1e-9

    # A_L from geometry vs the catalogue's own nH/N^2 (MS 125u)
    for size, a_l_cat_nh in ((250, 430), (184, 281), (226, 288)):
        core = cores.MicrometalsToroid('MS', 125, size)
        assert abs(core.A_L * 1e9 / a_l_cat_nh - 1) < 0.04, (size, core.A_L)

    # the coated bore is what a winding fits through, and it is load-bearing:
    # T250 at 15 turns takes 7 strands on the bare bore and only 6 on the real
    # one, which is the difference between two competing designs
    from maglib.winding import max_strands
    t250 = cores.MicrometalsToroid('MS', 125, 250)
    assert max_strands(cores.MicrometalsT250.ID, 1.909e-3, 15) == 7   # bare
    assert max_strands(t250.winding_bore()[0], 1.909e-3, 15) == 6     # real
    assert max_strands(t250.winding_bore()[0], 1.909e-3, 14) == 7
    # winding_geometry() must hand back ALL THREE coated dimensions. Returning
    # a subset is what let a coated ID/OD be combined with a BARE height, which
    # left mean_turn_length 1.6-2.9% short -- optimistic, and larger than the
    # error that adding the coated OD had just fixed.
    assert t250.winding_geometry() == (cores.MicrometalsT250.ID_coated,
                                       cores.MicrometalsT250.OD_coated,
                                       cores.MicrometalsT250.HT_coated)
    assert t250.winding_bore() == t250.winding_geometry()[:2]
    assert cores.MicrometalsT250.OD_coated > cores.MicrometalsT250.OD
    assert cores.MicrometalsT250.HT_coated > cores.MicrometalsT250.HT

    # KDM's KS184 sheet is a scan; its OCR'd "After Coating" ID(Min) agrees
    # with Micrometals T184 to the digit, which is the reason it is trusted
    assert cores.KDM_KS184.ID_coated == cores.MicrometalsT184.ID_coated == 23.32e-3
    assert cores.KDM_KS184.OD_coated == cores.MicrometalsT184.OD_coated == 47.63e-3
    assert cores.KDM_KS184.HT_coated == cores.MicrometalsT184.HT_coated == 18.92e-3
    # The OD agreement is weaker evidence than it looks -- 47.63 mm is 1.875 in
    # exactly, a round fraction any vendor lands on. The ID(min) agreement at
    # 23.32 mm = 0.918 in is the one that is hard to reach by coincidence.
    assert cores.KDM_KS184_125A.winding_bore() == (23.32e-3, 47.63e-3)

    # unknown coated ID must REFUSE, not fall back to the bare ID: the fallback
    # errs toward claiming a strand that does not physically fit
    unknown = cores.MagneticCoreSpecs(
        'unknown-coating', cores.KDM_SendustKS_60,
        shape=cores.ToroidShape('nc', l_e=8.15e-2, A_e=0.672e-4, Vol=5.48e-6,
                                od=33.02e-3, id=19.94e-3, ht=10.67e-3))
    with pytest.raises(ValueError, match='coated'):
        unknown.winding_bore()
    # a shape with two of the three coated dims must still refuse, and name the
    # missing one -- a partial set is what produced the bare-HT mix
    partial = cores.MagneticCoreSpecs(
        'partial-coating', cores.KDM_SendustKS_60,
        shape=cores.ToroidShape('pc', l_e=8.15e-2, A_e=0.672e-4, Vol=5.48e-6,
                                od=33.02e-3, id=19.94e-3, ht=10.67e-3,
                                id_coated=19.30e-3, od_coated=33.83e-3))
    with pytest.raises(ValueError, match='ht_coated'):
        partial.winding_geometry()
    # ...and the shape-less cores still fail on the earlier, coarser check
    with pytest.raises(ValueError, match=cores.KDM_KS130_060A.mpn):
        cores.KDM_KS130_060A.winding_bore()

    # stacking is axial: the bore does not change, which is exactly why
    # stacking cannot buy strands
    assert cores.MicrometalsT250.stack(3).ID_coated == cores.MicrometalsT250.ID_coated
    assert cores.MicrometalsT250.stack(3).OD_coated == cores.MicrometalsT250.OD_coated
    # ...but the coated HEIGHT is axial and must scale, exactly like HT
    assert cores.MicrometalsT250.stack(3).HT_coated == 3 * cores.MicrometalsT250.HT_coated
    assert cores.MicrometalsT250.stack(3).HT == 3 * cores.MicrometalsT250.HT


def test_micrometals_size_dependent_coefficients():
    """Micrometals splits several materials' curve fits at an OD threshold.

    ``micrometals.csv`` holds 16 rows whose PartType is size-qualified
    (``T(OD=5.22-6.00 in)``). The lookup matched ``PartType == 'T'`` exactly, so
    not one of them was reachable and every caller got the SMALL-size fit
    regardless of core size. The error is one-directional -- the small-size fit
    is the optimistic one, less loss and more retained permeability -- so a
    sweep ranking cores by loss promoted exactly the large cores it was getting
    wrong, with nothing surfacing as an error.
    """
    import pytest
    from maglib import materials as M

    assert M._part_type_od_range('T') == ('T', 0.0, math.inf)
    shape, lo, hi = M._part_type_od_range('T(OD=5.22-6.00 in)')
    assert shape == 'T' and 0.132 < lo < 0.133 and 0.152 < hi < 0.153

    # T520 is 132.54 mm = 5.2181 in against a stated band start of 5.22 in.
    # Strict comparison drops it out of its own band and back onto the
    # small-size fit -- calibrate that the tolerance actually catches it.
    assert lo <= 132.54e-3 <= hi
    assert not (5.22 * 25.4e-3 <= 132.54e-3)     # ...which a strict bound would fail

    # ambiguous without an OD must REFUSE, not silently pick one
    with pytest.raises(M.AmbiguousMaterialSize):
        M.micrometals_material('MS', 'T', 125)
    # and must not be swallowed by a sweep's `except MaterialNotFound: continue`
    assert not issubclass(M.AmbiguousMaterialSize, M.MaterialNotFound)

    # direction: the small-size fit really is the flattering one
    small = M.micrometals_material('MS', 'T', 125, od=46.74e-3)    # T184
    large = M.micrometals_material('MS', 'T', 125, od=132.54e-3)   # T520
    assert large.dc_bias(H_oe=30) < small.dc_bias(H_oe=30)
    assert abs(rel_err(large.dc_bias(H_oe=30), small.dc_bias(H_oe=30))) > 0.1

    # unambiguous materials keep working with no OD at all (back-compat)
    assert M.micrometals_material('MS', 'T', 60).mu_r == 60

    # A core LARGER than every band must refuse. The unqualified row is the
    # small-size fit; treating it as an unbounded catch-all would serve the
    # optimistic coefficients to the biggest cores of all, which is the same
    # anti-monotone failure in a new place. MS 125u tops out at T600 (152.4 mm).
    for oversize in (0.30, 2.0):
        with pytest.raises(M.MaterialNotFound, match='none of the coefficient bands'):
            M.micrometals_material('MS', 'T', 125, od=oversize)
    # ...while a core below the split still gets the small-size fit, as it should
    assert M.micrometals_material('MS', 'T', 125, od=33.02e-3).dc_bias(H_oe=30) \
        == small.dc_bias(H_oe=30)

    # MicrometalsToroid supplies the OD from the shape, so cores pick their own
    # band; T184 and T250 are both below every MS split, T250 deliberately so
    for size in (184, 250):
        core = cores.MicrometalsToroid('MS', 125, size)
        assert core.mat.dc_bias(H_oe=30) == small.dc_bias(H_oe=30), size

    # OC 125u is documented as splitting at T250, but the CSV carries NO
    # qualified row for it -- so this fix does not correct OC at 250 and up.
    # Pinned so the gap is not mistaken for a fixed one; closing it needs the
    # per-part datasheet coefficients, not a lookup change.
    df = M.load_micrometals_materials()
    qualified = {(r[0], int(r[2])) for r in
                 df[df.iloc[:, 1].astype(str).str.startswith('T(')].values}
    assert ('MS', 125) in qualified and ('MP', 125) in qualified
    assert ('OC', 125) not in qualified, 'OC 125u large-size row landed -- ' \
        'drop this assert and re-check the T250-and-up OC numbers'


def test_wound_pass_count_is_not_monotone_in_turns():
    """More turns does NOT mean a worse winding fit. Pinning the counterexample.

    A turns sweep that hits a fit failure is tempting to ``break`` out of, on
    the reasoning that more turns can only fit worse. It is false: the wound
    pass count is ``n * floor(passes / n)``, a step function that OSCILLATES --
    50 turns wind 100 passes, 51 turns wind 51. Acting on the false version
    deleted 40,433 of 42,445 candidates from apps/inductor_core_sweep.py at
    --fill 0.40 --packing 0.45, silently, taking the whole top 10 with it, and
    cost exactly nothing at the DEFAULT packing -- so no amount of
    default-value testing could have found it.
    """
    from maglib.winding import max_strands

    core_id, wire_od = 31.37e-3, 1.909e-3        # T250 coated bore, 1.8 mm G2
    wound = [n * max_strands(core_id, wire_od, n, 0.4) for n in range(1, 109)]
    assert wound[0] == 108, wound[0]             # the bore's whole pass budget

    # If it were monotone non-increasing no later entry could exceed an
    # earlier one. It does, repeatedly.
    rises = [(n + 1, wound[n - 1], wound[n]) for n in range(1, len(wound))
             if wound[n - 1] < wound[n]]
    assert len(rises) > 10, rises

    # The sharpest single step: 54 turns wind the full 108 passes, 55 turns
    # wind 55 -- and yet n=56..108 climb back to 108 again. A fit failure
    # anywhere in that valley says nothing whatsoever about larger n.
    assert wound[53] == 108 and wound[54] == 55
    assert max(wound[54:]) == 108


def test_micrometals_per_part_coefficients():
    """Every per-part row must reproduce its own datasheet's printed numbers.

    micrometals_parts.csv is machine-extracted from 804 datasheet PDFs, so the
    interesting failure is not "a row is missing" but "a row is subtly wrong" --
    a mis-parsed exponent produces a completely plausible material. Each
    datasheet prints a calibration point computed from the same coefficients
    (Core Loss nominal at a stated Bpk/f, %Initial Perm nominal at a stated
    H_DC), so every row can check itself. This runs that check on the shipped
    data rather than trusting that it passed once during extraction.
    """
    from maglib import materials as M

    df = M.load_micrometals_parts()
    assert len(df) > 700, len(df)

    worst_cl = worst_perm = 0.0
    for _, r in df.iterrows():
        mat = M.micrometals_part_material(r['part'])
        cl = mat.core_loss_density(Bpk_tesla=r['cal_bpk_g'] * 1e-4,
                                   f_khz=r['cal_f_khz'])
        perm = mat.dc_bias(H_oe=r['cal_h_oe']) * 100
        worst_cl = max(worst_cl, abs(cl / r['cal_cl_nom_mw_cm3'] - 1))
        worst_perm = max(worst_perm, abs(perm / r['cal_perm_nom_pct'] - 1))
    assert worst_cl < 0.02, worst_cl
    assert worst_perm < 0.02, worst_perm
    # the extraction really is tight, not just inside a loose bound
    assert worst_cl < 0.005 and worst_perm < 0.005, (worst_cl, worst_perm)

    # Calibrate: a mangled coefficient must FAIL that check, or it is not a
    # check. One decade on the core-loss 'a' term is a realistic parse slip.
    bad = M.micrometals_core_loss_model(1.394e11, 1.034e09, 1.244e07, 4.007e-14)
    assert abs(bad(Bpk_tesla=0.1, f_khz=50) / 276.0 - 1) > 0.02

    # The reason this file exists: OC 125u splits at exactly T250 and
    # micrometals.csv has no qualified row to express it, so the band model
    # serves the small-size fit to a T250 core. Per-part fixes it; pin both the
    # fix and the fact that the small sizes did NOT move.
    import pytest
    t250 = cores.MicrometalsToroid('OC', 125, 250)
    t184 = cores.MicrometalsToroid('OC', 125, 184)
    band250 = M.micrometals_material('OC', 'T', 125, od=t250.shape.OD)
    band184 = M.micrometals_material('OC', 'T', 125, od=t184.shape.OD)
    at = dict(Bpk_tesla=0.04, f_khz=40)
    assert t250.mat.core_loss_density(**at) / band250.core_loss_density(**at) > 1.3
    assert t250.mat.dc_bias(H_oe=30) < 0.9 * band250.dc_bias(H_oe=30)
    assert t184.mat.core_loss_density(**at) == band184.core_loss_density(**at)
    assert t184.mat.dc_bias(H_oe=30) == band184.dc_bias(H_oe=30)

    # The self-check above proves each row is INTERNALLY coherent. It cannot
    # prove the block belongs to the part it is keyed under: swapping two
    # rows' coefficients AND calibration together passes it untouched, and
    # that mis-keying is 78% wrong at the operating point. So check the key
    # against the row, and that no two rows are interchangeable.
    for _, r in df.iterrows():
        fam, rest = r['part'].split('-')[0], r['part'].split('-')[1]
        assert fam == r['fam'], r['part']
        assert rest[:3] == r['size'], r['part']
        assert int(rest[3:]) == int(r['ui']), r['part']
        assert r['part'].endswith('-2') or r['part'].endswith('-8'), r['part']
    # Sharing a calibration fingerprint is legal and common (same material and
    # permeability in several sizes). What must NOT happen is two rows sharing
    # a fingerprint while carrying DIFFERENT coefficients -- that is precisely
    # the pair a whole-row swap could exchange undetected.
    grouped = df.groupby(['cal_bpk_g', 'cal_f_khz', 'cal_cl_nom_mw_cm3',
                          'cal_h_oe', 'cal_perm_nom_pct'])
    for _, g in grouped:
        coefs = g[['cl_a', 'cl_b', 'cl_c', 'cl_d',
                   'ds_a', 'ds_b', 'ds_c', 'ds_d']].drop_duplicates()
        assert len(coefs) == 1, 'interchangeable rows: %s' % list(g['part'])

    # The fingerprint check above still cannot catch a WHOLE-ROW swap, because
    # moving coefficients and calibration together leaves both rows internally
    # coherent. Catching that needs an anchor OUTSIDE the row: the band fit for
    # the same (material, permeability). It is stale enough to disagree by up
    # to 41%, but not arbitrarily -- so a row whose coefficients belong to a
    # different material lands outside the legitimate spread.
    at = dict(Bpk_tesla=0.04, f_khz=40)
    ratios = []
    for _, r in df.iterrows():
        size = int(r['size'])
        if size not in cores.MicrometalsToroidShapes:
            continue
        try:
            band = M.micrometals_material(
                r['fam'], 'T', int(r['ui']),
                od=cores.MicrometalsToroidShapes[size].OD)
        except (M.MaterialNotFound, M.AmbiguousMaterialSize):
            continue
        part = M.micrometals_part_material(r['part'])
        ratios.append((part.core_loss_density(**at) / band.core_loss_density(**at),
                       r['part']))
    assert len(ratios) > 300, len(ratios)
    for ratio, part in ratios:
        assert 0.55 < ratio < 1.50, (part, ratio)

    # Calibrate that bound against the exact failure it exists to catch: the
    # OC-250090-2 row (rank #1 in a real sweep) carrying MS-130060-2's
    # coefficients. Internally self-consistent, 78% wrong at the operating
    # point, and invisible to every check above this one.
    mis_keyed = M.micrometals_part_material('MS-130060-2')
    band_oc = M.micrometals_material(
        'OC', 'T', 90, od=cores.MicrometalsToroidShapes[250].OD)
    bad_ratio = mis_keyed.core_loss_density(**at) / band_oc.core_loss_density(**at)
    assert not (0.55 < bad_ratio < 1.50), bad_ratio

    # provenance must be carried, not inferred: the band fit is optimistic
    # (up to 35% low on core loss), so a caller ranking cores by loss has to
    # be able to tell which coefficients it got
    assert M.micrometals_part_material('MS-250125-2').coef_source == 'datasheet'
    assert M.micrometals_material('MS', 'T', 125, od=46.74e-3).coef_source == 'band'
    assert cores.MicrometalsToroid('MS', 125, 250).mat.coef_source == 'datasheet'
    # GX has no per-part rows at all, so it can only come from the band --
    # this is the case that silently held rank #2 in a loss sweep
    assert 'GX' not in set(df['fam'])
    assert cores.MicrometalsToroid('GX', 125, 250).mat.coef_source == 'band'

    # a part with no datasheet row must refuse, not fall through to nan
    with pytest.raises(M.PartNotFound):
        M.micrometals_part_material('MS-999999-2')

    # dc_magnetization is not printed as coefficients, so a bare per-part
    # material must RAISE on it rather than return nan (which reads as zero)
    bare = M.micrometals_part_material('MS-250125-2')
    with pytest.raises(Exception):
        bare.dc_magnetization(H_oe=10)
    # ...but MicrometalsToroid supplies it from the band model
    assert cores.MicrometalsToroid('MS', 125, 250).mat.dc_magnetization is not None


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

    # The KDM KS184 carries its own datasheet dimensions, not the T184 clone's:
    # bare 24.11/46.70 as published...
    assert abs(rel_err(cores.KDM_KS184.ID, 24.11e-3)) < 1e-9
    assert abs(rel_err(cores.KDM_KS184.OD, 46.7e-3)) < 1e-9
    # ...but winding_bore() hands back the COATED pair, because that is what a
    # winding meets. This assertion used to pin the bare bore as correct, which
    # made the optimistic geometry the default for every caller including
    # dclib/powerloss's proximity term.
    core_id, core_od = cores.KDM_KS184_125A.winding_bore()
    assert (core_id, core_od) == (23.32e-3, 47.63e-3)
    wire = enameled_od(1.8e-3, 2)
    # 63 passes fit the bare bore, 59 the real one. At 16 turns both give 3
    # strands, so a check at one turns count proves nothing either way; the
    # difference bites where the floor divides differently.
    assert max_strands(cores.KDM_KS184.ID, wire, 16, 0.4) == 3
    assert max_strands(core_id, wire, 16, 0.4) == 3
    for turns, bare_strands, real_strands in ((15, 4, 3), (20, 3, 2)):
        assert max_strands(cores.KDM_KS184.ID, wire, turns, 0.4) == bare_strands
        assert max_strands(core_id, wire, turns, 0.4) == real_strands

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

    # Every assertion above passes hardcoded id/od, so no test ever drove this
    # from a real core -- which is how switching winding_bore() to the coated
    # dimensions moved this consumer's numbers unnoticed. Pin one real core.
    #
    # Note the DIRECTION, because it is the opposite of the intuition: b_eq
    # depends on the SUM ID+OD, and coating shrinks the bore ~0.9 mm while
    # growing the OD ~1.3 mm, so the sum RISES and the proximity factor FALLS
    # ~0.76%. "Coated is the pessimistic choice" holds for winding FIT, which
    # depends on ID alone; it does not transfer to a different function of the
    # same two numbers.
    core = cores.MicrometalsToroid('MS', 125, 250)
    core_id, core_od = core.winding_bore()
    coated = sum(acr_factor_micrometals(23e-9, 1.8e-3, 40e3, 7, 15, core_id, core_od))
    bare = sum(acr_factor_micrometals(23e-9, 1.8e-3, 40e3, 7, 15,
                                      core.shape.ID, core.shape.OD))
    assert 0.985 < coated / bare < 0.996, (coated, bare, coated / bare)
    assert 10 < coated < 15, coated

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


def test_ks184_125a_dc_bias_against_flu_bench():
    """KDM_KS184_125A + 17 turns, checked against a BENCH MEASUREMENT of flu's inductor.

    This is the first hardware validation of a core model in this library: everything else in
    this file is vendor-traceable (datasheet against model), which says the arithmetic is right,
    not that the physics is. Here the model is checked against a converter running on a bench.

    HOW THE MEASUREMENT WAS MADE, because that is what makes it admissible. A Rogowski coil
    (PEM CWT UM/06) around the low-side drain lead of dcdc-tools' `flu` buck. The coil is
    AC-coupled and therefore CANNOT read DC -- but the STEP across the switch-node edge is
    exactly the inductor valley current, and a step is a level difference, immune to the
    integration/window defects that invalidated the charge results from the same captures
    (dcdc-tools verifications/loaded-capture/RESULTS-*-20260816.md). L then follows from
    L = Vout*(1-D)/(dI*fsw) with dI = 2*(I_out - I_valley).

    Agreement is 0.3% at the bottom widening to 9% at the top, and the residual has the right
    SIGN and the right GROWTH: the datasheet law gives L at the DC bias, while the measurement
    averages over a ripple that dips into higher-permeability territory, and that ripple itself
    grows 5.5 -> 8.4 A across these rungs. The +-8% A_L tolerance covers the rest. So the
    tolerance below is 12%, not 1% -- tightening it would be pinning the measurement's own
    method error as if it were the model's.
    """
    from maglib.cores import KDM_KS184_125A as core

    N = 17
    L0 = N * N * core.A_L
    assert abs(L0 - 81.2e-6) < 0.5e-6, f"L(0)={L0*1e6:.1f} uH, expected 281 nH * 17^2"

    # (I_out [A], L measured [uH]) -- dcdc-tools flu, counts 829/832/838/844, 2026-08-16
    bench = [(6.09, 72.7), (8.93, 67.2), (14.39, 56.2), (19.39, 46.9)]
    for i_out, l_meas_uh in bench:
        h = N * i_out / core.l_e                      # A/m
        mu = core.mat.permeability_dc_bias(h, no_raise=True)
        l_pred_uh = L0 * (mu / core.mat.mu_r) * 1e6
        rel = abs(l_meas_uh - l_pred_uh) / l_pred_uh
        assert rel < 0.12, (
            f"I_out={i_out} A: maglib {l_pred_uh:.1f} uH vs bench {l_meas_uh:.1f} uH "
            f"({rel*100:.0f}% off)")
        # The measurement must not come out BELOW the DC-bias prediction: averaging over the
        # ripple can only sample higher permeability, never lower.
        assert l_meas_uh >= l_pred_uh * 0.99, (
            f"I_out={i_out} A: bench {l_meas_uh:.1f} uH is below the DC-bias prediction "
            f"{l_pred_uh:.1f} uH -- ripple averaging cannot do that, so one of them is wrong")


def test_ks184_125a_reproduces_its_own_datasheet_dc_bias_point():
    """The KDM sheet's own DC-bias row, which the flu check leans on indirectly.

    'phi 0.8mm/57Ts, 20kHz/1V, Idc=7.5A (Hdc=50Oe) -> 344.4 uH (Min.)', against a stated
    L(0) of 913.0 uH +-8%. Two independent things are pinned:

      * the H conversion -- 57 turns at 7.5 A over l_e must land on the sheet's own 50 Oe, which
        is what licenses using N*I/l_e everywhere else here;
      * the bias law itself, whose typical must sit ABOVE a Min. figure but not absurdly so.
    """
    from maglib.cores import KDM_KS184_125A as core
    from maglib import H2oe

    n_ds, i_ds = 57, 7.5
    l0 = n_ds * n_ds * core.A_L
    assert abs(l0 - 913.0e-6) < 5e-6, f"L(0)={l0*1e6:.1f} uH vs the sheet's 913.0 uH"

    h = n_ds * i_ds / core.l_e
    assert abs(H2oe(h) - 50.0) < 0.5, f"H={H2oe(h):.2f} Oe, the sheet says 50 Oe"

    mu = core.mat.permeability_dc_bias(h, no_raise=True)
    l_typ = l0 * (mu / core.mat.mu_r)
    assert l_typ > 344.4e-6, f"typical {l_typ*1e6:.1f} uH must exceed the 344.4 uH Min."
    assert l_typ < 344.4e-6 * 1.35, (
        f"typical {l_typ*1e6:.1f} uH is more than 35% above the Min. -- the bias law or A_L "
        f"is wrong, not merely conservative")
