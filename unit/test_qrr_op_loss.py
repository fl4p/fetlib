"""Wiring tests for the operating-point Qrr path in dcdc_buck_ls (--qrr-op).

The model itself is covered by unit/test_qrr_model.py. What is tested HERE is the
wiring, which is where this class of change usually dies quietly:

  * the flag reduces to a no-op at the datasheet's own test point (calibration —
    a rescale that does not reproduce its anchor is not a rescale);
  * it moves the number in the right DIRECTION, and by how much, at a real
    converter's di/dt;
  * a part with no curated conditions keeps the flat value but is LABELLED as such,
    so a CSV can never mix the two silently;
  * the commutation di/dt is the current-RISE phase, not the whole tr;
  * and specs built the way the pipeline builds them (dslib.field.get_mosfet_specs,
    NOT dslib.store.load_parts) actually carry the registries — without that the
    whole feature degrades to the flat value for 100% of parts while appearing to work.

Run:  python3 -m pytest unit/test_qrr_op_loss.py   (or execute directly)
"""
import math
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from dclib.powerloss import (dcdc_buck_hs, dcdc_buck_ls, ls_commutation_didt, GateLoopInfeasible,
                             mosfet_hs_current_rise_time, mosfet_hs_sw_timings_hs2)
from dslib.field import DatasheetFields, Field
from dslib.mosfet import GateDrive, MosfetSpecs, attach_qrr_registries, qrr_part_key
from dslib.spec_models import DcDcLoadParams

# IPP022N12NM6 (120 V OptiMOS 6). Its datasheet quotes Qrr at TWO di/dt points, so it
# exercises the per-part 2pt fit; the single-point conditions are curated as the fallback.
# Qrr=155.2 nC / trr=46.3 ns at IF=50 A, di/dt=300 A/us, VR=60 V, Tj=25 C.
MPN, MFR = "IPP022N12NM6", "infineon"
DS_QRR, DS_TRR, DS_IF, DS_DIDT = 155.2e-9, 46.3e-9, 50.0, 300e6

# Io/ripple chosen so the VALLEY current — what the body diode actually carries through
# the dead time, and therefore the IF the model is evaluated at — lands exactly on the
# datasheet's 50 A row. That is what makes the calibration test below an identity.
DC = DcDcLoadParams(vi=72, vo=27, f=40e3, io=60.0, ripple_factor=1 / 3, tDead=100e-9)
GD = GateDrive(rg_total=6, rg_total_dis=3, Von=11, Voff=0, fallback_V_pl=4.5)


def _specs(qrr=DS_QRR, trr=DS_TRR, registries=True, **kw):
    args = dict(Vds_max=120, Rds_on=2.2e-3, Qg=100e-9, tRise=10e-9, tFall=15e-9,
                Qrr=qrr, trr=trr, Qgd=15e-9, Qgs=30e-9, Qg_th=15e-9, Vpl=5.0, Vsd=0.9,
                Coss=1000e-12, Coss_Vds=60, Rg=1.5, Id=100,
                part=SimpleNamespace(mpn=MPN, mfr=MFR))
    args.update(kw)
    mf = MosfetSpecs(**args)
    return attach_qrr_registries(mf, MFR, MPN) if registries else mf


