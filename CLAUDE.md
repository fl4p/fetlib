# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Three related tools in one Python project ("fetlib"):

1. **MOSFET datasheet parser & parametric search** — scrape manufacturer sites, download PDFs, extract specs, build a CSV ranked by estimated DC-DC power loss.
2. **Power-loss modelling for synchronous buck** — gate-charge-curve based HS/LS loss estimate (more accurate than `Rds_on * Qg` FoM).
3. **Inductor (powder core) design & loss** — `maglib/`, sendust/Micrometals-style materials with DC-bias and core-loss models.

The README is mostly accurate for usage; this file captures the architecture and runtime contract that's not obvious from reading individual files.

## Running things

There is no `pyproject.toml`/`setup.py` — this is run as scripts from the repo root with `python3.9` and `requirements.txt` in a venv.

```bash
python3 main.py --config-file apps/proj/buck.yaml    # full pipeline driven by a YAML
python3 main.py                                       # uses DcDcLoadParams.default()
python3 discover_parts.py                             # only the parts-discovery + download phase
python3 datasheet.py <command> <pdf>                  # single-file utility: open|ascii|parse|read-sheet-debug|power|html|html-pm|rasterize
python3 power_loss_calc.py                            # plot loss curves for hard-coded MPPT designs in apps/mppts/
```

YAML projects live in `apps/proj/*.yaml` (`buck.yaml`, `fugu*.yaml`, `mppt*.yaml`). Schema is consumed in `main.py:main_yaml` → `RunArgs` / `DcdcArgs` / `ControlFetArgs` / `SyncFetArgs` / `InductorArgs`; each load point becomes a `DcDcLoadParams`. Currently only `topology: buck` is accepted and exactly one load point per run.

Tests use pytest (no `pytest.ini` / `conftest.py`):

```bash
pytest test/unit                  # focused unit tests (text norm, pdf tree, mosfet specs, etc.)
pytest test/tests.py              # broader, heavier integration-style tests
pytest test/unit/test_mosfet_specs.py::test_name   # single test
```

Many tests under `test/` are loose scripts (`benchmark.py`, `pdf2table.py`, `plumber.py`, …) — not pytest, run directly with `python` when needed.

## External tooling (must be installed; not pure-Python)

The datasheet pipeline shells out to / drives several non-Python tools — missing them silently degrades parsing. From the README:

- **Tabula** (Java) — `tabula-py` plus the Tabula app GUI used as a browser-style table extractor. `dslib/pdf/tabular.py` launches Tabula via file locks `.tabula_browser_{1..5}.lock` at the repo root, capped by `tabula_browser_concurrency = 5`. On macOS Apple Silicon use Zulu JDK.
- **Ghostscript ≥ 9.55**, **poppler-utils**, **qpdf**, **sips**, **CUPS-PDF**, **FontForge** (`dslib/pdf/fonts.py` shells `fontforge_bin`), **Tesseract** (used via `ocrmypdf`).
- **Chromium via `pyppeteer`** for anti-bot datasheet downloads — uses a persistent profile at `dslib/chromium-user-data-dir/`. **Chromium's built-in PDF viewer must be disabled** (`"plugins": {"always_open_pdf_externally": true}` in `Default/Preferences`) — otherwise PDF downloads can't be captured.

## Architecture: discovery → fetch → parse → model → CSV

The pipeline in `main.py:run` is a linear flow; understanding it requires reading several modules together.

### 1. Discovery — `dslib/discovery/`

Per-manufacturer scrapers (`infineon.py`, `ti.py`, `toshiba.py`, `st.py`, `onsemi.py`, `vishay.py`, `nxp.py` (nexperia), `ao.py` (alpha&omega), `tw.py` (taiwansemi), `huayi.py`, `qorvo.py`, `epc.py` (GaN), `lcsc.py`, `digikey.py`, `china.py`) each return `List[DiscoveredPart]`. `discover_parts.py:discover_mosfets` runs them all (mostly `async`) and merges with `unique_parts`.

`unique_parts` deduplicates by `(mfr, normalized_mpn)`. Infineon-specific suffix stripping (`AKMA1`, `AKSA1`, `XKSA1`, `XKMA1`) is applied. **Digikey rows are treated as untrustworthy** — if a duplicate already exists, a digikey-only entry is dropped rather than merged (comment: "digikey data is often wrong"). Otherwise `.specs.update(part.specs)` merges fields from later sources into earlier ones.

Digikey input is CSVs under `parts-lists/digikey/*.csv` (downloaded manually from the Digikey parametric search, 500 results max per CSV). LCSC inputs are HTML DOM dumps under `parts-lists/lcsc/`.

Pre-selection by Vds/Id happens in `DcDcLoadParams.select_mosfets(parts, max_parallel=…)` — this is what filters down to candidates worth downloading datasheets for.

### 2. Datasheet fetch — `dslib/fetch.py`

`fetch_datasheet(url, dest, mfr=, mpn=)` handles manufacturer-specific redirects, anti-bot challenges, and PDF-preview pages via pyppeteer. Files land at `datasheets/<mfr>/<mpn>.pdf` (computed by `DiscoveredPart.get_ds_path()`). The `datasheets/` directory is gitignored and ships as a separate repo: `https://github.com/open-pe/fet-datasheets`.

### 3. PDF parsing — `dslib/pdf/`

Parsing is **deliberately multi-strategy with a priority order** (`README.md` "Field priority"); LLMs were tried and rejected as non-deterministic. Order of preference per field:

