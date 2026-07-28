"""Acceptance tests for fl4p/fetlib#1's nonlinear Coss/Eoss checklist."""

from dataclasses import replace
import json
import math
from types import SimpleNamespace

import pytest

from dclib.coss_loss import (
    CossEnergyModel, CossHysteresisCalibration, CossSwitchingCellTransition,
    CossTransition, CURRENT_LOAD_TO_SOURCE, CURRENT_SOURCE_TO_LOAD,
    ENERGY_DC_SOURCE, FAIL, MECH_CHANNEL_DISCHARGE, MECH_COMMUTATED,
    OWNER_EXTERNAL, PASS, ROLE_HS, ROLE_LS, TOPOLOGY_SYNCHRONOUS_BUCK,
    UNVERIFIED,
    buck_hard_switching_cell, buck_hs_hard_transition, buck_ls_hard_transition,
    coss_audit_json,
    device_energy_endpoint, evaluate_coss_switching_cell,
    evaluate_coss_transition, validate_coss_report,
)
from dclib.powerloss import SwitchPowerLoss, dcdc_buck_hs, dcdc_buck_ls, qoss_at
from dslib.coss_curves import coss_curve_for, coss_curve_meta_for
from dslib.mosfet import GateDrive, MosfetSlot, MosfetSpecs, attach_coss_registry
from dslib.spec_models import BuckConverter, DcDcLoadParams


F = 40e3
META = dict(
    frequency_hz=F, temperature_c=25.0, gate_bias_v=0.0,
    provenance="synthetic isolated-fixture Coss(V), independently anchored",
    evidence_quality=PASS,
)
# Deliberately nonlinear: using the 1 nF endpoint as 1/2*C*V^2 is wrong by 2x.
CURVE = [(0.0, 4000.0, 0.0), (100.0, 1000.0, 0.0)]


def model(f=F, temp=25.0, gate=0.0):
    return CossEnergyModel(
        curve=CURVE, metadata=META, operating_frequency_hz=f,
        operating_temperature_c=temp, gate_bias_v=gate)


def ideal_hysteresis(v, f=F, temp=25.0, gate=0.0, energy=0.0):
    return CossHysteresisCalibration(
        energy_loss_j_per_event=energy, v_low_v=0.0, v_high_v=v,
        frequency_hz=f, temperature_c=temp, gate_bias_v=gate,
        provenance="isolated lossless-cap fixture" if energy == 0 else "double-pulse hysteresis fixture",
    )


def evaluate(transition, v, *, hyst=True, f=F, temp=25.0):
    return evaluate_coss_transition(
        model(f=f, temp=temp), transition, switching_frequency_hz=f,
        temperature_c=temp, gate_bias_v=0.0,
        hysteresis=ideal_hysteresis(v, f=f, temp=temp) if hyst else None)


def test_1_qoss_and_eoss_integrate_the_nonlinear_curve_not_one_table_coss():
    s = model().at(100.0)
    # C(V)=4nF-30pF/V*V: analytic controls for both independent integrals.
    assert s.qoss_c == pytest.approx(250e-9)
    assert s.eoss_j == pytest.approx(10e-6)
    assert s.eoss_j == pytest.approx(2 * (0.5 * 1e-9 * 100.0 ** 2))


def test_1b_zero_coss_is_refused_unless_declared():
    """Coss=0 is the best possible loss number, and a zero-parsed Coss is
    indistinguishable from the corrupt-parse class. An undeclared zero must become an
    unavailable/NaN result — never a silent 0 W with minted 'explicit fixture'
    provenance the code never verified."""
    corrupt = SimpleNamespace(Coss=0.0, Coss_Vds=50.0, coss_curve=None,
                              coss_curve_meta=None, part=None)
    with pytest.raises(ValueError, match="Coss=0 without explicit provenance"):
        CossEnergyModel.from_mosfet(corrupt)
    assert math.isnan(qoss_at(corrupt, 60.0))

    declared = SimpleNamespace(
        Coss=0.0, Coss_Vds=50.0, coss_curve=None,
        coss_curve_meta=dict(provenance="explicit zero-Coss analytic fixture"),
        part=None)
    m = CossEnergyModel.from_mosfet(declared)
    assert m.model_state == "explicit-zero-coss"
    assert m.provenance == "explicit zero-Coss analytic fixture"
    assert m.at(60.0).qoss_c == 0.0 and m.at(60.0).eoss_j == 0.0


def test_2_topology_mechanism_states_source_recovery_and_destination():
    hs = evaluate(buck_hs_hard_transition(72, evidence_quality=PASS), 72)
    ls = evaluate(buck_ls_hard_transition(72, evidence_quality=PASS), 72)

    assert hs.dissipated_commutation_j_per_event == pytest.approx(hs.eoss_initial_j)
    assert hs.destination_buckets_j_per_event[
        device_energy_endpoint("hs", "channel")] > 0
    assert ls.supplied_energy_j_per_event == pytest.approx(72 * ls.qoss_final_c)
    assert ls.dissipated_commutation_j_per_event == pytest.approx(
        ls.supplied_energy_j_per_event - ls.eoss_final_j)
    assert ls.destination_buckets_j_per_event[
        device_energy_endpoint("hs", "channel")] > 0
    assert any(f["source"] == ENERGY_DC_SOURCE
               and f["destination"] == device_energy_endpoint("ls", "coss")
               for f in ls.energy_flows_j_per_event)
    with pytest.raises(ValueError, match="invalid Coss energy destination"):
        CossTransition.from_points(
            "fiction", ((0, 72), (1, 0)),
            mechanism=MECH_CHANNEL_DISCHARGE, destination="unicorn")
    with pytest.raises(ValueError, match="distinct device"):
        replace(buck_hs_hard_transition(72), device_id="q", peer_device_id="q")
    with pytest.raises(ValueError, match="not implemented"):
        buck_hard_switching_cell(72, current_direction=CURRENT_LOAD_TO_SOURCE)