def test_calibration_point_reproduces_the_datasheet_minus_the_capacitive_share():
    """At the datasheet's own (IF, di/dt) the operating-point path must reproduce the
    datasheet charge — minus q0, the junction displacement charge that P_coss already
    books for this same part. Calibrating only that the flag "changes something" would
    pass just as well if it changed it in the wrong direction or by a wrong scale.

    The measured-equivalent headline (diffusion + q0) is what must equal the datasheet
    number; the BOOKED charge is deliberately smaller by exactly q0."""
    mf = _specs()
    flat = dcdc_buck_ls(DC, mf, gd=GD)
    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=DS_DIDT)

    assert abs(DC.Io_min - DS_IF) < 1e-9, DC.Io_min      # the identity's precondition
    assert flat.get_cond('P_rr')['Qrr_src'] == 'datasheet-flat-decontaminated'
    assert op.get_cond('P_rr')['Qrr_src'] == 'op-2pt'

    # the headline the model would rank on still lands on the datasheet row exactly
    head = mf.Qrr_op(IF=DS_IF, didt=DS_DIDT, detail=True)
    assert abs(head['Qrr'] / DS_QRR - 1) < 1e-6, head['Qrr']
    q0 = head['q0']
    assert q0 > 0, 'the 2pt fit must solve a positive capacitive share here'
    # ... and both paths book their own explicitly decontaminated charge. The flat
    # path uses the calibrated global q0 fraction; the 2pt path solves this die's q0.
    flat_q0 = flat.get_cond('P_rr')['Qrr_q0']
    assert flat_q0 > 0
    assert abs(op.P_rr / flat.P_rr
               - (DS_QRR - q0) / (DS_QRR - flat_q0)) < 1e-6
    assert op.get_cond('P_rr')['Qrr_decont'] is True
    assert abs(op.get_cond('P_rr')['Qrr_q0'] - q0) < 1e-18
    assert op.get_cond('P_rr')['Qrr_q0_basis'] == 'two-point-Qrr-fit'
    assert op.get_cond('P_rr')['Qrr_double_booking'] == 'exactly-once'
    assert op.get_cond('P_rr')['Qrr_qoss_vr'] is not None
    # attach_qrr_registries also attaches the curated Coss curve (IPP022N12NM6 is in
    # the registry), so the flat-path subtraction here is curve-backed — which is
    # exactly what keeps it legitimate under the curve-gate.
    assert op.get_cond('P_rr')['Qrr_qoss_model_state'] == 'datasheet-coss-curve'
    assert op.get_cond('P_rr')['Qrr_qoss_provenance']


def test_booked_charge_excludes_what_p_coss_already_books():
    """The double-count this fix exists to kill: the datasheet Qrr integral contains
    junction displacement charge, and dcdc_buck_ls books the LS Coss loss separately
    (doubled) a few lines below. Booking the measured-equivalent charge in P_rr would
    charge that share twice."""
    mf = _specs()
    d = mf.Qrr_op(IF=DC.Io_min, didt=5.7e9, detail=True)
    assert d['qrr_diffusion'] < d['Qrr']                  # they are different numbers
    assert abs(d['Qrr'] - d['qrr_diffusion'] - d['q0']) < 1e-18

    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=5.7e9)
    booked = op.get_cond('P_rr')['Qrr'] / 1.2            # undo the Tj factor
    assert abs(booked - d['qrr_diffusion']) < 1e-18, (booked, d['qrr_diffusion'])

    # 1pt with no Coss to work from: nothing is subtracted, and it says so rather than
    # implying a decontamination happened.
    bare = _specs(registries=False, Coss=math.nan, Coss_Vds=None)
    bare.qrr_cond = dict(IF=DS_IF, didt=DS_DIDT, Tj=25.0, VR=60.0)
    d1 = bare.Qrr_op(IF=DC.Io_min, didt=5.7e9, detail=True)
    assert d1['method'] == '1pt'
    assert d1['q0'] == 0.0 and d1['decontaminated'] is False
    assert d1['qrr_diffusion'] == d1['Qrr']


def test_qrr_op_delegates_the_calibration_and_does_not_re_derive_it():
    """Qrr_op must DELEGATE to qrr_model.best_lm_fit, not re-implement it.

    It once re-derived all three of that function's decisions — the 2pt-vs-1pt
    preference, the q0 decontamination, and the Qrr(Tj) exponent — which is exactly the
    divergence best_lm_fit was written to close: the dcdc-tools deck emitter calibrates
    off the same call, so a second copy here can silently fit a DIFFERENT diode than the
    deck it is supposed to agree with, and nothing downstream would look wrong.

    Pinned behaviourally rather than by scanning the source: whatever Qrr_op returns must
    equal best_lm_fit + evaluate_lm_fit on the same inputs, on every branch. Evaluated at
    Tj != the fit Tj on purpose, so a separately-resolved n_tau would show up as a
    different charge rather than only as a different stamp."""
    from dslib import qrr_model as qm

    two_pt = _specs()                                   # curated rows -> 2pt
    one_pt = _specs(registries=False)                   # conditions only -> 1pt
    one_pt.qrr_cond = dict(IF=DS_IF, didt=DS_DIDT, Tj=25.0, VR=60.0)
    # An AO die is REQUIRED here, not decoration: every infineon part resolves to the
    # conservative bound, which is also what a re-derivation would land on by default —
    # so an infineon-only check cannot see the exponent diverge at all.
    ao = _specs()
    ao.part = SimpleNamespace(mpn='AONS66811', mfr='ao')

    for label, mf, qoss in (('2pt', two_pt, None),
                            ('1pt', one_pt, None),
                            ('1pt+qoss', one_pt, 267e-9),
                            ('2pt-measured-n_tau', ao, None)):
        got = mf.Qrr_op(IF=33.3, didt=5.7e9, Tj=100.0, detail=True, qoss_vr=qoss)
        fit = qm.best_lm_fit(mf.Qrr, mf.trr, getattr(mf, 'qrr_cond', None),
                             qrr_points=getattr(mf, 'qrr_points', None),
                             qoss_vr=qoss, part=qrr_part_key(mf))
        want = qm.evaluate_lm_fit(fit, 33.3, 5.7e9, Tj=100.0)
        for k in ('Qrr', 'qrr_diffusion', 'q0', 'decontaminated', 'method',
                  'tau', 'n_tau', 'n_tau_state'):
            assert got[k] == want[k], (label, k, got[k], want[k])

    # the fit cache must not collapse a decontaminated request onto a raw one
    raw = one_pt.Qrr_op(IF=33.3, didt=5.7e9, detail=True)
    dec = one_pt.Qrr_op(IF=33.3, didt=5.7e9, detail=True, qoss_vr=267e-9)
    assert raw['q0'] == 0.0 and dec['q0'] > 0.0
    assert dec['qrr_diffusion'] < raw['qrr_diffusion']


