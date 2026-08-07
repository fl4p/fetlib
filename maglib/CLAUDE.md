# maglib — inductor (powder core) design & loss

Largely independent of the FET pipeline; pulled in via `dclib.powerloss` for AC-resistance and core-loss factors (`MagneticCoreSpecs`, `acr_factor_micrometals`, `skin_depth`, `d2awg`, `MaterialResistivity`). Materials are loaded from `maglib/materials/micrometals.csv`.

## maglib/fem — FEM AC resistance for toroid windings (FEMMT wrapper, 2026-08)

`femmt_toroid_acr(core_id, wire_d, turns, strands, freqs, wire_od=…)` returns
`AcrResult` with `fr_total` (TOTAL Rac/Rdc, ≥1) and `fr_excess` (= fr_total−1,
the same **excess** convention as `acr_factor_micrometals`'s F_se+F_pe — state
which one you mean, the total-vs-excess mixup is this repo's most-commented bug
class). `fr_excess_at(f)` is drop-in for the `(F_se + F_pe)` term in
`dclib/powerloss.py` (not wired in; FEM runs are ~1–4 min and cached 365 d).
A/B demo: `python -m maglib.examples.femmt_toroid_acr` (validated on T184,
16 turns × 1–4 strands of 1.8 mm wire: FEM/analytic total-Fr within ~10 % at
every strand count, 1–3 layers).

Load-bearing details:
- **FEMMT cannot model toroids.** The proxy (in `femmt_runner.py`): the ID wire
  bundle as equal full-height columns in a 2D-axisymmetric window whose
  **µr=20000** yokes mirror each column into an infinite periodic array — the
  closed wire ring around the toroid ID. Do NOT use the real toroid µr: in the
  window geometry it drowns the winding in leakage field (Fr ~10× high with a
  monotone per-turn profile). Do NOT let a column run short: 2 missing wires of
  64 skewed the per-turn losses of ALL columns by 45 % — indivisible counts are
  simulated as two bracketing all-columns-full configs and interpolated
  (`toroid_packing.fem_sim_configs`).
- **femmt lives in its own venv** (`FETLIB_FEMMT_HOME`, default
  `/Users/fab/dev/venvs/femmt`: py3.12, `setuptools<81` for pkg_resources,
  getdp binary in `<venv>/onelab/` registered in site-packages
  `femmt/config.json`). Repo python (3.9/3.10) cannot import it →
  `femmt_runner.py` is subprocess-only and guards against import; results come
  back as JSON files because femmt pollutes stdout. Missing toolchain RAISES
  with the full path list — there is no silent Fr=1.0 fallback anywhere.
- The runner enforces physics guards (winding=Σturn losses, per-column mirror
  symmetry — the periodicity-artifact detector —, Fr monotone in f) and femmt's
  conductor-fit check is float-boundary-exact by construction, so
  `PLACEMENT_EPS` shaves 1 µm off the inter-conductor insulation; without it a
  wire randomly falls into a partial extra column (caught by the guard).
- Cache: `disk_cache` keyed on the DERIVED column geometry + runner-file sha +
  femmt version (all as arguments — `hash_func_code` can't see callees).
  Run artifacts land in `out/femmt_toroid/<key>/<pid>-<rand>/`.