def test_2_paired_cross_device_transfer_is_emitted_once_and_must_match():
    common = dict(
        evidence_quality=PASS, topology=TOPOLOGY_SYNCHRONOUS_BUCK,
        switch_node="sw", current_direction=CURRENT_SOURCE_TO_LOAD,
        cell_event_id="resonant-transfer")
    hs = CossTransition.from_points(
        "hs-discharge", ((0, 72), (0.5, 36), (1, 0)),
        mechanism=MECH_COMMUTATED,
        source=device_energy_endpoint("hs", "coss"),
        destination=device_energy_endpoint("ls", "coss"),
        device_id="hs", device_role=ROLE_HS, peer_device_id="ls", **common)
    ls = CossTransition.from_points(
        "ls-charge", ((0, 0), (0.5, 36), (1, 72)),
        mechanism=MECH_COMMUTATED,
        source=device_energy_endpoint("hs", "coss"),
        destination=device_energy_endpoint("ls", "coss"),
        device_id="ls", device_role=ROLE_LS, peer_device_id="hs", **common)
    cell = CossSwitchingCellTransition(72, hs, ls)

    matched = evaluate_coss_switching_cell(
        model(), model(), cell, switching_frequency_hz=F,
        temperature_c=25, gate_bias_v=0,
        hs_hysteresis=ideal_hysteresis(72),
        ls_hysteresis=ideal_hysteresis(72))
    cross = [flow for flow in matched.energy_flows_j_per_event
             if flow["source"] == device_energy_endpoint("hs", "coss")
             and flow["destination"] == device_energy_endpoint("ls", "coss")]
    assert len(cross) == 1
    assert cross[0]["kind"] == "cell-coss-transfer"
    assert matched.cross_device_transfer_residual_j_per_event == 0
    assert matched.validation_status == PASS

    different_ls = CossEnergyModel(
        curve=[(0, 6000, 0), (100, 800, 0)], metadata=META,
        operating_frequency_hz=F, operating_temperature_c=25, gate_bias_v=0)
    mismatched = evaluate_coss_switching_cell(
        model(), different_ls, cell, switching_frequency_hz=F,
        temperature_c=25, gate_bias_v=0,
        hs_hysteresis=ideal_hysteresis(72),
        ls_hysteresis=ideal_hysteresis(72))
    assert mismatched.cross_device_transfer_residual_j_per_event > 0
    assert mismatched.validation_status == FAIL


def test_3_reversible_eoss_and_hysteresis_are_separate_conditioned_terms():
    transition = buck_hs_hard_transition(72, evidence_quality=PASS)
    no_cal = evaluate(transition, 72, hyst=False)
    assert math.isnan(no_cal.dissipated_hysteresis_j_per_event)
    assert math.isnan(no_cal.p_total_w)
    assert no_cal.p_accounted_w == no_cal.p_commutation_w
    assert "lower-bound" in no_cal.accounting_scope
    assert no_cal.hysteresis_model_state.startswith("UNVERIFIED")
    assert no_cal.evidence_quality == UNVERIFIED

    cal = ideal_hysteresis(72, energy=0.25e-6)
    got = evaluate_coss_transition(
        model(), transition, switching_frequency_hz=F,
        temperature_c=25.0, gate_bias_v=0.0, hysteresis=cal)
    assert got.dissipated_hysteresis_j_per_event == pytest.approx(0.25e-6)
    assert got.p_hysteresis_w == pytest.approx(0.25e-6 * F)
    assert got.p_total_w == pytest.approx(got.p_commutation_w + got.p_hysteresis_w)
    assert got.p_accounted_w == got.p_total_w

    wrong_frequency = replace(cal, frequency_hz=1e6)
    with pytest.raises(ValueError, match="refusing implicit extrapolation"):
        evaluate_coss_transition(
            model(), transition, switching_frequency_hz=F,
            temperature_c=25.0, gate_bias_v=0.0, hysteresis=wrong_frequency)

    impossible = replace(cal, energy_loss_j_per_event=100 * model().at(72).eoss_j)
    bad = evaluate_coss_transition(
        model(), transition, switching_frequency_hz=F,
        temperature_c=25.0, gate_bias_v=0.0, hysteresis=impossible)
    assert bad.validation_status == FAIL
    # A FAILed report books NaN — the same poison as an unavailable model — never the
    # physically-impossible figure; the raw number stays in p_accounted_w for audit.
    assert math.isnan(bad.p_bookable_w)
    assert math.isfinite(bad.p_accounted_w)
    assert math.isnan(bad.as_dict()["P_coss"])


