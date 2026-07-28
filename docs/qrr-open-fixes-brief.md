# Agent brief — open fixes around the operating-point Qrr work

Written 2026-07-28, after the `--qrr-op` chain landed (`71709bd3` → `22816626`). Everything
below is verified against the shipped DB unless marked otherwise. Numbers carry the commit
or date they were measured at, because several moved during that work and stale figures in
comments were a recurring problem.

---

## 0. Where things stand

`syncFet.qrrOperatingPoint` / `--qrr-op` rescales the LS body-diode reverse-recovery charge
from the datasheet test point to the converter's operating point via a Lauritzen–Ma fit
(`dslib/qrr_model.py`). Parts that cannot be evaluated there are excluded from the ranked
CSV and written to a sibling `-LS-unranked-` file with a reason.

Test-point provenance, highest evidence first — this ordering lives in
`dslib.mosfet.attach_qrr_registries` and is surfaced in the CSV's `Qrr_src`:

| tier | source | `Qrr_src` | where |
|---|---|---|---|
| per-row, two-point | generated + reviewed | `op-2pt` | `dslib/qrr_points.py` |
| hand-read from the PDF | human | `op-1pt` | `dslib/qrr_conditions.py` |
| machine-read from table geometry | generator | `op-1pt-layout` | `dslib/qrr_layout_conditions.py` |
| keyed cond-dict parse | parser | `op-1pt-parsed` | `DatasheetFields.qrr_test_conditions` |

Coverage at the fugu3 point (72→27 V, 900 W, 40 kHz): **3188 ranked / 815 excluded**,
measured at `ddc9521b` when the layout registry held 409 entries. Six were removed in
`22816626`, so **re-measure before quoting**.

---

## 1. Environment and gotchas

- Interpreter: `/Users/fab/dev/venvs/fetlib/bin/python`, run from the repo root.
- `datasheets_db.load()` takes ~30 s and holds a lot of memory. A full sweep over the
  corpus runs 5–20 min — **run it backgrounded**, not in a 120 s foreground call.
- `pdftotext` is on PATH. `-layout` matters (see §4).
- **Other agents edit this repo concurrently.** During the work above, peers committed to
  `dclib/powerloss.py`, `dslib/mosfet.py` and `unit/test_qrr_op_loss.py` mid-session, and
  one committed *my* uncommitted work under their own message. Before committing: check
  `git log --oneline -5` and `git status`, and if a file mixes your hunks with someone
  else's, stage surgically (save the file, write HEAD+your hunk, `git add`, restore) rather
  than sweeping their work into your commit.
- A single red test may be a peer mid-edit. Re-run before concluding.
- `test/unit` has 8 pre-existing failures (relative datasheet paths; they only resolve when
  pytest runs from inside `test/unit`). Not yours. `unit/` should be green — 84 at
  `22816626`.

---

## 2. FIX 1 — Qrr unit corruption in the DB (highest value, affects every consumer)

**Status:** root cause identified and quantified, **not fixed**. `22816626` only stops the
layout registry from inheriting it.

**What.** `dslib/field.py:494-499` converts a µC-scale Qrr to nC:

```python
if symbol == 'Qrr' and (not unit or unit.lower() == 'c'):
    if sum(math.isnan(v) or 0.1 < v < 0.9 for v in mtm) == 3:
        min *= 1e3; typ *= 1e3; max *= 1e3
```

It misses a whole class **twice over**: the gate demands the unit be absent or exactly
`'c'`, and the band demands every stat sit in 0.1–0.9.

**Evidence (verified).** `datasheets/infineon/IRFB38N20D.pdf` prints, via
`pdftotext -layout`:

```
Qrr  Reverse Recovery Charge   ---  1.3  2.0  C   di/dt = 100A/µs
```

