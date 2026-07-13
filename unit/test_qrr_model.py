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
    """Qoss decontamination of the datasheet Qrr (#18 item 1)."""
    # IPP024: Qrr=242nC @ VR=40V, Qoss(0-40V)~105nC -> half-Qoss removes 52.5nC
    q = qrr_model.calibration_qrr(242e-9, 105e-9)
    assert abs(q - (242e-9 - 0.5 * 105e-9)) < 1e-15
    assert qrr_model.calibration_qrr(242e-9, None) == 242e-9      # no curve -> raw
    try:
        qrr_model.calibration_qrr(50e-9, 105e-9, fraction=1.0)    # eats the whole Qrr
    except qrr_model.LMFitError:
        pass
    else:
        raise AssertionError("calibration_qrr must fail loud when subtraction >= Qrr")


def test_predict_charge_partition():
    """predict() exposes the qa (pre-snap triangle) / qb (tail) split used for the
    HS/LS thermal attribution; they must sum to Qrr."""
    d = DS["IPP024N08NF2S"]
    fit = qrr_model.fit_lm(d["Qrr"], d["trr"], d["IF"], d["didt"])
    p = qrr_model.predict(fit["tau"], fit["TM"], 15.0, 2.85e9)
    assert abs(p["qa"] + p["qb"] - p["Qrr"]) < 1e-15
    assert p["qa"] > 0 and p["qb"] > 0


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