def _mosfet_for_qrr():
    part = SimpleNamespace(mpn="QRR-COSS-FIXTURE", mfr="fixture")
    mf = MosfetSpecs(
        Vds_max=100, Rds_on=2e-3, Qg=50e-9, tRise=10e-9, tFall=10e-9,
        Qrr=200e-9, trr=40e-9, Qgd=10e-9, Qgs=20e-9, Qg_th=10e-9,
        Vpl=4.0, Vsd=0.9, Coss=1e-9, Coss_Vds=50, Rg=1.0, Id=100,
        part=part, coss_curve=CURVE, coss_curve_meta=META,
    )
    mf.qrr_cond = dict(IF=20.0, didt=100e6, VR=50.0, Tj=25.0, source="fixture")
    return mf


def test_4_flat_qrr_decontaminates_qoss_once_and_reports_the_state():
    dc = DcDcLoadParams(vi=72, vo=27, f=F, io=20, ripple_factor=0.2, tDead=100e-9)
    gd = GateDrive(rg_total=5, rg_total_dis=3, Von=10, Voff=0, fallback_V_pl=4)
    mf = _mosfet_for_qrr()
    loss = dcdc_buck_ls(dc, mf, gd, Qrr_temp_rise=1.0, Tj=25)
    rr = loss.get_cond("P_rr")

    assert rr["Qrr_src"] == "datasheet-flat-decontaminated"
    assert rr["Qrr_decont"] is True
    assert rr["Qrr_q0"] > 0
    assert rr["Qrr_double_booking"] == "exactly-once"
    assert rr["Qrr_double_booking_evidence"] == PASS
    assert rr["Qrr_qoss_evidence"] == PASS
    assert rr["Qrr_qoss_model_state"] == "datasheet-coss-curve"
    assert rr["Qrr_qoss_extrapolation_flags"] == ()
    assert rr["Qrr"] == pytest.approx(mf.Qrr - rr["Qrr_q0"])
    assert rr["Qrr"] + rr["Qrr_q0"] == pytest.approx(mf.Qrr)
    assert rr["Qrr_qoss_vr"] == pytest.approx(
        qoss_at(mf, mf.qrr_cond["VR"], operating_frequency_hz=F,
                operating_temperature_c=25, gate_bias_v=0))


def test_4_qrr_keeps_qoss_accounting_separate_from_evidence_and_fit_state():
    dc = DcDcLoadParams(vi=72, vo=27, f=F, io=20, ripple_factor=0.2, tDead=100e-9)
    gd = GateDrive(rg_total=5, rg_total_dis=3, Von=10, Voff=0, fallback_V_pl=4)

    nofit = _mosfet_for_qrr()
    nofit.qrr_cond = dict(VR=50.0)  # enough for Qoss correction, not for an LM fit
    rr = dcdc_buck_ls(
        dc, nofit, gd, Qrr_temp_rise=1.0, qrr_didt=100e6,
        Tj=25).get_cond("P_rr")
    assert rr["Qrr_src"] == "datasheet-flat-nofit"
    assert rr["Qrr_q0"] > 0 and rr["Qrr_decont"] is True
    assert rr["Qrr"] == pytest.approx(nofit.Qrr - rr["Qrr_q0"])
    assert rr["Qrr_double_booking"] == "exactly-once"
    assert rr["qrr_nofit"]

    # Known-bad calibration for the subtraction gate: the 0.1 global fraction was
    # calibrated against measured Coss(V) curves, and a scalar-guess Qoss lets a corrupt
    # Coss delete Qrr optimistically. The gate must keep the FULL flat value (direction,
    # not just firing), refuse the exactly-once claim, and put the refusal on record.
    scalar = _mosfet_for_qrr()
    scalar.coss_curve = None
    scalar.coss_curve_meta = None
    scalar_rr = dcdc_buck_ls(
        dc, scalar, gd, Qrr_temp_rise=1.0, Tj=25).get_cond("P_rr")
    assert scalar_rr["Qrr_src"] == "datasheet-flat-qoss-unverified"
    assert scalar_rr["Qrr_q0"] == 0
    assert scalar_rr["Qrr_decont"] is False
    assert scalar_rr["Qrr"] == pytest.approx(scalar.Qrr)
    assert scalar_rr["Qrr_double_booking"] == UNVERIFIED
    assert scalar_rr["Qrr_double_booking_evidence"] == UNVERIFIED
    assert scalar_rr["Qrr_qoss_evidence"] == UNVERIFIED
    assert scalar_rr["Qrr_qoss_model_state"] == "scalar-inverse-sqrt-fallback"
    assert "not a datasheet curve" in scalar_rr["Qrr_decont_reason"]

    extrapolated = _mosfet_for_qrr()
    extrapolated.coss_curve = [(0, 4000, 0), (40, 1200, 0)]
    extrapolated.qrr_cond["VR"] = 50.0
    extrap_rr = dcdc_buck_ls(
        dc, extrapolated, gd, Qrr_temp_rise=1.0, Tj=25).get_cond("P_rr")
    assert extrap_rr["Qrr_double_booking"] == "exactly-once"
    assert extrap_rr["Qrr_double_booking_evidence"] == UNVERIFIED
    assert any("constant-C-extension" in flag
               for flag in extrap_rr["Qrr_qoss_extrapolation_flags"])

    missing = _mosfet_for_qrr()
    missing.coss_curve = None
    missing.coss_curve_meta = None
    missing.Coss = math.nan
    missing.Coss_Vds = None
    missing_rr = dcdc_buck_ls(
        dc, missing, gd, Qrr_temp_rise=1.0, Tj=25).get_cond("P_rr")
    assert missing_rr["Qrr_q0"] == 0
    assert missing_rr["Qrr_decont"] is False
    assert missing_rr["Qrr_double_booking"] == UNVERIFIED
    assert missing_rr["Qrr_qoss_model_state"] == "unavailable"


