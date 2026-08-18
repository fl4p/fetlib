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
pytest unit                       # ROOT-level suite: the loss/registry models — Coss & Ciss
                                  # serving, Qrr op-point/Tj/layout, mpn_match, bv_specs (~2 min)
pytest test/unit                  # focused parser unit tests (text norm, pdf tree, mosfet specs) (~8-14 min)
pytest test/tests.py              # broader, heavier integration-style tests
pytest test/unit/test_mosfet_specs.py::test_name   # single test
```

**There are TWO pytest suites and `test/unit` is not the interesting one for model changes.**
`unit/` (repo root) and `test/unit/` are different directories: everything that exercises
`dslib/coss_curves.py`, `dclib/coss_loss.py` and the Qrr registries lives in the ROOT `unit/`.
Running only `test/unit` after touching a curve/loss registry passes without executing a single
test that covers it.

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

`unique_parts` deduplicates by `(mfr_tag, consolidation_key)`. **Digikey rows are treated as untrustworthy** — if a duplicate already exists, a digikey-only entry is dropped rather than merged (comment: "digikey data is often wrong"). Otherwise `.specs.update(part.specs)` merges fields from later sources into earlier ones.

Consolidation is union-find over three links (`_group_keys`), all of which must hold the same die — sources spell one part several ways and pre-2026-08 that shipped it as several competing CSV rows (603 extra rows out of 11,899 corpus-wide; `IPP039N10N5` / `…AKSA1` / `…XKSA1` were three rows, one of them holding the digitized Coss curve):

1. `normal_mpn` → `dslib.prices.family_mpn`, i.e. Infineon's full packing-code regex (this replaced four hardcoded suffixes) plus case/whitespace folding.
2. `mpn2` — the manufacturer's own "same part" pointer (`IRFB4110` ↔ `IRFB4110PBF`).
3. A reviewed cross-vendor packaging suffix (`PACKAGING_SUFFIXES`, shared with the DigiKey matcher) **on top of a base that is itself in the corpus** — never invents a base, so a lone `SUP70042E-GE3` stays as it is.

The merge is trial-run on a `deepcopy`: `MosfetBasicSpecs.update` asserts the sources agree (Vds exactly, Rds_on/ID within 45%, Qg within 1%) and mutates as it goes. On disagreement both rows are KEPT with a printed reason — a failed merge used to abort the whole run, and choosing a winner would publish one spelling's numbers under the other's name. Three parts are in that state today (`IAUCN10S5L094D`, `IAUCN10S7N021`, `IAUTN08S5N012L`: the base and `…ATMA1` listings disagree on Qg/ID).

The same ambiguity reaches the curated registries from the other side: an entry landed as `IPP039N10N5AKSA1` has to serve a run that ranked `IPP039N10N5`. `mpn_match.lookup_base_variant` therefore falls back to `are_packing_siblings` (exact key → base direction → sibling direction). Two cases, with different safe rules:

- **One side is the base** (`IQD020N10NM5` vs `…ATMA1`): `_is_packing_code` on the single remainder. The CG/SC **layout** allowance of `is_orderable_variant` is deliberately NOT applied — layout variants have their own datasheets and `COSS_CURVES` holds three distinct curves across `IQD020N10NM5`'s six spellings.
- **Neither side is a base** (`AKSA1` vs `XKSA1`): split at the DOCUMENTED packing-block width and require equal stems plus `_INFINEON_PACKING_RE` on both tails. Both looser formulations are wrong, and each was caught by an exhaustive pairwise scan of the corpus (cheap — re-run it after touching this):
  - splitting on the two MPNs' **common prefix** cuts inside the code when the codes share a leading letter (`AKSA1`/`ATMA1` → `KSA1`/`TMA1`);
  - accepting a loose `[A-Z]{2,5}\d` on **both** tails at once reads a die letter as a code — `ISC007N06LM6` vs `ISC007N06NM6` leaves `LM6`/`NM6`, same length and same shape as the real `AKSA1`/`XKSA1`, yet Infineon's `L` is the logic-level die (Vgs_th 1.1–2.3 V vs 2.1–3.3 V). No generic rule separates those two; only the documented block does.

**What counts as a packing code is reviewed, never guessed** — `_is_packing_code` accepts Infineon's fixed-width `[AXF][KTU][SM]A\d` block or a `PACKAGING_SUFFIXES` entry, and nothing else. Until 2026-08-08 the base direction used the same loose `[A-Z]{2,5}\d` shape, which cannot tell a packing code from a die/package letter *followed* by one, and it was live-serving curated `qrr_layout` rows across genuinely different parts. The corpus settles it: of the 2 992 Infineon MPNs whose stem is *also* a corpus part, 661 end in a width-5 block (14 distinct, all documented), and the only width-6 "codes" — `AXTMA1`, `TATMA1`, `GATMA1`, `AFKSA1` — are that same block with a letter stolen off the stem. `IAUTN15S6N025` is TOLL, `…G` is TOLG, `…T` is TOLT: three packages, three datasheets, and `qrr_layout` is layout-dependent. Two consequences worth knowing:

- The block's leading letter is `[AXF]`, not `[AX]` — `FKSA1` is real (5 parts). `dslib/prices:_INFINEON_PACKING` was missing it too, so `IPW60R045CPFKSA1` joined no price record and shipped as its own ranked row.
- `-7`/`-13` were **removed** from `PACKAGING_SUFFIXES`. They are reel diameters for Diodes/Zetex but the *lead count* for IXYS (`IXTA150N15X4` is TO-263-3, `…-7` is TO-263-7 with a Kelvin source), and all 8 corpus pairs are the IXYS case. Re-add only per-manufacturer.

Since `is_orderable_variant` sees no manufacturer, its allowlist is the union across vendors; that is safe in the refusing direction only, so prefer adding evidence over widening the pattern.

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

### 3a-bis. Scrambled font encodings — `dslib/pdf/fix_encoding.py` + two delegates (2026-08-18)

`fix_pdf_font_encoding` repairs PDFs whose embedded fonts use a scrambled encoding (text
extracts as `%&$!"#` but renders as `OptiMOS`) by deciding what each glyph IS and injecting a
fresh `/ToUnicode`. It runs from `pdf/pipeline.py` and sits **upstream of the entire
derivation** — a matcher change rewrites every value parsed from such a sheet, which is why
all three modules are in `_PARSE_DERIVATION_SOURCES`.

