"""
FEM AC-resistance factors for toroid inductor windings via FEMMT.

FEMMT (upb-lea FEM_Magnetics_Toolbox) has no toroid support; this wrapper
runs a validated 2D-axisymmetric proxy (see maglib/fem/femmt_runner.py for
the model and maglib/CLAUDE.md for the technique) in FEMMT's own venv and
returns Fr(f) = Rac/Rdc for the winding.

Conventions (the repo's most-commented bug class is total-vs-excess):
- ``AcrResult.fr_total``: TOTAL ratio, Rac = Rdc * fr_total, always >= 1.
- ``AcrResult.fr_excess``: fr_total - 1, the same convention as
  ``maglib.wire.acr_factor_micrometals``'s F_skin + F_prox sum
  (P_acr = Il_ac_rms2 * fr_excess * Rdc, cf. dclib/powerloss.py).

FEMMT lives in its own Python 3.12 venv (repo runs 3.9/3.10), so every
simulation is a subprocess; results come back as JSON files (femmt pollutes
stdout with warnings). A missing/broken installation RAISES with the full
list of missing paths — there is no code path that returns Fr = 1.0 or an
empty result on failure.

Runs take ~1-4 min per config and are disk-cached; the cache key includes
the DERIVED column geometry, the runner-script hash and the femmt version,
so packing-algorithm or solver changes miss the cache instead of serving a
stale result.
"""
import hashlib
import json
import math
import os
import subprocess
from dataclasses import dataclass, field
from glob import glob
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from dslib.cache import disk_cache
from maglib.fem.toroid_packing import assign_layers, fem_sim_configs

F_DC_REF = 100.0          # Hz, DC-reference sweep point (Fr == 1 by definition)
PROXY_LEG_DIAMETER = 24e-3  # proxy center-leg dia; cancels in Fr (turn length)
PROXY_YOKE = 6e-3
DEFAULT_FEMMT_HOME = '/Users/fab/dev/venvs/femmt'
_RUNNER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'femmt_runner.py')


def _tool_paths() -> Dict[str, str]:
    """Locate the femmt venv pieces; collect ALL missing paths and raise one
    RuntimeError naming them. FETLIB_FEMMT_HOME is read here, at call time."""
    home = os.environ.get('FETLIB_FEMMT_HOME', DEFAULT_FEMMT_HOME)
    python = os.path.join(home, 'bin', 'python')
    pkg_glob = os.path.join(home, 'lib', 'python*', 'site-packages', 'femmt')
    pkgs = sorted(glob(pkg_glob))
    pkg = pkgs[-1] if pkgs else pkg_glob
    config = os.path.join(pkg, 'config.json')
    missing = [p for p in (python, pkg, config, _RUNNER_PATH)
               if not os.path.exists(p)]
    if os.path.isfile(config):
        with open(config) as fh:
            onelab_dir = json.load(fh).get('onelab', '')
        if not os.path.isabs(onelab_dir):
            # resolve like femmt would from its own package dir, not our CWD
            onelab_dir = os.path.join(pkg, onelab_dir)
        getdp = os.path.join(onelab_dir, 'getdp')
        if not os.path.isfile(getdp):
            missing.append(getdp + ' (onelab dir from femmt config.json)')
    if missing:
        raise RuntimeError(
            'femmt toolchain incomplete (FETLIB_FEMMT_HOME=%s), missing:\n  %s\n'
            'Set FETLIB_FEMMT_HOME to a venv with femmt installed, a getdp '
            'binary in <venv>/onelab/ and site-packages/femmt/config.json '
            'pointing at it (see maglib/CLAUDE.md).'
            % (home, '\n  '.join(missing)))
    return {'home': home, 'python': python, 'pkg': pkg}


