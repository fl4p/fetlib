"""Qrr(IF, di/dt, Tj) curve model from the single datasheet point (fl4p/fetlib#37).

Datasheets quote body-diode Qrr/trr at ONE operating point (IF, di/dt, Tj — curated per
part in dslib/qrr_conditions.py). A real converter commutates at a different IF, a
di/dt often 5-10x the datasheet's, and a hot junction — so the flat scalar (and any
FoMqrr ranking built on it) uses the wrong charge at the operating point.

This module inverts the two Lauritzen-Ma charge-control macro-parameters (tau, TM)
from the datasheet (Qrr, trr) pair — closed form, no SPICE — and predicts
(Qrr, trr, IRRM) anywhere in the (IF, di/dt, Tj) operating space:

    i = (qE - qM)/TM                       (terminal current)
    dqM/dt = -qM/tau + (qE - qM)/TM        (diffusion-charge continuity)

Forcing i(t) = IF - a*t (the constant-di/dt DPT/datasheet condition) from the forward
steady state qM(0) = tau*IF, the junction snaps when the emitter charge is exhausted;
writing IRRM for the peak reverse current and td = tau*TM/(tau + TM) for the post-snap
decay constant, the two observables are

    IRRM = a*(tau - td)*(1 - exp(-(IF + IRRM)/(a*tau)))                     ... (1)
    Qrr  = IRRM^2/(2a) + IRRM*td            (ta triangle + exponential tail) ... (2)
    trr  = IRRM/a + td*ln(1/K_TRR)          (ta + tail to K_TRR of IRRM)     ... (3)

(2)+(3) give (IRRM, td) in closed form; (1) is a scalar root-solve for tau. The fit is
EXACT at the calibration point; elsewhere it is a physically-anchored PREDICTION —
linear-ish in IF (charge ~ IF*tau), sub-linear in di/dt (the axis the SPICE TT model
misses entirely), and better than either default engineers use (flat Qrr, or
linear-in-IF with no di/dt). For a load-bearing loss number, validate on the bench.

The math is a verbatim port of dcdc-tools/loss/lib/lm_diode.py (same repo family, which
also emits the SPICE subcircuit form) so the analytic curve and the transient deck stay
in lock-step. References: Lauritzen & Ma, IEEE TPE 6(2) 1991; Zaikin, SIMULTECH 2023
(DOI 10.5220/0012096500003546); Bououd 2024 (HAL 04591673) validates two constant
macro-parameters across a wide operating range.

ASSUMPTIONS a consumer must surface (see fl4p/fetlib#37 item 4):
  * K_TRR = 0.1 — the datasheet trr end criterion (reverse current decayed to 10% of
    IRRM). Vendors rarely state it. It only sets the ta/tail split of trr; fitted Qrr
    is insensitive to it (IRRM moves ~10% between K=0.05 and 0.25).
  * N_TAU = 1.2 — tau(Tj) = tau0*(Tj_K/Tfit_K)^N_TAU. Datasheets give NO Qrr(Tj)
    curve. Recalibrated 2026-07-13 (#18) so the MODEL's Qrr doubles 25->125 C per the
    empirical Si rule (see the constant's comment); in lock-step with lm_diode.py.
    The Tj axis is a MODEL GUESS, not a datasheet fact — Qrr_op results at
    Tj != Tj_fit carry `tj_extrapolated=True`.
  * Basic LM is calibrated for SOFT recovery (Si trench body diodes are; snappy SiC
    needs the Ma 2013 three-charge extension). VR does not enter the charge dynamics.
"""
import math

K_TRR = 0.1   # datasheet trr end criterion (fraction of IRRM) — see module docstring
# tau temperature exponent — since 2026-07-17 the CONSERVATIVE-BOUND state of a
# three-state resolution (see resolve_n_tau / dslib/qrr_tj_specs.py). History:
# recalibrated 2026-07-13 (#18) so the MODEL's Qrr doubles 25->125 C per the empirical
# Si folk rule (n = 1.16-1.19 across IPP018/019/022/024; 1.2 rounded; the older 2.0
# doubled TAU instead, over-predicting Qrr(125C) ~3.2x). MEASURED evidence (five
# human-verified AO dies with 25/125 C charts, dsdig-verify-backlog/qrr-tj-fit/) puts
# the diffusion exponent at ~0.66 — the doubles rule is ~2x too steep, so 1.2
# OVER-predicts hot Qrr for parts without their own measurement: retained deliberately
# as the conservative default (the safe direction for a loss budget), never as fact.
# Kept in lock-step with loss/lib/lm_diode.py (test_lm_parity pins equality).
N_TAU = 1.2

