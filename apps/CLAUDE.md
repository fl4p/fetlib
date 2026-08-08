# apps/ — project configs and one-off analysis tools

- `apps/proj/*.yaml` — runnable project configs (consumed by `main.py --config-file`).
- `apps/mppts/libresolar.py` — hard-coded buck designs (`Fugu2_tall`, `MPPT_Fheat2`, …) used by `power_loss_calc.py`.
- Top-level scripts in `apps/` (`L`, `Ldc-turns.py`, `dcm.py`, `high-side.py`, `mag-dc-bias-curve.py`, `pv-coil-core-mat.py`, `Lmin.py`, `transfer_cache.py`) are one-off analysis tools.
- `apps/inductor_core_sweep.py` — ranks toroid core × material × permeability × stacking × turns by copper + core loss for a buck inductor:

  ```bash
  python3 apps/inductor_core_sweep.py --vin 72 --vout 27 --pin 900 --f 40e3 [--max-od-mm 65]
  ```

  Reads its limits honestly in the module docstring — no AC resistance, no thermal model, nominal-only A_L, and ripple taken from the fully-biased L (6–20 % pessimistic). Three behaviours are load-bearing rather than incidental:
  - **Band-fit cores are EXCLUDED by default** (`--allow-band` to include, `src` column marks them). The band fit is optimistic, so those rows win rankings they should not — see `maglib/CLAUDE.md`.
  - **The turns loop must `continue`, never `break`, on a winding-fit failure.** The wound pass count `n·floor(passes/n)` OSCILLATES — 54 turns wind 108 passes, 55 wind 55, 56–108 climb back to 108. A `break` deleted 40,433 of 42,445 candidates at `--fill 0.40 --packing 0.45` and cost nothing at the default packing, so testing at defaults could not find it. Pinned by `test_wound_pass_count_is_not_monotone_in_turns`.
  - Every skip is counted and printed (not manufactured / band coefficients / below the validated 25 %-of-µi permeability band), and `--bore bare` prints that it is optimistic. A silently shortened table reads as a fact about physics.
