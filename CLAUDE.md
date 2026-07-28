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

Digikey input is CSVs under `parts-lists/digikey/*.csv` (downloaded manually from the Digikey parametric search, 500 results max per CSV). LCSC discovery hits the live `wmsc.lcsc.com` JSON API per brand id, browser-proxied through Playwright because of an Akamai TLS-fingerprint WAF (`dslib/discovery/lcsc.py:fetch`); the raw catalog rows are cached 7d by `fetch_brand_rows_raw` and shared with the price harvester. (An older HTML-DOM-dump path, `read_lcsc_search_results`, is dead code — no dumps were ever committed.)

Pre-selection by Vds/Id happens in `DcDcLoadParams.select_mosfets(parts, max_parallel=…)` — this is what filters down to candidates worth downloading datasheets for.

### 2. Datasheet fetch — `dslib/fetch.py`

`fetch_datasheet(url, dest, mfr=, mpn=)` handles manufacturer-specific redirects, anti-bot challenges, and PDF-preview pages via pyppeteer. Files land at `datasheets/<mfr>/<mpn>.pdf` (computed by `DiscoveredPart.get_ds_path()`). The `datasheets/` directory is gitignored and ships as a separate repo: `https://github.com/open-pe/fet-datasheets`.

### 3. PDF parsing — `dslib/pdf/`

Parsing is **deliberately multi-strategy with a priority order** (`README.md` "Field priority"); LLMs were tried and rejected as non-deterministic. **Priority = insertion order**: `DatasheetFields.add`/`Field.fill` keep the *first* non-NaN value per stat, so whichever stage adds a symbol first wins and later stages only fill gaps (`dslib/field.py`). The order values are added, highest priority first:

1. **Manual overrides** (`'ref'`) — `dslib/manual_fields.py` (`get_fields()` returns hand-curated `{mfr: {mpn: [Field, …]}}`; `fallback_specs(mfr, mpn)` provides GaN fallbacks). Added in `compile_part_datasheet` before parse.
2. **pdf2txt + regex** (`text`) — `dslib/pdf/pdf2txt/` and `dslib/pdf/expr.py` (`get_field_detect_regex`, `dim_regs_csv`, `dim_regs_multiline`). Cheapest (~0.5 s) and ~0% regression risk per the method-domination study, so it runs **first** inside `parse_datasheet` (as of the 2026-07 text-first reorder — it used to run last) both to win and to shrink `need_symbols`.
3. **Spatial query** (`v2`) — `dslib/v2/` (`parse_datasheet`; fitz/PyMuPDF char geometry, baseline row clustering, no Java/Tabula). **Replaced the hand-written `read_sheet` in the 2026-07 swap**: the method-domination study measured `read_sheet` at 0% sole-source with 97% of its values covered by v2 alone, while v2 matches tabular's precision (98%) and beats read_sheet on recall (89% vs 69%) at ~1.9 s/part vs ~25-113 s. Runs unconditionally (kept so, not gated — gating it dropped ~50 range values in testing). Falls back to OCR + re-parse when it yields nothing (v2 skips scanned PDFs by design). `read_charts` backfills `Vpl` here. `dslib/pdf/sheet/read_sheet` still exists for `datasheet.py read-sheet-debug` and tests, but is no longer in the pipeline.
4. **Tabula + regex** (`tabular`) — `dslib/pdf/tabular.py` (`tabula_browser`, `tabula_read`) iterates table rows. Most expensive (~177 s) and ~90 % redundant, so it runs **last** and is **skipped entirely / narrowed via `need_symbols`** once text+v2 cover what the caller asked for. When `need_symbols` drains to empty (text+v2 covered everything), tabular is skipped — which drops non-needed fields a cheap Tabula pass would have opportunistically harvested (pre-2026-07, Tabula *always* ran at least one pass). Those fields are re-fetched on demand by any run with a broader `need_symbols`, since parse is cached per need-set. Pass `--tabular-harvest` (→ `parse_datasheet(tabular_harvest=True)`) to restore the always-run behaviour for the fullest DB record, at the cost of a Tabula pass per otherwise-covered part.
5. **OCR** — `ocrmypdf` for unreadable/image-only PDFs (a text-extraction *fallback*, gated by `--no-ocr`, not a priority tier).

After parse, `compile_part_datasheet` appends discovery/vendor `part.specs` and GaN `fallback_specs` at lowest priority.

