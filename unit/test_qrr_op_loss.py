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


def test_calibration_point_reproduces_the_flat_value():
    """At the datasheet's own (IF, di/dt) the operating-point path must return the
    datasheet charge. Calibrating only that the flag "changes something" would pass
    just as well if it changed it in the wrong direction or by a wrong scale."""
    mf = _specs()
    flat = dcdc_buck_ls(DC, mf, gd=GD)
    op = dcdc_buck_ls(DC, mf, gd=GD, qrr_didt=DS_DIDT)

    assert abs(DC.Io_min - DS_IF) < 1e-9, DC.Io_min      # the identity's precondition
    assert flat.get_cond('P_rr')['Qrr_src'] == 'datasheet-flat'
    assert op.get_cond('P_rr')['Qrr_src'] == 'op-2pt'
    assert abs(op.P_rr / flat.P_rr - 1) < 1e-6, (op.P_rr, flat.P_rr)


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
