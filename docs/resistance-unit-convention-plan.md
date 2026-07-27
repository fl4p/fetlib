# Plan: settle the resistance unit convention, then repair the data

**Status:** proposed, not started. Written 2026-07-26 after a botched `Rg` data repair
(reverted) showed the defect is in the *readers*, not the data.

## Why the obvious fix is wrong

The tempting move is "find implausible resistance values in the DB and rescale them".
That was attempted and reverted. It deleted ~352 **correct** values and preserved the
genuinely broken ones, because it measured the *storage* convention while ignoring the
*consumption* convention.

**Do not repair data until the readers agree.** Otherwise the repair is calibrated
against whichever reader you happened to look at, and it relocates the error instead of
removing it.

## The actual defect: three readers, three conventions

Two symbols hold resistance, on **different scales**, and every consumer hand-rolls its
own conversion:

- `Rds_on` — canonical **mΩ** (mostly; see contamination below)
- `Rds_on_10v` — **ohm**-scale by convention (100% unitless in the DB, median ratio vs
  `Rds_on` exactly 1.0)
- `Rg` — **either**: `field_mul` reads a `m*`-prefixed unit as mΩ and *anything else as
  ohms*

| consumer | `Rds_on_10v` | `Rds_on` | verdict |
|---|---|---|---|
| `dslib/field.py:350` + `:377` `get_row` → `Rds_max` | `*1000` → mΩ ✓ | `*1000` on an already-mΩ value | **503 parts 1000x too big** |
| `dslib/field.py:458` + `:500` `get_mosfet_specs` | `*1e3` then `*1e-3` → Ω ✓ | `*1e-3` → Ω ✓ *if truly mΩ* | correct unless the entry is ohm-scale |
| `main.py:649-653` and `:807-811` | fallback **2nd** | tried **1st**, then `if <0.1: *=1000` | **anti-monotone**, see below |
| `dslib/field.py:462` `field_mul` (`Rg`) | n/a | non-`m` unit ⇒ ohms | the only reader that is explicit |

Three further consequences, all verified:

1. **`main.py` precedence is inverted vs `field.py`.** `main.py` prefers `Rds_on` then
   `Rds_on_10v`; `field.py:350` and `:458` prefer `Rds_on_10v` then `Rds_on`. Two call
   sites, opposite order, for the parameter the tool ranks on.
2. **`main.py:652` / `:810` `if rds_on_max < 0.1: *= 1000` is anti-monotone.** It is the
   (undocumented) Ω→mΩ conversion for the `Rds_on_10v` branch above it — so it must not
   simply be deleted — but **299 parts with `Rds_on_10v` in 0.1-0.145 Ω (>=100 mΩ) escape it** and are reported 1000x
   low, giving ~0 computed `P_on`. The failure direction **promotes** wrong parts to the
   top of the ranked CSV, which is the worst possible direction for a ranking tool.
3. **`Rds_on` itself is unit-heterogeneous**: 135 parts carry unit `':'` and 17 carry
   `'Q'`, holding ohm-scale numbers in the mΩ symbol. Unlike `Rg`, `field_mul` gives
   `Rds_on` no ohm handling. Currently masked by two accidents rather than guards:
   `get_mosfet_specs` prefers `Rds_on_10v`, and an FoM assert **silently drops 336
   parts** rather than reporting a unit problem.

### Counts and how they were measured

The two figures above are **metric-dependent** — an independent reviewer measured ~350
and 74 for the same defects using different accessors and additional selection filters.
Mine, measured over all 6040 DB parts taking `Rds_on.max` falling back to
`typ_or_max_or_min`:

- `Rds_on` present and `Rds_on_10v` absent (so `get_row` takes the fallback and applies
  `*1000` to an already-mΩ value): **503 parts**
- `Rds_on_10v` between 0.1 and 0.145 Ω, i.e. >=100 mΩ, so `main.py`'s `<0.1` gate never
  fires: **299 parts**

Re-measure with the exact accessor a fix will use before quoting a number in a commit
message; do not treat either set as authoritative.

## Phases

### Phase 0 — make the tests capable of failing (do this first)

`Field.__eq__` returns `True` for **any** scalar (verified: `Field(typ=620) == 999999`
is `True`). So every assertion of the form `assert ...Rg == 0.62` in
`test/unit/test_extract_text.py` **cannot fail** — at least lines ~615 and ~654.