def test_qrr_factor_derates_only_the_reverse_recovery():
    """syncFet.reverseRecoveryFactor. 1.0 must be a no-op (every shipped config uses it),
    a fraction must scale P_rr and NOTHING else, and the de-rating must be visible —
    a halved P_rr that looks like the part's own charge would flatter it in the CSV."""
    mf = _specs()
    full = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=5.7e9)
    assert dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=5.7e9, qrr_factor=1.0).P_rr == full.P_rr
    assert 'qrr_factor' not in full.get_cond('P_rr')      # no note when nothing happened

    half = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=5.7e9, qrr_factor=0.5)
    assert abs(half.P_rr / full.P_rr - 0.5) < 1e-12
    assert half.get_cond('P_rr')['qrr_factor'] == 0.5
    for attr in ('P_cl', 'P_gd', 'P_coss', 'P_dt'):
        assert getattr(half, attr) == getattr(full, attr), attr

    # it de-rates the flat path too, not just the model path
    assert abs(dcdc_buck_ls(DC, mf, gd=GD, qrr_factor=0.25).P_rr
               / dcdc_buck_ls(DC, mf, gd=GD).P_rr - 0.25) < 1e-12
    # out-of-range is a config error, not a silent clamp
    for bad in (-0.1, 1.5):
        try:
            dcdc_buck_ls(DC, mf, gd=GD, qrr_factor=bad)
        except AssertionError:
            pass
        else:
            raise AssertionError('qrr_factor=%r must be rejected' % bad)


def test_tj_exponent_resolves_per_part_not_always_the_bound():
    """dslib/qrr_tj_specs.py's measured AO exponents were unreachable from Qrr_op: both
    qrr_model entries defaulted n_tau to the conservative bound and nothing passed
    anything else, so a die with its own 25/125 C chart was still extrapolated on the
    legacy 'Qrr doubles' rule. Calibrate that it now resolves AND that it bites."""
    from dslib import qrr_model
    mf = _specs()
    d = mf.Qrr_op(IF=DC.Io_min, didt=5.7e9, Tj=125.0, detail=True)
    assert d['n_tau_state'] == 'conservative-bound'       # infineon: no measured data
    assert d['n_tau'] == qrr_model.N_TAU

    # an AO die resolves to the family pool, and a LOWER exponent must predict LESS
    # hot charge — the direction is the point, not merely that a different number rode along
    ao = _specs()
    ao.part = SimpleNamespace(mpn='AONS66811', mfr='ao')
    d_ao = ao.Qrr_op(IF=DC.Io_min, didt=5.7e9, Tj=125.0, detail=True)
    assert d_ao['n_tau_state'] == 'ao-family-pool'
    assert d_ao['n_tau'] < qrr_model.N_TAU
    assert d_ao['Qrr'] < d['Qrr'], (d_ao['Qrr'], d['Qrr'])
    # and at the calibration Tj the exponent cannot matter at all
    assert (ao.Qrr_op(IF=DC.Io_min, didt=5.7e9, Tj=25.0)
            == mf.Qrr_op(IF=DC.Io_min, didt=5.7e9, Tj=25.0))