# Fraction of the junction displacement charge Qoss(VR) assumed to be counted INSIDE the
# datasheet Qrr integral (JESD24-10-style). The datasheet Qrr is measured while the diode
# charges to VR, so it contains a capacitive share that the LM fit would otherwise
# mis-attribute to diffusion charge — double-counting it against a separately-booked Coss
# loss bucket. CALIBRATED 2026-07-13 against 36 dies whose datasheets quote Qrr at TWO
# di/dt points AND a Qoss spec (Infineon NM6/LM6/M5 families + onsemi FDMS, extracted
# from the local datasheet library): fit on one point, predict the other, sweep the
# fraction. Median out-of-sample |err| minimizes flat at f = 0.10-0.15 (13.3-13.7%,
# median bias -5% in the fit-low/predict-high direction the loss tool uses); f = 0
# gives 19.9% (+7% bias) and the old assumption f = 0.5 gives 47-51% (-47% bias, i.e.
# systematic Qrr UNDER-prediction) plus fit failures on small-charge dies. The per-die
# implied offset q0 (root-solved so both rows are LM-consistent) has median 0.13*Qoss.
# The true share still varies by family (unit test enforces the band only loosely).
QRR_QOSS_FRACTION = 0.1


def calibration_qrr(qrr_ds, qoss_vr, fraction=QRR_QOSS_FRACTION):
    """Diffusion-only calibration charge: datasheet Qrr minus the assumed capacitive
    share `fraction`*Qoss(VR) counted inside the Qrr integral (#18 item 1).

    qoss_vr [C] is the part's output charge integrated 0..VR at the Qrr test voltage
    (from the digitized Coss(V) curve). Pass qoss_vr=None to skip decontamination
    (returns qrr_ds unchanged) — consumers should then say so in provenance.
    Raises LMFitError when the subtraction consumes the whole Qrr (the contamination
    assumption is inconsistent with the datasheet pair — fail loud)."""
    if qoss_vr is None:
        return qrr_ds
    q = qrr_ds - fraction * qoss_vr
    if not (q > 0):
        raise LMFitError(
            f"Qoss decontamination consumed the whole datasheet Qrr "
            f"({qrr_ds*1e9:.0f} nC - {fraction:g}*{qoss_vr*1e9:.0f} nC <= 0) — "
            f"check Qoss(VR)/fraction; this pair cannot be diffusion-only-fitted")
    return q


class LMFitError(ValueError):
    """The datasheet (Qrr, trr) pair is not representable by a Lauritzen-Ma diode."""