- Make `Field.__eq__` return `NotImplemented` for unsupported types (or compare against
  `typ_or_max_or_min`), then fix the assertions that start failing.
- Rationale: every later phase is validated by this suite. Fixing data or readers while
  the suite contains vacuous assertions means the validation proves nothing.
- **Calibrate:** confirm at least one previously-passing assertion now fails.

#### Phase 0 — DONE 2026-07-26

`Field.__eq__` now returns `NotImplemented` for anything that is not a `Field` or a
(min,typ,max) triple. Calibrated: `Field(typ=620) == 0.62` and `== 999999` both went
`True` -> `False`; triple comparison unchanged. `test/unit` back to its 14 pre-existing
failures / 112 passed baseline (no new breakage).

Five vacuous assertions found and made explicit — and **three of them exposed live
bugs**, so their original expected values were KEPT rather than bent to match output:

| site | was | now | outcome |
|---|---|---|---|
| `test_extract_text.py:611` | `.Qg == 120` | `.Qg.typ == 120` | passes (was right) |
| `test_extract_text.py:647` | `.Rg == 0.62` | `.Rg.typ == 620` | passes; expectation was in Ω, storage is mΩ |
| `tests.py:318` | `.Qrr == 220` | `.Qrr.typ == 220` | **FAILS — see (a)** |
| `tests.py:322` | `.Qrr == 1.18e3` | `.Qrr.typ == 1.18e3` | **FAILS — extraction yields 1100, not 1180** |
| `tests.py:325` | `.Qrr == 1.18e3` | `.Qrr.typ == 1.18e3` | **FAILS — see (b)** |

**(a) `mC` is an unhandled charge-unit spelling.** `ao/AON7462` stores `Qrr` = 0.22 with
unit `'mC'`. `Field.__init__` converts `{uC, μC, ∝C, uc}` -> nC (x1000) but not `'mC'`, a
misrendered µC, so 0.22 µC never becomes 220 nC. Same class as the ohm-spelling gap.

**(b) NEW, and the most serious: `fill()` merges stats across candidates without
re-validating, and v2 loses charge units.** `ao/AOB66515L` ends up with
`Qrr typ=1.18, max=1180, unit='nC'` — `max/typ = 1000`, a ratio `Field.__init__` can
never produce because its own assert caps it at 5. Mechanism: v2 emitted
`typ=1.18, unit=None` (source `['v2','pg2','y371']`) while THREE text candidates
correctly gave `typ=1180 nC`; `fill()` took v2's unitless typ and text's united max, and
`get_unit` reported the first candidate's `'nC'` so the result LOOKS coherent.
Two fixes needed, and they belong in Phase 1:

- `fill()` must re-run the max/typ ratio check after merging, or refuse to mix stats whose
  source units differ.
- v2's `_UNIT_REQUIRED` covers only `{Rds_on, Rg, Rds_on_10v}`. `Qrr` is printed in both
  nC and µC across this corpus — 1000x apart, exactly the property that made resistance
  dangerous — so the unit-required refusal must extend to the charge family
  (`Qrr, Qg, Qgs, Qgd, Qsw, Qoss, Qg_th`). Relayed to the v2 owner.

### Phase 1 — one conversion helper, no hand-rolled scaling

Add a single accessor that is the *only* way to read resistance, e.g.
`DatasheetFields.get_resistance_ohm(sym, cond=None) -> float`:

- Uses `Field.unit` when it is a recognised resistance unit (canonicalising the ohm
  spellings `Ω`/`Ω`/`O`/`Q`/`QO`/`Ohm`/`W` with optional `m`/`k`/`M`).