def test_converter_didt_raises_the_charge_and_the_loss():
    """A tight-loop converter commutates ~10-20x faster than the datasheet test, and
    Qrr grows with di/dt (exponent ~0.8) — so the loss must go UP, not down. A model
    that made P_rr fall here would be flattering every part in the ranking."""
    mf = _specs()
    flat = dcdc_buck_ls(DC, mf, gd=GD)
    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=5.7e9)

    assert op.P_rr > flat.P_rr
    ratio = op.P_rr / flat.P_rr
    assert 1.5 < ratio < 12, ratio    # sanity band, not a precision claim
    # and it is monotone along the axis: faster commutation, more charge
    mid = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=1e9)
    assert flat.P_rr < mid.P_rr < op.P_rr

    # Only P_rr moves. If the flag also shifted conduction/gate/Coss, a ranking
    # difference could not be attributed to the reverse-recovery model.
    for attr in ('P_cl', 'P_gd', 'P_coss', 'P_dt'):
        assert getattr(op, attr) == getattr(flat, attr), attr


def test_nofit_rows_are_excluded_from_an_operating_point_ranking():
    """The ranking filter. Asserted on the REAL Qrr_src strings the loss model emits, not
    on hand-written literals, so a renamed state breaks this instead of silently
    disabling the filter (the two live in different modules).

    Direction matters more than firing: the fitted part must SURVIVE and the nofit part
    must be DROPPED. A filter that removed the wrong side would also 'fire'."""
    from dclib.powerloss import qrr_rankable_at_operating_point as rankable

    fitted = _specs()
    nofit = _specs(registries=False)
    gan = _specs(qrr=0.0, trr=math.nan)

    def src(mf, didt):
        return dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=didt).get_cond('P_rr')['Qrr_src']

    # with an operating point requested: the unevaluable part goes, the others stay
    assert rankable(True, src(fitted, 5.7e9)) is True
    assert rankable(True, src(nofit, 5.7e9)) is False
    assert rankable(True, src(gan, 5.7e9)) is True, 'GaN zero charge IS an evaluated result'

    # with the flag OFF nothing may be filtered — 'datasheet-flat' is the answer, not a
    # failure, and filtering on the string alone would empty the CSV entirely
    for mf in (fitted, nofit, gan):
        assert rankable(False, src(mf, None)) is True

    # the dropped part carries a machine-readable reason for the unranked sheet
    assert dcdc_buck_ls(DC, nofit, gd=GD, qrr_didt=5.7e9).get_cond('P_rr')['qrr_nofit']


def test_flag_on_but_no_didt_is_excluded_not_ranked_as_flat():
    """The integration case a unit test of the predicate alone cannot reach.

    ls_commutation_didt() returns None for TWO different reasons — flag off, and flag on
    but the HS gate charges needed for the current-rise time are missing. dcdc_buck_ls
    labels the second `datasheet-flat`, identical to the first. Keying the filter on the
    di/dt therefore ranked those parts on the un-rescaled vendor charge: measured, 75
    parts took that path and 9 reached the ranking. Reconstructed here in main.py's exact
    call order so the two Nones cannot be conflated again."""
    from dclib.powerloss import qrr_rankable_at_operating_point as rankable

    blind = _specs(Qgs=math.nan, Qg_th=math.nan, Qgd=math.nan, Vpl=None)
    qrr_op = True                                        # the CONFIG flag is on
    didt = ls_commutation_didt(DC, blind, GD)
    assert didt is None, 'precondition: this part yields no operating point'

    ls = dcdc_buck_ls(DC, blind, gd=GD, qrr_didt=didt)
    assert ls.get_cond('P_rr')['Qrr_src'] == 'datasheet-flat-decontaminated'
    assert rankable(qrr_op, ls.get_cond('P_rr')['Qrr_src']) is False, \
        'a part with no operating point must not be ranked as if it had one'
    # ... and the same row IS rankable when nobody asked for an operating point
    assert rankable(False, ls.get_cond('P_rr')['Qrr_src']) is True


def test_unrecognised_qrr_src_is_excluded_not_waved_through():
    """Allowlist, not denylist. A future state added to dcdc_buck_ls — a new
    low-confidence tier, a renamed fallback — must default to NOT rankable. Keyed on the
    exact bad string, any new sibling state would silently rank and the bias returns
    wearing a different name."""
    from dclib.powerloss import qrr_rankable_at_operating_point as rankable

    for unknown in ('op-1pt-uncalibrated-future', 'op-zero'):
        assert rankable(True, unknown) is True, 'op-* states are the evaluated ones'
    for unknown in ('datasheet-flat', 'datasheet-flat-nofit', 'datasheet-flat-nodidt',
                    'some-new-tier', '', None):
        assert rankable(True, unknown) is False, unknown


