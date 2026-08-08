# maglib — inductor (powder core) design & loss

Largely independent of the FET pipeline; pulled in via `dclib.powerloss` for AC-resistance and core-loss factors (`MagneticCoreSpecs`, `acr_factor_micrometals`, `skin_depth`, `d2awg`, `MaterialResistivity`).

**Tests in `maglib/tests.py` are not collected by pytest.** They run only because
`test/unit/test_maglib_refs.py` imports each one BY NAME. A new test there that is
not added to that import list silently never runs — three had rotted that way before
anyone noticed. See that file's docstring.

## Core geometry: coated vs bare (2026-08)

`ToroidShape` carries the published BARE nominals (`ID`/`OD`/`HT`) **and** the coated
values (`ID_coated` = datasheet ID(min), `OD_coated` = OD(max), `HT_coated` = Ht(max)).
Powder cores ship epoxy/parylene coated and the sheets say "If coated, Max./Min.
includes coating".

- **Use `MagneticCoreSpecs.winding_geometry()`** → `(ID_coated, OD_coated, HT_coated)`.
  It RAISES unless all three are known, naming the missing one. `winding_bore()` is
  its first two elements (that is what `dclib/powerloss.py` wants for
  b_eq = π/2·(ID+OD)).
- **It returns all three together on purpose.** Handing back a subset is what caused
  the bug it exists to prevent: coated ID+OD with a BARE height left
  `mean_turn_length` — 2·(build + HT), where HT dominates — 1.6–2.9 % short, which is
  optimistic and *larger* than the error that adding the coated OD had just fixed.
- **There is deliberately only ONE accessor.** A `winding_bore_coated()` existed
  briefly alongside a bare-returning `winding_bore()`; two accessors differing only in
  optimism, with the safe one opt-in, get picked wrongly — `dclib/powerloss.py` was
  already calling the optimistic one. Don't reintroduce the split.
- **"Coated is the pessimistic choice" is FALSE in general.** True for winding *fit*,
  which depends on ID alone. For `b_eq`, which depends on the SUM ID+OD, coating
  removes ~0.9 mm of bore but adds ~1.3 mm of OD, so the sum rises and the proximity
  factor *falls* ~0.76 %. Check the direction per consumer.
- **Winding fit is limited by BORE AREA, not core volume.** Stacking multiplies A_L and
  adds exactly zero bore, so one size up beats a stack. A sweep over only the shapes
  maglib happens to define answers a narrower question than asked, silently — the
  missing sizes are absent, not wrong.

## Material coefficients: two sources, and they are not equally trustworthy

1. **`micrometals_parts.csv`** (761 rows) — per orderable part, off its own datasheet.
   `micrometals_part_material(part)`. Prefer this; the split IS the row.
2. **`micrometals.csv`** — per (material, permeability) with a coarse OD band.
   `micrometals_material(mat, shape, ui, od=…)`. **`od=` is required** whenever more
   than one row exists, else `AmbiguousMaterialSize` — the 16 size-qualified rows
   (`T(OD=5.22-6.00 in)`) were unreachable for years, so every caller silently got the
   SMALL-size fit. Band bounds carry a 0.02 in tolerance (T520 is 5.2181 in against a
   stated 5.22).

`MagneticCoreMaterialSpecs.coef_source` is `'datasheet'` or `'band'`.
**The band fit is optimistic** — up to 35 % low on core loss, 22 % high on retained
permeability — so a core whose datasheet could not be fetched *outscores* the
manufacturer's own numbers and rises in a loss ranking. Check `coef_source` before
ranking. `MicrometalsToroid()` prefers per-part and falls back to the band.

Known gaps: **GX and SM have no per-part rows at all**; 43 datasheet URLs return HTTP
403 AccessDenied (the parts ARE catalogued — sizes 250–775 at µ 125–205, i.e. the large
cores a loss ranking favours); OC 125 µ splits at exactly T250 and `micrometals.csv` has
no qualified row for it. `dc_magnetization` is not printed as coefficients on the
datasheets, so it always comes from the band model.

Every per-part row is validated against the calibration point printed on its OWN
datasheet, and `test_micrometals_per_part_coefficients` re-runs that check on the
shipped data. Note the self-check cannot catch a whole-row mis-keying on its own (both
halves move together and stay coherent) — the part↔fam/size/ui check and the
per-part-vs-band ratio bound (0.55–1.50) are what cover that.

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
