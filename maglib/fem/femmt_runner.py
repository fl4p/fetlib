"""
FEMMT subprocess runner: toroid-ID winding proxy, frequency sweep.

Executed ONLY as a script by the femmt venv's python (3.12):

    <FEMMT_HOME>/bin/python femmt_runner.py <config.json> <out.json>

Never import this module — it needs femmt, which does not exist in the repo
venv, and it is not part of maglib's importable surface. The wrapper
(maglib/fem/femmt_toroid.py) builds the config, launches this script and
parses <out.json>; stdout/stderr go to a log file (femmt pollutes stdout).

Model (validated 2026-08-07 against the Micrometals analytic formula, see
maglib/CLAUDE.md): the wires passing through the toroid ID are represented as
equal full-height columns of solid round conductors in a 2D-axisymmetric
window core. The window height equals exactly conductors_per_column * pitch,
so the near-infinite-mu yokes (mirror planes at half-pitch) continue each
column into an infinite periodic array — topologically the closed wire ring
around the toroid ID (no free column end). mu_r must be ~20000, NOT the real
toroid permeability: a realistic mu in this window geometry drowns the
winding in core-leakage field that does not exist on a toroid.

Exit codes: 0 ok, 2 crash (femmt/parse error), 3 physics guard failed.
out.json always gets written with "ok": true/false; on failure the wrapper
raises — there is no silent Fr=1.0 path anywhere.
"""
if __name__ != "__main__":
    raise RuntimeError("femmt_runner is a subprocess script, never importable")

import json
import os
import sys
import time
import traceback
from typing import NoReturn

CONFIG_SCHEMA = 1
GUARD_TURNSUM_RTOL = 1e-6
GUARD_SYMMETRY_RTOL = 0.05
# The column stack height equals the available window height EXACTLY by
# construction, so femmt's fits-check is decided by float rounding — one lost
# ULP silently demotes a wire into a partial third column (caught by the
# symmetry guard, 23+23+2 instead of 24+24). Shave this off the
# inter-conductor insulation so the intended count always fits; the mirror
# planes shift < 1e-3 of a pitch, well inside the symmetry guard's tolerance.
PLACEMENT_EPS = 1e-6  # m

t0 = time.time()
# absolutize immediately: femmt os.chdir()s into its working_directory, which
# would silently relocate a relative out.json
cfg_path, out_path = (os.path.abspath(p) for p in sys.argv[1:3])
with open(cfg_path) as fh:
    cfg = json.load(fh)


def fail(code, error, guards=None) -> NoReturn:
    with open(out_path, 'w') as fh:
        json.dump({'schema': 1, 'ok': False, 'error': error,
                   'guards': guards or {}, 'elapsed_s': time.time() - t0}, fh,
                  indent=1)
    sys.exit(code)


if cfg.get('schema') != CONFIG_SCHEMA:
    fail(2, 'config schema %r != %d' % (cfg.get('schema'), CONFIG_SCHEMA))