def test_uncurated_part_falls_back_visibly_not_silently():
    """No conditions -> keep the flat charge (that is what the caller had), but the
    provenance must say the operating-point path did NOT run. Absence of a fit must
    never read as a fit that happened to agree."""
    mf = _specs(registries=False)
    flat = dcdc_buck_ls(DC, mf, gd=GD)
    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=5.7e9)

    assert op.P_rr == flat.P_rr
    assert op.get_cond('P_rr')['Qrr_src'] == 'datasheet-flat-nofit'
    assert 'qrr_nofit' in op.get_cond('P_rr')          # and it says why
    # the two fallbacks are distinguishable from the honest flat run
    assert flat.get_cond('P_rr')['Qrr_src'] == 'datasheet-flat-qoss-unverified'


def test_nan_qrr_without_registries_stays_nan():
    """Most parts in the DB have no parsed Qrr at all. With nothing curated for them,
    NaN in must stay NaN out — an operating-point model is not a way to invent
    missing data."""
    mf = _specs(qrr=math.nan, trr=math.nan, registries=False)
    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=5.7e9)
    assert math.isnan(op.P_rr)
    assert op.get_cond('P_rr')['Qrr_src'] == 'datasheet-flat-nofit'


def test_nan_qrr_with_curated_rows_is_a_labelled_substitution():
    """A part whose parse lost Qrr but which HAS curated two-di/dt rows gets a finite
    charge: the 2pt fit calibrates on the registry rows and never reads the scalar.

    That is a data-source substitution, not a rescale — P_rr goes from NaN (visibly
    missing, and NaN-poisoning P_tot so the part cannot be ranked) to a real number.
    Defensible, because the rows are datasheet values for that same die, but it must
    never be invisible: Qrr_src says the number came from the fit, and a measurement
    comparing flat vs operating-point has to count these rows separately instead of
    folding them into "the ranking moved"."""
    mf = _specs(qrr=math.nan, trr=math.nan)
    flat = dcdc_buck_ls(DC, mf, gd=GD)
    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=5.7e9)
    assert math.isnan(flat.P_rr)
    assert math.isfinite(op.P_rr) and op.P_rr > 0
    assert op.get_cond('P_rr')['Qrr_src'] == 'op-2pt'
    assert math.isnan(op.get_cond('P_rr')['Qrr_ds'])   # the scalar it did NOT use


def test_gan_zero_qrr_stays_zero():
    mf = _specs(qrr=0.0, trr=math.nan)
    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=5.7e9)
    assert op.P_rr == 0.0
    assert op.get_cond('P_rr')['Qrr_src'] == 'op-zero'


def test_commutation_didt_uses_the_current_rise_phase_only():
    """di/dt is set by the Qgs2 phase alone. Using the whole tr (which also contains
    the Qgd voltage-fall phase) would understate it by 1 + Qgd/Qgs2 and quietly
    under-predict Qrr on every part."""
    mf = _specs()
    t_ir = mosfet_hs_current_rise_time(mf, GD)
    tr, _tf = mosfet_hs_sw_timings_hs2(mf, GD)
    assert 0 < t_ir < tr
    # the ratio is exactly the charge partition, so the two cannot drift apart
    assert abs(tr / t_ir - (1 + (mf.Qgd / (GD.Von - mf.V_pl))
                            / (mf.Qgs2 / (GD.Von - .5 * (mf.V_pl + 2.5))))) < 1e-9

    didt = ls_commutation_didt(DC, mf, GD)
    assert abs(didt - DC.Io_min / t_ir) < 1e-6


def test_missing_gate_charges_yield_no_didt():
    """Unknown di/dt must stay unknown (-> None -> flat value with provenance),
    never a default that silently stands in for a measurement."""
    mf = _specs(Qgs=math.nan, Qg_th=math.nan, Qgd=math.nan, Vpl=None)
    assert ls_commutation_didt(DC, mf, GD) is None


