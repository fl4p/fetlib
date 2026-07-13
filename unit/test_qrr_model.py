"""Tests for dslib/qrr_model.py — the fl4p/fetlib#37 Qrr(IF, di/dt, Tj) curve model.

Run:  python3 -m pytest unit/test_qrr_model.py   (or execute directly)
"""
import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dslib import qrr_model
from dslib.mosfet import MosfetSpecs

# The curated datasheet points (must mirror dslib/qrr_conditions.py + the parts DB).
DS = {
    "IPP019N08NF2S": dict(Qrr=285e-9, trr=44e-9, IF=100.0, didt=500e6, Tj=25.0),
    "IPP024N08NF2S": dict(Qrr=242e-9, trr=39e-9, IF=100.0, didt=500e6, Tj=25.0),
    "IPP055N08NF2S": dict(Qrr=154e-9, trr=30e-9, IF=60.0, didt=500e6, Tj=25.0),
    "IPP026N10NF2S": dict(Qrr=327e-9, trr=44e-9, IF=100.0, didt=500e6, Tj=25.0),
    "IPP018N10N5":   dict(Qrr=287e-9, trr=99e-9, IF=100.0, didt=100e6, Tj=25.0),
    "IPP022N12NM6":  dict(Qrr=155.2e-9, trr=46.3e-9, IF=50.0, didt=300e6, Tj=25.0),
}


def test_roundtrip_exact_at_calibration():
    """fit_lm -> predict must reproduce the datasheet (Qrr, trr) at the test point."""
    for mpn, d in DS.items():
        fit = qrr_model.fit_lm(d["Qrr"], d["trr"], d["IF"], d["didt"], tj_fit=d["Tj"])
        p = qrr_model.predict(fit["tau"], fit["TM"], d["IF"], d["didt"])
        assert abs(p["Qrr"] / d["Qrr"] - 1) < 1e-6, (mpn, p["Qrr"], d["Qrr"])
        assert abs(p["trr"] / d["trr"] - 1) < 1e-6, (mpn, p["trr"], d["trr"])
        assert fit["tau"] > fit["td"] > 0 and fit["TM"] > 0, (mpn, fit)


def test_monotone_in_IF_and_didt():
    d = DS["IPP024N08NF2S"]
    fit = qrr_model.fit_lm(d["Qrr"], d["trr"], d["IF"], d["didt"])
    q = lambda IF, a: qrr_model.predict(fit["tau"], fit["TM"], IF, a)["Qrr"]
    # linear-ish in IF (the axis the flat scalar misses most)
    assert q(20, 500e6) < q(50, 500e6) < q(100, 500e6) < q(200, 500e6)
    # sub-linear but increasing in di/dt (the axis the SPICE TT model misses entirely)
    assert q(100, 100e6) < q(100, 500e6) < q(100, 5e9)
    ratio = q(100, 5e9) / q(100, 500e6)
    assert 1.0 < ratio < 10.0, ratio  # grows, but far less than the 10x di/dt step


def test_tj_axis_flagged_and_increasing():
    d = DS["IPP024N08NF2S"]
    cond = dict(IF=d["IF"], didt=d["didt"], Tj=d["Tj"])
    cold = qrr_model.qrr_op(d["Qrr"], d["trr"], cond, IF=33.3, didt=5.7e9, Tj=25.0)
    hot = qrr_model.qrr_op(d["Qrr"], d["trr"], cond, IF=33.3, didt=5.7e9, Tj=100.0)
    assert not cold["tj_extrapolated"] and hot["tj_extrapolated"]
    assert hot["Qrr"] > cold["Qrr"] > 0
    # N_TAU=1.2 (recalibrated #18: the MODEL's Qrr doubles 25->125C, matching the
    # empirical Si rule): tau grows (373/298)^1.2 = 1.31x from 25->100C; Qrr responds
    # slightly super-linearly -> measured 1.41x.
    assert 1.3 < hot["Qrr"] / cold["Qrr"] < 1.55


