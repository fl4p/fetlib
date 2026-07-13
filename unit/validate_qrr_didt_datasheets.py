"""Out-of-sample validation of the LM Qrr(di/dt) model against two-point datasheets.

Some datasheets quote reverse recovery at TWO di/dt points (Infineon OptiMOS
NM6/LM6/M5 families, onsemi FDMS/NTMFS PowerTrench C). That gives a free
out-of-sample test of the di/dt axis that dslib/qrr_model.py extrapolates on:
fit (tau, TM) on one row, predict the other, compare with the datasheet itself.

Three analyses (2026-07-13 results in the docstrings below):

  1. cross-validation  — raw two-point fit/predict per die
                         (52 dies: median |err| 23%, worst cases are small-die parts
                          whose Qrr integral is dominated by Qoss displacement charge)
  2. implied q0        — per-die constant charge offset that makes both rows
                         LM-consistent, compared to the SAME datasheet's quoted Qoss
                         (median q0 = 0.13*Qoss, IQR 0.07-0.17, n=21)
  3. fraction sweep    — the loss-tool calibration procedure (subtract f*Qoss(VR),
                         fit low row, predict high row, add back f*Qoss) vs fixed f.
                         Median |err| minimizes flat at f=0.10-0.15 (13.3-13.7%);
                         f=0.5 (the original #18 assumption) gives 47-51% with -47%
                         bias -> QRR_QOSS_FRACTION recalibrated 0.5 -> 0.1.

Not a unit test (needs the datasheets/ corpus + ~seconds); run manually:
    python3 unit/validate_qrr_didt_datasheets.py
Regression anchor: unit/test_qrr_model.py::test_didt_axis_out_of_sample.
Findings write-up: dcdc-tools/loss/docs/reverse-recovery.md section 7.

Caveat: all two-point rows are Tj=25C — this validates the di/dt axis ONLY. The Tj
axis (N_TAU) stays an assumption; Alpha & Omega datasheets (AOT414 etc.) chart
Qrr(IF) at 25C AND 125C @ 800 A/us and are the cheapest N_TAU check short of bench.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dslib import qrr_model

ROOT = os.path.join(os.path.dirname(__file__), "..", "datasheets")
MU = "µμu"  # micro sign / greek mu / ascii fallback

# --- Infineon rows: value block then a 'VR=..V, IF=..A, diF/dt=..A/us' condition line.
#     (pdftotext emits \x03 for the narrow no-break space; normalized to ' ' on read.)
INF_TRR = re.compile(
    r"Reverse recovery time.?\)?\s*\n\s*t\s*rr\s*\n(?:-+\s*\n)?"
    r"(?P<typ>[\d.]+)\s*\n(?P<max>[\d.]+)\s*\nns\s*\n"
    r"V\s*R\s*=\s*(?P<vr>[\d.]+)\s*V\s*,\s*I\s*F\s*=\s*(?P<if_>[\d.]+)\s*A\s*,\s*"
    r"di\s*F?\s*/dt\s*=\s*(?P<didt>[\d.]+)\s*A/[" + MU + r"]s", re.IGNORECASE)
INF_QRR = re.compile(
    r"V\s*R\s*=\s*(?P<vr>[\d.]+)\s*V\s*,\s*I\s*F\s*=\s*(?P<if_>[\d.]+)\s*A\s*,\s*"
    r"di\s*F?\s*/dt\s*=\s*(?P<didt>[\d.]+)\s*A/[" + MU + r"]s\s*\n"
    r"Reverse recovery charge.?\)?\s*\n\s*Q\s*rr\s*\n(?:-+\s*\n)?"
    r"(?P<typ>[\d.]+)\s*\n(?P<max>[\d.]+)\s*\nnC", re.IGNORECASE)
INF_QOSS = re.compile(
    r"Output charge.?\)?\s*\n\s*Q\s*oss\s*\n(?:-+\s*\n)?"
    r"(?P<typ>[\d.]+)\s*\n(?:(?P<max>[\d.]+)\s*\n)?nC\s*\n"
    r"V\s*DS\s*=\s*(?P<vds>[\d.]+)\s*V", re.IGNORECASE)

# --- onsemi rows: trr and Qrr blocks share one 'IF = x A, di/dt = y A/us' line.
ONSEMI_BLOCK = re.compile(
    r"t\s*rr\s*\n\s*Reverse Recovery Time\s*\n\s*"
    r"I[FS]\s*=\s*(?P<if_>[\d.]+)\s*A[, ]+di/dt\s*=\s*(?P<didt>[\d.]+)\s*A/[" + MU + r"]s.*?\n"
    r"(?P<t1>[\d.]+)\s*\n(?:(?P<t2>[\d.]+)\s*\n)?ns\s*\n"
    r"Q\s*rr\s*\n\s*Reverse Recovery Charge\s*\n\s*"
    r"(?P<q1>[\d.]+)\s*\n(?:(?P<q2>[\d.]+)\s*\n)?nC", re.IGNORECASE)
ONSEMI_QOSS = re.compile(
    r"Q\s*oss\s*\n\s*Output Charge\s*\n\s*V\s*DS\s*=\s*(?P<vds>[\d.]+)\s*V.*?\n"
    r"(?P<typ>[\d.]+)\s*\n", re.IGNORECASE)


def collect():
    """-> {die_key: dict(pts=[(IF, didt, Qrr, trr, VR)...], qoss, qoss_vds, mpns)}
    using TYPICAL values; die_key dedups package variants / order codes."""
    dies = {}
    for dirpath, _dirs, files in os.walk(ROOT):
        for fn in sorted(files):
            if not fn.endswith(".pdf.txt"):
                continue
            text = open(os.path.join(dirpath, fn), encoding="utf-8",
                        errors="replace").read().replace("\x03", " ")
            trr = {(float(m["if_"]), float(m["didt"]), float(m["vr"])): float(m["typ"]) * 1e-9
                   for m in INF_TRR.finditer(text)}
            qrr = {(float(m["if_"]), float(m["didt"]), float(m["vr"])): float(m["typ"]) * 1e-9
                   for m in INF_QRR.finditer(text)}
            pts = [(k[0], k[1] * 1e6, qrr[k], trr[k], k[2]) for k in sorted(trr.keys() & qrr.keys())]
            m = INF_QOSS.search(text)
            qoss, vds = (float(m["typ"]) * 1e-9, float(m["vds"])) if m else (None, None)
            if not pts:
                pts = [(float(m["if_"]), float(m["didt"]) * 1e6,
                        float(m["q1"]) * 1e-9, float(m["t1"]) * 1e-9, None)
                       for m in ONSEMI_BLOCK.finditer(text)]
                m = ONSEMI_QOSS.search(text)
                qoss, vds = (float(m["typ"]) * 1e-9, float(m["vds"])) if m else (None, None)
            if len({p[1] for p in pts}) >= 2:
                key = tuple(sorted((p[0], p[1], p[2], p[3]) for p in pts))
                d = dies.setdefault(key, dict(pts=pts, qoss=qoss, qoss_vds=vds, mpns=[]))
                d["mpns"].append(os.path.relpath(os.path.join(dirpath, fn), ROOT)
                                 [:-len(".pdf.txt")])
    return dies


def _pairs(dies, need_qoss):
    """(name, IF, low_pt, high_pt, qoss_at_vr|None) for same-IF lowest/highest di/dt."""
    out = []
    for d in sorted(dies.values(), key=lambda d: d["mpns"][0]):
        if need_qoss and not d["qoss"]:
            continue
        by = sorted(d["pts"], key=lambda p: p[1])
        a, b = by[0], by[-1]
        if a[0] != b[0]:
            continue
        qv = None
        if d["qoss"]:
            vr, vds = a[4], d["qoss_vds"]
            qv = d["qoss"] * ((vr / vds) ** 0.5 if (vr and vds) else 1.0)  # Q ~ sqrt(V)
        out.append((d["mpns"][0], a[0], a, b, qv))
    return out


def cross_validate(dies):
    print(f"=== 1. raw two-point cross-validation ({len(dies)} unique dies) ===")
    errs = []
    for name, IF, a, b, _qv in _pairs(dies, need_qoss=False):
        for src, dst in ((a, b), (b, a)):
            try:
                fit = qrr_model.fit_lm(src[2], src[3], IF, src[1])
                pr = qrr_model.predict(fit["tau"], fit["TM"], IF, dst[1])
            except qrr_model.LMFitError as e:
                print(f"  {name}: LMFitError @{src[1]/1e6:g} A/us: {e}")
                continue
            e = pr["Qrr"] / dst[2] - 1
            errs.append(abs(e))
            print(f"  {name:32s} fit@{src[1]/1e6:>5g} -> @{dst[1]/1e6:>5g} A/us: "
                  f"Qrr {pr['Qrr']*1e9:7.1f} nC ({e*100:+6.1f}%)  ds {dst[2]*1e9:g} nC")
    errs.sort()
    n = len(errs)
    print(f"  -> {n} predictions: median |err| {errs[n//2]*100:.1f}%  "
          f"p90 {errs[int(n*0.9)]*100:.1f}%  worst {errs[-1]*100:.1f}%\n")


def implied_q0(dies):
    """Root-solve the constant offset q0 making both rows LM-consistent; compare
    with the datasheet's own quoted Qoss."""
    print("=== 2. implied capacitive offset q0 vs quoted Qoss ===")

    def f_err(q0, a, b, IF):
        fit = qrr_model.fit_lm(a[2] - q0, a[3], IF, a[1])
        return qrr_model.predict(fit["tau"], fit["TM"], IF, b[1])["Qrr"] - (b[2] - q0)

    fracs = []
    for name, IF, a, b, qv in _pairs(dies, need_qoss=False):
        lo, hi, upper = 0.0, min(a[2], b[2]) * 0.98, min(a[2], b[2]) * 0.98

        def f(q0):
            try:
                return f_err(q0, a, b, IF)
            except qrr_model.LMFitError:
                return None

        flo = f(lo)
        fhi = None
        while hi > upper * 1e-3 and (fhi := f(hi)) is None:
            hi *= 0.9
        if flo is None or fhi is None or flo * fhi > 0:
            print(f"  {name:32s} no consistent offset in [0, min(Qrr))")
            continue
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            fm = f(mid)
            if fm is None or flo * fm <= 0:
                hi = mid
            else:
                lo, flo = mid, fm
        q0 = 0.5 * (lo + hi)
        line = f"  {name:32s} q0 = {q0*1e9:6.1f} nC"
        if qv:
            fracs.append(q0 / qv)
            line += f"  = {q0/qv:5.2f} * Qoss(VR)"
        print(line)
    if fracs:
        fracs.sort()
        n = len(fracs)
        print(f"  -> implied fraction over {n} dies: median {fracs[n//2]:.2f}  "
              f"IQR {fracs[n//4]:.2f}-{fracs[3*n//4]:.2f}\n")