def test_plateau_at_or_above_the_drive_is_refused_not_ranked():
    """A plateau voltage that is not below the gate drive has no gate-loop solution:
    (Von - Vpl) is the denominator of both switching-time terms. It must REFUSE with the
    numbers, not abort the run (an AssertionError out of _hs_gate_phases killed a whole
    6000-part run over one part) and not silently fall back to gd.fallback_V_pl, which
    would rank the part on an invented plateau exactly where the parsed one is unusable.

    The direction matters as much as the firing: the 5.0 V part must be the one refused
    and the 2.8 V part the one evaluated. A guard that dropped both would "fire" too.
    """
    gd_gan = GateDrive(rg_total=6, rg_total_dis=3, Von=11, Von_GaN=5, Voff=0,
                       fallback_V_pl=4.5)

    # EPC2934C's shape: read_charts digitized the END of the Qg curve, which is the 5 V
    # drive rail, so Vpl == Von exactly.
    bad = _specs(Vpl=5.0, Qgs=4e-9, Qg_th=2e-9, Qgd=2e-9, Qrr=0.0, trr=math.nan)
    try:
        mosfet_hs_sw_timings_hs2(bad, gd_gan, isGaN=True)
        assert False, 'a plateau at the drive rail must not yield switching times'
    except GateLoopInfeasible as e:
        assert '5.00' in str(e) and MPN in str(e), str(e)

    # ... while a real GaN plateau below the rail still evaluates, at this same drive
    good = _specs(Vpl=2.8, Qgs=4e-9, Qg_th=2e-9, Qgd=2e-9, Qrr=0.0, trr=math.nan)
    tr, tf = mosfet_hs_sw_timings_hs2(good, gd_gan, isGaN=True)
    assert tr > 0 and tf > 0, (tr, tf)

    # and the LS commutation path degrades to "unknown di/dt" instead of propagating —
    # it caught AssertionError only, so the typed exception had to be added there too
    assert ls_commutation_didt(DC, bad, gd_gan, isGaN=True) is None


def test_threshold_above_plateau_is_refused_not_ranked():
    """Qg_th >= Qgs makes the derived vgs_th land at or above the plateau — a charge
    parse error, not a device. Same treatment: refuse this part, keep the run.

    Set AFTER construction on purpose: MosfetSpecs.__init__ rejects Qg_th >= Qgs, but the
    records in dslib.store are pickles and unpickling bypasses __init__, so a stored spec
    can carry the pair this refusal exists for. Passing it to the ctor would only test the
    ctor's assert."""
    mf = _specs()
    mf.Qg_th = mf.Qgs   # vgs_th == Vpl
    try:
        mosfet_hs_sw_timings_hs2(mf, GD)
        assert False, 'vgs_th >= Vpl must not yield switching times'
    except GateLoopInfeasible as e:
        assert 'threshold' in str(e), str(e)
    assert ls_commutation_didt(DC, mf, GD) is None


def test_corrupt_qsw_is_refused_not_aborted():
    """The last bare assert on this path. A 1000x Qsw unit slip must refuse the PART,
    like every other parsed quantity here — an AssertionError escapes main.py's except
    and aborts the whole run, which is the exact failure GateLoopInfeasible exists to
    stop. Set post-construction because store records are pickles: unpickling bypasses
    MosfetSpecs.__init__, so its own range check never runs on them."""
    mf = _specs()
    mf._Qsw = 2000e-9   # 2 uC — a nC value read as uC

    try:
        dcdc_buck_hs(DC, mf, gd=GD)
        assert False, 'a 2 uC switching charge must not produce a loss number'
    except GateLoopInfeasible as e:
        assert 'Qsw' in str(e), str(e)


def test_pipeline_built_specs_carry_the_registries():
    """THE dead-guard test. get_mosfet_specs — not load_parts — is what the whole
    main.py pipeline builds specs with. Before attach_qrr_registries was called there,
    qrr_cond/qrr_points were None on every one of them, so Qrr_op could only raise and
    --qrr-op would have measured as "no change" on a corpus that has 110 fitted dies."""
    f = lambda sym, v, unit=None: Field(sym, min=math.nan, typ=v, max=math.nan, unit=unit)
    ds = DatasheetFields(mfr=MFR, mpn=MPN, fields=[
        f('Vds', 120, 'V'), f('Rds_on', 2.2, 'mOhm'), f('Qg', 100, 'nC'),
        f('tRise', 10, 'ns'), f('tFall', 15, 'ns'),
        f('Qrr', DS_QRR * 1e9, 'nC'), f('trr', DS_TRR * 1e9, 'ns'),
        f('Qgd', 15, 'nC'), f('Qgs', 30, 'nC'), f('Qg_th', 15, 'nC'),
        f('Vpl', 5.0, 'V'), f('Vsd', 0.9, 'V'), f('Coss', 1000, 'pF'),
    ])
    mf = ds.get_mosfet_specs()
    assert mf.qrr_points, "get_mosfet_specs must attach dslib/qrr_points rows"
    # and the model is actually reachable on that object
    assert mf.Qrr_op(IF=DS_IF, didt=DS_DIDT) > 0


