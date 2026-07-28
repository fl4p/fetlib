# apps/ — project configs and one-off analysis tools

- `apps/proj/*.yaml` — runnable project configs (consumed by `main.py --config-file`).
- `apps/mppts/libresolar.py` — hard-coded buck designs (`Fugu2_tall`, `MPPT_Fheat2`, …) used by `power_loss_calc.py`.
- Top-level scripts in `apps/` (`L`, `Ldc-turns.py`, `dcm.py`, `high-side.py`, `mag-dc-bias-curve.py`, `pv-coil-core-mat.py`, `Lmin.py`, `transfer_cache.py`) are one-off analysis tools.
