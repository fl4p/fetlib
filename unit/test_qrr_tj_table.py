"""fit_n_tau_2rows: the Qrr(Tj) exponent from one matched datasheet table pair.

The IR/AUIR recovery sections print (Qrr, trr) at 25 C AND 125 C for one
(IF, di/dt) — direct N_TAU evidence from the table (fetlib#41), no chart
digitisation. One pair pins the exponent with zero degrees of freedom, so these
tests calibrate the estimator itself: a synthetic die with a KNOWN exponent must
round-trip, a displacement-dominated pair must refuse, and skipping the q0
subtraction must bias the exponent in the LOW (non-conservative) direction —
asserted as a direction, not just 'different'.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dslib.qrr_model import LMFitError, predict
from dslib.qrr_tj_fit import T0_K, fit_n_tau_2rows

IF, DIDT = 56.0, 100e6
TAU25, TM = 120e-9, 3e-9
T_RATIO = (125.0 + T0_K) / (25.0 + T0_K)


def synth(n_true, q0=0.0):
    """A die that obeys the tau-power law exactly: rows the model itself
    generates, plus an optional constant displacement charge in both."""
    cold = predict(TAU25, TM, IF, DIDT)
    hot = predict(TAU25 * T_RATIO ** n_true, TM, IF, DIDT)
    return dict(qrr_cold=cold["Qrr"] + q0, trr_cold=cold["trr"],
                qrr_hot=hot["Qrr"] + q0, trr_hot=hot["trr"])


@pytest.mark.parametrize("n_true", [0.4, 0.66, 1.0, 1.5])
def test_round_trips_a_known_exponent(n_true):
    r = fit_n_tau_2rows(IF=IF, didt=DIDT, **synth(n_true))
    assert abs(r["n_tau"] - n_true) < 0.02
    # the model generated the hot trr too, so the holdout must close
    assert abs(r["trr_hot_resid"]) < 0.02


def test_q0_subtraction_round_trips_a_contaminated_pair():
    q0 = 40e-9
    r = fit_n_tau_2rows(IF=IF, didt=DIDT, q0=q0, **synth(1.0, q0=q0))
    assert abs(r["n_tau"] - 1.0) < 0.02


def test_skipping_q0_biases_the_exponent_low_not_just_differently():
    # The constant inflates the cold charge relatively more, so a raw fit of a
    # contaminated pair UNDER-estimates n_tau -- the direction that
    # under-predicts hot losses. Pin the direction, not merely a mismatch.
    q0 = 40e-9
    r_raw = fit_n_tau_2rows(IF=IF, didt=DIDT, q0=0.0, **synth(1.0, q0=q0))
    assert r_raw["n_tau"] < 1.0 - 0.03


def test_non_growing_hot_charge_refuses():
    rows = synth(1.0)
    rows["qrr_hot"] = rows["qrr_cold"] * 0.95      # displacement-dominated shape
    with pytest.raises(LMFitError, match="does not exceed cold"):
        fit_n_tau_2rows(IF=IF, didt=DIDT, **rows)


def test_q0_consuming_the_charge_refuses():
    rows = synth(1.0)
    with pytest.raises(LMFitError, match="consumes"):
        fit_n_tau_2rows(IF=IF, didt=DIDT, q0=rows["qrr_cold"] * 1.01, **rows)


def test_holdout_reports_a_corrupt_hot_trr_without_moving_the_fit():
    rows = synth(1.0)
    r_clean = fit_n_tau_2rows(IF=IF, didt=DIDT, **rows)
    rows["trr_hot"] *= 2.0                          # printed time now nonsense
    r = fit_n_tau_2rows(IF=IF, didt=DIDT, **rows)
    assert abs(r["n_tau"] - r_clean["n_tau"]) < 1e-12   # holdout never enters the fit
    assert r["trr_hot_resid"] < -0.45                   # ... but the residual says so


def test_exponent_is_positive_by_construction():
    r = fit_n_tau_2rows(IF=IF, didt=DIDT, **synth(0.05))
    assert r["n_tau"] > 0