def test_coss_vds_condition_floor_drops_strays_keeps_real():
    """Calibration for the Coss_Vds plausibility floor (|Vds| >= 5 V, deliberately NOT
    rating-relative — a rating-relative band measured against the full DB dropped
    ~480 parts' legitimate 25 V/10 V legacy anchors and inherited Vds-rating parse
    corruption). Known-bad: the 'Vds=1' mis-bucketed-condition artifact (317x in the
    DB) and Vsd-class sub-volt strays must be dropped; known-good: 25 V on a 500 V
    legacy part and 10 V on a 100 V part must survive and be the value SERVED."""
    import pytest
    f = lambda sym, v, unit=None, cond=None: Field(
        sym, min=math.nan, typ=v, max=math.nan, unit=unit, cond=cond)

    def base(vds, rds=2.2):
        return [
            f('Vds', vds, 'V'), f('Rds_on', rds, 'mOhm'), f('Qg', 100, 'nC'),
            f('tRise', 10, 'ns'), f('tFall', 15, 'ns'),
            f('Qgd', 15, 'nC'), f('Qgs', 30, 'nC'), f('Qg_th', 15, 'nC'),
            f('Vpl', 5.0, 'V'), f('Vsd', 0.9, 'V'),
        ]

    stray = DatasheetFields(mfr=MFR, mpn=MPN, fields=base(120) + [
        f('Coss', 2400, 'pF', cond=dict(Vds=1.0))])
    with pytest.warns(UserWarning, match='plausibility floor'):
        mf = stray.get_mosfet_specs()
    assert not mf.Coss_Vds

    mixed = DatasheetFields(mfr=MFR, mpn=MPN, fields=base(120) + [
        f('Coss', 2400, 'pF', cond=dict(Vds=60.0)),
        f('Coss', 5000, 'pF', cond=dict(Vds=1.0))])
    with pytest.warns(UserWarning, match='plausibility floor'):
        mf2 = mixed.get_mosfet_specs()
    assert mf2.Coss_Vds == 60.0

    # The corpus classes a rating-relative band wrongly killed: legacy 25 V anchor on
    # a 500 V part (ratio 0.05) and 10 V on a 100 V part — both must be served.
    legacy = DatasheetFields(mfr=MFR, mpn=MPN, fields=base(500, rds=50) + [
        f('Coss', 780, 'pF', cond=dict(Vds=25.0))])
    assert legacy.get_mosfet_specs().Coss_Vds == 25.0
    toshiba = DatasheetFields(mfr=MFR, mpn=MPN, fields=base(100) + [
        f('Coss', 1200, 'pF', cond=dict(Vds=10.0))])
    assert toshiba.get_mosfet_specs().Coss_Vds == 10.0


# --- Qrr(Tj): the measured law replacing the flat scalar (fetlib#41, gated 2026-07-28) --

def test_resolve_n_tau_four_states_and_the_ir_pool_scope():
    from dslib.qrr_model import resolve_n_tau
    r = resolve_n_tau("infineon:IRFB4137")
    assert r["state"] == "measured-fit" and abs(r["n_tau"] - 0.7496) < 1e-9
    # a table-harvested variant spelling hits its own per-die row ...
    r = resolve_n_tau("infineon:IRFP4768PBF")
    assert r["state"] == "measured-fit" and abs(r["n_tau"] - 0.7815) < 1e-9
    # ... and so does the OTHER spelling of an already-measured die. PbF is IR's
    # lead-free designator on the same datasheet, so serving the 0.666 family-pool
    # AVERAGE to a part that has its own measured fit is strictly worse evidence.
    # (This asserted 'ir-family-pool' until 2026-08-08, when is_orderable_variant
    # started honouring the reviewed PACKAGING_SUFFIXES list.)
    r = resolve_n_tau("infineon:IRFB4137PBF")
    assert r["state"] == "measured-fit" and abs(r["n_tau"] - 0.7496) < 1e-9
    # an UNREVIEWED code on the same die still falls to the pool: the suffix list is
    # an allowlist, not a pattern
    r = resolve_n_tau("infineon:IRFB4137XYZ9")
    assert r["state"] == "ir-family-pool" and abs(r["n_tau"] - 0.666) < 1e-9
    assert resolve_n_tau("infineon:IRFZ44N")["state"] == "ir-family-pool"
    assert resolve_n_tau("infineon:AUIRF1324S")["state"] == "ir-family-pool"
    # scope pin, the direction that matters: non-IR Infineon naming must NEVER
    # inherit the IR pool — those dies have no measured relatives.
    r = resolve_n_tau("infineon:IPP022N12NM6")
    assert r["state"] == "conservative-bound" and r["n_tau"] == 1.2
    assert resolve_n_tau("st:STP150N10F7")["state"] == "conservative-bound"
    assert resolve_n_tau(None)["state"] == "conservative-bound"