def test_n_tau_matches_qrr_doubling_rule():
    """The N_TAU calibration contract itself: Qrr(125C)/Qrr(25C) ~ 2 at DATASHEET
    conditions (that is what the empirical Si rule states), for every curated part."""
    for mpn, d in DS.items():
        fit = qrr_model.fit_lm(d["Qrr"], d["trr"], d["IF"], d["didt"], tj_fit=25.0)
        tau_h = qrr_model.tau_at_tj(fit["tau0"], 125.0, 25.0)
        r = qrr_model.predict(tau_h, fit["TM"], d["IF"], d["didt"])["Qrr"] / d["Qrr"]
        assert 1.8 < r < 2.25, (mpn, r)


def test_calibration_qrr():
    """Qoss decontamination of the datasheet Qrr (#18 item 1; fraction calibrated to
    0.1 on 2026-07-13 from two-di/dt-point datasheets — see the constant's comment)."""
    f = qrr_model.QRR_QOSS_FRACTION
    assert 0.05 <= f <= 0.15, f   # data says 0.10-0.15 optimal; 0.5 was refuted
    # IPP024: Qrr=242nC @ VR=40V, Qoss(0-40V)~105nC
    q = qrr_model.calibration_qrr(242e-9, 105e-9)
    assert abs(q - (242e-9 - f * 105e-9)) < 1e-15
    assert qrr_model.calibration_qrr(242e-9, None) == 242e-9      # no curve -> raw
    try:
        qrr_model.calibration_qrr(50e-9, 105e-9, fraction=1.0)    # eats the whole Qrr
    except qrr_model.LMFitError:
        pass
    else:
        raise AssertionError("calibration_qrr must fail loud when subtraction >= Qrr")


def test_didt_axis_out_of_sample():
    """Genuine out-of-sample validation of the di/dt axis (2026-07-13): these parts'
    datasheets quote reverse recovery at TWO di/dt points. Fit at the low point using
    the standard calibration procedure (Qoss decontamination at QRR_QOSS_FRACTION),
    predict the high point, compare against the datasheet's own second row. Measured
    errors at f=0.1: -6.3% / +9.3% / +15.0%; band +/-20%. Across the full 36-die
    two-point sweep the median |err| is ~14% (vs 47-51% at the refuted f=0.5)."""
    cases = [
        # (mpn, IF, Qoss@VR [C] or None, (didt, Qrr, trr) low, (didt, Qrr) high)
        ("IPP022N12NM6", 50.0, 267e-9, (300e6, 155.2e-9, 46.3e-9), (1000e6, 412.1e-9)),
        ("ISC030N10NM6", 25.0, 101e-9, (100e6, 56e-9, 46.5e-9), (1000e6, 266e-9)),
        ("FDMS86180", 33.0, None, (300e6, 109e-9, 44e-9), (1000e6, 235e-9)),  # onsemi, no Qoss quote
    ]
    for mpn, IF, qoss, lo, hi in cases:
        q_cal = qrr_model.calibration_qrr(lo[1], qoss)
        fit = qrr_model.fit_lm(q_cal, lo[2], IF, lo[0])
        p = qrr_model.predict(fit["tau"], fit["TM"], IF, hi[0])
        q_meas = p["Qrr"] + (qrr_model.QRR_QOSS_FRACTION * qoss if qoss else 0.0)
        err = q_meas / hi[1] - 1
        assert abs(err) < 0.20, (mpn, q_meas, hi[1], err)


def test_predict_charge_partition():
    """predict() exposes the qa (pre-snap triangle) / qb (tail) split used for the
    HS/LS thermal attribution; they must sum to Qrr."""
    d = DS["IPP024N08NF2S"]
    fit = qrr_model.fit_lm(d["Qrr"], d["trr"], d["IF"], d["didt"])
    p = qrr_model.predict(fit["tau"], fit["TM"], 15.0, 2.85e9)
    assert abs(p["qa"] + p["qb"] - p["Qrr"]) < 1e-15
    assert p["qa"] > 0 and p["qb"] > 0