def fit_lm(Qrr, trr, IF, didt, tj_fit=25.0):
    """Fit (tau, TM) at the datasheet operating point. Returns a dict with the fitted
    params plus the intermediates (IRRM, td) for reporting/validation.

    Qrr [C], trr [s], IF [A], didt [A/s], tj_fit [degC] = the Tj those were measured at.
    """
    for nm, v in (("Qrr", Qrr), ("trr", trr), ("IF", IF), ("didt", didt)):
        if v is None or not math.isfinite(v) or v <= 0:
            raise LMFitError(f"Lauritzen-Ma fit needs a positive finite {nm} (got {v!r})")

    a = float(didt)
    L = math.log(1.0 / K_TRR)

    # (2)+(3) -> quadratic in IRRM:  A*IRRM^2 + B*IRRM - Qrr = 0
    A = (L - 2.0) / (2.0 * a * L)
    B = trr / L
    disc = B * B + 4.0 * A * Qrr
    if disc < 0:
        raise LMFitError(f"no Lauritzen-Ma solution for Qrr={Qrr*1e9:.1f}nC, trr={trr*1e9:.1f}ns "
                         f"at di/dt={a/1e6:.0f}A/us (negative discriminant)")
    # Citardauq form: irrm = 2C/(B + sqrt(disc)) — algebraically the same positive root as
    # (-B + sqrt(disc))/(2A) but with NO catastrophic cancellation (B and sqrt(disc) are
    # close), and it stays finite as A -> 0. A changes sign at K_TRR = e^-2 = 0.1353
    # (L = 2); for K_TRR > that, A < 0 and the quadratic has two positive roots — this
    # form selects the SMALLER (physical) one in both sign cases.
    irrm = 2.0 * Qrr / (B + math.sqrt(disc))
    if irrm <= 0:
        raise LMFitError(f"fitted IRRM<=0 for Qrr={Qrr*1e9:.1f}nC, trr={trr*1e9:.1f}ns")

    # ta = IRRM/a must fit inside trr, else the datasheet pair is self-inconsistent for LM
    # (an all-triangle recovery with no tail — trr too short for its own Qrr).
    ta = irrm / a
    td = (trr - ta) / L
    if td <= 0:
        raise LMFitError(
            f"datasheet trr={trr*1e9:.1f}ns is shorter than the current-ramp time "
            f"ta=IRRM/(di/dt)={ta*1e9:.1f}ns implied by Qrr={Qrr*1e9:.1f}nC at "
            f"di/dt={a/1e6:.0f}A/us — no Lauritzen-Ma (tau,TM) reproduces this pair. "
            f"Check the Qrr/trr entries and dslib/qrr_conditions.py.")

    # (1): solve  f(tau) = a*(tau-td)*(1 - exp(-(IF+IRRM)/(a*tau))) - IRRM = 0  for tau > td.
    t0 = (IF + irrm) / a

    def f(tau):
        return a * (tau - td) * (1.0 - math.exp(-t0 / tau)) - irrm

    lo = td * (1.0 + 1e-9)
    hi = max(10.0 * td, 10.0 * t0, 1e-6)
    # f(lo) = -IRRM < 0; f grows without bound in tau -> bracket then bisect.
    n = 0
    while f(hi) < 0:
        hi *= 4.0
        n += 1
        if n > 60:
            raise LMFitError("could not bracket the Lauritzen-Ma tau root")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    tau = 0.5 * (lo + hi)
    TM = tau * td / (tau - td)

    return dict(tau=tau, TM=TM, tau0=tau, irrm=irrm, td=td, ta=ta,
                Qrr=Qrr, trr=trr, IF=IF, didt=a, tj_fit=tj_fit)


def predict(tau, TM, IF, didt):
    """Forward model: (tau, TM) -> (IRRM, Qrr, trr) at an operating point. The inverse
    of fit_lm — verifies a fit round-trips, and predicts recovery away from the
    datasheet point. IF >= 0 (0 = no stored charge -> Qrr 0); didt/tau/TM must be
    positive finite — same fail-loud LMFitError contract as fit_lm."""
    for nm, v, lo_ok in (("tau", tau, False), ("TM", TM, False),
                         ("IF", IF, True), ("didt", didt, False)):
        if v is None or not math.isfinite(v) or v < 0 or (v == 0 and not lo_ok):
            raise LMFitError(f"predict needs a {'non-negative' if lo_ok else 'positive'} "
                             f"finite {nm} (got {v!r})")
    a = float(didt)
    td = tau * TM / (tau + TM)

    # solve IRRM = a*(tau-td)*(1 - exp(-(IF+IRRM)/(a*tau)))  (monotone in IRRM -> bisect)
    def g(ir):
        return a * (tau - td) * (1.0 - math.exp(-(IF + ir) / (a * tau))) - ir

    lo, hi = 0.0, max(1.0, 10.0 * a * tau)
    n = 0
    while g(hi) > 0:
        hi *= 4.0
        n += 1
        if n > 60:   # same defensive cap as fit_lm's bracket loop
            raise LMFitError("could not bracket IRRM in predict()")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if g(mid) > 0:
            lo = mid
        else:
            hi = mid
    irrm = 0.5 * (lo + hi)
    qa = irrm * irrm / (2.0 * a)          # pre-snap triangle (diode still low-voltage)
    qb = irrm * td                         # post-snap exponential tail (diode blocking)
    trr = irrm / a + td * math.log(1.0 / K_TRR)
    return dict(irrm=irrm, Qrr=qa + qb, trr=trr, td=td, qa=qa, qb=qb)


def resolve_n_tau(part=None):
    """Three-state Qrr(Tj) exponent resolution (Fab 2026-07-17).

    `part` is a "mfr:MPN" string, a (mfr, mpn) pair, or None. Returns
    dict(n_tau, state, source) with state in:
    measured-fit | ao-family-pool | conservative-bound.
    Unknown/absent parts get the conservative bound — never silently the
    measured value of a different family.
    """
    from dslib.qrr_tj_specs import (
        AO_FAMILY_POOL_N_TAU, MEASURED_SOURCE, QRR_TJ_MEASURED)
    mfr = mpn = None
    if isinstance(part, str) and ":" in part:
        mfr, mpn = part.split(":", 1)
    elif isinstance(part, (tuple, list)) and len(part) == 2:
        mfr, mpn = part
    if mfr is not None:
        key = (str(mfr).lower(), str(mpn))
        if key in QRR_TJ_MEASURED:
            return dict(n_tau=QRR_TJ_MEASURED[key], state="measured-fit",
                        source=MEASURED_SOURCE)
        if key[0] == "ao":
            return dict(n_tau=AO_FAMILY_POOL_N_TAU, state="ao-family-pool",
                        source=MEASURED_SOURCE)
    return dict(n_tau=N_TAU, state="conservative-bound",
                source="legacy 'Qrr doubles' rule — no measured Tj data for this family")