def _ir_specs():
    """A part whose Tj exponent is per-die MEASURED (IRFB4137), with a 1pt condition
    set manually — the wiring under test is the law booking, not the registries."""
    mf = _specs(part=SimpleNamespace(mpn="IRFB4137", mfr="infineon"), registries=False)
    mf.qrr_cond = dict(IF=DS_IF, didt=DS_DIDT, Tj=25.0, VR=75.0)
    return mf


def test_measured_tj_law_replaces_the_flat_scalar_not_stacks_on_it():
    """The booked charge must be the model's own 80 C evaluation with the flat x1.2
    OFF — an exact identity. 'It changed' would also pass for stacking (x1.2 on top
    of the law, ~x1.5 total), which is the double-count the wiring must exclude."""
    mf = _ir_specs()
    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=DS_DIDT)
    pr = op.get_cond('P_rr')
    assert pr['Qrr_tj_law'] == 'measured-n-tau'
    assert pr['Qrr_tj_c'] == 80.0
    d_cold = mf.Qrr_op(IF=DC.Io_min, didt=DS_DIDT, Tj=25.0, detail=True)
    d_hot = mf.Qrr_op(IF=DC.Io_min, didt=DS_DIDT, Tj=80.0, detail=True)
    assert d_hot['n_tau_state'] == 'measured-fit' and d_hot['tj_extrapolated']
    assert abs(pr['Qrr'] - d_hot['qrr_diffusion']) < 1e-18       # law, x1.2 OFF
    rise = d_hot['qrr_diffusion'] / d_cold['qrr_diffusion']
    assert 1.05 < rise < 1.6, rise            # superlinear in tau, but far below 2x
    assert abs(pr['Qrr_tj_rise'] - rise) < 1e-9
    assert pr['Qrr_n_tau'] == 'measured-fit'


def test_caller_tj_wins_over_the_assumed_80c():
    # Rds_on() hard-asserts Tj == 25 for finite Tj, so 25 C is the only finite value
    # dcdc_buck_ls accepts today — which still pins the override direction: a caller
    # that MODELS 25 C gets no temperature rise at all on a measured part (rise 1.0),
    # where the old behaviour multiplied 1.2 regardless.
    mf = _ir_specs()
    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=DS_DIDT, Tj=25.0)
    pr = op.get_cond('P_rr')
    assert pr['Qrr_tj_c'] == 25.0
    assert abs(pr['Qrr_tj_rise'] - 1.0) < 1e-9
    d25 = mf.Qrr_op(IF=DC.Io_min, didt=DS_DIDT, Tj=25.0, detail=True)
    assert abs(pr['Qrr'] - d25['qrr_diffusion']) < 1e-18


def test_bound_part_keeps_the_flat_scalar_exactly_as_before():
    mf = _specs()                             # IPP022N12NM6 -> conservative-bound
    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=DS_DIDT)
    pr = op.get_cond('P_rr')
    assert pr['Qrr_tj_law'] == 'flat-scalar'
    assert pr['Qrr_tj_rise'] == 1.2 and 'Qrr_tj_c' not in pr
    d = mf.Qrr_op(IF=DC.Io_min, didt=DS_DIDT, detail=True)
    assert d['n_tau_state'] == 'conservative-bound'
    assert abs(pr['Qrr'] - d['qrr_diffusion'] * 1.2) < 1e-18


def test_flat_path_never_applies_the_law_even_for_measured_parts():
    # No qrr_didt -> no fit record -> no tau to scale. The flat scalar stays for
    # everyone, including a measured-family part; only the op path books the law.
    mf = _ir_specs()
    flat = dcdc_buck_ls(DC, mf, gd=GD)
    pr = flat.get_cond('P_rr')
    assert pr['Qrr_tj_law'] == 'flat-scalar'
    assert pr['Qrr_tj_rise'] == 1.2 and 'Qrr_tj_c' not in pr


if __name__ == "__main__":
    for nm, fn in sorted(globals().items()):
        if nm.startswith("test_"):
            fn()
            print(f"{nm}: OK")
