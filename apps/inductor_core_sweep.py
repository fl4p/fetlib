"""Rank toroid core + turns + strand-count options for a buck inductor by loss.

    python3 apps/inductor_core_sweep.py --vin 72 --vout 27 --pin 900 --f 40e3

Sweeps every toroid shape in maglib.cores.MicrometalsToroidShapes x every
material family/permeability x stacking x turns, keeps the candidates under a
ripple ceiling, and ranks by copper + core loss.

Why this exists as a repo script rather than a scratch file: the answer it
gives is counter-intuitive enough to be worth re-deriving. Winding fit is
limited by BORE AREA, not core volume, so the optimum is few turns / many
parallel strands / a bigger core -- and stacking, which multiplies A_L but
adds exactly zero bore, loses to going one size up. A sweep restricted to the
sizes maglib happened to define could not see that, and said nothing about it:
the missing sizes were absent, not wrong.

Deliberate limitations, stated because a ranked table reads as more authority
than it has:

  * AC resistance is NOT modelled. At a typical buck operating point the AC
    component is ~0.5% of I_rms^2, so a proximity factor of ~13 (measured by
    FEM on the winner here, 4 layers) still only moves total loss ~4%. Push
    ripple much past 40% and that stops being true -- see maglib/fem.
  * Ripple uses the DC-biased L at full I_o, which OVERSTATES ripple by 6-20%
    (worst for materials with the best bias retention) because the valley half
    of the excursion sees higher permeability. B_pk is unaffected: L*dI is
    identically Vout*(1-D)/f, so L cancels.
  * Everything is NOMINAL. A_L carries +-8% and the datasheets quote a minimum
    %perm well below nominal (T250 MS: 55.0% nom, 46.4% min).
  * No thermal model. Two designs with equal loss but different surface area
    are not equally good.
"""
import argparse
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maglib import cores  # noqa: E402
from maglib.winding import (enameled_od, layer_fit, max_strands,  # noqa: E402
                            mean_turn_length, strand_cut_length)
from maglib.wire import MaterialResistivity, copper_resistivity_tempco  # noqa: E402

FAMILIES = ('MS', 'SH', 'MP', 'HF', 'FS', 'OC', 'OD', 'OE', 'SM', 'GX')
PERMS = (14, 26, 40, 60, 75, 90, 125, 147, 160, 173, 205)