Four stages now decide a glyph, in descending order of evidence. Each **abstains** rather
than guessing, and the next one picks up what it left:

1. **`dslib/pdf/glyph_exact.py` — outline fingerprint.** A large share of broken files embed a
   standard face IN FULL (Arial, Arial-BoldMT, TimesNewRomanPSMT, Calibri) and merely withhold
   the `/ToUnicode`. Hash each glyph's decomposed outline at 1/1000 em and match against an
   index of installed system fonts (262 faces / 21k outlines here, cached to
   `data/cache/glyph-outline-index-v*.pkl`, ~7 s to build). Where it fires it is a lookup, not
   a similarity score. **Coverage is bimodal at 0.0 and 1.0** — the right face explains 60/60,
   82/82, 26/26 and every wrong one explains 0 — so `_MIN_COVERAGE` is a formality, not a tuned
   threshold. Requires the exact cut to be installed; abstains otherwise.
   - **Dead end, recorded so it is not re-attempted:** those Infineon fonts DO carry `post` and
     `cmap` with 84/87 glyphs "named" — but the names are `uniF020`, `uniF021`… i.e. the
     symbol-range spelling of the *scrambled* code, written by the subsetter after the scramble.
     Decoding them yields the identity map dressed as evidence, confidently wrong for 5 of the
     8 known-broken datasheets. Outline geometry is the only internal evidence not overwritten.