def tau_at_tj(tau0, tj, tj_fit=25.0, n_tau=None):
    """Scale the fitted carrier lifetime from the datasheet Tj to the operating Tj.

    `n_tau=None` applies the conservative-bound N_TAU; pass a resolved
    per-part exponent (fit["n_tau"] from best_lm_fit(part=...)) to apply
    measured evidence — deck and analytic consumers must use the SAME value
    (read it off the shared fit record, don't resolve twice)."""
    n = N_TAU if n_tau is None else float(n_tau)
    return tau0 * ((tj + 273.15) / (tj_fit + 273.15)) ** n


def fit_lm_2pt(p_lo, p_hi, tj_fit=25.0):
    """Two-point (tau, TM, q0) fit from datasheet rows at TWO di/dt values.

    p_lo/p_hi: dict(IF, didt, Qrr, trr) — same IF, p_lo at the lower di/dt.
    q0 is the constant capacitive share of the measured Qrr integral (Qoss
    displacement charge counted by the JESD-style integration): solved so that
    a diffusion-only LM fit on (Qrr_lo - q0, trr_lo) reproduces (Qrr_hi - q0)
    at didt_hi exactly. This replaces the global QRR_QOSS_FRACTION assumption
    with the part's own data (fl4p/fetlib#37; calibrated 2026-07-13: implied
    per-die offsets median 0.13*Qoss across 21 dies).

    Returns the fit_lm dict plus q0 [C] and trr_hi_resid — the SECOND trr row
    is not consumed by the fit (3 observables Qrr_lo/trr_lo/Qrr_hi determine
    the 3 parameters), so its prediction error is a free residual check.

    Raises LMFitError when the rows differ in IF, or when no q0 in
    [0, ~min(Qrr)) makes the pair LM-consistent (contamination-dominated
    pairs: Qrr ~flat or falling with di/dt, e.g. ISK057N04LM6/ISC320N12LM6 —
    those cannot be diffusion-fitted; fail loud, never force a fit)."""
    if p_lo["didt"] > p_hi["didt"]:
        p_lo, p_hi = p_hi, p_lo
    if p_lo["IF"] != p_hi["IF"]:
        raise LMFitError(f"two-point fit needs equal IF rows "
                         f"(got {p_lo['IF']} A and {p_hi['IF']} A)")
    if p_lo["didt"] == p_hi["didt"]:
        raise LMFitError("two-point fit needs two DISTINCT di/dt rows")
    IF = float(p_lo["IF"])

    def err(q0):
        f = fit_lm(p_lo["Qrr"] - q0, p_lo["trr"], IF, p_lo["didt"], tj_fit=tj_fit)
        return (predict(f["tau"], f["TM"], IF, p_hi["didt"])["Qrr"]
                - (p_hi["Qrr"] - q0))

    lo, hi = 0.0, min(p_lo["Qrr"], p_hi["Qrr"]) * 0.98
    try:
        f_lo = err(lo)
    except LMFitError as e:
        raise LMFitError(f"two-point fit: low row not LM-representable ({e})")
    f_hi = None
    while hi > lo + 1e-12:
        try:
            f_hi = err(hi)
            break
        except LMFitError:
            hi *= 0.85  # subtraction consumed the pair; walk back into range
    if f_hi is None or f_lo * f_hi > 0:
        raise LMFitError(
            "no LM-consistent capacitive offset q0 in [0, min(Qrr)) — the pair "
            "is contamination-dominated or non-LM (Qrr ~flat/falling with di/dt)")
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        try:
            f_mid = err(mid)
        except LMFitError:
            hi = mid
            continue
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    q0 = 0.5 * (lo + hi)
    fit = fit_lm(p_lo["Qrr"] - q0, p_lo["trr"], IF, p_lo["didt"], tj_fit=tj_fit)
    trr_hi = predict(fit["tau"], fit["TM"], IF, p_hi["didt"])["trr"]
    # explicit charge names at the calibration point — the inherited fit["Qrr"]
    # (the diffusion charge the fit consumed) is ambiguous next to q0:
    return dict(fit, q0=q0, trr_hi_resid=trr_hi / p_hi["trr"] - 1.0,
                qrr_diffusion=p_lo["Qrr"] - q0, qrr_measured_equiv=p_lo["Qrr"])