try:
    import femmt as fmt

    wire_r = cfg['wire_r']
    n_cond = cfg['n_cond']
    n_per_col = cfg['conductors_per_column']
    n_layers = cfg['n_layers']
    pitch = cfg['pitch']
    freqs = cfg['freqs']
    temperature = cfg['temperature']

    window_h = n_per_col * pitch
    # width must scale with the COLUMN COUNT or femmt would re-pack tighter
    # than the declared pitch and desync the guard's column indexing;
    # max(4, ...) keeps the 1-3-layer validated geometry byte-identical
    window_w = max(4, n_layers + 1) * pitch + 3e-3
    edge_gap = (pitch - 2 * wire_r) / 2  # yoke mirror planes at half-pitch

    geo = fmt.MagneticComponent(
        simulation_type=fmt.SimulationType.FreqDomain,
        component_type=fmt.ComponentType.Inductor,
        working_directory=cfg['working_directory'],
        verbosity=fmt.Verbosity.Silent, is_gui=False)

    core_dimensions = fmt.dtos.SingleCoreDimensions(
        core_inner_diameter=cfg['core_inner_diameter'],
        window_w=window_w, window_h=window_h,
        core_h=window_h + 2 * cfg['yoke'])
    core = fmt.Core(
        core_type=fmt.CoreType.Single, core_dimensions=core_dimensions,
        material="custom", mu_r_abs=cfg['mu_r'], phi_mu_deg=0.5, sigma=0.5,
        loss_approach=fmt.LossApproach.LossAngle, temperature=temperature,
        permeability_datasource=fmt.MaterialDataSource.Custom,
        permittivity_datasource=fmt.MaterialDataSource.Custom)
    geo.set_core(core)

    # toroid powder cores are distributed-gap: no discrete air gap
    geo.set_air_gaps(fmt.AirGaps(fmt.AirGapMethod.Percent, core))

    insulation = fmt.Insulation(flag_insulation=False)
    insulation.add_core_insulations(edge_gap, edge_gap, 1e-3, 1e-3)
    insulation.add_winding_insulations([[pitch - 2 * wire_r - PLACEMENT_EPS]])
    geo.set_insulation(insulation)

    winding_window = fmt.WindingWindow(core, insulation)
    vww = winding_window.split_window(fmt.WindingWindowSplit.NoSplit)
    winding = fmt.Conductor(0, fmt.Conductivity.Copper,
                            winding_material_temperature=temperature)
    winding.set_solid_round_conductor(
        conductor_radius=wire_r,
        conductor_arrangement=fmt.ConductorArrangement.Square)
    vww.set_winding(
        winding, n_cond, None, fmt.Align.ToEdges,
        placing_strategy=fmt.ConductorDistribution.VerticalUpward_HorizontalRightward)
    geo.set_winding_windows([winding_window])

    geo.create_model(freq=freqs[1] if len(freqs) > 1 else freqs[0],
                     pre_visualize_geometry=False, save_png=False)
    geo.excitation_sweep(frequency_list=freqs,
                         current_list_list=[[1.0]] * len(freqs),
                         phi_deg_list_list=[[0.0]] * len(freqs))

    log_file = os.path.join(cfg['working_directory'], 'results',
                            'log_electro_magnetic.json')
    with open(log_file) as fh:
        em = json.load(fh)
    sweeps = [{'f': s['f'],
               'winding_losses': s['winding1']['winding_losses'],
               'turn_losses': s['winding1']['turn_losses']}
              for s in em['single_sweeps']]
except SystemExit:
    raise
except BaseException:
    fail(2, traceback.format_exc())

# --- physics guards -------------------------------------------------------
guards = {}
try:
    # 1. winding_losses must equal sum(turn_losses)
    turnsum_err = max(
        abs(s['winding_losses'] - sum(s['turn_losses'])) / s['winding_losses']
        for s in sweeps)
    guards['turn_loss_sum_rel_err'] = turnsum_err

    # 2. per-column mirror symmetry at the highest frequency. All columns are
    #    full by construction (indivisible counts are bracketed upstream).
    #    Placement is VerticalUpward_HorizontalRightward: turn k sits in
    #    column k // n_per_col at height index k % n_per_col (verified
    #    against the prototype's symmetric S=1 profile).
    hi = max(sweeps, key=lambda s: s['f'])
    sym_dev = 0.0
    for c in range(n_cond // n_per_col):
        col = hi['turn_losses'][c * n_per_col:(c + 1) * n_per_col]
        dev = max(abs(a - b) for a, b in zip(col, reversed(col))) / max(col)
        sym_dev = max(sym_dev, dev)
    guards['column_symmetry_rel_dev'] = sym_dev

    # 3. Fr monotone non-decreasing in f (sweeps are frequency-ordered)
    p_ref = sweeps[0]['winding_losses']
    frs = [s['winding_losses'] / p_ref for s in sweeps]
    guards['fr_monotone'] = all(
        b >= a * (1 - 1e-9) for a, b in zip(frs, frs[1:]))
except SystemExit:
    raise
except BaseException:
    # e.g. a zero winding_losses -> ZeroDivisionError: keep the structured
    # out.json path instead of an unhandled-traceback exit
    fail(2, traceback.format_exc(), guards)

if turnsum_err > GUARD_TURNSUM_RTOL:
    fail(3, 'winding_losses != sum(turn_losses), rel err %g' % turnsum_err, guards)
if sym_dev > GUARD_SYMMETRY_RTOL:
    fail(3, 'column loss profile asymmetric (rel dev %.3f > %.2f) - '
            'periodicity artifact' % (sym_dev, GUARD_SYMMETRY_RTOL), guards)
if not guards['fr_monotone']:
    fail(3, 'Fr not monotone in f: %s' % frs, guards)

with open(out_path, 'w') as fh:
    json.dump({'schema': 1, 'ok': True, 'sweeps': sweeps, 'guards': guards,
               'elapsed_s': time.time() - t0}, fh, indent=1)
