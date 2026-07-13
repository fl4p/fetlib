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
# tau temperature exponent — ASSUMPTION, recalibrated 2026-07-13 (#18): chosen so the
# MODEL's Qrr (not tau) doubles 25->125 C at datasheet conditions, per the empirical Si
# body-diode rule. Solving Qrr(125C)/Qrr(25C)=2 through fit+predict gives n = 1.16-1.19
# across IPP018/019/022/024 (remarkably part-independent); 1.2 rounded. The old 2.0
# (inherited from lm_diode.cir) doubled TAU instead, which over-predicts Qrr(125C) ~3.2x.
# Kept in lock-step with loss/lib/lm_diode.py.
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


def tau_at_tj(tau0, tj, tj_fit=25.0):
    """Scale the fitted carrier lifetime from the datasheet Tj to the operating Tj.
    N_TAU is an assumption — see module docstring; flag results as extrapolated."""
    return tau0 * ((tj + 273.15) / (tj_fit + 273.15)) ** N_TAU


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