The `µ` glyph is dropped by extraction, so the unit reads `C` and the DB stores
`typ=1.3, max=2.0, unit='PC'` (µC mangled further). True value 1.3 µC = **1300 nC**;
stored as 1.3 nC — 1000× low. Same for `IRFB41N15D`, `IRFIB41N15D`, `IRFS38N20D`,
`IRFS41N15D`, `IRFSL38N20D`.

**Scale (measured over the shipped DB, 2026-07-27).** Qrr field units:
`nC` 5359, `None` 463, `nc` 41, `UC` 12, `C` 8, `PC` 6, `μC`-with-whitespace 2.
So **28 fields carry a unit proving normalisation did not happen**, and 93 parts pair a
value < 10 with a non-`nC` unit (candidate lost prefix; includes the `None`-unit ones).

**Why it matters beyond `--qrr-op`.** The same scalar feeds the **flat** `P_rr` path in
`dcdc_buck_ls`, so these parts have been under-charged for reverse recovery in every run
ever made, flag or no flag. This is the same class as the `Rds_on` 1000× corruption already
on record.

**Acceptance criteria.**
- Handle mangled prefixes (`PC`, `UC`, `μC`-with-whitespace, and any surviving
  `[A-Zµμ]?C`) rather than only bare `c`/empty.
- Do **not** widen the 0.1–0.9 magnitude band into a general magnitude guess — that is the
  anti-monotone shape this repo keeps getting bitten by. Prefer deciding on the *unit*, and
  refuse (NaN) when the scale genuinely cannot be established. A missing Qrr is
  recoverable; a plausible wrong one is not.
- Calibrate on both directions: the six parts above must come out at ~1300 nC, **and** a
  set of known-good `nC` parts must be unchanged. Diff the whole DB's Qrr before/after and
  report how many records move and by what factor.
- Note `dslib/qrr_layout_conditions.py`'s unit gate becomes partly redundant afterwards —
  leave it (defence in depth, and it is cheap), but update its comment.

---

## 3. FIX 2 — two dies that need per-row data, not conditions

**Status:** diagnosed, not fixed.

`IPT013N08NM5LF` and `ISC014N08NM6` quote a complete test point but their DB `(Qrr, trr)`
pair is internally inconsistent — the `trr` belongs to a *different* di/dt row — so
`fit_lm` refuses them ("trr shorter than the current-ramp time"). **No `qrr_conditions.py`
entry can rescue them**; that was tested and it still fails.

`ISC014N08NM6`'s datasheet states both rows explicitly:
`VR=40V,IF=25A,diF/dt=100A/µs` and `VR=40V,IF=25A,diF/dt=1000A/µs`.

They belong in `dslib/qrr_points.py`, whose generator is
`unit/validate_qrr_didt_datasheets.py --emit-points`. Check whether that generator can pick
them up (it may need the same `-layout` treatment as §4), rather than hand-editing a
generated file.

---

## 4. FIX 3 — the remaining exclusions, by cause

From the final harvest at `22816626` (whole corpus, not the Vds window):

| count | reason | what would actually help |
|--:|---|---|
| 888 | no Qrr/trr in the DB | nothing here — no charge to scale |
| 610 | no recovery block in the layout text | OCR: many are image-only PDFs |
| 403 | **accepted** | — |
| 229 | Qrr value mismatch (wrong block) | per-row extraction (§3-style) |
| 58 | no PDF locally | `datasheets/` completeness |
| 30 | LM fit fails | genuine datasheet/parse inconsistency |
| 20 | Qrr unit not normalised | **fixed by §2** |

The **229 wrong-block** rejections are the most interesting: these are sheets where the DB's
Qrr came from a different block than the one the extractor read, i.e. multi-di/dt parts. They
are `qrr_points` candidates, and recovering them would also give those dies the better
two-point fit rather than a single-point one.

Separately, at the fugu3 point ~71–75 parts are excluded because
`ls_commutation_didt()` returns `None` — the HS gate charges (`Qgs2`/`Qg_th`/`Vpl`) are
missing, so no operating point can be formed at all. That is a **gate-charge parsing**
target, not a Qrr one.