2. **`dslib/pdf/glyph_fontid.py` — face identification (biggest single win).** The pixel matcher
   used to compare every vendor face against DejaVu Sans regular+bold. Identifying the face
   first turns a cross-face comparison into a same-face one, and the face is a far easier
   question than the glyph: one font supplies 50–150 glyphs of evidence for a single answer.
   Two stages, and both are necessary:
   - **Width shortlist.** Nothing NAMES a scrambled font — Infineon's `name` table is the temp
     filename and PANOSE is zeroed. But METRICS survive: `Z_C00220.tmp`'s `/Widths` is
     `278 333 333 277 … 556 556 … 722 722 666`, Helvetica/Arial exactly (278 space, 556 digits,
     889 for `%`, 584 for the comparison operators). The widths are in *scrambled* code order so
     they identify no individual glyph, but as a MULTISET they fingerprint the face: over 184
     installed faces, `Z_C00220`→Arial Bold and `Z_C00222`→Microsoft Sans Serif/Arial. Correct
     both times (the first is the heading font, the second body text; MS Sans Serif is metrically
     identical to Arial by design).
   - **Visual rerank**, because obliquing a face does not change its advances, so widths cannot
     tell an upright from an italic — the two are separated by 0.3 out of 16.

   **The acceptance test is the whole safety argument, and the naive version regressed.** A face
   is used only if it beats the incumbent on BOTH `top1` and `margin`. Requiring both is not
   belt-and-braces:
   - `top1` alone cannot discriminate at all — it maxes over ~130 reference characters, so
     something always resembles the glyph. Measured on an Arial subset: DejaVu 0.9637, Arial
     0.9634. **DejaVu is already an excellent proxy for Arial-like faces**, which is why this
     stage correctly does nothing for most of the corpus.
   - `margin` alone picked **Verdana Italic** for an upright Verdana and cost 7.4 points
     (88.0%→80.6%). The italic is metrically perfect (EMD 2.75, obliquing preserves advances)
     and slanted glyphs are *more* mutually distinguishable, so it won on margin while losing
     0.018 of top-1. Margin says "this reference decides confidently"; top-1 says "about the
     right shapes". Pinned by `test_wrong_weight_or_slope_is_rejected`.
3. **The pixel matcher**: `cosine_blur` over baseline-anchored inked-pixel arrays, with the
   advance-width and hole-count tie-breakers. When stage 2 accepted a face, its bitmaps AND its
   metrics become the reference — so the width tie-break compares against the true advances
   rather than a fitted scale factor.

   **The metric was chosen by measurement** (`FETLIB_GLYPH_METRIC` to re-run it; 24 fonts,
   `holdout=family`):

   | metric | vision | +fontid |
   |---|---|---|
   | `cosine` (the original) | 69.9% | 75.9% |
   | `zncc` | 69.1% | 75.2% |
   | **`cosine_blur`** | **71.7%** | **80.0%** |
   | `zncc_blur` | 71.5% | 79.9% |

   Two ideas were tried and one paid. **Blurring** (a separable box blur, chamfer-matching
   without needing a distance transform or scipy) stops charging full price for a one-pixel
   offset between two renderings of the same letter. **Mean-centring** — expected to help by
   decompressing cosine's narrow high band — did not: it is a wash at best. The compression is
   real but harmless, because the median correct top1-vs-top2 gap is ~0.13, not the ~0.003 seen
   on the few genuinely hard pairs. `test/fix_enc_eval.py --calibrate` prints the distributions
   each metric's thresholds would need; carrying thresholds across a metric change is meaningless.

   **`dslib/pdf/fonts/` — the reference is bundled, not borrowed from the host.** It used to be
   whatever `fc-match sans-serif` returned: Arial on this Mac, DejaVu on a Linux box. Same
   commit, same PDF, different text — and this file previously *documented* it as DejaVu while
   the code was in fact using Arial. Now: **Liberation Sans** regular+bold (metric-compatible
   with Arial, which is what these datasheets are set in), gap-filled from **DejaVu Sans** for
   the two characters Liberation lacks (`℃℉`). The split is load-bearing — `_break_tie`
   separates `l` from `I` on advance width because vision cannot, and Liberation/Arial put them
   25% apart (222/278) where DejaVu puts them 6% apart (278/295). Switching the reference to
   DejaVu broke four tie-break tests outright. The bundle also gives `glyph_fontid` metric
   stand-ins for Arial/Times/Courier on a machine licensing none of them.
4. **`dslib/pdf/glyph_lm.py` — document-level n-gram arbitration.** The CIDs are not
   independent, they spell words. Coordinate ascent maximising `visual + LM(text) - collisions`,
   over an interpolated character 3-gram model trained on `dslib/pdf/glyph_lm_corpus.txt.gz`
   (regenerate: `apps/build_glyph_lm_corpus.py`). This is the shape the literature uses for
   exactly this problem (Krutko/Stefanovitch/Postanogov, DAS 2018 — CNN symbol recognition
   *with language model*; recovering CID→Unicode is a monoalphabetic substitution cipher).