def _pick_2pt_rows(points):
    """Best same-IF row pair from a qrr_points list: the IF group with the
    widest di/dt span (all curated rows are Tj=25 C)."""
    by_if: dict = {}
    for r in points or []:
        by_if.setdefault(float(r["IF"]), []).append(r)
    best = None
    for rows in by_if.values():
        rows = sorted(rows, key=lambda r: r["didt"])
        if rows[-1]["didt"] <= rows[0]["didt"]:
            continue
        span = rows[-1]["didt"] / rows[0]["didt"]
        if best is None or span > best[0]:
            best = (span, rows[0], rows[-1])
    if best is None:
        raise LMFitError("qrr_points has no same-IF pair with distinct di/dt")
    p_lo, p_hi = best[1], best[2]
    # the pair must also share Tj and VR: mixed Tj would fold the temperature
    # law into (tau, TM); mixed VR folds a Qoss(VR) DIFFERENCE into q0 instead
    # of the capacitive share. Today's generated corpus is clean on both, but
    # the guard must not depend on that staying true (review 2026-07-13).
    if p_lo.get("Tj", 25.0) != p_hi.get("Tj", 25.0):
        raise LMFitError(f"two-point rows mix Tj ({p_lo.get('Tj')} / "
                         f"{p_hi.get('Tj')} C) — cannot diffusion-fit across "
                         f"the temperature law")
    if p_lo.get("VR") != p_hi.get("VR"):
        raise LMFitError(f"two-point rows mix VR ({p_lo.get('VR')} / "
                         f"{p_hi.get('VR')} V) — q0 would absorb a Qoss(VR) "
                         f"difference, not the capacitive share")
    return p_lo, p_hi


def qrr_op_2pt(points, IF, didt, Tj=25.0, _fit_cache=None):
    """Two-point sibling of qrr_op(): calibrate (tau, TM, q0) from the part's
    own two-di/dt datasheet rows (dslib/qrr_points.py), predict at the
    operating point. Headline Qrr is the MEASURED-EQUIVALENT charge
    (diffusion + q0) for comparability with the single-point path and
    FoM ranking; `qrr_diffusion` carries the stored-charge-only prediction
    (what a loss model books separately from Coss/Eoss)."""
    p_lo, p_hi = _pick_2pt_rows(points)
    tj_fit = float(p_lo.get("Tj", 25.0))
    key = ("2pt", p_lo["Qrr"], p_lo["trr"], p_lo["didt"],
           p_hi["Qrr"], p_hi["trr"], p_hi["didt"], p_lo["IF"], tj_fit)
    fit = _fit_cache.get(key) if _fit_cache is not None else None
    if fit is None:
        fit = fit_lm_2pt(p_lo, p_hi, tj_fit=tj_fit)
        if _fit_cache is not None:
            _fit_cache[key] = fit
    tau = tau_at_tj(fit["tau0"], Tj, tj_fit)
    p = predict(tau, fit["TM"], IF, didt)
    return dict(Qrr=p["Qrr"] + fit["q0"], qrr_diffusion=p["Qrr"], q0=fit["q0"],
                trr=p["trr"], irrm=p["irrm"], td=p["td"],
                tau=tau, TM=fit["TM"], tj_extrapolated=(Tj != tj_fit),
                method="2pt", fit=fit)


