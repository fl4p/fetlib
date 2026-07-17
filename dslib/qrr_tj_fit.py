"""Fit the Qrr(Tj) tau exponent from human-verified 25/125 C recovery curves.

fetlib#37's remaining gap: ``N_TAU = 1.2`` in :mod:`dslib.qrr_model` is a MODEL
GUESS calibrated to the "Qrr doubles 25->125 C" folk rule, because datasheets
quote no Qrr(Tj) curve. The dsdig reverse-recovery digitizer produced
human-verified Qrr/Irm curves at BOTH temperatures for a set of AO trench
dies (dual-agent green + human gate) — the first measured evidence for the Tj
axis.

Design (curvefet record): fit the NORMALIZED RATIO Qrr(125C)/Qrr(25C) at
matched (IF, di/dt), so the existing operating-point law keeps scale and this
fit owns ONLY temperature:

1. Calibrate ``(tau25, TM)`` once per part at the reference anchor (the
   cross-panel-checked point, e.g. IF=20 A / 800 A/us) from measured
   (Qrr, IRRM) at 25 C — the same LM forward model the consumer uses.
2. Hold TM (the N_TAU law scales ONLY tau, in lock-step with the consumer)
   and fit ``n_tau`` minimizing squared log-ratio error of the model ratio
   against the measured ratio across ALL matched grid points of both figures
   (Qrr vs IF and Qrr vs di/dt).
3. Holdout: the fitted (tau125, TM) predicts IRRM at 125 C — never used in
   the fit; its error is reported per part.
4. Pool across dies (median/IQR) with leave-one-part-out validation; the
   legacy 1.2 survives only as the conservative upper bound.

Nothing here changes the consumer: results are review evidence first
(three-state wiring into qrr_model is a separate, human-gated step).
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from dslib.qrr_model import LMFitError, predict

T0_K = 273.15


def _golden(f, lo, hi, iters=90):
    invphi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c = b - invphi * (b - a)
    d = a + invphi * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - invphi * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + invphi * (b - a)
            fd = f(d)
    return 0.5 * (a + b)


def _bisect_increasing(f, lo, hi, target, iters=80):
    """Solve f(x)=target for f monotone increasing on [lo, hi]."""
    if f(lo) > target or f(hi) < target:
        raise LMFitError(f"target {target:g} outside f({lo:g})..f({hi:g})")
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def solve_tau_tm(qrr_c, irm_a, if_a, didt_a_per_s):
    """Calibrate (tau, TM) so the LM forward model reproduces the measured
    (Qrr, IRRM) at one anchor point. Qrr is monotone increasing in tau at
    fixed TM (inner bisection); TM is then chosen so predicted IRRM matches
    (outer golden section on log10 TM); both residuals are checked, not
    assumed."""
    if not (qrr_c > 0 and irm_a > 0 and if_a > 0 and didt_a_per_s > 0):
        raise LMFitError("anchor values must be positive")

    def qrr_of_tau(tau, tm):
        return predict(tau, tm, if_a, didt_a_per_s)["Qrr"]

    def tau_for_qrr(tm):
        lo, hi = 1e-10, 1e-5
        while qrr_of_tau(hi, tm) < qrr_c:
            hi *= 4.0
            if hi > 1.0:
                raise LMFitError("tau solve diverged")
        return _bisect_increasing(lambda t: qrr_of_tau(t, tm), lo, hi, qrr_c)

    def irm_err(log_tm):
        tm = 10.0 ** log_tm
        try:
            tau = tau_for_qrr(tm)
            irm = predict(tau, tm, if_a, didt_a_per_s)["irrm"]
        except LMFitError:
            return 1e9
        return abs(math.log(irm / irm_a))

    lo_log, hi_log = -10.0, -5.0
    log_tm = _golden(irm_err, lo_log, hi_log)
    tm = 10.0 ** log_tm
    tau = tau_for_qrr(tm)
    pred = predict(tau, tm, if_a, didt_a_per_s)
    irm_pred, qrr_pred = pred["irrm"], pred["Qrr"]
    resid = dict(qrr_rel=qrr_pred / qrr_c - 1.0, irm_rel=irm_pred / irm_a - 1.0)
    if abs(resid["qrr_rel"]) > 0.02 or abs(resid["irm_rel"]) > 0.10:
        raise LMFitError(f"anchor calibration does not round-trip: {resid}")
    # In the TM << tau regime the model grows insensitive to TM, so a
    # search-box-pinned TM can be decades wrong yet still pass the round-trip
    # bounds (review finding): surface the pin instead of trusting residuals.
    tm_edge_pinned = (log_tm - lo_log < 0.05) or (hi_log - log_tm < 0.05)
    return tau, tm, resid, tm_edge_pinned


def _interp(xs, ys, x):
    """Linear interpolation, refusing extrapolation (endpoint float noise
    within 1e-9 relative is clamped, not refused)."""
    tol = 1e-9 * max(abs(xs[0]), abs(xs[-1]), 1.0)
    if xs[0] - tol <= x < xs[0]:
        x = xs[0]
    elif xs[-1] < x <= xs[-1] + tol:
        x = xs[-1]
    if not xs[0] <= x <= xs[-1]:
        raise LMFitError(f"{x:g} outside curve span {xs[0]:g}..{xs[-1]:g}")
    for i in range(1, len(xs)):
        if x <= xs[i]:
            w = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + w * (ys[i] - ys[i - 1])
    return ys[-1]


def _load_points_csv(path, x_col, y_col, y_scale=1.0):
    xs, ys = [], []
    with Path(path).open(newline="") as fh:
        for row in csv.DictReader(fh):
            xs.append(float(row[x_col]))
            ys.append(float(row[y_col]) * y_scale)
    order = sorted(range(len(xs)), key=xs.__getitem__)
    # Collapse exact-duplicate x (the digitizer emits them; a duplicate pair at
    # array start would divide by zero in _interp) by averaging their y's.
    out_x, out_y = [], []
    for i in order:
        if out_x and xs[i] == out_x[-1]:
            out_y[-1] = 0.5 * (out_y[-1] + ys[i])
        else:
            out_x.append(xs[i])
            out_y.append(ys[i])
    return out_x, out_y


def matched_ratio_grid(cold, hot, n=25):
    """Measured hot/cold ratio at matched x over the overlapping span."""
    lo = max(cold[0][0], hot[0][0])
    hi = min(cold[0][-1], hot[0][-1])
    if hi <= lo:
        raise LMFitError("no overlapping span between temperatures")
    out = []
    for i in range(n):
        x = lo + (hi - lo) * i / (n - 1)
        q_cold = _interp(*cold, x)
        q_hot = _interp(*hot, x)
        if q_cold <= 0 or q_hot <= 0:
            continue
        out.append((x, q_hot / q_cold))
    return out


def fit_n_tau(anchor, grids, tj_cold=25.0, tj_hot=125.0, n_lo=0.0, n_hi=2.5):
    """Fit the tau temperature exponent to the measured Qrr ratios.

    anchor: dict(qrr_c, irm_a, if_a, didt_a_per_s) at ``tj_cold``.
    grids: list of (kind, points) where kind is "if" (x = IF [A], di/dt fixed
    at the anchor) or "didt" (x = di/dt [A/s], IF fixed at the anchor) and
    points are (x, measured_ratio) pairs from :func:`matched_ratio_grid`.
    """
    tau25, tm, anchor_resid, tm_edge_pinned = solve_tau_tm(**anchor)
    t_ratio = (tj_hot + T0_K) / (tj_cold + T0_K)

    def model_ratio(n, kind, x):
        tau_hot = tau25 * t_ratio**n
        if kind == "if":
            args_c = (x, anchor["didt_a_per_s"])
        else:
            args_c = (anchor["if_a"], x)
        q_cold = predict(tau25, tm, *args_c)["Qrr"]
        q_hot = predict(tau_hot, tm, *args_c)["Qrr"]
        return q_hot / q_cold

    def sse(n):
        err = 0.0
        for kind, points in grids:
            for x, r_meas in points:
                if r_meas <= 0:
                    continue
                err += math.log(model_ratio(n, kind, x) / r_meas) ** 2
        return err

    n_fit = _golden(sse, n_lo, n_hi)
    n_points = sum(len(p) for _k, p in grids)
    rms = math.sqrt(sse(n_fit) / max(1, n_points))
    tau_hot = tau25 * t_ratio**n_fit
    return dict(
        n_tau=n_fit, tau25_s=tau25, tm_s=tm, tau_hot_s=tau_hot,
        anchor_residual=anchor_resid, log_ratio_rms=rms, n_grid_points=n_points,
        n_grid_points_per_kind={k: len(p) for k, p in grids},
        # Qrr temperature ratio the fit implies at the anchor condition itself
        anchor_qrr_ratio=model_ratio(n_fit, "if", anchor["if_a"]),
        edge_pinned=(n_fit - n_lo < 0.02 or n_hi - n_fit < 0.02
                     or tm_edge_pinned),
        tm_edge_pinned=tm_edge_pinned,
        model_ratio_fn_args=dict(tau25_s=tau25, tm_s=tm),
    )