def fraction_sweep(dies):
    """The loss-tool procedure vs a fixed global QRR_QOSS_FRACTION."""
    pairs = _pairs(dies, need_qoss=True)
    print(f"=== 3. QRR_QOSS_FRACTION sweep ({len(pairs)} dies with quoted Qoss) ===")
    print("      (fit-low/predict-high = the loss-tool extrapolation direction)")
    print(f"    {'f':>5} {'n':>4} {'median|err|':>12} {'p90':>8} {'median bias':>12}")
    for f in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50):
        errs = []
        for name, IF, a, b, qv in pairs:
            q_cal = a[2] - f * qv
            if q_cal <= 0:
                continue
            try:
                fit = qrr_model.fit_lm(q_cal, a[3], IF, a[1])
                pr = qrr_model.predict(fit["tau"], fit["TM"], IF, b[1])
            except qrr_model.LMFitError:
                continue
            errs.append((pr["Qrr"] + f * qv) / b[2] - 1)
        ab = sorted(abs(e) for e in errs)
        n = len(ab)
        mark = " <- QRR_QOSS_FRACTION" if abs(f - qrr_model.QRR_QOSS_FRACTION) < 1e-9 else ""
        print(f"    {f:5.2f} {n:4d} {ab[n//2]*100:11.1f}% {ab[int(n*0.9)]*100:7.1f}% "
              f"{sorted(errs)[n//2]*100:+11.1f}%{mark}")