**Four guards on the LM, each measured, not assumed** — the first version scored *worse* than no
LM at all (76.9% vs 78.3%) and every intermediate fix is load-bearing:
   - `_VIS_TEMP` converts cosine to a log-likelihood. Without it the two terms are in different
     units, vision contributes no dynamic range (its whole shortlist sits inside 0.05), and the
     LM decides every glyph on fluency alone.
   - `_CAND_BAND` — only candidates within 0.06 of the CID's best may be proposed. Unrestricted,
     the error profile was pure frequency preference: `9`→`0`, `q`→`o`, `μ`→`u`, `®`→`C`.
   - `_MIN_CID_OCCURRENCES` — a CID seen once is one n-gram window; deciding from it is
     noise-fitting, and every wrong move in the unrestricted run was a single-occurrence CID.
   - `_COLLISION_PENALTY` — a substitution cipher is near-injective and a font has no five
     identical glyphs. Nothing expressed this before, which is how `OptiMOS Power-Transistor`
     could read `Op//MOS Power-7rans/s/or` with `t`, `i` and `l` all collapsed onto `/`.

   **`cid_runs` assembles LINES from `Tm`/`Td` geometry, not from text-showing operands.**
   Infineon's distiller emits one `Tm <XX> Tj` PER GLYPH, so operand grouping hands the model
   one-character documents and it can do nothing at all. This is the difference between the LM
   working and not working — do not "simplify" it back.

**Face detection improves in aggregate but is NOT monotone per font, and no available statistic
fixes that.** Measured over ten faces at `holdout=family`: Times +5.6, Georgia +7.1, Trebuchet
+7.2, Arial +1.8, but **Verdana −5.5 and Tahoma −6.5**. Gain does not separate the groups
(Verdana harms at 0.040, Times helps at 0.056), nor does incumbent quality (Verdana 0.898 harms,
Trebuchet 0.895 helps), nor width consistency (it passes DejaVu for Verdana at 0.022 against the
incumbent's 0.063). The aggregate scores measure how well a face's repertoire *covers* the page,
and two sans faces can cover it equally well while disagreeing about which glyph is which. Where
the incumbent is the wrong CATEGORY (sans reference, monospace text) the gain is large and
reliable; where it is already a decent generic sans the swap is lateral, and lateral moves are
near coin flips. Raising the acceptance bar to suppress them costs more than they do — at a 0.05
gain threshold only Times survives, +5.6 against +9.7. So the contract asserted by
`test_improves_in_aggregate_with_bounded_individual_loss` is aggregate gain with a bounded tail,
not no-regression; the first version of that test asserted no-regression and was simply false.

**Accuracy is measured** — `test/fix_enc_eval.py`. It draws the matcher's own `_COMMON_GLYPHS`
plus real datasheet prose with a real font via pymupdf, records the correct `/ToUnicode`, then
deletes it; truth is known by construction.

**`--holdout` is not optional rigour, it is what makes the number mean anything.** Every trial is
drawn with an INSTALLED face, so without it `glyph_exact` finds the very file it was drawn from
and reports 100% — the harness handing the answer to the thing it tests. Three levels, 30 fonts:

| holdout | vision | +fontid | +exact | +lm | full |
|---|---|---|---|---|---|
| `none` — this exact cut installed | 73.4% | 100.0% | 100.0% | 77.2% | 100.0% |
| `file` — exact cut hidden, relatives visible | 73.4% | **94.9%** | 73.4% | 77.2% | **95.5%** |
| `family` — whole name stem hidden | 73.4% | **79.9%** | 73.4% | 77.2% | **82.4%** |

Cost: `fontid` is ~1.7 s/font against 0.5 for vision alone, because `_SHORTLIST` is 28 faces and
each needs rendering. Per-face renderings are cached across a run, and the stage is skipped
entirely when `glyph_exact` already resolved the font.

Read down the `exact` column: it is 100% or nothing, which is the method being honest. Read
across `fontid`: **face identification is the largest single improvement** and it degrades
gracefully rather than falling off a cliff, because a near-relative is still a far better
reference than DejaVu. `family` is the closest analogue to the Infineon subsets, whose true face
is installed nowhere here.

**`test/fix_enc_corpus_survey.py`** takes the same question to the REAL corpus, where no truth
exists at any price. It ranks files by the mean log-probability per character of the repaired
text under the `glyph_lm` model — a proxy, not accuracy, and one that lies in three known ways
(a font that declines every glyph scores WELL, since spaces contain no improbable n-grams; a page
of legitimate numbers scores BADLY), so `blank_frac` and `alpha_frac` are printed beside every
score and the pre-repair text is scored as a baseline. It defaults to running the matcher WITHOUT
its LM stage, because scoring a stage with its own objective is circular.

What it found on a 160-file sample: **most suspect fonts carry almost no text** — 113 files
produced under 50 characters, i.e. the suspect font is a logo or a few symbols while the body
text sits in an unaffected font. That is consistent with the pipeline note that only 88 of 2 368
suspect PDFs fail validation. The files where repair clearly helps are visible in the delta
(HY3503C2 −4.89→−2.86, HY1603C2 −4.54→−2.81, AON6220 −4.88→−2.70); at the median the delta is
about zero, which the proxy cannot distinguish from "there was little to fix". The report
accounts for every file it could not score rather than dropping them, because a survey that
lists only what it managed to score reads as a statement about the corpus.

The LM's value does not show in that table at all, because its production job is the subsets the
other two abstain on. It is demonstrated instead by a known-bad calibration in
`test/unit/test_glyph_exact_and_lm.py`: with `_break_tie` reverted to the raw visual winner,
`BSC190N15NS3_G.pdf` reproduces the documented `N-channeI, normaI IeveI` and **the LM repairs it
to `N-channel, normal level` on its own**, while leaving the already-correct mapping untouched
when the tie-breakers are on.

**Bug the harness found:** `_build_pil_font_for_gid_render` mapped *every* gid to
`_PUA_BASE + gid`, but the BMP Private Use Area is 6 400 codes and a format-4 cmap is 16-bit.
Any font over ~6 400 glyphs failed to compile, returned None, and produced **no mapping at
all** — silently, since a missing repair looks like a font that needed none. Arial Unicode has
50 377 glyphs; `MCAC100N08Y-TP.pdf` embeds MicrosoftYaHei at 30 133 and SegoeUISymbol at 9 209.
Now only the page's used gids are packed into the PUA.

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
  **default OFF**): DigiKey support confirmed 2026-07-28 that BatchProductDetails is
  DEPRECATED and will not be enabled for new users (PI V4 has no batch equivalent), so the
  ~3,073-candidate fugu3 corpus costs several key-days of keyword quota — add keys
  (`data/.digikey-api<N>`) to scale. The batch code is kept for apps with legacy
  enablement: SDK-default `/BatchSearch/v3` host (the fork's "v4" batch package is a v3
  alias — do not force /v4, that 404s), 50 MPNs+family bases = 1 request, per-key
  enablement probing (not-enabled signal: **401 "not subscribed"**; 403/404 too), fails
  open to keyword which owns all negative/quota accounting.