def test_5_conditions_provenance_and_extrapolation_are_machine_readable():
    exact = model()
    assert exact.provenance == META["provenance"]
    assert exact.evidence_quality == PASS
    assert exact.extrapolation_flags == []

    moved = model(f=80e3, temp=100.0)
    assert moved.evidence_quality == UNVERIFIED
    # The switching frequency is NOT an extrapolation axis for the quasi-static C(V)
    # curve: frequency-dependent Coss loss belongs to the hysteresis calibration,
    # which refuses a frequency mismatch outright. Temperature still caps evidence.
    assert not any(x.startswith("frequency_hz:") for x in moved.extrapolation_flags)
    assert any(x.startswith("temperature_c:") for x in moved.extrapolation_flags)

    # Beyond the graph is allowed only as a labelled constant-C extension.
    moved.at(120)
    assert any("constant-C-extension" in x for x in moved.extrapolation_flags)

    missing_temperature = model(temp=None)
    assert missing_temperature.evidence_quality == UNVERIFIED
    assert "temperature_c:operating-unknown" in missing_temperature.extrapolation_flags


def test_5_registry_curve_and_provenance_attach_atomically_and_serialize():
    registry_curve = coss_curve_for("infineon", "IPP024N08NF2SAKMA1")
    registry_meta = coss_curve_meta_for("infineon", "IPP024N08NF2SAKMA1")
    assert registry_curve and registry_meta["curve_registry_id"].endswith(":coss-v1")
    assert registry_meta["datasheet_revision"] == "2.1"
    assert registry_meta["source_figure"] == "Diagram 11"

    complete = SimpleNamespace(coss_curve=None, coss_curve_meta=None)
    attach_coss_registry(complete, "infineon", "IPP024N08NF2SAKMA1")
    assert complete.coss_curve == registry_curve
    assert complete.coss_curve_meta == registry_meta
    attached = CossEnergyModel(
        curve=complete.coss_curve, metadata=complete.coss_curve_meta,
        operating_frequency_hz=1e6, operating_temperature_c=25,
        gate_bias_v=0)
    conditions = attached.conditions
    assert conditions["curve_registry_id"] == registry_meta["curve_registry_id"]
    assert conditions["datasheet_revision"] == "2.1"
    assert conditions["digitization_method"] == "raster-dark-pixel-column-trace"
    # PASS is reachable with SHIPPED registry data at matching conditions: the curated
    # meta carries the datasheet's blanket Tj=25 °C, and the per-entry source_document
    # names the actual sheet instead of a shared "Infineon datasheet" literal.
    assert attached.extrapolation_flags == []
    assert attached.evidence_quality == PASS
    assert registry_meta["temperature_c"] == 25.0
    assert "IPP024N08NF2S" in registry_meta["source_document"]

    custom_curve = [(0, 1234, 0), (80, 234, 0)]
    curve_only = SimpleNamespace(coss_curve=custom_curve, coss_curve_meta=None)
    attach_coss_registry(curve_only, "infineon", "IPP024N08NF2S")
    assert curve_only.coss_curve == custom_curve
    assert curve_only.coss_curve_meta is None

    custom_meta = dict(META, provenance="custom unrelated fixture")
    meta_only = SimpleNamespace(coss_curve=None, coss_curve_meta=custom_meta)
    attach_coss_registry(meta_only, "infineon", "IPP024N08NF2S")
    assert meta_only.coss_curve is None
    assert meta_only.coss_curve_meta == custom_meta

    cross_wired = SimpleNamespace(
        coss_curve=registry_curve, coss_curve_meta=custom_meta)
    attach_coss_registry(cross_wired, "infineon", "IPP024N08NF2S")
    assert cross_wired.coss_curve_meta["evidence_quality"] == UNVERIFIED
    assert cross_wired.coss_curve_meta["binding_state"].startswith("unverified-")

    # Registry-lineage refresh — the two staleness shapes that used to stay green.
    # (a) An older-generation baked copy (coss-v0 id + superseded trace) refreshes
    #     BOTH halves to the current registry; it must not keep serving the old curve.
    stale_meta = dict(registry_meta, curve_registry_id="infineon:IPP024N08NF2S:coss-v0")
    stale = SimpleNamespace(coss_curve=custom_curve, coss_curve_meta=stale_meta)
    attach_coss_registry(stale, "infineon", "IPP024N08NF2S")
    assert stale.coss_curve == registry_curve
    assert stale.coss_curve_meta == registry_meta
    # (b) Same id, superseded trace (an in-place correction): the REGISTRY curve must
    #     survive with full provenance — direction matters, not just that a guard fired.
    superseded = SimpleNamespace(coss_curve=custom_curve,
                                 coss_curve_meta=dict(registry_meta))
    attach_coss_registry(superseded, "infineon", "IPP024N08NF2S")
    assert superseded.coss_curve == registry_curve
    assert superseded.coss_curve_meta["evidence_quality"] == PASS
    # (c) Older-generation meta with the curve missing restores both halves too.
    old_meta_only = SimpleNamespace(coss_curve=None, coss_curve_meta=dict(stale_meta))
    attach_coss_registry(old_meta_only, "infineon", "IPP024N08NF2S")
    assert old_meta_only.coss_curve == registry_curve
    assert old_meta_only.coss_curve_meta == registry_meta