def trr_shape_residuals(dies):
    """Analysis 4 (2026-07-13): how well does LM model-FORM match the 2pt data?

    With per-part q0 the fit reproduces both Qrr rows by construction; the
    fit-free observables are the SECOND trr row (and, for AO parts, the
    digitized Irm curves — regenerate with `dsdig digitize-reverse-recovery`
    on AOT414 and compare predict()["irrm"]; measured 2026-07-13: LM under-
    predicts IRRM ~20-26% across 200-800 A/us). Result here: trr_hi over-
    predicted median +37% / trr_lo -21% symmetric — real recovery shortens
    with di/dt faster than LM(K_TRR, single tau) allows; big 120V dies fit
    best (+12-14%), small ISC dies worst. Charge axis unaffected; the Ma
    soft-recovery extension is the cure if SHAPE ever needs to be right,
    calibratable from exactly these residuals."""
    from dslib import qrr_model as qm
    print("=== 4. LM model-form: fit-free trr residuals per die ===")
    res_hi, res_lo = [], []
    for d in sorted(dies.values(), key=lambda d: d["mpns"][0]):
        pts = sorted(d["pts"], key=lambda p: p[1])
        a, b = pts[0], pts[-1]
        if a[0] != b[0]:
            continue
        lo = dict(IF=a[0], didt=a[1], Qrr=a[2], trr=a[3])
        hi = dict(IF=b[0], didt=b[1], Qrr=b[2], trr=b[3])
        try:
            f = qm.fit_lm_2pt(lo, hi)
        except qm.LMFitError:
            continue
        fh = qm.fit_lm(hi["Qrr"] - f["q0"], hi["trr"], b[0], b[1])
        r_lo = qm.predict(fh["tau"], fh["TM"], a[0], a[1])["trr"] / a[3] - 1
        res_hi.append(f["trr_hi_resid"])
        res_lo.append(r_lo)
        print(f"  {d['mpns'][0].split('/')[1]:22s} trr_hi {f['trr_hi_resid']*100:+6.1f}%"
              f"   trr_lo* {r_lo*100:+6.1f}%")
    for nm, rs in (("trr_hi", res_hi), ("trr_lo*", res_lo)):
        rs = sorted(rs)
        n = len(rs)
        print(f"  -> {nm}: n={n} median {rs[n//2]*100:+.1f}%  "
              f"IQR {rs[n//4]*100:+.1f}..{rs[3*n//4]*100:+.1f}%  "
              f"range {rs[0]*100:+.1f}..{rs[-1]*100:+.1f}%")
    print()


