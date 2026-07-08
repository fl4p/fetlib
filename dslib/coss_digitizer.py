#!/usr/bin/env python3
"""Datasheet capacitance-graph digitizer -> Coss(V)/Crss(V) points for coss_curves.py.

Turns a datasheet "Typical capacitances vs V_DS" diagram (log-C y-axis, linear V_DS x-axis,
three curves Ciss/Coss/Crss) into a COSS_CURVES entry, using the method that actually
produced the verified IPP024N08NF2S read:

  1. render the page (pdftoppm, high DPI) and work on the FULL image;
  2. calibrate from an EXPLICIT plot-box `--box L,R,T,B` (pixels of the axes rectangle) +
     the DATA extent `--vspan v0,v1` (x, linear) and `--cdec dmin,dmax` (y, log decades).
     Calibration is the one bit that needs a human -- so `--probe` overlays the box and the
     decade/V gridlines on the image and saves it, to VERIFY the calibration is right BEFORE
     trusting any number (a silent mis-calibration was the old tool's failure mode);
  3. trace by per-column DARK-PIXEL clustering: threshold isolates the BOLD curves from the
     THIN grey grid, cluster each column, and assign clusters top->bottom = Ciss/Coss/Crss
     (the three curves never cross, so vertical order == identity). A mid-column seed with 3
     well-separated clusters anchors 3 tracks that walk outward by nearest-cluster continuity
     -- robust where curves merge (low V) or in-plot text labels intrude;
  4. validate against the datasheet Table anchors (Coss@Vspec, Qoss integral) and print a
     COSS_CURVES entry ready to paste.

This REPLACES the old auto-`detect_frame` (grabbed the cell/title border) + single-curve
`track_from_anchor`. It is still a dev tool -- nothing imports it at runtime -- and the read
MUST be sanity-checked against the datasheet Table (that's the anchor step). The `dslib/viz/`
vector path (`curve_extract.py`, exact from PDF drawing paths, currently Vpl-specialised) is
the eventual upgrade for vector charts; this raster path handles any datasheet image. See
fl4p/fetlib#37.

Usage (IPP024N08NF2S, verified):
  python -m dslib.coss_digitizer DATASHEET.pdf --page 8 --dpi 600 \
      --box 500,2323,206,2198 --vspan 0,80 --cdec 1,4 \
      --mfr infineon --mpn IPP024N08NF2S --anchor-coss 40,1000 --anchor-qoss 40,105
  # find/verify the box first:
  python -m dslib.coss_digitizer DATASHEET.pdf --page 8 --dpi 600 --box 500,2323,206,2198 \
      --vspan 0,80 --cdec 1,4 --probe /tmp/probe.png
Deps: numpy, Pillow, poppler's pdftoppm on PATH.
"""
import argparse
import subprocess
import sys
import numpy as np


def render_page(pdf, page, dpi, out_prefix="/tmp/_cossdig"):
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
                    pdf, out_prefix], check=True)
    # pdftoppm zero-pads the page number to the width of the last page; find what it wrote
    import glob
    cands = sorted(glob.glob(out_prefix + "*.png"))
    if not cands:
        raise FileNotFoundError(f"pdftoppm produced no PNG for {pdf} page {page}")
    return cands[-1]


def load_gray(path):
    from PIL import Image
    return np.asarray(Image.open(path).convert("L")).astype(float)


class Cal:
    """Axis calibration from the plot-box pixels + data extent. x linear, y log10."""
    def __init__(self, box, vspan, cdec):
        self.L, self.R, self.T, self.B = box          # left,right,top,bottom px of axes
        self.v0, self.v1 = vspan                       # V at L, V at R
        self.dmin, self.dmax = cdec                    # log10(C) at B (bottom), at T (top)

    def x_of_v(self, v):
        return self.L + (v - self.v0) / (self.v1 - self.v0) * (self.R - self.L)

    def v_of_x(self, x):
        return self.v0 + (x - self.L) / (self.R - self.L) * (self.v1 - self.v0)

    def y_of_c(self, c):
        return self.T + (self.dmax - np.log10(c)) / (self.dmax - self.dmin) * (self.B - self.T)

    def c_of_y(self, y):
        return 10 ** (self.dmax - (y - self.T) / (self.B - self.T) * (self.dmax - self.dmin))