- **LCSC** (`dslib/prices/lcsc.py`): re-parses the price ladders out of the same
  `fetch_brand_rows_raw` envelopes discovery uses (`usdPrice` only — `currencyPrice` is
  locale-dependent), for `dslib.discovery.lcsc.brands` ∪ `EXTRA_PRICE_BRANDS` (major brands,
  ids probe-verified). Offers are aggregated by store key GLOBALLY across brands before ONE
  `add()` — per-brand batches would last-write-wins on cross-brand duplicates. Price-only path:
  it never feeds `DiscoveredPart`s into discovery. CLI: `python -m dslib.prices.lcsc
  --probe|--harvest|--find-brand NAME` (probe before harvesting after any brand/schema change).
- **main.py**: price fetching is **ON by default** (`--no-fetch-prices` opts out; the old
  opt-in `--fetch-prices` still exists and is now a no-op affirmation). It runs the LCSC
  harvest corpus-wide BEFORE the generators, then
  a DigiKey fetch for the **top `priceTopN`** (YAML, default 100; 0 = uncapped) of the fresh
  HS+LS ranking (interleaved, best first — quota goes to the interesting parts), then
  re-emits the CSVs if anything was fetched. Repeat runs are near-free (LCSC raw lists
  disk-cached 7d, DigiKey skips records younger than 7d); **both phases fail soft** — a
  missing/broken DigiKey key or an LCSC error prints a warning and the run completes with
  whatever the store holds, and neither writes a false "no price". The reason for the flip:
  the columns only ever showed what some *earlier* run happened to fetch, so a manufacturer
  that appears only in a config nobody had run with the flag (EPC, GaN-only) shipped 100%
  empty price/stock cells next to priced Si rows. The
  `price_usd`/`price_src`/`price_date`/`stock_dk`/`stock_lcsc` CSV columns fill from the
  store either way
  (`priceQty` YAML knob, default 100; per-row price = price@priceQty × parallel count; staged
  two-device rows price only when BOTH parts have prices). Fill-rate stats print next to each
  CSV path. Note each `asyncio.run` phase closes the shared Playwright browser on exit
  (`_discover_and_close_browser`) — `get_browser_page` asserts against contexts from dead
  event loops.