Entry point is `dslib.pdf.parse.parse_datasheet(...)`, called from `main.py:compile_part_datasheet`. Output is a `DatasheetFields` populated with `Field(symbol, min, typ, max, unit, cond=…, source=…)`. Fields carry their source tag (`'ref'`, `'v2'`, `'tabular'`, …) so later merges respect priority.

`subsctract_needed_symbols(need, have, copy=True)` is used everywhere to skip expensive extraction stages once a symbol is satisfied — it is what lets text-first skip tabular. Note it is **symbol-level, not stat-level**: a symbol counts as satisfied once *any* stat is present, so a stage may be skipped even if a needed `max`/`min` is still missing. It accepts tuple-symbol aliases.

The PDF cache (`@disk_cache` from `dslib/cache.py`) is keyed by file content + args and stored under `data/cache/`. Disable globally with `--no-cache` (calls `disk_cache_disable(True)`); per-worker, this must be re-called inside the worker (see `compile_part_datasheet`).

### 3b. The object stores — `dslib/store.py` (SQLite as of 2026-07-27)

`parts_db` and `datasheets_db` are **SQLite, one row per record, value = a pickle BLOB** (`data/parts-lib.sqlite3`, `data/datasheets-lib.sqlite3`), zlib-compressed. They used to be single whole-file pickles; the `.pkl` files are kept as rollback snapshots.

Why it changed: `compile_part_datasheet` calls `load_obj` **inside every joblib worker** (`main.py`), and on the old store that unpickled the entire DB — 3.5 s and **1.5 GB resident**, times `num_cores()+1` workers, to read two records. Keyed reads are now ~0.5 ms and ~0 MB. `add`/`del_obj` touch only the keys involved instead of rewriting 150 MB, which also removes the read-modify-write race that cost 1348 records 65,631 fields on 2026-07-27.

- **The API is unchanged** — `load()`, `load_obj()`, `add(merge=)`, `del_obj()`, `keys()` all behave as before. `load()` still returns a whole dict.
- **`load()`/`load_obj()` share instances** (an identity map). This is required, not an optimisation: `load_parts()` attaches curves/conditions by *mutating* the objects `load()` returned, and `MosfetSpecs.from_mpn` reads them back via `load_obj`. Break it and every curve/Qrr feature silently falls back for 100 % of parts.
- **New:** `iter_items(mfr=, mpn_like=)` streams (1.7 s, ~0 MB for a full pass — use it for audits), `save_all()`, `snapshot()`, `unload()`, `contains()`, `count()`.
- **Backup with `snapshot()`, never `shutil.copy2`** — a plain copy of a WAL-mode store misses the `-wal` sidecar and yields a backup with no tables in it, silently.
- **Rollback:** `FETLIB_STORE=pickle` forces the legacy backend, or delete the `.sqlite3`. `apps/migrate_store_to_sqlite.py --db X --export-pkl PATH` writes the store back out as a whole-file pickle.
- **Do NOT turn the blob into JSON.** A serializer would have to live in `dslib/field.py`, whose content hash *is* `field_repr_salt()` — editing it invalidates ~17 GB of parse cache and forces a full re-parse. It also cannot represent what the records hold (59 % of stat values are NaN; `Field.cond` keys are int 8:1). The long version is in the `dslib/store.py` module docstring.
- The migration is `apps/migrate_store_to_sqlite.py` (dry-run by default; verifies every record structurally, NaN/numpy-aware, and calibrates its own comparator against known-bad inputs before trusting it).

### 3c. Distributor prices — `dslib/prices/` (2026-07)