def clusters(col, ytop, ybot, thr=90, gap=18, minrun=3):
    """Dark-pixel cluster centres in one image column, within [ytop,ybot]. `thr` isolates the
    BOLD curves from the THIN grey grid; `gap` merges a curve's own thickness; `minrun` drops
    stray specks."""
    ys = np.where(col < thr)[0]
    ys = ys[(ys >= ytop) & (ys <= ybot)]
    if len(ys) == 0:
        return []
    groups, cur = [], [ys[0]]
    for y in ys[1:]:
        if y - cur[-1] <= gap:
            cur.append(y)
        else:
            if len(cur) >= minrun:
                groups.append(float(np.mean(cur)))
            cur = [y]
    if len(cur) >= minrun:
        groups.append(float(np.mean(cur)))
    return groups


def trace(gray, cal, ncurve=3, thr=90, jump=60, step_px=4):
    """Trace `ncurve` curves across the plot box by column clustering + vertical-order tracks.

    Curves never cross (Ciss > Coss > Crss), so sorted-by-y clusters map straight to curve
    identity. Seed the tracks at the column with the clearest `ncurve` well-separated clusters,
    then walk both directions taking, per track, the nearest cluster within `jump` px (holding
    the last value across gaps/merges). Returns {curve_index: {col_px: y_px}}."""
    L, R, T, B = int(cal.L), int(cal.R), int(cal.T), int(cal.B)
    cols = list(range(L, R + 1, step_px))
    allc = {c: clusters(gray[:, c], T, B, thr=thr) for c in cols}

    # seed: prefer a column with exactly `ncurve` clusters spanning the widest y-range
    seed, best = None, -1
    for c in cols:
        g = allc[c]
        if len(g) == ncurve:
            spread = g[-1] - g[0]
            if spread > best:
                best, seed = spread, c
    if seed is None:                                   # fallback: most clusters
        seed = max(cols, key=lambda c: len(allc[c]))
    seeds = sorted(allc[seed])[:ncurve]
    seeds += [seeds[-1]] * (ncurve - len(seeds)) if seeds else [T] * ncurve
    tracks = {i: {seed: seeds[i]} for i in range(ncurve)}

    def walk(rng):
        prev = dict(enumerate(seeds))
        for c in rng:
            g = allc[c]
            for i in range(ncurve):
                if g:
                    cand = min(g, key=lambda y: abs(y - prev[i]))
                    if abs(cand - prev[i]) <= jump:
                        prev[i] = cand
                tracks[i][c] = prev[i]

    walk(range(seed + step_px, R + 1, step_px))
    walk(range(seed - step_px, L - 1, -step_px))
    return tracks, cols


def sample(tracks, cols, cal, vgrid):
    """Resample each traced curve onto `vgrid` (volts) -> {curve_index: np.array(pF)}."""
    out = {}
    xs = np.array(sorted(cols))
    for i, tr in tracks.items():
        vv = np.array([cal.v_of_x(x) for x in xs])
        cc = np.array([cal.c_of_y(tr[x]) for x in xs])
        o = np.argsort(vv)
        out[i] = np.interp(vgrid, vv[o], cc[o])
    return out


def qoss(V, Cpf, vmax):
    m = V <= vmax
    trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")
    return float(trapz(Cpf[m], V[m]) / 1000.0)          # pF*V -> nC