### 3d. C(V) review packets — `dslib/coss_review.py` (2026-07-29)

`main.py --coss-review N` builds a human-review packet for the top N parts of THIS run
still carrying a `scalar:` `Coss_provenance` (P_coss from the unverified single-anchor
1/√V guess, not a digitized curve). Which parts those are is design-dependent — the gan
project's LS top-10 is 9/10 EPC, the Si LS1p project's is Infineon/NCE — so the corpus is
derived from the ranking, never hand-listed. Parts are interleaved HS/LS, best first;
`0` = off, `<0` = every scalar part.

The work happens in **two other repos with their own venvs** (there is no importable path
from py3.9/3.10 fetlib into the digitizer's 3.14 env), so every stage is a subprocess:
`dsdig find` → `dsdig digitize-capacitance` → dsdig-verify-backlog
`tools/import_capacitance_batch.py` (this is where the fail-closed eligibility gate lives:
axis trust / trace validation / Qoss anchors — an ineligible row becomes a `gap`, never a
value) → rank injection → `tools/build_html_review_packets.py`. Paths default to the
checkouts under `~/dev/pv/ee/` and are overridable via `FETLIB_DSDIG_HOME` /
`FETLIB_DSDIG_BACKLOG_HOME`; a missing tool **raises** rather than skipping quietly.
Output: `out/<project>/coss-review-top<N>-<date>/`, packet HTML under
`review-backlog/review-html/`.

Load-bearing details, each of which cost a debugging round when absent:
- **`--include-gaps`** on the packet build. The fail-closed rows ARE the review corpus
  (25 of 48 cards in the first gan packet); without it the packet shows only extractions
  that already passed, i.e. the ones needing the least attention.
- **Rank injection.** The packet builder sorts cards on a `rank` field the importer does
  not write; without it every card sorts at `+inf` and the reviewer's attention goes to an
  arbitrary part.
- **Corpus-keyed scan reuse.** `charts.json` is reused only when `pdfs.txt` matches the
  requested PDF list exactly — keying on the directory alone would serve yesterday's scan
  after the ranking moved (same N, same date, different parts).
- **`source_head` says `-dirty`** when the digitizer worktree has uncommitted edits. A
  bare sha would claim a reproducibility the packet does not have.
- A part with unknown provenance is **counted and skipped**, never assumed scalar.
- **The scan is sharded here, not upstream.** `find_charts.main` is a plain sequential
  for-loop (~25 s/PDF) and per-PDF work is independent, so `_find_charts` splits the PDF
  list round-robin (not contiguous — per-PDF cost varies several-fold with page count)
  across `-j` processes, each with its own `--out`, then merges: `crop_png` is relative
  and namespaced per part, so the merge is concatenate-JSON + move `crops/<PART>/`, with
  the same final sort as `write_outputs`. Verified byte-identical to a sequential run on
  the same corpus and the same digitizer code. **A failing shard aborts** — merging the
  survivors would give the packet a silently short corpus, and a part missing from a
  review looks exactly like a part reviewed and found clean; failed shard dirs are left
  in place for debugging. Two datasheets mapping to one basename is refused up front
  (dsdig keys crops and review ids by basename). `FETLIB_COSS_REVIEW_JOBS` overrides.
  The **digitize stage is still sequential** — it's the smaller half.

Verified curves do NOT flow back automatically: a Green verdict has to be landed in
`dslib/coss_curves.py` as a `COSS_CURVES` entry **plus** a matching `COSS_CURVE_SOURCE`
entry (`COSS_CURVE_META` is a comprehension over `COSS_CURVES` doing
`**COSS_CURVE_SOURCE[key]` — a curve without its source entry is an import-time
`KeyError`). Once landed, any run picks it up with no re-parse: the attach is
`dslib/mosfet.py:attach_coss_registry`, reached via `get_mosfet_specs` on every run,
so `--no-parse` runs see new curves too.

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