def best_lm_fit(Qrr, trr, cond, qrr_points=None, qoss_vr=None, part=None):
    """ONE calibration decision point, shared by the analytic Qrr loss bucket
    (dcdc-tools loss.py) and the SPICE deck emitter (loss/lib/lm_diode.py) so
    the two can never fit different diodes again (qrr-lm coordination
    2026-07-13; the deck/bucket split was audit finding (b)).

    Preference order:
      1. method='2pt' — per-part (tau, TM, q0) from the part's own two-di/dt
         datasheet rows (dslib/qrr_points.py) when a same-IF pair exists and
         admits a diffusion-only fit. `cond` may be None on this path.
      2. method='1pt' — single-point fit on calibration_qrr(Qrr, qoss_vr).
         q0 = QRR_QOSS_FRACTION*qoss_vr; with qoss_vr=None the fit runs on the
         RAW datasheet Qrr with q0=0.0 and decontaminated=False — the caller
         must surface that (it over-states diffusion charge).
    A 2pt attempt that admits no fit falls back EXPLICITLY
    (fallback_from_2pt carries the reason); no conditions at all raises.

    `part` ("mfr:MPN") resolves the Qrr(Tj) exponent ONCE, here at the shared
    decision point: the fit record carries n_tau/n_tau_state/n_tau_source and
    every consumer must scale tau via tau_at_tj(..., n_tau=fit["n_tau"]) —
    resolving separately in the deck and the bucket is the same divergence
    class this function was created to kill. part=None resolves to the
    conservative bound (stamped, never silent).

    CONTRACT (encoded in tests): q0 is calibration PROVENANCE only — the
    capacitive share excluded from the diffusion fit. predict(tau, TM, ...)
    on this fit yields the DIFFUSION charge, which is what both the deck and
    the loss bucket book; consumers must NOT add q0 back (the Coss/Eoss
    bucket owns displacement charge — adding q0 would recreate the exact
    double-count this function exists to prevent).
    """
    n_res = resolve_n_tau(part)
    n_stamp = dict(n_tau=n_res["n_tau"], n_tau_state=n_res["state"],
                   n_tau_source=n_res["source"])
    fallback = None
    if qrr_points:
        try:
            p_lo, p_hi = _pick_2pt_rows(qrr_points)
            fit = fit_lm_2pt(p_lo, p_hi, tj_fit=float(p_lo.get("Tj", 25.0)))
            return dict(fit, method="2pt", decontaminated=True, **n_stamp)
        except LMFitError as e:
            fallback = str(e)
    if cond is None:
        raise LMFitError(
            "no reverse-recovery test conditions — add the part to "
            "dslib/qrr_conditions.py (see fl4p/fetlib#37)"
            + (f" (2pt path failed first: {fallback})" if fallback else ""))
    q_cal = calibration_qrr(Qrr, qoss_vr)
    fit = fit_lm(q_cal, trr, cond.get("IF"), cond.get("didt"),
                 tj_fit=float(cond.get("Tj", 25.0)))
    # explicit charge names (same keys as the 2pt path): fit["Qrr"] alone is
    # ambiguous beside q0 — name what the fit consumed and what was measured
    out = dict(fit, method="1pt", q0=Qrr - q_cal,
               qrr_diffusion=q_cal, qrr_measured_equiv=Qrr,
               decontaminated=qoss_vr is not None, **n_stamp)
    if fallback:
        out["fallback_from_2pt"] = fallback
    return out


def qrr_op(Qrr, trr, cond, IF, didt, Tj=25.0, _fit_cache=None):
    """One-call fl4p/fetlib#37 entry: datasheet (Qrr, trr) + test conditions `cond`
    (dict with IF/didt/Tj, see dslib/qrr_conditions.py) -> predicted recovery at the
    operating point (IF, didt, Tj).

    Returns dict(Qrr, trr, irrm, td, tau, TM, tj_extrapolated, fit) — Qrr/trr/irrm at
    the OPERATING point; `fit` is the calibration record; `tj_extrapolated` is True
    whenever Tj != the datasheet Tj (the temperature axis rests on the N_TAU
    assumption, not on datasheet data).

    Raises LMFitError when the datasheet point is missing/inconsistent — per the house
    rule, consumers fail loud instead of inventing an operating point.
    """
    if cond is None:
        raise LMFitError("no reverse-recovery test conditions — add the part to "
                         "dslib/qrr_conditions.py (see fl4p/fetlib#37)")
    tj_fit = float(cond.get("Tj", 25.0))
    key = (Qrr, trr, cond.get("IF"), cond.get("didt"), tj_fit)
    fit = _fit_cache.get(key) if _fit_cache is not None else None
    if fit is None:
        fit = fit_lm(Qrr, trr, cond.get("IF"), cond.get("didt"), tj_fit=tj_fit)
        if _fit_cache is not None:
            _fit_cache[key] = fit
    tau = tau_at_tj(fit["tau0"], Tj, tj_fit)
    p = predict(tau, fit["TM"], IF, didt)
    return dict(Qrr=p["Qrr"], trr=p["trr"], irrm=p["irrm"], td=p["td"],
                tau=tau, TM=fit["TM"], tj_extrapolated=(Tj != tj_fit), fit=fit)