def test_fit_lm_2pt_roundtrip_ipp022():
    """Two-point (tau, TM, q0) fit must reproduce BOTH datasheet Qrr rows as
    measured-equivalent charge (diffusion + q0); the second trr row is a free
    residual and stays within the band measured at review time (~+12%)."""
    lo = dict(IF=50.0, didt=300e6, Qrr=155.2e-9, trr=46.3e-9)
    hi = dict(IF=50.0, didt=1000e6, Qrr=412.1e-9, trr=39.0e-9)
    fit = qrr_model.fit_lm_2pt(lo, hi)
    assert 0 < fit["q0"] < 30e-9, fit["q0"]      # implied offset ~9.6 nC
    for row in (lo, hi):
        p = qrr_model.predict(fit["tau"], fit["TM"], row["IF"], row["didt"])
        assert abs((p["Qrr"] + fit["q0"]) / row["Qrr"] - 1) < 1e-6, row
    assert abs(fit["trr_hi_resid"]) < 0.25, fit["trr_hi_resid"]


def test_fit_lm_2pt_fail_loud_on_contamination_dominated():
    """ISC320N12LM6's datasheet Qrr FALLS with di/dt (23.8 -> 20.3 nC) —
    impossible for stored charge; no q0 makes it LM-consistent. Must raise,
    never force a fit."""
    lo = dict(IF=4.5, didt=300e6, Qrr=23.8e-9, trr=20.5e-9)
    hi = dict(IF=4.5, didt=1000e6, Qrr=20.3e-9, trr=10.3e-9)
    try:
        qrr_model.fit_lm_2pt(lo, hi)
    except qrr_model.LMFitError:
        pass
    else:
        raise AssertionError("fit_lm_2pt must reject a falling-Qrr pair")
    # mismatched IF rows are equally invalid
    try:
        qrr_model.fit_lm_2pt(dict(lo, IF=25.0), hi)
    except qrr_model.LMFitError:
        pass
    else:
        raise AssertionError("fit_lm_2pt must reject rows at different IF")


def test_qrr_op_prefers_2pt_and_falls_back_explicitly():
    d = DS["IPP022N12NM6"]
    pts = [dict(IF=50.0, didt=300e6, VR=60.0, Tj=25.0, Qrr=155.2e-9, trr=46.3e-9),
           dict(IF=50.0, didt=1000e6, VR=60.0, Tj=25.0, Qrr=412.1e-9, trr=39.0e-9)]
    fet = _FakeFet(Qrr=d["Qrr"], trr=d["trr"], Rds_on=2.2e-3,
                   qrr_cond=dict(IF=d["IF"], didt=d["didt"], Tj=d["Tj"]),
                   qrr_points=pts)
    p = fet.Qrr_op(IF=50.0, didt=300e6, detail=True)
    assert p["method"] == "2pt" and p["q0"] > 0
    assert abs(p["Qrr"] / 155.2e-9 - 1) < 1e-6          # measured-equivalent at row
    assert p["qrr_diffusion"] < p["Qrr"]                # diffusion excludes q0
    # contamination-dominated points -> explicit single-point fallback
    bad = [dict(IF=4.5, didt=300e6, Tj=25.0, Qrr=23.8e-9, trr=20.5e-9),
           dict(IF=4.5, didt=1000e6, Tj=25.0, Qrr=20.3e-9, trr=10.3e-9)]
    fet2 = _FakeFet(Qrr=d["Qrr"], trr=d["trr"], Rds_on=2.2e-3,
                    qrr_cond=dict(IF=d["IF"], didt=d["didt"], Tj=d["Tj"]),
                    qrr_points=bad)
    p2 = fet2.Qrr_op(IF=50.0, didt=300e6, detail=True)
    assert p2["method"] == "1pt" and "fallback_from_2pt" in p2