def _femmt_version(home: str) -> str:
    dists = sorted(glob(os.path.join(
        home, 'lib', 'python*', 'site-packages', 'femmt-*.dist-info')))
    if not dists:  # femmt has no __version__; dist-info is the only source
        raise RuntimeError('no femmt-*.dist-info under %s — cannot determine '
                           'femmt version for the cache key' % home)
    return os.path.basename(dists[-1])[len('femmt-'):-len('.dist-info')]


def _runner_sha() -> str:
    # file BYTES by path — the runner must never be imported (it guards
    # against that itself)
    with open(_RUNNER_PATH, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def _tail(path: str, n: int = 15) -> str:
    try:
        with open(path, errors='replace') as fh:
            return ''.join(fh.readlines()[-n:])
    except OSError:
        return '<no log>'


RUN_TIMEOUT_S = 3600  # runs are ~1-4 min; a hung getdp/gmsh must not block forever


def _run(cmd, log_path: str, what: str):
    with open(log_path, 'w') as log_fh:
        try:
            ret = subprocess.run(cmd, stdout=log_fh, stderr=subprocess.STDOUT,
                                 timeout=RUN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise RuntimeError('%s timed out after %ds, see %s\n%s' % (
                what, RUN_TIMEOUT_S, log_path, _tail(log_path)))
    if ret.returncode != 0:
        raise RuntimeError('%s failed (exit %d), see %s\n%s' % (
            what, ret.returncode, log_path, _tail(log_path)))


@dataclass(frozen=True)
class AcrResult:
    """FEM AC-resistance result for a toroid winding.

    ``fr_total`` is the TOTAL Rac/Rdc ratio (>= 1) at each of ``freqs``;
    ``fr_excess`` is ``fr_total - 1`` (the acr_factor_micrometals F_se+F_pe
    convention). The internal 100 Hz DC reference point is excluded from
    ``freqs``; its absolute loss (1 A excitation) is ``p_dc_ref``.
    ``provenance['run_dir']`` is best-effort — it points into the reclaimable
    ``out/`` tree and outlives cache entries only until cleanup.
    """
    freqs: Tuple[float, ...]
    fr_total: Tuple[float, ...]
    p_dc_ref: float
    layers: Tuple[int, ...]        # wires per toroid-ID packing layer
    n_layers: int                  # FEM columns (== len(layers))
    conductors_per_column: int
    pitch: float                   # m
    provenance: dict = field(default_factory=dict)

    @property
    def fr_excess(self) -> Tuple[float, ...]:
        """fr_total - 1: drop-in for acr_factor_micrometals' F_se + F_pe."""
        return tuple(f - 1.0 for f in self.fr_total)

    def fr_at(self, f: float) -> float:
        """Total Rac/Rdc at f, interpolated vs sqrt(f) with the implicit
        (F_DC_REF, 1.0) anchor; flat extrapolation beyond the last point."""
        xs = np.sqrt(np.concatenate(([F_DC_REF], self.freqs)))
        ys = np.concatenate(([1.0], self.fr_total))
        return float(np.interp(math.sqrt(f), xs, ys))

    def fr_excess_at(self, f: float) -> float:
        return self.fr_at(f) - 1.0


def _build_config(wire_r_um: int, n_cond: int, conductors_per_column: int,
                  n_layers: int, pitch_um: int, freqs_hz: tuple,
                  temp_c: int, mu_r: int, leg_d_um: int, yoke_um: int,
                  working_directory: str) -> dict:
    """Runner config dict (pure; unit-tested against a golden value)."""
    return {
        'schema': 1,
        'wire_r': wire_r_um * 1e-6,
        'n_cond': n_cond,
        'conductors_per_column': conductors_per_column,
        'n_layers': n_layers,
        'pitch': pitch_um * 1e-6,
        'mu_r': float(mu_r),
        'temperature': float(temp_c),
        'freqs': [F_DC_REF] + [float(f) for f in freqs_hz],
        'working_directory': working_directory,
        'core_inner_diameter': leg_d_um * 1e-6,
        'yoke': yoke_um * 1e-6,
    }


@disk_cache(ttl='365d', hash_func_code=True, salt='femmt_toroid_v1')
def _femmt_acr_cached(wire_r_um: int, n_cond: int, conductors_per_column: int,
                      n_layers: int, pitch_um: int, freqs_hz: tuple,
                      temp_c: int, mu_r: int, leg_d_um: int, yoke_um: int,
                      runner_sha: str, femmt_version: str) -> dict:
    """Run one FEM config (cached). Takes the DERIVED geometry so packing
    changes miss the cache; runner_sha/femmt_version enter the key as args
    because hash_func_code cannot see callees or the foreign tool."""
    tools = _tool_paths()
    repo_root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    key = hashlib.sha224(str((wire_r_um, n_cond, conductors_per_column,
                              n_layers, pitch_um, freqs_hz, temp_c, mu_r,
                              leg_d_um, yoke_um,
                              runner_sha, femmt_version)).encode()).hexdigest()[:16]
    # per-process suffix: no cross-process lock exists; two concurrent misses
    # must not interleave gmsh/getdp files in one dir
    run_dir = os.path.join(repo_root, 'out', 'femmt_toroid', key,
                           '%d-%s' % (os.getpid(), os.urandom(3).hex()))
    os.makedirs(os.path.join(run_dir, 'femmt'))

    cfg = _build_config(wire_r_um, n_cond, conductors_per_column, n_layers,
                        pitch_um, freqs_hz, temp_c, mu_r, leg_d_um, yoke_um,
                        working_directory=os.path.join(run_dir, 'femmt'))
    cfg_path = os.path.join(run_dir, 'config.json')
    out_path = os.path.join(run_dir, 'out.json')
    with open(cfg_path, 'w') as fh:
        json.dump(cfg, fh, indent=1)

    _run([tools['python'], _RUNNER_PATH, cfg_path, out_path],
         os.path.join(run_dir, 'runner.log'),
         'femmt toroid proxy (%d cond, %d layers)' % (n_cond, n_layers))

    if not os.path.isfile(out_path):
        raise RuntimeError('femmt runner exited 0 but wrote no %s' % out_path)
    with open(out_path) as fh:
        out = json.load(fh)
    if out.get('schema') != 1 or not out.get('ok'):
        raise RuntimeError('femmt runner reported failure: %s (guards %s), '
                           'see %s' % (out.get('error'), out.get('guards'),
                                       run_dir))

    sweeps = out['sweeps']
    p_dc_ref = sweeps[0]['winding_losses']
    if not (p_dc_ref > 0):
        raise RuntimeError('non-positive DC reference loss %r' % p_dc_ref)
    fr_total = [s['winding_losses'] / p_dc_ref for s in sweeps[1:]]
    if any(fr < 1.0 for fr in fr_total):
        raise RuntimeError('Fr < 1 in %s — FEM result unphysical' % fr_total)
    if any(b < a for a, b in zip(fr_total, fr_total[1:])):
        raise RuntimeError('Fr not monotone in f: %s' % fr_total)

    return {
        'freqs': [s['f'] for s in sweeps[1:]],
        'fr_total': fr_total,
        'p_dc_ref': p_dc_ref,
        'guards': out['guards'],
        'elapsed_s': out['elapsed_s'],
        'run_dir': run_dir,
        'femmt_version': femmt_version,
        'runner_sha': runner_sha,
    }


def femmt_toroid_acr(core_id: float, wire_d: float, turns: int, strands: int,
                     freqs: Sequence[float],
                     wire_od: Optional[float] = None,
                     pack_eff: float = 0.8,
                     temperature: float = 60.0,
                     mu_r_proxy: float = 20000.0) -> AcrResult:
    """FEM Rac/Rdc factors for a toroid inductor winding.

    :param core_id: toroid inner (bore) diameter [m], e.g.
        ``MagneticCoreSpecs.winding_bore()[0]``
    :param wire_d: bare copper diameter [m]
    :param turns: number of turns
    :param strands: parallel strands (bundle); the FEM models the
        equal-current-share equivalent (turns*strands conductors at I/strands)
    :param freqs: frequencies [Hz] to simulate, ascending (fundamental +
        harmonics); the 100 Hz DC reference is added internally
    :param wire_od: over-enamel OD [m]; default 1.055*wire_d (~grade-2 build
        for mm-class wire) — pass the real value for accuracy
    :param pack_eff: hand-winding packing efficiency vs ideal ring packing
    :param temperature: copper temperature [degC]
    :param mu_r_proxy: proxy-core permeability. NOT the toroid's real mu_r —
        must stay high (~20000) so the FEM window field is purely the
        winding's own MMF, like the toroid ID hole. See maglib/CLAUDE.md.
    """
    freqs = [float(f) for f in freqs]
    assert freqs and all(f > F_DC_REF for f in freqs), \
        'freqs must be > %g Hz' % F_DC_REF
    assert sorted(freqs) == freqs, 'freqs must be ascending'
    if wire_od is None:
        wire_od = 1.055 * wire_d
    assert wire_od >= wire_d

    n_wires = turns * strands
    layers = assign_layers(n_wires, core_id, wire_od, pack_eff)
    # indivisible counts run as TWO bracketing all-columns-full configs with
    # linear interpolation — a short column is not a local defect, it skews
    # the field of the whole model (see toroid_packing.fem_sim_configs)
    configs = fem_sim_configs(n_wires, core_id, wire_od, pack_eff)

    tools = _tool_paths()  # raises before any cache interaction when broken
    runner_sha = _runner_sha()
    femmt_version = _femmt_version(tools['home'])
    freqs_hz = tuple(int(round(f)) for f in freqs)
    results = []
    for weight, geom in configs:
        res = _femmt_acr_cached(
            wire_r_um=int(round(wire_d / 2 * 1e6)),
            n_cond=geom.n_wires,
            conductors_per_column=geom.conductors_per_column,
            n_layers=geom.n_layers,
            pitch_um=int(round(geom.pitch * 1e6)),
            freqs_hz=freqs_hz,
            temp_c=int(round(temperature)),
            mu_r=int(round(mu_r_proxy)),
            # proxy geometry constants enter the cache key as args:
            # hash_func_code cannot see module-level constants via _build_config
            leg_d_um=int(round(PROXY_LEG_DIAMETER * 1e6)),
            yoke_um=int(round(PROXY_YOKE * 1e6)),
            runner_sha=runner_sha,
            femmt_version=femmt_version,
        )
        assert tuple(res['freqs']) == tuple(map(float, freqs_hz)), \
            (res['freqs'], freqs_hz)
        results.append((weight, geom, res))

    fr_total = tuple(
        sum(w * r['fr_total'][i] for w, _, r in results)
        for i in range(len(freqs)))
    geom_dom = max(results, key=lambda t: t[0])[1]
    return AcrResult(
        freqs=tuple(freqs),
        fr_total=fr_total,
        p_dc_ref=sum(w * r['p_dc_ref'] for w, _, r in results),
        layers=tuple(layers),
        n_layers=geom_dom.n_layers,
        conductors_per_column=geom_dom.conductors_per_column,
        pitch=geom_dom.pitch,
        provenance={
            'femmt_version': femmt_version,
            'runner_sha': runner_sha,
            'configs': [
                {'weight': w, 'n_cond': g.n_wires,
                 'run_dir': r['run_dir'], 'guards': r['guards'],
                 'elapsed_s': r['elapsed_s']}
                for w, g, r in results],
            # convenience aliases for the (common) single-config case
            'guards': results[0][2]['guards'],
            'run_dir': results[0][2]['run_dir'],
        },
    )