1. **Manual overrides** — `dslib/manual_fields.py` (`get_fields()` returns hand-curated `{mfr: {mpn: [Field, …]}}`; `fallback_specs(mfr, mpn)` provides GaN fallbacks).
2. **pdf2txt + regex** — `dslib/pdf/pdf2txt/` and `dslib/pdf/expr.py` (`get_field_detect_regex`, `dim_regs_csv`, `dim_regs_multiline`). The PDF text extractor reconstructs words/lines/blocks from character bounding boxes; super/subscript handling is intentional.
3. **Tabula + regex** — `dslib/pdf/tabular.py` (`tabula_browser`, `tabula_read`) iterates table rows.
4. **Spatial query** — `dslib/pdf/sheet/` (`read-sheet-debug` in `datasheet.py` exposes it); regex-style search combined with 2-D raytracing over character bounding boxes for awkwardly-laid-out tables.
5. **OCR** — `ocrmypdf` for unreadable/image-only PDFs, gated by `--no-ocr`.

Entry point is `dslib.pdf.parse.parse_datasheet(...)`, called from `main.py:compile_part_datasheet`. Output is a `DatasheetFields` populated with `Field(symbol, min, typ, max, unit, cond=…, source=…)`. Fields carry their source tag (`'ref'`, `'read_sheet'`, `'tabular'`, …) so later merges respect priority.

`subsctract_needed_symbols(need, have, copy=True)` is used everywhere to skip expensive extraction stages once a symbol is satisfied. It accepts tuple-symbol aliases.

The PDF cache (`@disk_cache` from `dslib/cache.py`) is keyed by file content + args and stored under `data/cache/`. Disable globally with `--no-cache` (calls `disk_cache_disable(True)`); per-worker, this must be re-called inside the worker (see `compile_part_datasheet`).

### 4. Modelling — `dclib/powerloss.py`

`SwitchPowerLoss(P_cl, P_gd, P_sw, P_coss, P_rr, P_dt, cond=…)` aggregates loss components. `dcdc_buck_hs(...)` / `dcdc_buck_ls(...)` are the per-slot entry points used by `main.py` to fill the CSV columns (`P_on`, `P_on_ls`, `P_sw`, `P_rr`, `P_dt_ls`, `P_hs`, `P_2hs`, `P_ls`, `P_2ls`). The HS/LS asymmetry — reverse-recovery loss `P_rr` is caused by LS but dissipated in HS — is built into the column semantics; preserve that when changing the model.

CCM is assumed (`DCMNotImplemented` exists as a placeholder).

### 5. `maglib/` — inductor design

Largely independent of the FET pipeline; pulled in via `dclib.powerloss` for AC-resistance and core-loss factors (`MagneticCoreSpecs`, `acr_factor_micrometals`, `skin_depth`, `d2awg`, `MaterialResistivity`). Materials are loaded from `maglib/materials/micrometals.csv`.

### Project apps — `apps/`

- `apps/proj/*.yaml` — runnable project configs (consumed by `main.py --config-file`).
- `apps/mppts/libresolar.py` — hard-coded buck designs (`Fugu2_tall`, `MPPT_Fheat2`, …) used by `power_loss_calc.py`.
- Top-level scripts in `apps/` (`L`, `Ldc-turns.py`, `dcm.py`, `high-side.py`, `mag-dc-bias-curve.py`, `pv-coil-core-mat.py`, `Lmin.py`, `transfer_cache.py`) are one-off analysis tools.

## Conventions & gotchas

- **Python 3.9** is the target. `pyppeteer` and the asyncio control flow depend on it; don't bump without checking.
- Datasheet parsing surfaces lots of warnings like `error parsing field …` — these are **expected** for unsupported table layouts (see the TODO block at the bottom of `README.md`). Don't try to silence them blindly; they're signal for which parser strategy failed.
- `tabula_is_running()` and the `.tabula_browser_N.lock` files at the repo root are the cross-process lock. If they're stale after a crash, delete them.
- `excludes = {…}` at the top of `main.py` is a runtime skip-list of known-broken datasheets. The file currently `excludes.clear()`s right after, then re-adds a couple — keep that pattern if extending.
- Manufacturer name normalization goes through `dslib/__init__.py:mfrs` (e.g. `infineon` covers "international rectifier", `onsemi` covers "fairchild", `ts` covers "taiwan semiconductor / taiwansemi"). `mfr_tag()` is the canonical-key helper.
- "Substrate" is one of `{Si, GaN, SiC}`; GaN parts use `Von_GaN` from `GateDrive` and an `IDP_ID_RATIO = 10` pulse-current allowance.
- A pile of `?? docs/img*.png` and stray `img.png` files at the repo root are intentional README assets — don't tidy them away.
- `out/` (gitignored) is where generated CSVs land (`fets-buck-…-csv`, etc.).
- The `data/cache/` directory (gitignored) can grow large. `disk_cache` has TTL semantics — see `disk_cache(ttl, ignore_kwargs=, file_dependencies=, out_files=, salt=)`.
- The Chromium profile under `dslib/chromium-user-data-dir/` is checked in for `Preferences` only; the rest is gitignored. Don't commit cookies or auth state from it.


## Agent Instructions
In case you cannot find a tool or software package try to install it, if you cannot install let me know.
Do the same when you encounter a dependency issue or ModuleNotFound error.