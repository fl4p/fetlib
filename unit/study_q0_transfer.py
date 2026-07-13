"""Can the 2pt population improve 1pt fits? Leave-one-out study.

For every two-point die (same-IF pair, quoted Qoss), pretend we only had the
LOW row (the 1pt situation), estimate q0 from an estimator TRAINED ON THE
OTHER DIES, fit, predict the high row, and score. Baselines: f=0 (raw),
global f=0.1 (current model), oracle per-part q0 (upper bound).

Estimators:
  A. global-fraction (LOO median of q0/Qoss)
  B. family-median fraction (MPN technology token: NM6/LM6/NM5/LM5/FDMS...)
  C. q0 ~ a*Qoss (LOO least-squares through origin)
  D. TM/tau prior: choose q0 so the 1pt fit's TM/tau matches the LOO
     population median (uses ONLY the low row + the prior — no Qoss needed!)

Committed for auditability (qrr-lm channel, 2026-07-13): the quoted figures —
current global f=0.1 -> 13.7% median; LOO global 12.3%, family 15.4%,
q0~a*Qoss 13.9%, TM/tau prior 19.3%; oracle per-part q0 ~0% — support the
NULL RESULT: the 2pt population cannot tighten 1pt parts; per-part second
points (bench double-pulse) are the only upgrade path. Run:
    python3 unit/study_q0_transfer.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from dslib import qrr_model as qm
from validate_qrr_didt_datasheets import collect


def solve_q0(a, b, IF):
    def err(q0):
        f = qm.fit_lm(a[2] - q0, a[3], IF, a[1])
        return qm.predict(f["tau"], f["TM"], IF, b[1])["Qrr"] - (b[2] - q0)
    lo, hi = 0.0, min(a[2], b[2]) * 0.98
    try:
        flo = err(lo)
    except qm.LMFitError:
        return None
    fhi = None
    while hi > 1e-12:
        try:
            fhi = err(hi)
            break
        except qm.LMFitError:
            hi *= 0.85
    if fhi is None or flo * fhi > 0:
        return None
    for _ in range(70):
        mid = (lo + hi) / 2
        try:
            fm = err(mid)
        except qm.LMFitError:
            hi = mid
            continue
        if flo * fm <= 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


FAMILY_RE = re.compile(r"(NM6|LM6|NM5|LM5|LM7|NF2S|N5)$|^(FDMS|NTMFS|FDB)")


def family(mpn):
    m = FAMILY_RE.search(mpn)
    return (m.group(1) or m.group(2)) if m else "other"


# ---- build the study set: same-IF pair + quoted Qoss + solvable q0
dies = []
for d in collect().values():
    if not d["qoss"]:
        continue
    pts = sorted(d["pts"], key=lambda p: p[1])
    a, b = pts[0], pts[-1]
    if a[0] != b[0]:
        continue
    vr = a[4]
    qoss_vr = d["qoss"] * ((vr / d["qoss_vds"]) ** 0.5 if (vr and d["qoss_vds"]) else 1.0)
    q0 = solve_q0(a, b, a[0])
    base = d["mpns"][0].split("/")[1]
    fit0 = None
    if q0 is not None:
        fit0 = qm.fit_lm(a[2] - q0, a[3], a[0], a[1])
    dies.append(dict(mpn=base, fam=family(base), IF=a[0], lo=a, hi=b,
                     qoss=qoss_vr, q0=q0,
                     frac=(q0 / qoss_vr if q0 is not None else None),
                     tm_tau=(fit0["TM"] / fit0["tau"] if fit0 else None)))

ok = [d for d in dies if d["q0"] is not None]
print(f"{len(dies)} dies, {len(ok)} with solvable q0")
print("\nper-die: mpn fam frac TM/tau")
for d in sorted(ok, key=lambda d: d["frac"]):
    print(f"  {d['mpn']:<20} {d['fam']:>5} f={d['frac']:5.2f} TM/tau={d['tm_tau']:5.2f}")

tm_taus = sorted(d["tm_tau"] for d in ok)
n = len(tm_taus)
print(f"\nTM/tau population: median {tm_taus[n//2]:.3f} "
      f"IQR {tm_taus[n//4]:.3f}-{tm_taus[3*n//4]:.3f} "
      f"range {tm_taus[0]:.3f}-{tm_taus[-1]:.3f}")


def score(name, q0_of):
    """q0_of(i, die) -> q0 estimate; fit low row with it, predict high row."""
    errs = []
    for i, d in enumerate(dies):
        a, b = d["lo"], d["hi"]
        q0 = q0_of(i, d)
        if q0 is None or q0 >= a[2] * 0.98:
            q0 = 0.0
        try:
            f = qm.fit_lm(a[2] - q0, a[3], d["IF"], a[1])
            pred = qm.predict(f["tau"], f["TM"], d["IF"], b[1])["Qrr"] + q0
        except qm.LMFitError:
            continue
        errs.append(abs(pred / b[2] - 1))
    errs.sort()
    m = len(errs)
    print(f"  {name:34s} n={m:2d} median {errs[m//2]*100:5.1f}%  "
          f"p90 {errs[int(m*0.9)]*100:5.1f}%")


fracs = [d["frac"] for d in ok]
all_frac = [d["frac"] if d["q0"] is not None else None for d in dies]

print("\n=== LOO out-of-sample (fit low row, predict high row) ===")
score("raw (f=0)", lambda i, d: 0.0)
score("global f=0.1 (current)", lambda i, d: 0.1 * d["qoss"])
score("oracle per-part q0 (bound)", lambda i, d: d["q0"])


def loo_global(i, d):
    others = [x["frac"] for j, x in enumerate(dies) if j != i and x["q0"] is not None]
    others.sort()
    return others[len(others)//2] * d["qoss"]


score("A: LOO global median fraction", loo_global)


def loo_family(i, d):
    fam = [x["frac"] for j, x in enumerate(dies)
           if j != i and x["q0"] is not None and x["fam"] == d["fam"]]
    if not fam:
        return loo_global(i, d)
    fam.sort()
    return fam[len(fam)//2] * d["qoss"]


score("B: LOO family median fraction", loo_family)


def loo_linreg(i, d):
    xs = [(x["qoss"], x["q0"]) for j, x in enumerate(dies)
          if j != i and x["q0"] is not None]
    sxx = sum(x*x for x, _ in xs)
    sxy = sum(x*y for x, y in xs)
    return (sxy / sxx) * d["qoss"] if sxx else None


score("C: LOO q0 ~ a*Qoss regression", loo_linreg)


def loo_tmtau(i, d):
    """q0 from the LOW ROW ALONE + a population prior on TM/tau: bisect q0
    until the 1pt fit's TM/tau hits the LOO median. No Qoss needed."""
    others = sorted(x["tm_tau"] for j, x in enumerate(dies)
                    if j != i and x["tm_tau"] is not None)
    prior = others[len(others)//2]
    a = d["lo"]

    def ratio(q0):
        f = qm.fit_lm(a[2] - q0, a[3], d["IF"], a[1])
        return f["TM"] / f["tau"]

    lo, hi = 0.0, a[2] * 0.9
    try:
        rlo = ratio(lo)
    except qm.LMFitError:
        return None
    rhi = None
    while hi > 1e-12:
        try:
            rhi = ratio(hi)
            break
        except qm.LMFitError:
            hi *= 0.85
    if rhi is None or (rlo - prior) * (rhi - prior) > 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        try:
            rm = ratio(mid)
        except qm.LMFitError:
            hi = mid
            continue
        if (rlo - prior) * (rm - prior) <= 0:
            hi = mid
        else:
            lo, rlo = mid, rm
    return (lo + hi) / 2


score("D: TM/tau prior (low row only!)", loo_tmtau)