IPP022_PTS = [dict(IF=50.0, didt=300e6, VR=60.0, Tj=25.0, Qrr=155.2e-9, trr=46.3e-9),
              dict(IF=50.0, didt=1000e6, VR=60.0, Tj=25.0, Qrr=412.1e-9, trr=39.0e-9)]
ISC320_PTS = [dict(IF=4.5, didt=300e6, Tj=25.0, Qrr=23.8e-9, trr=20.5e-9),
              dict(IF=4.5, didt=1000e6, Tj=25.0, Qrr=20.3e-9, trr=10.3e-9)]


def test_best_lm_fit_prefers_2pt_and_q0_contract():
    """best_lm_fit is the ONE deck/bucket calibration decision point. CONTRACT:
    q0 is calibration provenance only — predictions from (tau, TM) are the
    DIFFUSION charge; a consumer adding q0 back would double-count against the
    Coss bucket (that is the exact bug this function exists to prevent)."""
    f = qrr_model.best_lm_fit(155.2e-9, 46.3e-9, None, qrr_points=IPP022_PTS)
    assert f["method"] == "2pt" and f["decontaminated"] and f["q0"] > 0
    # diffusion prediction at a datasheet row == row Qrr MINUS q0, exactly
    p = qrr_model.predict(f["tau"], f["TM"], 50.0, 300e6)
    assert abs(p["Qrr"] - (155.2e-9 - f["q0"])) < 1e-15
    assert p["Qrr"] < 155.2e-9  # diffusion-only: never the full measured integral


def test_best_lm_fit_explicit_fallbacks():
    cond = dict(IF=50.0, didt=300e6, Tj=25.0)
    # contamination-dominated points -> loud 1pt fallback, decontaminated via Qoss
    f = qrr_model.best_lm_fit(155.2e-9, 46.3e-9, cond,
                              qrr_points=ISC320_PTS, qoss_vr=267e-9)
    assert f["method"] == "1pt" and "fallback_from_2pt" in f
    assert f["decontaminated"]
    assert abs(f["q0"] - qrr_model.QRR_QOSS_FRACTION * 267e-9) < 1e-15
    # no Qoss available -> raw fit, q0=0, decontaminated=False (caller must warn)
    f2 = qrr_model.best_lm_fit(155.2e-9, 46.3e-9, cond)
    assert f2["method"] == "1pt" and f2["q0"] == 0.0 and not f2["decontaminated"]
    # neither points nor conditions -> fail loud
    try:
        qrr_model.best_lm_fit(155.2e-9, 46.3e-9, None, qrr_points=ISC320_PTS)
    except qrr_model.LMFitError as e:
        assert "2pt path failed first" in str(e)
    else:
        raise AssertionError("best_lm_fit must raise without cond or usable points")


def test_qrr_op_fugu2_operating_point():
    """Fugu2 sync-buck LS: IF ~ 33 A (1/3 the datasheet's), di/dt ~ 5.7 kA/us (11x the
    datasheet's). The two axes pull opposite ways; the result must be finite, positive,
    and different from the flat scalar."""
    d = DS["IPP024N08NF2S"]
    cond = dict(IF=d["IF"], didt=d["didt"], Tj=d["Tj"])
    p = qrr_model.qrr_op(d["Qrr"], d["trr"], cond, IF=33.3, didt=5.7e9, Tj=100.0)
    assert math.isfinite(p["Qrr"]) and p["Qrr"] > 0
    assert p["Qrr"] != d["Qrr"]
    assert p["irrm"] > 0 and p["trr"] > 0


def test_missing_conditions_fail_loud():
    d = DS["IPP024N08NF2S"]
    try:
        qrr_model.qrr_op(d["Qrr"], d["trr"], None, IF=33.3, didt=5.7e9)
    except qrr_model.LMFitError:
        pass
    else:
        raise AssertionError("qrr_op must raise on missing test conditions")