- Knows the per-symbol storage default for a **missing/unrecognised** unit
  (`Rds_on` ⇒ mΩ, `Rds_on_10v` ⇒ Ω, `Rg` ⇒ Ω — matching today's `field_mul`).
- Returns **NaN, never a guess**, when the unit is *cross-dimension* (`ns`, `pF`, `V`,
  `nC`). Absence of a usable unit must not encode "assume the default" for a quantity
  printed in two scales 1000x apart.
- Never inspects magnitude. Magnitude may be used to *warn*, never to *rescale*.

Then replace all four call sites above with it, and **delete** the
`if rds_on_max < 0.1: *= 1000` heuristic — but only *after* the helper covers the
`Rds_on_10v` branch it currently serves. Also settle the precedence question in one
place (recommend: prefer the entry whose `cond` matches the actual gate-drive `Vgs`,
falling back to `Rds_on_10v` then `Rds_on`, since that is what the buck model wants).

### Phase 2 — make the units explicit at the producer

`dslib/field.py` `Field.__init__` already has an ohm normaliser (uncommitted, currently
**inert**). It is inert because **no cache salt covers `dslib/field.py`**:
`regex_ver_salt()` returns only `expr` artefacts, `v2_code_salt` covers only
`dslib/v2/*.py`, and `hash_func_code=True` hashes only the decorated function's own
body — and pickled `Field` objects bypass `__init__` entirely on unpickle.

- Add `dslib/field.py` to the salt of every cached producer of `Field`s (innermost
  first), or bump `regex_ver_salt`'s `'v51'`. **Cost: full text-extraction cache
  rebuild** — measure before accepting.
- Keep the "sync with `expr.py`'s `unit_regex`" invariant, but note it is insufficient
  by construction: four producers hand free-form units to `Field` and only one is
  regex-constrained (`':'`, `'|Q'`, `'JO'` are real observed units). Missing an
  *m-prefixed* spelling is harmless; missing a *bare* one is 1000x.

#### Phase 2 — DONE 2026-07-27

Two peer reviewers independently flagged the missing salt as blocking, and the defect was
reproduced end-to-end rather than argued:

```
  stale Field(Rds_on, typ=.005, unit=':')    unpickled, pre-canonicalisation generation
+ fresh Field(Rds_on, max=.006, unit=':')    new writer scales it to max=6, 'mΩ'
= merged typ=.005, max=6.0, unit=':'         fill() copies stats, never converts units
  get_resistance_milliohm(stat='max') -> 6000 mΩ for a 6 mΩ part
```

A 1000x from a cache **hit**. `fill()` merging stats that sit 1000x apart is the same root
cause as the `AOB66515L` defect already pinned in `test/tests.py`.

Implemented as `dslib.field.field_repr_salt()`, wired into the four producers that lacked
coverage: `extract_fields_from_text`, the aggregate `parse_datasheet`, `tabula_read`
(`dslib/pdf/parse.py`) and `read_sheet` (`dslib/pdf/sheet/__init__.py`). `dslib.v2` was
already covered by `v2_code_salt`. `tabula_browser` deliberately is **not** — it returns
`List[pd.DataFrame]` and has no Field representation to go stale.

**Not** a content hash of `field.py`, unlike `v2_code_salt`, because the measured cost of
that is a full-corpus rebuild on a comment edit (tabular ~177 s/part x 6040 parts). It
follows `pdf/ascii.py`'s idiom instead and pins the exact surface that decides the stored
representation: the unit tables **by value** (bytecode alone would miss them — `_OHM_BODY`
is a global, so editing it moves no `LOAD_GLOBAL`) plus `co_code` of
`ohm_unit_to_milli_mul`, `get_value_with_unit` and `Field.__init__` (bytecode, not source,
so prose edits are free).

Closure was **measured, not assumed** — a salt that is defined but absent from a given key
is dead. Perturbing a unit table and diffing each producer's own `.cache_key`: all four
moved, and all restored to baseline. The first run reported v2 as *not* moving; that was a
probe limitation, not a dead salt — `v2_code_salt` hashes `field.py` on disk, which an
in-memory monkeypatch cannot move. Re-tested by mutating the file itself: v2's key moves
and restores. **A zero difference meant "not measured", not "no change".**

Calibrated in both directions in `test/unit/test_field_repr_salt.py` (7 tests): the salt
moves for a table edit, a writer-scope change and a stored-default change, and does *not*
move for comments/docstrings. A salt that fires on every edit is as useless as one that
never fires, because the pressure to stop bumping it is how these guards die.

Also landed here: `Field.__init__`'s canonicalisation gate changed from `symbol[0] == 'R'`
to the explicit `_WRITER_CANONICAL_SYMBOLS`. `Rth*` also starts with `R` and is quoted in
°C/W or K/W; the prefix test only looked safe because `K`/`C` are not `mkM` prefixes, so a
bare `W` or `mW` capture on a thermal row would have become milliohms. Measured latent, not
firing: 0 `Rth` fields among the 61046 R-fields in the shipped DB (`Rds_on` 24475, `Rg`
25663, `Rds_on_10v` 10908), and `detect_fields` exposes no `Rth` symbol.

**Cost incurred now:** v2's cache is keyed on `field.py` content, so this session's edits
already invalidated it for the whole corpus (~1.9 s/part x 6040 ≈ 3.2 h of re-parsing on
the next full run). The other four only rebuild when the representation actually changes.

### Phase 3 — only now, repair the data

With one reader and explicit producer units, re-derive which entries are actually wrong:

- An entry is wrong only if the helper returns NaN (cross-dimension unit) or if the
  value disagrees with a sibling candidate that carries a *recognised* unit.
- Repair by **re-selecting a better candidate** or by **re-parsing the PDF** (v2 is now
  the pipeline spatial stage and validates units per symbol). Never by magnitude.
- Known genuinely-broken examples to use as the calibration set:
  `nxp/BUK965R8-100E,118` `Rg`=168 Ω from a `unit='ns'` switching-time row;
  `diotec/DIT120N08` `Rg`=64 Ω from a `"Qgd … 64 nC"` row;
  `littelfuse/IXTX46N50L` `Rds_on`=0.16 mΩ.
- Back up `data/datasheets-lib.pkl` first. Persist with
  `datasheets_db.add(list(db.values()))` — `load()` returns a shallow copy, there is no
  `save()`, and `add()` requires a **list** because the db has a `key_func`.
- Verify by **reloading from disk** and diffing against the backup: assert that only the
  intended symbols changed and no parts were added or removed.

## Guard checklist for each phase

1. What does it return when it cannot evaluate the unit? → **NaN/refuse**, never a
   defaulted scale.
2. Monotone? As the unit gets less trustworthy, the verdict must move toward refuse —
   no band where it flips back to "believe".
3. Is the precondition checked? A helper nothing calls fixes nothing — grep for
   remaining hand-rolled `*1000` / `*1e-3` on resistance.
4. Signature vs proxy: cache salts must cover the code that *derives* the value
   (`dslib/field.py`), not only the data it reads.
5. Can a failed check persist its verdict? Do not write a guessed scale back into the DB.
6. Provenance: a repaired value must record that it was repaired, not masquerade as
   parsed.
7. Calibrate against the known-bad set above and watch it FAIL before the fix.
8. Fixing the check or the number? A magnitude rescale that silences a warning without
   establishing the unit is a mute button.

## Explicitly out of scope

- Migrating the pickle DB to SQLite (worth doing separately; the load-everything cost is
  what OOM-killed audit runs, but it touches every `datasheets_db` consumer).
- `dslib/pdf/expr.py:577` — `RthJC` leads the *electrical* resistance `head_regex` while
  that dimension accepts a bare `W`. Latent: currently unreachable via v2's path because
  v2's symbol→dimension map contains no thermal symbols, and no `Rth*` symbol exists in
  the fields table. **The writer side of this is now closed** (2026-07-27): the
  canonicalisation gate is the explicit `_WRITER_CANONICAL_SYMBOLS`, not `symbol[0] == 'R'`,
  so an `Rth*` Field is no longer rescaled to mΩ even if the regex does capture one. The
  regex overlap itself is still there — fix it if an `Rth` symbol is ever added to the
  fields table.

## Step 1 result — the provenance trust matrix (measured 2026-07-26)

> **STATUS: MEASURED, NOT IMPLEMENTED.** Nothing in this section ships. `field.py`'s
> `get_resistance_milliohm` reads `fields_filled` and applies the symbol default to *any*
> empty unit **without inspecting the stat's source**, so the `tabular` refusal below does
> not happen: `diotec/DIT120N08`-shaped input (`Rg` typ=64, unitless, source
> `tabula_cli_guess`/`iter_table`) returns 64000 mΩ rather than NaN. A reviewer confirmed
> this against HEAD. Read the policy below as a design, not as behaviour.
>
> Superseded in three ways by the review that followed, so do not implement it as written:
> - **Explicit producer allowlist**, not "everything except `tabular`" and not a
>   `vendor:*` wildcard. Trust must be enumerated, because an unrecognised source string
>   falling through to trusted is the same absence-of-evidence-means-fine shape this plan
>   exists to remove.
> - **Siblings may be selected but never lend their unit.** A candidate's unit applies
>   only to the stats that candidate produced.
> - **`fill()` must become transactional and condition-aware**, and be tested
>   permutation-invariantly. It is currently neither: both arrival orders of the
>   `AOB66515L` case yield `typ=1.18` with `max=1180`, and only the *unit* differs by
>   order. A merge whose result depends on arrival order cannot be validated by a test
>   that fixes one order.
>
> Affordability of the strict policy was measured: **119 values lost vs 1373 rescued.**

Cross-tabulated every resistance Field in the shipped DB by (symbol, unit class, source
of the winning stat) and counted how many fall OUTSIDE a physics-justified band after
applying the current scale rule. Bands (mOhm, deliberately wide sanity bounds, not
selection criteria): `Rds_on`/`Rds_on_10v` 0.3..1e5, `Rg` 100..5e4.

| symbol | unit class | source | n | implausible | median mOhm |
|---|---|---|---|---|---|
| Rds_on | cross-dim | read_sheet / tabular | 425 | — (already NaN) | — |
| Rds_on | no-unit | read_sheet | 547 | 11 (2.0%) | 13.9 |
| Rds_on | no-unit | **tabular** | 224 | **121 (54.0%)** | **0.085** |
| Rds_on | no-unit | text | 3 | 0 | 100 |
| Rds_on | ohm-unit | read_sheet | 4447 | 0 | 8.1 |
| Rds_on | ohm-unit | tabular | 20 | 0 | 10.5 |
| Rds_on_10v | no-unit | vendor:* (14 sources) | ~5500 | **0 (0.0%) in every one** | 4-60 |
| Rg | cross-dim | read_sheet | 374 | — (already NaN) | — |
| Rg | no-unit | read_sheet | 182 | 0 | 1500 |
| Rg | no-unit | **tabular** | 62 | **15 (24.2%)** | 5000 |
| Rg | ohm-unit | read_sheet / tabular / text | 4183 | 9 (0.2%) | 1300-1500 |

**Policy this supports:** the unitless default is trustworthy in EVERY cell except
`tabular`. `Rds_on` no-unit from tabular is 54% implausible with a median of 0.085 mOhm
(= 85 microohm, impossible) — those are ohm-scale values whose unit column Tabula missed.
`Rg` no-unit from tabular is 24.2% implausible. Everything else is <=2%, and
`Rds_on_10v` unitless from all 14 vendor sources is **0.0% implausible across ~5500
entries**, confirming that unitless is that symbol's convention by construction
(`dslib/discovery/__init__.py:126` creates it with no unit at all).

So: **refuse the unitless default when the stat's source is `tabular`; honour it
otherwise.** This is provenance-based, not magnitude-based — the decision keys on WHO
produced the value, and the band is used only to VALIDATE the policy, never to rescale.

**Honest limit — provenance alone does not close the calibration set.** Of the three
targets: `nxp/BUK965R8-100E,118` Rg (unit `ns`, cross-dim) is already refused;
`diotec/DIT120N08` Rg=64 unit=None source=**tabular** lands squarely in the distrusted
cell and WOULD be refused; but `littelfuse/IXTX46N50L` Rds_on=0.16 unit=None
source=**read_sheet** sits in a TRUSTED cell — it is one of that cell's 11 (2.0%)
outliers. Catching it needs a second signal beyond provenance. Do not claim step 1
closes the set.

## Scope limit on the plausibility-band technique (added 2026-07-26)

This plan uses physics bands to VALIDATE the provenance tier table (never to rescale).
That is legitimate **for resistance only, and only because those distributions are
bimodal with a genuine void**: `Rds_on` has a gap at ~0.01-0.9 mOhm and `Rg` at
~5-100 mOhm, so an ohm-scale value that lost its unit lands in empty space.

**Do NOT port the technique to charge or any unimodal symbol.** Measured on the DB
(canonical nC): `Qrr` n=7357 min=0.18 p1=1.2 p5=26 median=183; `Qg` min=1.2 p1=9.4;
`Qgs` min=0.27; `Qgd` min=0.7. A lost-microcoulomb 1.18 lands *inside* the real `Qrr`
population, 45 entries (0.6%) sit below 1 nC, and GaN parts legitimately report `Qrr`
near zero. There is no void, so any floor that catches the error also deletes real
small-part values. A plausibility band is a property of the SYMBOL'S DISTRIBUTION, not
a reusable method.