def sweep(vin, vout, pin, f, eff, wire_mm, grade, ripple_max, fill,
          packing, t_cu, stacks, turns_max, bore='coated'):
    duty = vout / vin
    io = pin * eff / vout
    wire_od = enameled_od(wire_mm * 1e-3, grade)
    a_cu = math.pi * (wire_mm * 1e-3 / 2) ** 2
    rho = copper_resistivity_tempco(MaterialResistivity.CopperAnnealed.value, t_cu)

    rows = []
    for size, shape in sorted(cores.MicrometalsToroidShapes.items()):
        for fam in FAMILIES:
            for ui in PERMS:
                try:
                    core = cores.MicrometalsToroid(fam, ui, size)
                except Exception:
                    continue        # not manufactured in this size/material
                for stk in stacks:
                    c = core.stack(stk)
                    # The coating takes 0.8-1.3 mm of bore -- a whole strand on
                    # a small core. Refuse rather than fall back to the bare
                    # ID: that errs toward a strand that does not fit.
                    core_id = (c.winding_bore_coated() if bore == 'coated'
                               else c.winding_bore())[0]
                    for n in range(3, turns_max + 1):
                        h_oe = n * io / c.l_e / 79.577
                        r = c.mat.dc_bias(H_oe=h_oe)
                        if not (0 < r <= 1.01):
                            continue
                        ind = c.A_L * n ** 2 * r
                        d_i = vout * (1 - duty) / (ind * f)
                        if d_i / io > ripple_max:
                            continue
                        try:
                            strands = max_strands(core_id, wire_od, n, fill)
                            layers = layer_fit(core_id, wire_od, n * strands, packing)
                        except ValueError:
                            break   # more turns can only fit worse
                        mlt = mean_turn_length(c.shape.OD, core_id, c.shape.HT,
                                               wire_od, len(layers))
                        rdc = rho * mlt * n / (a_cu * strands)
                        p_cu = rdc * (io ** 2 + d_i ** 2 / 12)
                        bpk = ind * d_i / (2 * n * c.A_e)
                        p_fe = c.mat.core_loss_density(
                            Bpk_tesla=bpk, f_khz=f / 1e3) * c.Vol * 1e3
                        rows.append((p_cu + p_fe, core.mpn, size, fam, ui, stk, n,
                                     strands, len(layers), ind * 1e6, r * 100,
                                     d_i / io * 100, rdc * 1e3, p_cu, bpk * 1e3,
                                     p_fe, c.Vol * 1e6, strand_cut_length(mlt, n)))
    return io, duty, wire_od, sorted(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--vin', type=float, required=True)
    p.add_argument('--vout', type=float, required=True)
    p.add_argument('--pin', type=float, required=True)
    p.add_argument('--f', type=float, required=True, help='switching frequency Hz')
    p.add_argument('--eff', type=float, default=0.96)
    p.add_argument('--wire-mm', type=float, default=1.8, help='BARE copper diameter')
    p.add_argument('--grade', type=int, default=2, help='IEC 60317 enamel grade')
    p.add_argument('--ripple-max', type=float, default=0.40)
    p.add_argument('--fill', type=float, default=0.40, help='bore area fill target')
    p.add_argument('--packing', type=float, default=0.80)
    p.add_argument('--t-cu', type=float, default=60.0, help='copper temperature C')
    p.add_argument('--stacks', type=int, nargs='+', default=[1, 2, 3])
    p.add_argument('--turns-max', type=int, default=80)
    p.add_argument('--max-od-mm', type=float, default=None)
    p.add_argument('--bore', choices=('coated', 'bare'), default='coated')
    p.add_argument('--top', type=int, default=25)
    args = p.parse_args()

    io, duty, wire_od, rows = sweep(
        args.vin, args.vout, args.pin, args.f, args.eff, args.wire_mm,
        args.grade, args.ripple_max, args.fill, args.packing, args.t_cu,
        args.stacks, args.turns_max, args.bore)

    if args.max_od_mm is not None:
        keep = {s for s, sh in cores.MicrometalsToroidShapes.items()
                if sh.OD * 1e3 <= args.max_od_mm}
        dropped = len(rows)
        rows = [r for r in rows if r[2] in keep]
        # Say what was dropped. A silently truncated table reads as "these are
        # all the options" when it is not.
        print('# --max-od-mm %.0f dropped %d of %d candidates'
              % (args.max_od_mm, dropped - len(rows), dropped))

    print('# Io=%.1f A  D=%.3f  wire %.2f mm bare / %.3f mm over enamel  '
          'ripple<=%.0f%%  %d feasible'
          % (io, duty, args.wire_mm, wire_od * 1e3, args.ripple_max * 100, len(rows)))
    print('# loss = Rdc(%.0fC)*(Idc^2 + dI^2/12) + core loss; AC resistance NOT '
          'modelled (see module docstring)' % args.t_cu)
    hdr = ('part', 'stk', 'N', 'str', 'lay', 'L_uH', 'perm%', 'rip%',
           'Rdc_mR', 'Pcu_W', 'Bpk_mT', 'Pfe_W', 'Ptot_W', 'cm3', 'cut_m')
    print('%-14s %3s %3s %4s %3s %7s %6s %6s %7s %6s %7s %6s %7s %7s %6s' % hdr)
    for r in rows[:args.top]:
        (ptot, mpn, _size, _fam, _ui, stk, n, strands, layers, l_uh, perm,
         rip, rdc, p_cu, bpk, p_fe, vol, cut) = r
        print('%-14s %3d %3d %4d %3d %7.1f %5.0f%% %5.0f%% %7.2f %6.2f %7.1f '
              '%6.2f %7.2f %7.1f %6.2f'
              # vol already covers the stack -- c.Vol is the STACKED core's
              % (mpn, stk, n, strands, layers, l_uh, perm, rip, rdc, p_cu,
                 bpk, p_fe, ptot, vol, cut))


if __name__ == '__main__':
    main()