def test_inconsistent_pair_fail_loud():
    # trr shorter than the ramp time its own Qrr implies -> no LM solution
    try:
        qrr_model.fit_lm(1e-6, 5e-9, 100.0, 500e6)
    except qrr_model.LMFitError:
        pass
    else:
        raise AssertionError("fit_lm must reject an LM-inconsistent (Qrr, trr) pair")


def test_predict_validates_inputs():
    """predict() must fail loud with LMFitError (not ZeroDivisionError/OverflowError)
    on degenerate operating points — public-API hardening from the adversarial review."""
    d = DS["IPP024N08NF2S"]
    fit = qrr_model.fit_lm(d["Qrr"], d["trr"], d["IF"], d["didt"])
    bad = [dict(IF=33.3, didt=0.0), dict(IF=33.3, didt=-5e9),
           dict(IF=-1.0, didt=5e9), dict(IF=float("nan"), didt=5e9),
           dict(IF=33.3, didt=float("inf"))]
    for kw in bad:
        try:
            qrr_model.predict(fit["tau"], fit["TM"], **kw)
        except qrr_model.LMFitError:
            pass
        else:
            raise AssertionError(f"predict must raise LMFitError for {kw}")
    # IF=0 stays legal: no stored charge -> Qrr ~ 0
    p = qrr_model.predict(fit["tau"], fit["TM"], 0.0, 5e9)
    assert p["Qrr"] < 1e-12


def test_qrr_op_stale_pickle_object():
    """MosfetSpecs.Qrr_op on an object lacking the qrr_cond attribute entirely
    (stale-pickle shape) must raise LMFitError, not AttributeError."""
    d = DS["IPP024N08NF2S"]
    stale = _FakeFet(Qrr=d["Qrr"], trr=d["trr"], Rds_on=2.4e-3)   # no qrr_cond attr
    try:
        stale.Qrr_op(IF=33.3, didt=5.7e9)
    except qrr_model.LMFitError:
        pass
    else:
        raise AssertionError("Qrr_op must LMFitError on a stale object without qrr_cond")


class _FakeFet(SimpleNamespace):
    """Attribute bag carrying the real MosfetSpecs methods under test."""
    Qrr_op = MosfetSpecs.Qrr_op
    FoMqrr_op = MosfetSpecs.FoMqrr_op


def test_mosfet_method_and_fom():
    d = DS["IPP024N08NF2S"]
    fake = _FakeFet(Qrr=d["Qrr"], trr=d["trr"], Rds_on=2.4e-3,
                    qrr_cond=dict(IF=d["IF"], didt=d["didt"], Tj=d["Tj"]))
    q_ds = fake.Qrr_op(IF=d["IF"], didt=d["didt"], Tj=d["Tj"])
    assert abs(q_ds / d["Qrr"] - 1) < 1e-6      # exact at the calibration point
    detail = fake.Qrr_op(IF=33.3, didt=5.7e9, Tj=100.0, detail=True)
    assert detail["tj_extrapolated"] is True
    fom = fake.FoMqrr_op(IF=d["IF"], didt=d["didt"], Tj=d["Tj"])
    assert abs(fom / (2.4e-3 * d["Qrr"] * 1e3 * 1e9) - 1) < 1e-6
    # fit cache populated and reused
    assert len(fake._lm_fit_cache) == 1
    # GaN: zero Qrr short-circuits to 0.0 with no conditions needed
    gan = _FakeFet(Qrr=0, trr=math.nan, Rds_on=5e-3, qrr_cond=None)
    assert gan.Qrr_op(IF=30, didt=1e9) == 0.0


if __name__ == "__main__":
    for nm, fn in sorted(globals().items()):
        if nm.startswith("test_"):
            fn()
            print(f"{nm}: OK")