`prices_db` (`data/prices-lib.sqlite3`, same `ObjectDatabase` machinery) holds one `PartOffers`
record per **4-tuple key `(mfr, mpn, distributor, currency)`** — full qty ladders + MOQ/stock +
`fetched_at` (always the ORIGIN fetch time, never a DB-write time). The store itself is
latest-snapshot; **price history** is the append-only side table `data/prices-history.sqlite3`
(`dslib/prices/history.py`): both fetchers call `record_history()` after `prices_db.add`, and a
snapshot is appended only when its price CONTENT changed (hash over status/currency/sku/moq/
ladder — deliberately not `stock`, which jitters every fetch; stock is sampled at change points).
Negative statuses are datapoints (a part vanishing from the catalog gets a NULL-price row).
Inspect with `python -m dslib.prices.history <mfr> <mpn>`. Guard semantics are load-bearing: absent key = never fetched;
`status='catalog_miss'` = DigiKey said no such part (LCSC can never assert this — a brand-list
harvest can't prove absence); fetch/parse errors write **nothing**. `PriceLookup(qty, max_age)`
is the read side: it skips-and-counts foreign-currency and stale records (never mixes them into
a column) and returns `None`, never 0, for unpriced parts.

- **DigiKey** (`dslib/prices/digikey_api.py`): official v4 API via the **hurricaneJoef
  digikey-api fork** pinned in requirements.txt (PyPI release is broken/v3-only; the old
  vendored `digikey/` dir and `dslib/pricing.py` are gone). **Multi-key**: creds from env plus
  every gitignored `data/.digikey-api*` file (one app each, 120/min + 1,000/day PER key); OAuth
  token stores per key in `dslib/dk-cache*/`; jobs rotate across keys, a key retires on 2
  consecutive post-backoff 429s (daily quota) or X-RateLimit-Remaining < 25, and un-fetched
  parts wait for the next run. Calls `keyword_search_with_http_info` DIRECTLY — the SDK wrapper
  swallows ApiException and drops the rate-limit headers. Per-MPN keyword search of the ranked
  candidates only; no disk_cache (prices_db freshness gate, `max_age='7d'`, is the single
  authority). Match tiers: exact / MPN equality / `base_product_number` / a COMPLETE
  reviewed packaging suffix (`PACKAGING_SUFFIXES`; generic letter/separator continuations are
  different parts); all-candidates-rejected ⇒ `IndeterminateMatch`, writes nothing. Offers
  with `moq > qty` do not price at qty (no MOQ-tier flattery). **Batch path** (`use_batch`,
  default on): BatchProductDetails at the SDK-default `/BatchSearch/v3` host (the fork's
  "v4" batch package is a v3 alias — do not force /v4, that 404s), 50 MPNs = 1 request;
  enablement is PER APP, so each key is probed and a not-enabled signal retires it from
  batch only (keyword still works) — the observed live signal is **401 "not subscribed to
  this API"**, with 403/404 handled too; batch writes only `ok` records and returns
  everything else to the keyword phase, which owns all negative/quota accounting. As of 2026-07-28 enablement was
  requested but not yet granted — until then runs print the fallback line and the
  ~3,073-candidate fugu3 corpus costs several key-days of keyword quota.
- **LCSC** (`dslib/prices/lcsc.py`): re-parses the price ladders out of the same
  `fetch_brand_rows_raw` envelopes discovery uses (`usdPrice` only — `currencyPrice` is
  locale-dependent), for `dslib.discovery.lcsc.brands` ∪ `EXTRA_PRICE_BRANDS` (major brands,
  ids probe-verified). Offers are aggregated by store key GLOBALLY across brands before ONE
  `add()` — per-brand batches would last-write-wins on cross-brand duplicates. Price-only path:
  it never feeds `DiscoveredPart`s into discovery. CLI: `python -m dslib.prices.lcsc
  --probe|--harvest|--find-brand NAME` (probe before harvesting after any brand/schema change).
- **main.py**: `--fetch-prices` runs both fetchers for the post-`select_mosfets` candidates;
  the `price_usd`/`price_src`/`price_date` CSV columns fill from the store either way
  (`priceQty` YAML knob, default 100; per-row price = price@priceQty × parallel count; staged
  two-device rows price only when BOTH parts have prices). Fill-rate stats print next to each
  CSV path. Note each `asyncio.run` phase closes the shared Playwright browser on exit
  (`_discover_and_close_browser`) — `get_browser_page` asserts against contexts from dead
  event loops.

### 4. Modelling — `dclib/powerloss.py`

`SwitchPowerLoss(P_cl, P_gd, P_sw, P_coss, P_rr, P_dt, cond=…)` aggregates loss components. `dcdc_buck_hs(...)` / `dcdc_buck_ls(...)` are the per-slot entry points used by `main.py` to fill the CSV columns (`P_on`, `P_on_ls`, `P_sw`, `P_rr`, `P_dt_ls`, `P_hs`, `P_2hs`, `P_ls`, `P_2ls`). The HS/LS asymmetry — reverse-recovery loss `P_rr` is caused by LS but dissipated in HS — is built into the column semantics; preserve that when changing the model.

CCM is assumed (`DCMNotImplemented` exists as a placeholder).

### 5. `maglib/` — inductor design

See `maglib/CLAUDE.md` (loads when working under that directory).

### Project apps — `apps/`

See `apps/CLAUDE.md` (loads when working under that directory).

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