`IPT014N10N5` is the canonical no-text-layer case: "Microsoft: Print To PDF", 11 characters
extract from 1.6 MB. It was curated by rendering page 5 and reading the table. If OCR is
attempted for the 610, that part is a ready-made test case.

---

## 5. FIX 4 — the Tj axis is still a flat scalar

`dcdc_buck_ls` applies `Qrr_temp_rise = 1.2` regardless of Tj. `qrr_model` *can* extrapolate
(`tau ~ T^N_TAU`), but its own docstring records that `N_TAU = 1.2` is a deliberately
conservative bound — roughly **2× steeper than the five measured AO dies** in
`dslib/qrr_tj_specs.py`. Switching the axis on today would replace one crude number with an
over-predicting model.

The honest fix is **more measured entries** in `qrr_tj_specs.py` (digitised 25/125 °C Qrr
charts), not flipping the switch. Per the global instructions, chart digitisation goes
through the `datasheet-chart-digitizer` library, and a new parameter category needs
human-verified samples before batch use.

---

## 6. Method rules — each of these cost a real defect in the work above

1. **Calibrate a guard in BOTH directions.** An `IF < 0.05 × Id` check written to catch
   captured multipliers refused 36 parts, *all false* (Vishay/AO/Diodes genuinely test body
   diodes at ~10 A on 200–400 A parts) and caught **zero** true cases the physics check did
   not already reject. It had been calibrated only against its known-bad input.
2. **A one-sided bound is not a bound.** `reject IRRM > 5×IF` let a 1000×-too-small charge
   (IRRM ≈ 0) through untouched. Bound both ends, and test the far tail.
3. **Two readings of the same corrupted source are not a cross-check.** The layout
   registry's headline safety property was exactly this and it shipped six wrong entries.
   Ask what the two signals *share* before calling them independent.
4. **Judge a datasheet from the PDF, not the text layer.** Six Infineon dies were written
   off as uncurateable from `pdftotext` output; `-layout` recovered five (their condition
   cell spans the trr/Qrr rows) and the sixth needed the page rendered and read.
5. **Never take a neighbouring number.** On every one of those dies the recovery `IF`
   differs from the adjacent Vsd row's (50 A vs 88 A, 50 A vs 100 A). Cross-row attribution
   would have been ~2× wrong on four of five.
6. **Verification artifacts must call the same code path as the code.** A sample sheet that
   re-derived its evidence quoted a marketing bullet as the source block. Evidence that
   doesn't match what ran is worse than none.
7. **Don't assert your expectations over the data.** A test pinning di/dt ∈
   {100,300,500,1000} was wrong: 400 A/µs and 3000 A/µs entries are genuine, corroborated by
   a stated `Irrm`. Assert a physical range plus a distribution, not an allowlist.
8. **Provenance must survive to the output.** If two tiers of evidence can't be told apart
   in the CSV, they will be compared as equals.
9. **Re-measure before quoting.** Several comments in this subsystem carried numbers that
   were true when written and stale by the time they were read. Date them or re-derive them.

---

## 7. Do not

- Do not hand-edit `dslib/qrr_layout_conditions.py` or `dslib/qrr_points.py` — both are
  generated. Change the generator and re-emit.
- Do not add machine-read entries to `dslib/qrr_conditions.py`. Its precedence over parsed
  data rests on a human having read the PDF; that is the only thing distinguishing the tiers.
- Do not run `apps/emit_qrr_layout_conditions.py` with a modified extractor without
  `--calibrate` passing 6/6 — it refuses on purpose, and the gate has already caught one
  cross-row miscapture that would have hit hundreds of parts.
- Do not "fix" a warning by making it quieter. Several numbers in this subsystem look wrong
  because they *are* wrong upstream.
