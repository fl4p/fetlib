import math

import pytest

from dslib.qrr_model import predict
from dslib.qrr_tj_fit import (
    LMFitError,
    _interp,
    _load_points_csv,
    fit_n_tau,
    matched_ratio_grid,
    solve_tau_tm,
)


def _mk_csv(tmp_path, rows):
    p = tmp_path / "c.csv"
    p.write_text("x,y\n" + "\n".join(f"{a},{b}" for a, b in rows) + "\n")
    return p


def test_duplicate_x_collapsed_even_at_array_start(tmp_path):
    # a duplicate x pair at the START previously divided by zero in _interp
    xs, ys = _load_points_csv(_mk_csv(tmp_path, [(1.0, 10.0), (1.0, 12.0), (2.0, 20.0)]), "x", "y")
    assert xs == [1.0, 2.0]
    assert ys[0] == pytest.approx(11.0)
    assert _interp(xs, ys, 1.0) == pytest.approx(11.0)


def test_solve_tau_tm_roundtrips_and_flags_tm_edge():
    tau_true, tm_true = 3e-8, 4e-9
    p = predict(tau_true, tm_true, 20.0, 8e8)
    tau, tm, resid, edge = solve_tau_tm(p["Qrr"], p["irrm"], 20.0, 8e8)
    assert tau == pytest.approx(tau_true, rel=1e-3)
    assert tm == pytest.approx(tm_true, rel=1e-2)
    assert not edge
    # TM far below the search box: the round-trip guard alone would pass
    # (model insensitive to TM there) — the edge flag must fire instead.
    p2 = predict(3e-8, 1e-12, 20.0, 8e8)
    try:
        _tau, _tm, _resid, edge2 = solve_tau_tm(p2["Qrr"], p2["irrm"], 20.0, 8e8)
    except LMFitError:
        return  # refusing outright is also acceptable
    assert edge2, "search-box-pinned TM must be flagged"


def _synth_curves(tau25, tm, n_true, xs, kind, anchor_didt, anchor_if,
                  tj_hot=125.0, qcap=0.0):
    t_ratio = (tj_hot + 273.15) / (25.0 + 273.15)
    tau_hot = tau25 * t_ratio**n_true
    cold, hot = [], []
    for x in xs:
        args = (x, anchor_didt) if kind == "if" else (anchor_if, x)
        cold.append(predict(tau25, tm, *args)["Qrr"] + qcap)
        hot.append(predict(tau_hot, tm, *args)["Qrr"] + qcap)
    return (list(xs), cold), (list(xs), hot)


def test_fit_recovers_known_exponent():
    tau25, tm, n_true = 3e-8, 4e-9, 0.7
    xs = [5.0 + i for i in range(26)]
    cold, hot = _synth_curves(tau25, tm, n_true, xs, "if", 8e8, 20.0)
    anchor = dict(qrr_c=_interp(*cold, 20.0), irm_a=predict(tau25, tm, 20.0, 8e8)["irrm"],
                  if_a=20.0, didt_a_per_s=8e8)
    fit = fit_n_tau(anchor, [("if", matched_ratio_grid(cold, hot))])
    assert fit["n_tau"] == pytest.approx(n_true, abs=0.01)
    assert not fit["edge_pinned"]


def test_uncorrected_capacitive_share_biases_n_low():
    """The review finding pinned as physics: a temperature-independent additive
    share dilutes the measured ratio, so fitting RAW chart curves must yield a
    SMALLER exponent than the true diffusion exponent."""
    tau25, tm, n_true = 3e-8, 4e-9, 0.7
    xs = [5.0 + i for i in range(26)]
    cold_raw, hot_raw = _synth_curves(tau25, tm, n_true, xs, "if", 8e8, 20.0,
                                      qcap=0.15 * 90e-9)
    anchor = dict(qrr_c=_interp(*cold_raw, 20.0),
                  irm_a=predict(tau25, tm, 20.0, 8e8)["irrm"],
                  if_a=20.0, didt_a_per_s=8e8)
    fit = fit_n_tau(anchor, [("if", matched_ratio_grid(cold_raw, hot_raw))])
    assert fit["n_tau"] < n_true - 0.03, (
        "contaminated fit must sit visibly below the true diffusion exponent")


# ---------------------------------------------- three-state wiring (qrr_model)

def test_resolve_n_tau_three_states():
    from dslib.qrr_model import N_TAU, resolve_n_tau

    m = resolve_n_tau("ao:AOT414")
    assert m["state"] == "measured-fit" and m["n_tau"] == pytest.approx(0.660)
    fam = resolve_n_tau("ao:AOD4126")  # AO part WITHOUT its own valid fit
    assert fam["state"] == "ao-family-pool" and fam["n_tau"] == pytest.approx(0.657)
    for part in ("infineon:IPP024N08NF2S", None, "onsemi:FDPF085N10A"):
        c = resolve_n_tau(part)
        assert c["state"] == "conservative-bound" and c["n_tau"] == N_TAU


def test_best_lm_fit_stamps_resolved_exponent():
    from dslib.qrr_model import best_lm_fit

    cond = dict(IF=20.0, didt=8e8, Tj=25.0)
    fit_ao = best_lm_fit(100e-9, 30e-9, cond, part="ao:AOT414")
    assert fit_ao["n_tau"] == pytest.approx(0.660)
    assert fit_ao["n_tau_state"] == "measured-fit"
    fit_other = best_lm_fit(100e-9, 30e-9, cond, part="infineon:IPP024N08NF2S")
    assert fit_other["n_tau_state"] == "conservative-bound"
    # part omitted: stamped conservative, never silent/absent
    fit_none = best_lm_fit(100e-9, 30e-9, cond)
    assert fit_none["n_tau_state"] == "conservative-bound"


def test_tau_at_tj_override_matches_convention():
    from dslib.qrr_model import N_TAU, tau_at_tj

    t0 = 3e-8
    assert tau_at_tj(t0, 100.0) == pytest.approx(
        t0 * ((373.15) / (298.15)) ** N_TAU)
    assert tau_at_tj(t0, 100.0, n_tau=0.657) == pytest.approx(
        t0 * ((373.15) / (298.15)) ** 0.657)
    # measured exponent must predict LESS hot lifetime growth than the bound
    assert tau_at_tj(t0, 100.0, n_tau=0.657) < tau_at_tj(t0, 100.0)