def test_6_device_multiplicity_and_event_count_are_explicit():
    t = replace(buck_hs_hard_transition(72, evidence_quality=PASS),
                events_per_cycle=2.0, device_count=3)
    got = evaluate(t, 72)
    one = evaluate(buck_hs_hard_transition(72, evidence_quality=PASS), 72)
    assert got.events_per_cycle == 2.0
    assert got.device_count == 3
    assert got.p_total_w == pytest.approx(6 * one.p_total_w)
    assert got.dissipated_total_j_per_cycle == pytest.approx(
        6 * one.dissipated_total_j_per_cycle)


@pytest.mark.parametrize(
    "field,value,match",
    (("device_count", 0, "positive integer"),
     ("device_count", -1, "positive integer"),
     ("device_count", 1.5, "positive integer"),
     ("events_per_cycle", 0, "positive"),
     ("events_per_cycle", -1, "positive"),
     ("events_per_cycle", math.nan, "positive")))
def test_6_invalid_multiplicity_and_event_counts_are_rejected(field, value, match):
    with pytest.raises(ValueError, match=match):
        replace(buck_hs_hard_transition(72), **{field: value})


@pytest.mark.parametrize("count", (0, -2, 1.5, math.nan, "2", True))
def test_6_production_parallel_scaling_rejects_non_positive_integers(count):
    loss = SwitchPowerLoss(
        P_cl=1, P_sw=2, P_coss=3, P_rr=4, P_gd=5, P_dt=6,
        cond={"P_coss": evaluate(
            buck_hs_hard_transition(72, evidence_quality=PASS), 72).as_dict()})
    with pytest.raises(ValueError, match="positive integer"):
        loss.parallel(count)
    with pytest.raises(ValueError, match="positive integer"):
        MosfetSlot(object(), rg_total=1, parallel=count)