def emit_points(dies, path):
    """Write dslib/qrr_points.py: the curated-by-extraction two-point table
    consumed by qrr_model.fit_lm_2pt / MosfetSpecs.Qrr_op (fl4p/fetlib#37)."""
    lines = [
        '"""Datasheet reverse-recovery rows for parts quoting Qrr at MULTIPLE di/dt',
        "points, keyed by (mfr, mpn) — GENERATED, do not edit by hand:",
        "",
        "    python3 unit/validate_qrr_didt_datasheets.py --emit-points dslib/qrr_points.py",
        "",
        "Extraction is the geometry parser validated in that script (typ values,",
        "all rows Tj=25 C). Package/order-code variants are listed as their own",
        "keys. Used for per-part two-point (tau, TM, q0) fits that replace the",
        "global QRR_QOSS_FRACTION assumption — see dslib/qrr_model.fit_lm_2pt().",
        '"""',
        "",
        "QRR_POINTS = {",
    ]
    entries = []
    for d in dies.values():
        rows = sorted(d["pts"], key=lambda p: (p[0], p[1]))
        for rel in d["mpns"]:
            mfr, mpn = rel.split("/", 1)
            entries.append((mfr, mpn, rows))
    for mfr, mpn, rows in sorted(entries):
        lines.append(f'    ("{mfr}", "{mpn}"): [')
        for IF, didt, qrr, trr, vr in rows:
            vr_s = f"{vr:g}" if vr is not None else "None"
            lines.append(
                f"        dict(IF={IF:g}, didt={didt/1e6:g}e6, VR={vr_s}, Tj=25.0, "
                f"Qrr={qrr*1e9:g}e-9, trr={trr*1e9:g}e-9),")
        lines.append("    ],")
    lines += [
        "}",
        "",
        "",
        "def qrr_points_for(mfr, mpn):",
        '    """(mfr, mpn) -> list of row dicts or None. Same base-MPN prefix',
        '    fallback as qrr_conditions (orderable suffixes resolve to the base)."""',
        "    if not mfr or not mpn:",
        "        return None",
        "    hit = (QRR_POINTS.get((mfr, mpn))",
        "           or QRR_POINTS.get((str(mfr).lower(), mpn)))",
        "    if hit:",
        "        return [dict(r) for r in hit]",
        "    for (m, p), v in QRR_POINTS.items():",
        "        if str(m).lower() == str(mfr).lower() and str(mpn).startswith(p):",
        "            return [dict(r) for r in v]",
        "    return None",
        "",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"wrote {path}: {len(entries)} part keys")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-points", metavar="PATH",
                    help="write the dslib/qrr_points.py data module and exit")
    args = ap.parse_args()
    dies = collect()
    if args.emit_points:
        emit_points(dies, args.emit_points)
    else:
        cross_validate(dies)
        implied_q0(dies)
        fraction_sweep(dies)
        trr_shape_residuals(dies)
