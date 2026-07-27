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

from dclib.powerloss import (dcdc_buck_ls, ls_commutation_didt,
                             mosfet_hs_current_rise_time, mosfet_hs_sw_timings_hs2)
from dslib.field import DatasheetFields, Field
from dslib.mosfet import GateDrive, MosfetSpecs, attach_qrr_registries
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
    assert flat.get_cond('P_rr')['Qrr_src'] == 'datasheet-flat'
    assert op.get_cond('P_rr')['Qrr_src'] == 'op-2pt'

    # the headline the model would rank on still lands on the datasheet row exactly
    head = mf.Qrr_op(IF=DS_IF, didt=DS_DIDT, detail=True)
    assert abs(head['Qrr'] / DS_QRR - 1) < 1e-6, head['Qrr']
    q0 = head['q0']
    assert q0 > 0, 'the 2pt fit must solve a positive capacitive share here'
    # ... and the BOOKED charge is that minus q0, so P_rr scales by the same ratio
    assert abs(op.P_rr / flat.P_rr - (DS_QRR - q0) / DS_QRR) < 1e-6, (op.P_rr, flat.P_rr)
    assert op.P_rr < flat.P_rr
    assert op.get_cond('P_rr')['Qrr_decont'] is True
    assert abs(op.get_cond('P_rr')['Qrr_q0'] - q0) < 1e-18


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
    assert flat.get_cond('P_rr')['Qrr_src'] == 'datasheet-flat'


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


if __name__ == "__main__":
    for nm, fn in sorted(globals().items()):
        if nm.startswith("test_"):
            fn()
            print(f"{nm}: OK")