def test_6_parallel_scaling_reaches_both_converter_slots(monkeypatch):
    hs_report = evaluate(
        buck_hs_hard_transition(72, evidence_quality=PASS), 72).as_dict()
    ls_report = evaluate(
        buck_ls_hard_transition(72, evidence_quality=PASS), 72).as_dict()
    base_hs = SwitchPowerLoss(
        P_cl=1, P_sw=2, P_coss=hs_report["p_accounted_w"],
        P_rr=0, P_gd=3, P_dt=0, cond={"P_coss": hs_report})
    base_ls = SwitchPowerLoss(
        P_cl=1, P_sw=0, P_coss=ls_report["p_accounted_w"],
        P_rr=2, P_gd=3, P_dt=4, cond={"P_coss": ls_report})

    import dclib.powerloss as powerloss
    monkeypatch.setattr(powerloss, "dcdc_buck_hs", lambda *a, **k: base_hs)
    monkeypatch.setattr(powerloss, "dcdc_buck_ls", lambda *a, **k: base_ls)
    monkeypatch.setattr(powerloss, "dcdc_buck_coil",
                        lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(powerloss, "dcdc_buck_caps",
                        lambda *a, **k: SimpleNamespace())

    coil = SimpleNamespace(Ldc=lambda current: 100e-6)
    hs_slot = SimpleNamespace(mf=object(), parallel=2)
    ls_slot = SimpleNamespace(mf=object(), parallel=3)
    converter = BuckConverter(
        "fixture", 30, F, coil, hs_slot, ls_slot, output_parasitics={})
    dc = DcDcLoadParams(
        vi=72, vo=27, f=F, io=20, ripple_factor=0.2, tDead=100e-9)
    losses, _ = converter.powerloss(
        dc, GateDrive(rg_total=5, rg_total_dis=3, Von=10, Voff=0))

    assert losses.hs.P_coss == pytest.approx(2 * base_hs.P_coss)
    assert losses.ls.P_coss == pytest.approx(3 * base_ls.P_coss)
    hs_cond, ls_cond = losses.hs.get_cond("P_coss"), losses.ls.get_cond("P_coss")
    assert hs_cond["device_count"] == 2
    assert ls_cond["device_count"] == 3
    assert hs_cond["events_per_cycle"] == ls_cond["events_per_cycle"] == 1
    assert hs_cond["p_accounted_w"] == pytest.approx(losses.hs.P_coss)
    assert ls_cond["p_accounted_w"] == pytest.approx(losses.ls.P_coss)


def test_7_partial_zvs_uses_the_deadtime_waveform_and_only_dumps_residual_eoss():
    waveform = ((0.0, 72.0), (20e-9, 45.0), (40e-9, 18.0))
    partial = CossTransition.partial_zvs(
        "hs-partial-zvs", waveform,
        channel_destination=device_energy_endpoint("hs", "channel"),
        evidence_quality=PASS)
    got = evaluate(partial, 72)
    e18 = model().at(18).eoss_j

    assert len(got.waveform) == 3  # two deadtime intervals + residual channel dump
    assert got.dissipated_commutation_j_per_event == pytest.approx(e18)
    assert got.recovered_energy_j_per_event == pytest.approx(
        model().at(72).eoss_j - e18)

    full_zvs = CossTransition.partial_zvs(
        "hs-full-zvs", ((0.0, 72.0), (40e-9, 0.0)),
        channel_destination=device_energy_endpoint("hs", "channel"),
        evidence_quality=PASS)
    assert evaluate(full_zvs, 72).dissipated_commutation_j_per_event == 0.0


def test_7_deadtime_deadline_interpolates_rebound_and_binds_production():
    channel = device_energy_endpoint("hs", "channel")
    partial = CossTransition.partial_zvs(
        "interpolated", ((0.0, 72.0), (200e-9, 0.0)),
        turn_on_time_s=100e-9, channel_destination=channel,
        evidence_quality=PASS)
    got = evaluate(partial, 72)
    e36, e72 = model().at(36).eoss_j, model().at(72).eoss_j
    assert got.dissipated_commutation_j_per_event == pytest.approx(e36)
    assert got.recovered_energy_j_per_event == pytest.approx(e72 - e36)
    assert got.turn_on_time_s == pytest.approx(100e-9)
    assert got.waveform_start_time_s == 0
    assert got.waveform_covered_until_s == pytest.approx(200e-9)
    assert got.conditions["configured_deadtime_s"] == pytest.approx(100e-9)
    assert e36 != pytest.approx(e72 * (36 / 72))

    rebound = CossTransition.partial_zvs(
        "rebound", ((0.0, 72.0), (50e-9, 0.0), (100e-9, 12.0)),
        turn_on_time_s=100e-9, channel_destination=channel,
        evidence_quality=PASS)
    ringing = evaluate(rebound, 72)
    e12 = model().at(12).eoss_j
    assert ringing.supplied_energy_j_per_event == pytest.approx(e12)
    assert ringing.recovered_energy_j_per_event == pytest.approx(e72)
    assert ringing.dissipated_commutation_j_per_event == pytest.approx(e12)
    assert any(flow["source"] == "load/inductor"
               and flow["destination"] == device_energy_endpoint("hs", "coss")
               for flow in ringing.energy_flows_j_per_event)

    with pytest.raises(ValueError, match="must be covered"):
        CossTransition.partial_zvs(
            "late", ((0.0, 72.0), (100e-9, 0.0)),
            turn_on_time_s=200e-9, channel_destination=channel)

    dc = DcDcLoadParams(
        vi=72, vo=27, f=F, io=20, ripple_factor=0.2, tDead=100e-9)
    gd = GateDrive(rg_total=5, rg_total_dis=3, Von=10, Voff=0, fallback_V_pl=4)
    production = dcdc_buck_hs(
        dc, _mosfet_for_qrr(), gd, Tj=25, coss_transition=partial)
    assert production.get_cond("P_coss")["turn_on_time_s"] == pytest.approx(100e-9)
    wrong_deadtime = DcDcLoadParams(
        vi=72, vo=27, f=F, io=20, ripple_factor=0.2, tDead=50e-9)
    # A per-part timing mismatch refuses THIS part — unavailable/NaN report, poisoned
    # total — instead of raising out of the per-part loop and aborting a 6000-part run
    # (main catches only GateLoopInfeasible).
    refused = dcdc_buck_hs(
        wrong_deadtime, _mosfet_for_qrr(), gd, Tj=25, coss_transition=partial)
    assert math.isnan(refused.P_coss) and math.isnan(refused.buck_hs())
    refused_rep = refused.get_cond("P_coss")
    assert refused_rep["accounting_scope"] == "unavailable"
    assert "does not match configured deadtime" in refused_rep["provenance"]

    shifted = CossTransition.partial_zvs(
        "shifted-origin", ((50e-9, 72.0), (250e-9, 0.0)),
        turn_on_time_s=150e-9, channel_destination=channel,
        evidence_quality=PASS)
    shifted_loss = dcdc_buck_hs(
        dc, _mosfet_for_qrr(), gd, Tj=25, coss_transition=shifted)
    shifted_report = shifted_loss.get_cond("P_coss")
    assert shifted_report["waveform_start_time_s"] == pytest.approx(50e-9)
    assert shifted_report["conditions"]["configured_deadtime_s"] == pytest.approx(
        100e-9)
    mislabeled = replace(
        shifted, model_state="measured-deadtime-waveform",
        turn_on_time_s=90e-9)
    mislabeled_loss = dcdc_buck_hs(
        dc, _mosfet_for_qrr(), gd, Tj=25, coss_transition=mislabeled)
    assert math.isnan(mislabeled_loss.P_coss)
    assert "does not match configured deadtime" in \
        mislabeled_loss.get_cond("P_coss")["provenance"]


def test_8_report_contains_the_required_audit_fields():
    d = evaluate(buck_hs_hard_transition(72, evidence_quality=PASS), 72).as_dict()
    required = {
        "initial_vds_v", "final_vds_v", "Eoss",
        "recovered_energy_j_per_event", "dissipated_commutation_j_per_event",
        "dissipated_hysteresis_j_per_event", "destination_buckets_j_per_event",
        "model_state", "evidence_quality", "validation_status",
        "events_per_cycle", "device_count", "provenance", "conditions",
        "topology", "device_id", "peer_device_id", "energy_flows_j_per_event",
        "p_accounted_w", "accounting_scope",
    }
    assert required <= set(d)
    payload = json.loads(coss_audit_json(d))
    assert payload["energy_flows_j_per_event"][0]["source"]
    assert payload["energy_flows_j_per_event"][0]["destination"]
    assert payload["energy_flows_j_per_event"][0]["kind"]
    assert payload["waveform"][0]["mechanism"]
    assert payload["dissipated_hysteresis_j_per_event"] is not None

    unknown_hysteresis = evaluate(
        buck_hs_hard_transition(72, evidence_quality=PASS), 72,
        hyst=False).as_dict()
    unknown_payload = json.loads(coss_audit_json(unknown_hysteresis))
    assert unknown_payload["dissipated_hysteresis_j_per_event"] is None
    assert unknown_payload["p_total_w"] is None

    staged = json.loads(coss_audit_json(
        {"switcher": d, "conductor": unknown_hysteresis}))
    assert staged["switcher"]["device_role"] == ROLE_HS
    assert staged["conductor"]["device_role"] == ROLE_HS
    assert staged["switcher"]["energy_flows_j_per_event"]


@pytest.mark.parametrize("vin", (24.0, 48.0, 72.0))
def test_9_charge_discharge_and_switching_cell_conserve_energy_at_multiple_vin(vin):
    cell = buck_hard_switching_cell(vin, evidence_quality=PASS)
    hs_cal = ideal_hysteresis(vin)
    ls_cal = ideal_hysteresis(vin)
    paired = evaluate_coss_switching_cell(
        model(), CossEnergyModel(
            curve=[(0, 6000, 0), (100, 800, 0)], metadata=META,
            operating_frequency_hz=F, operating_temperature_c=25,
            gate_bias_v=0),
        cell, switching_frequency_hz=F, temperature_c=25, gate_bias_v=0,
        hs_hysteresis=hs_cal, ls_hysteresis=ls_cal)
    hs, ls = paired.hs, paired.ls
    assert paired.validation_status == PASS
    assert hs.eoss_initial_j != ls.eoss_final_j
    assert hs.p_commutation_w != ls.p_commutation_w
    assert paired.current_direction == CURRENT_SOURCE_TO_LOAD
    assert validate_coss_report(
        hs, expected_destination=device_energy_endpoint("hs", "channel")) == PASS
    assert validate_coss_report(
        ls, expected_destination=device_energy_endpoint("hs", "channel")) == PASS
    assert abs(hs.conservation_residual_j_per_event) < 1e-15
    assert abs(ls.conservation_residual_j_per_event) < 1e-15
    assert abs(paired.conservation_residual_j_per_event) < 1e-15
    assert paired.cross_device_transfer_residual_j_per_event == 0
    assert any(f["destination"] == device_energy_endpoint("ls", "coss")
               for f in paired.energy_flows_j_per_event)

    broken = replace(hs, validation_status=FAIL,
                     conservation_residual_j_per_event=1e-3)
    assert validate_coss_report(broken) == FAIL


def test_9_validator_recomputes_ledger_and_fail_evidence_is_monotonic():
    report = evaluate(
        buck_hs_hard_transition(72, evidence_quality=PASS), 72)
    assert validate_coss_report(report) == PASS

    # Cached status and total watts remain unchanged: neither can hide a corrupt ledger.
    stale_residual = replace(
        report, conservation_residual_j_per_event=1.0)
    assert validate_coss_report(stale_residual) == FAIL
    corrupt_energy = replace(
        report, supplied_energy_j_per_event=report.supplied_energy_j_per_event + 1e-6)
    assert corrupt_energy.p_total_w == report.p_total_w
    assert validate_coss_report(corrupt_energy) == FAIL
    assert validate_coss_report(replace(
        report, validation_status=UNVERIFIED)) == UNVERIFIED

    failed_transition = evaluate(
        buck_hs_hard_transition(72, evidence_quality=FAIL), 72)
    assert failed_transition.evidence_quality == FAIL
    assert failed_transition.validation_status == FAIL

    failed_meta = dict(META, evidence_quality=FAIL)
    failed_model = CossEnergyModel(
        curve=CURVE, metadata=failed_meta, operating_frequency_hz=F,
        operating_temperature_c=25, gate_bias_v=0)
    model_failure = evaluate_coss_transition(
        failed_model, buck_hs_hard_transition(72, evidence_quality=PASS),
        switching_frequency_hz=F, temperature_c=25, gate_bias_v=0,
        hysteresis=ideal_hysteresis(72))
    assert model_failure.validation_status == FAIL

    failed_hysteresis = replace(ideal_hysteresis(72), evidence_quality=FAIL)
    hysteresis_failure = evaluate_coss_transition(
        model(), buck_hs_hard_transition(72, evidence_quality=PASS),
        switching_frequency_hz=F, temperature_c=25, gate_bias_v=0,
        hysteresis=failed_hysteresis)
    assert hysteresis_failure.validation_status == FAIL

    # The validator checks more than the five-term identity: a zeroed or rescaled
    # power figure with an intact energy quintet used to validate.
    assert validate_coss_report(replace(report, p_accounted_w=0.0)) == FAIL
    assert validate_coss_report(replace(
        report, p_commutation_w=2 * report.p_commutation_w)) == FAIL
    # ... and destination buckets must equal the flows that claim to feed them.
    bucket_key = next(iter(report.destination_buckets_j_per_event))
    padded = dict(report.destination_buckets_j_per_event)
    padded[bucket_key] = padded[bucket_key] + 1e-6
    assert validate_coss_report(replace(
        report, destination_buckets_j_per_event=padded)) == FAIL


def test_9_validator_runs_in_production_and_zero_dissipation_zvs_passes():
    """The independent recompute is wired into p_coss_eoss (recorded in conditions),
    and a PERFECT full-ZVS event — zero dissipation, hence no channel bucket — must
    not FAIL an expected_destination check: better input, better verdict."""
    dc = DcDcLoadParams(vi=72, vo=27, f=F, io=20, ripple_factor=0.2, tDead=100e-9)
    gd = GateDrive(rg_total=5, rg_total_dis=3, Von=10, Voff=0, fallback_V_pl=4)
    loss = dcdc_buck_hs(dc, _mosfet_for_qrr(), gd, Tj=25)
    assert loss.get_cond("P_coss")["conditions"]["independent_validation"] in (
        PASS, FAIL, UNVERIFIED)

    channel = device_energy_endpoint("hs", "channel")
    perfect = CossTransition.partial_zvs(
        "full-zvs", ((0.0, 72.0), (100e-9, 0.0)),
        turn_on_time_s=100e-9, channel_destination=channel,
        evidence_quality=PASS)
    got = evaluate(perfect, 72)
    assert got.dissipated_commutation_j_per_event == pytest.approx(0.0, abs=1e-18)
    assert channel not in got.destination_buckets_j_per_event
    assert validate_coss_report(got, expected_destination=channel) != FAIL
    # ... while a real dissipating event with the bucket MISSING still fails.
    hard = evaluate(buck_hs_hard_transition(72, evidence_quality=PASS), 72)
    stripped = {k: v for k, v in hard.destination_buckets_j_per_event.items()
                if k != channel}
    assert validate_coss_report(
        replace(hard, destination_buckets_j_per_event=stripped,
                energy_flows_j_per_event=tuple(
                    f for f in hard.energy_flows_j_per_event
                    if f["destination"] != channel)),
        expected_destination=channel) == FAIL


def test_9_cell_far_tail_mismatch_fails_not_averages():
    """A 2x cross-device disagreement at picojoule scale used to be silently merged
    (fixed 1e-12 J absolute tolerance in _close), averaged into one flow, and
    contributed ZERO residual — the far tail could never FAIL. The match tolerance is
    now tied to the cell's own energy scale."""
    from dclib.coss_loss import _reconcile_cell_flows
    base = evaluate(buck_hs_hard_transition(72, evidence_quality=PASS), 72)
    pair = dict(source="device:hs:coss", destination="device:ls:coss")
    discharging = replace(
        base, eoss_stored_peak_j=1.0e-12, energy_flows_j_per_event=(
            dict(pair, energy_j=5.0e-13, kind="recovered-transfer"),))
    charging = replace(
        base, eoss_stored_peak_j=1.0e-12, energy_flows_j_per_event=(
            dict(pair, energy_j=1.0e-12, kind="stored-transfer"),))
    flows, mismatch = _reconcile_cell_flows(discharging, charging)
    # The 2x disagreement is a residual now, and both audit views are retained.
    assert mismatch == pytest.approx(5.0e-13)
    assert sum(1 for f in flows if f["kind"] == "cell-coss-transfer") == 0
    # An agreeing pair still collapses to the single physical transfer.
    agreeing = replace(
        charging, energy_flows_j_per_event=(
            dict(pair, energy_j=5.0e-13, kind="stored-transfer"),))
    flows2, mismatch2 = _reconcile_cell_flows(discharging, agreeing)
    assert mismatch2 == 0.0
    assert sum(1 for f in flows2 if f["kind"] == "cell-coss-transfer") == 1


def test_10_external_waveform_owner_disables_analytic_add_on_and_ring_esr_is_absent():
    external = replace(
        buck_hs_hard_transition(72, evidence_quality=PASS),
        accounting_owner=OWNER_EXTERNAL, model_state="dcdc-tools-waveform")
    got = evaluate(external, 72)
    assert got.accounting_owner == OWNER_EXTERNAL
    assert got.p_total_w == 0.0
    assert got.p_accounted_w == 0.0
    assert "no-analytic-add-on" in got.model_state
    assert "rcoss" not in got.as_dict()
    assert "ring" not in got.conditions

    # External waveform/ring commutation does not suppress an independently
    # calibrated intrinsic material-loss term owned by fetlib.
    calibrated = evaluate_coss_transition(
        model(), external, switching_frequency_hz=F,
        temperature_c=25, gate_bias_v=0,
        hysteresis=ideal_hysteresis(72, energy=0.25e-6))
    assert calibrated.p_commutation_w == 0
    assert calibrated.p_hysteresis_w == pytest.approx(0.25e-6 * F)
    assert calibrated.p_total_w == calibrated.p_hysteresis_w
    assert calibrated.p_accounted_w == calibrated.p_hysteresis_w
    assert calibrated.commutation_accounting_owner == OWNER_EXTERNAL
    assert calibrated.hysteresis_accounting_owner != OWNER_EXTERNAL

    unknown_hysteresis = evaluate(external, 72, hyst=False)
    assert math.isnan(unknown_hysteresis.p_total_w)
    assert unknown_hysteresis.p_accounted_w == 0
    assert unknown_hysteresis.validation_status == UNVERIFIED
    assert "known-booked-lower-bound" in unknown_hysteresis.accounting_scope

    # Both terms can be handed off, but only by explicitly naming both owners.
    fully_external = replace(
        external, hysteresis_accounting_owner=OWNER_EXTERNAL)
    handed_off = evaluate(fully_external, 72, hyst=False)
    assert handed_off.p_commutation_w == 0
    assert handed_off.p_hysteresis_w == 0
    assert handed_off.p_total_w == 0
    assert handed_off.p_accounted_w == 0
    assert handed_off.validation_status == PASS
    assert "hysteresis=external-waveform" in handed_off.accounting_scope
