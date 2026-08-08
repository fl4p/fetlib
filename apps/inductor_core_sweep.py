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

from maglib import cores, materials  # noqa: E402
from maglib.winding import (enameled_od, layer_fit, max_strands,  # noqa: E402
                            mean_turn_length, strand_cut_length)
from maglib.wire import MaterialResistivity, copper_resistivity_tempco  # noqa: E402

FAMILIES = ('MS', 'SH', 'MP', 'HF', 'FS', 'OC', 'OD', 'OE', 'SM', 'GX')
PERMS = (14, 26, 40, 60, 75, 90, 125, 147, 160, 173, 205)


def sweep(vin, vout, pin, f, eff, wire_mm, grade, ripple_max, fill,
          packing, t_cu, stacks, turns_max, bore='coated', allow_band=False):
    duty = vout / vin
    io = pin * eff / vout
    wire_od = enameled_od(wire_mm * 1e-3, grade)
    a_cu = math.pi * (wire_mm * 1e-3 / 2) ** 2
    rho = copper_resistivity_tempco(MaterialResistivity.CopperAnnealed.value, t_cu)

    rows = []
    skipped = {'not_manufactured': 0, 'band_coefficients': 0}
    for size in sorted(cores.MicrometalsToroidShapes):
        for fam in FAMILIES:
            for ui in PERMS:
                try:
                    core = cores.MicrometalsToroid(fam, ui, size)
                except (materials.MaterialNotFound,
                        materials.AmbiguousMaterialSize) as e:
                    # Narrow on purpose. `except Exception` here reads as "not
                    # manufactured" but also swallows typos and real bugs: a
                    # one-character slip in FAMILIES silently removed 7,461
                    # rows with no error, no warning and a zero exit status,
                    # and the shorter table looked exactly like physics.
                    if isinstance(e, materials.AmbiguousMaterialSize):
                        raise                       # never a data-absence signal
                    skipped['not_manufactured'] += 1
                    continue
                if core.mat.coef_source != 'datasheet':
                    # The band fit is not a neutral substitute: against the
                    # datasheets' own printed nominals it runs up to 35% LOW on
                    # core loss and 22% HIGH on retained permeability, so a core
                    # whose datasheet could not be fetched scores BETTER than
                    # the manufacturer says and rises in a loss ranking. Whole
                    # families (GX, SM) have no per-part rows at all.
                    skipped['band_coefficients'] += 1
                    if not allow_band:
                        continue
                for stk in stacks:
                    c = core.stack(stk)
                    # Coated ID(min)/OD(max)/Ht(max): the dimensions a winding
                    # actually meets. winding_geometry() refuses if any are
                    # unknown rather than serving the optimistic bare ones, and
                    # returns all three so HT cannot be left bare while the
                    # other two are coated -- HT dominates the mean turn length.
                    core_id, core_od, core_ht = c.winding_geometry()
                    if bore == 'bare':
                        core_id, core_od, core_ht = c.shape.ID, c.shape.OD, c.shape.HT
                    for n in range(3, turns_max + 1):
                        h_oe = n * io / c.l_e / 79.577
                        r = c.mat.dc_bias(H_oe=h_oe)
                        # `0 < r <= 1.01` was a guard that can never fire:
                        # dc_bias is 0.01/(a+b*H^c)+d, structurally bounded in
                        # (0, 1]. As the bias got worse it kept saying PASS.
                        # The real bound is the 25%-of-mu_i band that
                        # permeability_dc_bias validates against; count the
                        # candidates outside it and report, rather than
                        # ranking them silently.
                        below_band = r < 0.25
                        ind = c.A_L * n ** 2 * r
                        d_i = vout * (1 - duty) / (ind * f)
                        if d_i / io > ripple_max:
                            continue
                        try:
                            strands = max_strands(core_id, wire_od, n, fill)
                            layers = layer_fit(core_id, wire_od, n * strands, packing)
                        except ValueError:
                            # NOT break. The wound pass count is
                            # n*floor(passes/n), a step function that
                            # OSCILLATES in n -- 50 turns wind 100 passes, 51
                            # wind 51 -- so a fit failure at n says nothing
                            # about n+1. Breaking here silently deleted 40,433
                            # of 42,445 candidates at --fill 0.40
                            # --packing 0.45, and every row of the top 10 with
                            # them, while printing a plausible table. It cost
                            # nothing at the DEFAULT packing, which is exactly
                            # why testing at defaults could never find it.
                            continue
                        mlt = mean_turn_length(core_od, core_id, core_ht,
                                               wire_od, len(layers))
                        rdc = rho * mlt * n / (a_cu * strands)
                        p_cu = rdc * (io ** 2 + d_i ** 2 / 12)
                        bpk = ind * d_i / (2 * n * c.A_e)
                        p_fe = c.mat.core_loss_density(
                            Bpk_tesla=bpk, f_khz=f / 1e3) * c.Vol * 1e3
                        rows.append((p_cu + p_fe, core.mpn, size, fam, ui, stk, n,
                                     strands, len(layers), ind * 1e6, r * 100,
                                     d_i / io * 100, rdc * 1e3, p_cu, bpk * 1e3,
                                     p_fe, c.Vol * 1e6, strand_cut_length(mlt, n),
                                     core.mat.coef_source, below_band))
    return io, duty, wire_od, sorted(rows), skipped


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
    p.add_argument('--bore', choices=('coated', 'bare'), default='coated',
                   help="'bare' uses the published nominal ID/OD instead of the "
                        "coated ones; optimistic, for comparison only")
    p.add_argument('--allow-band', action='store_true',
                   help='also rank cores whose coefficients come from the OD-band '
                        'fit rather than their own datasheet. Off by default: the '
                        'band is optimistic (up to 35%% low on core loss), so those '
                        'rows win rankings they should not.')
    p.add_argument('--top', type=int, default=25)
    args = p.parse_args()

    io, duty, wire_od, rows, skipped = sweep(
        args.vin, args.vout, args.pin, args.f, args.eff, args.wire_mm,
        args.grade, args.ripple_max, args.fill, args.packing, args.t_cu,
        args.stacks, args.turns_max, args.bore, args.allow_band)

    if args.max_od_mm is not None:
        # the COATED OD is the envelope the part occupies -- filtering on the
        # bare OD keeps cores that do not fit the slot being filtered for
        keep = {s for s, sh in cores.MicrometalsToroidShapes.items()
                if sh.OD_coated * 1e3 <= args.max_od_mm}
        dropped = len(rows)
        rows = [r for r in rows if r[2] in keep]
        # Say what was dropped. A silently truncated table reads as "these are
        # all the options" when it is not.
        print('# --max-od-mm %.0f dropped %d of %d candidates'
              % (args.max_od_mm, dropped - len(rows), dropped))

    print('# Io=%.1f A  D=%.3f  wire %.2f mm bare / %.3f mm over enamel  '
          'ripple<=%.0f%%  %d ranked'
          % (io, duty, args.wire_mm, wire_od * 1e3, args.ripple_max * 100, len(rows)))
    print('# loss = Rdc(%.0fC)*(Idc^2 + dI^2/12) + core loss; AC resistance NOT '
          'modelled (see module docstring)' % args.t_cu)
    # Say which geometry produced the table. --bore bare is not cosmetic: it
    # admits ~800 more candidates and changes the winner, and it reads BETTER,
    # so a bare-mode table pasted into a design note must not be
    # indistinguishable from a real one.
    print('# bore=%s' % ('coated ID(min)/OD(max)/Ht(max)' if args.bore == 'coated'
                         else 'BARE nominal ID/OD/Ht -- OPTIMISTIC, comparison only'))
    print('# cores skipped: %d not manufactured, %d with band-fit (not '
          'datasheet) coefficients%s'
          % (skipped['not_manufactured'], skipped['band_coefficients'],
             ' -- INCLUDED via --allow-band, see src column' if args.allow_band
             else ' -- excluded; --allow-band to include'))
    below = sum(1 for r in rows if r[19])
    if below:
        print('# %d of %d ranked rows sit below the validated 25%%-of-mu_i '
              'permeability band (marked * on perm%%)' % (below, len(rows)))
    hdr = ('part', 'src', 'stk', 'N', 'str', 'lay', 'L_uH', 'perm%', 'rip%',
           'Rdc_mR', 'Pcu_W', 'Bpk_mT', 'Pfe_W', 'Ptot_W', 'cm3', 'cut_m')
    print('%-14s %-4s %3s %3s %4s %3s %7s %7s %6s %7s %6s %7s %6s %7s %7s %6s' % hdr)
    for r in rows[:args.top]:
        (ptot, mpn, _size, _fam, _ui, stk, n, strands, layers, l_uh, perm,
         rip, rdc, p_cu, bpk, p_fe, vol, cut, src, below_band) = r
        print('%-14s %-4s %3d %3d %4d %3d %7.1f %6.0f%s %5.0f%% %7.2f %6.2f '
              '%7.1f %6.2f %7.2f %7.1f %6.2f'
              # vol already covers the stack -- c.Vol is the STACKED core's
              % (mpn, 'ds' if src == 'datasheet' else 'BAND', stk, n, strands,
                 layers, l_uh, perm, '*' if below_band else '%', rip, rdc,
                 p_cu, bpk, p_fe, ptot, vol, cut))


if __name__ == '__main__':
    main()