def probe_overlay(gray, cal, out_path):
    """Save the image with the calibration box + decade/V gridlines drawn on it, so the box
    can be VERIFIED against the real plot axes before trusting the trace."""
    from PIL import Image, ImageDraw
    im = Image.fromarray(gray.astype("uint8")).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle([cal.L, cal.T, cal.R, cal.B], outline=(255, 0, 0), width=3)
    dmin, dmax = int(np.floor(cal.dmin)), int(np.ceil(cal.dmax))
    for dec in range(dmin, dmax + 1):                   # decade lines (green) + minor (faint)
        for mant in range(1, 10):
            c = mant * 10 ** dec
            if not (10 ** cal.dmin <= c <= 10 ** cal.dmax):
                continue
            y = cal.y_of_c(c)
            d.line([cal.L, y, cal.R, y], fill=(0, 160, 0) if mant == 1 else (150, 220, 150),
                   width=2 if mant == 1 else 1)
    v = cal.v0
    dv = 10 if (cal.v1 - cal.v0) > 30 else 5
    while v <= cal.v1:                                  # V gridlines (blue)
        x = cal.x_of_v(v)
        d.line([x, cal.T, x, cal.B], fill=(0, 80, 255), width=2)
        v += dv
    im.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Digitize a datasheet capacitance chart.")
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--image", default=None, help="use a pre-rendered PNG instead of pdftoppm")
    ap.add_argument("--box", required=True,
                    help="plot-axes rectangle in FULL-image px: left,right,top,bottom")
    ap.add_argument("--vspan", default="0,80", help="V_DS at left,right of box (linear x)")
    ap.add_argument("--cdec", default="1,4", help="log10 C decades at bottom,top of box")
    ap.add_argument("--vstep", type=float, default=5.0, help="output V grid step")
    ap.add_argument("--thr", type=float, default=90, help="dark-pixel threshold (bold curves)")
    ap.add_argument("--jump", type=float, default=60, help="max px a track moves per column")
    ap.add_argument("--probe", default=None,
                    help="save a calibration-overlay PNG here and exit (verify the box first)")
    ap.add_argument("--mfr", default="mfr")
    ap.add_argument("--mpn", default="MPN")
    ap.add_argument("--anchor-coss", default="40,1000", help="V,pF datasheet Coss check point")
    ap.add_argument("--anchor-qoss", default=None, help="V,nC datasheet Qoss integral to check")
    args = ap.parse_args()

    img = args.image or render_page(args.pdf, args.page, args.dpi)
    gray = load_gray(img)
    box = [float(x) for x in args.box.split(",")]
    cal = Cal(box, [float(x) for x in args.vspan.split(",")],
              [float(x) for x in args.cdec.split(",")])

    if args.probe:
        p = probe_overlay(gray, cal, args.probe)
        print(f"wrote calibration overlay {p} -- check the red box hugs the plot axes and the "
              f"green decade / blue V lines land on the datasheet gridlines, then drop --probe.",
              file=sys.stderr)
        return

    tracks, cols = trace(gray, cal, ncurve=3, thr=args.thr, jump=args.jump)
    Vg = np.arange(cal.v0, cal.v1 + args.vstep / 2, args.vstep)
    s = sample(tracks, cols, cal, Vg)
    ciss, coss, crss = s[0], s[1], s[2]                 # top, middle, bottom

    print(f"{'V':>4} {'Ciss':>7} {'Coss':>7} {'Crss':>7}")
    for i, v in enumerate(Vg):
        print(f"{v:4.0f} {ciss[i]:7.0f} {coss[i]:7.0f} {crss[i]:7.0f}")
    av, ac = (float(x) for x in args.anchor_coss.split(","))
    print(f"\nCoss@{av:g} = {np.interp(av, Vg, coss):.0f} pF (ds {ac:g})", file=sys.stderr)
    if args.anchor_qoss:
        av, aq = (float(x) for x in args.anchor_qoss.split(","))
        print(f"Qoss(0-{av:g}) = {qoss(Vg, coss, av):.1f} nC (ds {aq:g})", file=sys.stderr)
    pts = ", ".join(f"({v:.0f}, {coss[i]:.0f}, {crss[i]:.0f})" for i, v in enumerate(Vg))
    print(f"\n    (\"{args.mfr}\", \"{args.mpn}\"): [\n        {pts},\n    ],")


if __name__ == "__main__":
    main()
