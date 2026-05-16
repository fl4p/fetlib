## MOSFET Power Loss Models (`dcdc_buck_hs` / `dcdc_buck_ls`)

Read both functions in `dclib/powerloss.py` and the surrounding helpers.

### Conduction loss `P_cl`

**`dcdc_buck_hs`:**
```python
i_rms2 = dc.D_buck * dc.Io_mean_squared_on
P_cl  = i_rms2 * rds
```
`Io_mean_squared_on = (Imax² + Imax·Imin + Imin²)/3` is the standard triangular-wave RMS² formula. Multiplying by D gives the period-averaged i² for a segment of width D·T_sw. **Correct.**

**`dcdc_buck_ls`:** same with `(1 − D_buck)`. **Correct** — LS conducts the complement of D.

### Switching loss `P_sw` (HS only)

```python
Psw_on  = 0.5 * Vi * Io_min * f * tr
Psw_off = 0.5 * Vi * Io_max * f * tf
```
Inductor current is `Io_min` at HS turn-on and `Io_max` at HS turn-off, so the asymmetric tr/tf weighting is right. `tr`/`tf` come from `mosfet_hs_sw_timings_hs2()` (gate-charge based, eq 5/6 from SLVAEQ9) — the Qgs2/(Von−v_ir) + Qgd/(Von−Vpl) decomposition is the right approach and more accurate than datasheet tr/tf.

Minor caveat: `Rds_on=Rds_on*1.22` for `Tj=nan` is a single hand-tuned hot-Rds factor that ignores Tj, current, and family-specific α (Si vs GaN vs SiC differ a lot at high Tj). The `Rds_on(Tj=25)` branch demands `Tj==25` exactly, so any other temperature with a real Tj is unreachable — acknowledged as TODO at line 144.

### Gate drive loss `P_gd` — **likely 2× overestimate**

Both sides:
```python
P_gd = (von - gd.Voff) * dc.f * 2 * mf.Qg
```

The standard formula is `P_gd = Qg · Vgs_swing · f`. The charge Qg flows through Rg during turn-on (dissipating ~½Qg·Vswing in Rg) and back through Rg-off during turn-off (another ½Qg·Vswing). Per cycle, total dissipation in the driver path = `Qg·Vswing`, **not** `2·Qg·Vswing`. The `2 *` factor is suspect — and the stale unit tests at line 629/637 codify it (`assert P_gd == 12 * 40e3 * 2 * 100e-9`), so it's not a typo, just propagated. Worth confirming.

### Reverse recovery `P_rr` (LS)

```python
P_rr = Vi * f * Qrr_eff;   Qrr_eff = Qrr * 1.2
```
Standard `E_rr = Vi·Qrr` per HS turn-on, attributed to LS but dissipated in HS — matches the column semantics in CLAUDE.md. The 1.2× rise is the rule of thumb from the comment; reasonable. Open issues from the TODOs (Qrr(di/dt), Qrr(Id)) are legitimate — Qrr can vary 2–3× with di/dt.

`dcdc_buck_hs` asserts `mf.Qrr is not None` even though HS sets `P_rr=0`; that assertion is misplaced — it should live in `dcdc_buck_ls`.

### Dead-time loss `P_dt` (LS)

```python
P_dt = vsd * dc.Io * (dc.tDead * 2) * dc.f
```
Body diode conducts twice per cycle. Strictly the two dead-times carry `Io_min` and `Io_max`; using `Io = (Imin+Imax)/2` averaged across both gives the same total. **Correct.** Missing-Vsd defaults silently to 1 V (warning is commented out at line 247).

### Coss loss `P_coss` (asymmetric split between HS and LS)

```python
P_coss_hs = (2/3) · Coss · Vi² · f
P_coss_ls = (4/3) · Coss · Vi² · f
qoss      = 2 · Coss · Vi          # in ls cond block
```

Internally consistent and physically right for the nonlinear-Coss model `Coss(V) ∝ 1/√V`:
- `Qoss(Vi) = ∫Coss dV = 2·Coss·Vi` ✓
- `Eoss(Vi) = (2/3)·Coss·Vi²` ✓
- On HS turn-on, the source delivers `Vi·Qoss_ls = 2·Coss·Vi²` to recharge LS Coss; `(2/3)·Coss·Vi²` ends up stored, `(4/3)·Coss·Vi²` is dissipated in HS channel and attributed to LS — same convention as P_rr. ✓
- HS self-dissipates its own `(2/3)·Coss·Vi²` at the next turn-on.

The TODO at lines 206–209 (scaling `Coss` from datasheet ref voltage to actual Vi) is real: for an 80V FET with Coss spec'd at 40V, using the raw value at a Vi=60V bus underestimates by ~√(60/40) ≈ 1.22×. One-line fix.

### Misc

- **`buck_hs()` / `buck_ls()` totals**: HS sum = `P_sw + P_cl + P_gd + P_coss`; LS sum = `P_rr + P_cl + P_gd + P_dt + P_coss`. Sum = full converter FET loss without double-counting. Labelling convention (LS-attributed P_rr/P_coss are dissipated in HS) is consistent with CLAUDE.md and the CSV columns.
- **`parallel(n)`**: `P_cl/n * 0.9` models thermal/Rds imbalance. Hand-tuned but defensible. `P_sw` unchanged (fastest device takes the switching event) is pessimistic for matched pairs but realistic. `P_coss/P_rr/P_gd` scale linearly with n. ✓
- **`SwitchPowerLoss.__init__` docstring**: says `:param P_on:` but the parameter is `P_cl` — stale.
- **Stale tests at line 620–683**: `dcdc_buck_hs(..., Rds_temp_rise=1)` — that kwarg doesn't exist on the current signature, and the `P_sw == 24*10*40e3*40e-9` assertion is based on the deprecated `mosfet_switching_trf` formula. Will `TypeError` if invoked.
- **`mosfet_hs_sw_timings_lcsi`** has `fallback_V_pl=math.nan` default; when `mf.V_pl` is also NaN, `vpl` is NaN and the whole computation silently produces NaN.
- **`use_datasheet_timings=True`** does `max(computed, datasheet_tr)` — odd, since datasheet tr/tf is measured under fixed conditions usually unrelated to your gate driver.

### Bottom line — three priorities

1. **`P_gd` 2× factor** — verify intentional; if not, every CSV row overestimates gate drive loss by 2×.
2. **Coss voltage scaling** — the existing TODO shifts ranking of high-Vds parts.
3. **Stale `tests()` at the bottom** — don't run against current signatures.

---

## Coil Loss (`dcdc_buck_coil`)

### DC resistance loss `P_dcr`

```python
I_ms = dc.Io**2 + dc.Iripple**2 / 12     # RMS² of DC + triangular ripple
P_dcr = I_ms * coil.Rdc
```
RMS² decomposition is right. **Correct.**

Caveats:
- **No temperature correction.** `coil.Rdc` is at construction-time temperature (presumably 20–25 °C). Cu TC ≈ 0.39 %/K — at Tw=80 °C `Rdc` is ~24 % higher. `copper_resistivity_tempco()` exists in `wire.py` but isn't wired in.
- The `assert math.isfinite(dc.Iripple)` at line 421 makes the `else: I_ms = dc.Io ** 2` branch at line 427 unreachable.

### AC resistance loss `P_acr` — **double-counts the AC component**

```python
F_se, F_pe = acr_factor_micrometals(...)         # excess factors, "Rac = Rdc·(1 + F_se + F_pe)"
rac = (1 + F_se + F_pe) * coil.Rdc               # full Rac (DC term + skin + prox)
P_acr = dc.Il_ac_rms2 * rac                      # Il_ac_rms2 = Iripple²/12
```

Step-by-step:

Total wire current `i(t) = Idc + i_ac(t)` with `mean(i_ac)=0`. So:
```
RMS²(i) = Idc² + RMS²(i_ac) = Io² + Iripple²/12
```
Correct total wire loss treats each spectral component at the resistance it actually sees:
```
P_wire_correct = Idc²·Rdc + Iac_rms²·Rac
              = Io²·Rdc + (Iripple²/12)·Rdc·(1 + F_se + F_pe)
```

What the code computes:
```
P_dcr = (Io² + Iripple²/12) · Rdc
P_acr = (Iripple²/12) · Rdc·(1 + F_se + F_pe)
P_dcr + P_acr = Io²·Rdc + (Iripple²/12)·Rdc·(2 + F_se + F_pe)
```

vs. correct `Io²·Rdc + (Iripple²/12)·Rdc·(1 + F_se + F_pe)`.

The AC component is billed `Rdc` once via `I_ms·Rdc` and again via the `1·Rdc` inside `rac = (1+F_se+F_pe)·Rdc`. Over-count is exactly `(Iripple²/12)·Rdc`.

**Naming vs. semantics.** If the intent of `P_acr` is "loss from increased AC resistance due to skin+prox," the multiplier should be just the *excess* over Rdc — i.e. `F_se + F_pe`, not `1 + F_se + F_pe`:

```python
P_acr = dc.Il_ac_rms2 * (F_se + F_pe) * coil.Rdc      # excess only
```

With that, `P_dcr` handles **all** copper loss at DC resistance (DC current and the Rdc share of the AC current), and `P_acr` is the extra loss caused by skin+prox at the AC harmonics.

The alternative convention (`I_ms = Io ** 2`, `P_acr = Il_ac_rms2 · Rac`) is also fine; the bug is that the code does both at once.

**Magnitude check.** For ripple_factor `r = Iripple/Io`:
```
overcount / (Io²·Rdc) = r² / 12
```
- r = 0.3  → 0.75 %  (negligible)
- r = 0.5  → 2.1 %
- r = 1.0  → 8.3 %   (high-ripple buck)

Real bug, but only material for high-ripple designs. For typical 20–40 % ripple it's lost in the noise.

### Core loss `P_core`

```python
P_core1, Bpk1, cld1 = 0, 0, 0
P_core2, Bpk2, cld2 = core_loss_from_dc_bias(dc, coil)
P_core = max(P_core1, P_core2)
```

1. **Method 1 is dead-coded.** With `P_core1=0` and `cld1=0`, the `max()` and the `mthd=2 if cld2 > cld1 else 1` selector both reduce to "always method 2". Either delete the comparison machinery or re-enable `core_loss_from_dc_magnetization`. Mag-Inc's own guidance: **method 1** (B-H curve integration over the ripple range) is preferred for medium-to-high ripple; method 2 is the "small ΔH" approximation.

2. **Method 2's premise isn't enforced.** `Bpk_dc_bias` uses `Bpk = 0.5·µ0·μ(Hdc)·ΔH` — linearizes around the DC bias point and assumes ΔI ≪ Io. For powder cores at significant DC bias, μ drops sharply over the ripple span, so the linearized Bpk diverges from the true B(H) integral. No assertion on Iripple/Io ratio.

3. **`core_loss_density(Bpk, f)` has no DC-bias term.** The empirical fits in `materials/__init__.py` take Bpk and f only. For Sendust at moderate H_dc this is OK; newer powder materials (XFlux, MS-X) show 20–50 % core-loss elevation at high DC bias.

4. **Triangular vs. sinusoidal excitation.** The Steinmetz-like fit `f/(a/Bpk³ + b/Bpk^2.3 + c/Bpk^1.65) + d·Bpk²·f²` is calibrated against sinusoidal data per the Oliver paper. PWM-driven inductors have triangular flux. For powder cores with low β this difference is small; iGSE-style correction would be more honest.

### Misc

- **Stale exploratory comments lines 446–480** (candidate Bpk formulas) — dead text since the actual computation is delegated to `core_loss_from_dc_bias`. Could be deleted or moved to a design note.
- **No saturation/L-drop coupling.** The function takes `coil.L0` and `dc.Iripple` as given. At high DC bias, μ_eff drops, L drops, and *actual ripple is larger* than nominal `dc.Iripple` — raising both P_acr and P_core. TODO at line 487 acknowledges this. `BuckConverter.powerloss()` in `spec_models.py` does step one (`Ldc = coil.Ldc(dcdc.Io)`) but doesn't re-derive `Iripple`.
- **`sd` reporting.** `skin_depth()` is called separately on line 439 just to report δ — `acr_factor_micrometals` already computes it internally.

### Bottom line — three priorities

1. **AC double-count in `P_dcr + P_acr`** — real bug, small (<1 %) for typical designs but grows with ripple. One-line fix.
2. **Core-loss method selection is misleading** — `max(0, method2)` is always method 2; either restore method 1 as a comparison or delete the scaffolding.
3. **No Rdc temperature correction** — for a parametric search ranking inductors, 20–30 % understatement of P_dcr at hot operating temperatures is more impactful than the AC double-count.









# conversation (backup)

review the mosfet power loss models for buck converters in  dcdc_buck_ls and dcdc_buck_hs                                                                                   

  Searched for 2 patterns, read 2 files (ctrl+o to expand)

⏺ Read both functions and the surrounding helpers. Here's a focused review.

  Conduction loss P_cl

  dcdc_buck_hs:
  i_rms2 = dc.D_buck * dc.Io_mean_squared_on
  P_cl  = i_rms2 * rds 
  Io_mean_squared_on = (Imax² + Imax·Imin + Imin²)/3 is the standard triangular-wave RMS² formula. Multiplying by D gives the period-averaged i² for a segment of width
  D·T_sw. Correct.
  
  dcdc_buck_ls: same with (1 − D_buck). Correct — LS conducts the complement of D.

  Switching loss P_sw (HS only)

  Psw_on  = 0.5 * Vi * Io_min * f * tr
  Psw_off = 0.5 * Vi * Io_max * f * tf
  Inductor current is Io_min at HS turn-on and Io_max at HS turn-off, so the asymmetric tr/tf weighting is right. tr/tf come from mosfet_hs_sw_timings_hs2() (gate-charge
  based, eq 5/6 from SLVAEQ9) — the Qgs2/(Von−v_ir) + Qgd/(Von−Vpl) decomposition is the right approach and more accurate than datasheet tr/tf.
  
  Minor caveat: Rds_on=Rds_on*1.22 for Tj=nan is a single hand-tuned hot-Rds factor that ignores Tj, current, and family-specific α (Si vs GaN vs SiC differ a lot at high
  Tj). The Rds_on(Tj=25) branch demands Tj==25 exactly, so any other temperature with a real Tj is unreachable — this is acknowledged as TODO at line 144.

  Gate drive loss P_gd — likely 2× overestimate

  Both sides:
  P_gd = (von - gd.Voff) * dc.f * 2 * mf.Qg
  
  The standard formula is P_gd = Qg · Vgs_swing · f. The charge Qg flows through Rg during turn-on (dissipating ~½Qg·Vswing in Rg) and back through Rg-off during turn-off
  (another ½Qg·Vswing). Per cycle, total dissipation in the driver path = Qg·Vswing, not 2·Qg·Vswing. The 2 * factor is suspect — and the stale unit tests at line 629/637
  codify it (assert P_gd == 12 * 40e3 * 2 * 100e-9), so it's not a typo, just propagated. Worth confirming.

  Reverse recovery P_rr (LS)

  P_rr = Vi * f * Qrr_eff;   Qrr_eff = Qrr * 1.2
  Standard E_rr = Vi·Qrr per HS turn-on, attributed to LS but dissipated in HS — matches the column semantics in CLAUDE.md. The 1.2× rise is the rule of thumb from the
  comment; reasonable. Open issues from the TODOs (Qrr(di/dt), Qrr(Id)) are legitimate — Qrr can vary 2–3× with di/dt, which directly translates into the column.
  
  dcdc_buck_hs asserts mf.Qrr is not None even though HS sets P_rr=0; that assertion is misplaced — it should live in dcdc_buck_ls.

  Dead-time loss P_dt (LS)

  P_dt = vsd * dc.Io * (dc.tDead * 2) * dc.f
  Body diode conducts twice per cycle. Strictly the two dead-times carry Io_min (after HS turn-off → before LS turn-on… wait, before HS turn-on) and Io_max respectively;
  using Io = (Imin+Imax)/2 averaged across both gives the same total. Correct. Missing-Vsd defaults silently to 1 V (warning is commented out at line 247) — silent fallback
  for parts with no Vsd extracted from the datasheet.

  Coss loss P_coss (asymmetric split between HS and LS)

  P_coss_hs = (2/3) · Coss · Vi² · f
  P_coss_ls = (4/3) · Coss · Vi² · f
  qoss      = 2 · Coss · Vi          # in ls cond block

  This is internally consistent and physically right for the nonlinear-Coss model Coss(V) ∝ 1/√V:
  - Qoss(Vi) = ∫Coss dV = 2·Coss·Vi ✓
  - Eoss(Vi) = (2/3)·Coss·Vi² ✓
  - On HS turn-on, the source delivers Vi·Qoss_ls = 2·Coss·Vi² to recharge LS Coss; (2/3)·Coss·Vi² ends up stored, (4/3)·Coss·Vi² is dissipated in HS channel and attributed
  to LS — same convention as P_rr. ✓
  - HS self-dissipates its own (2/3)·Coss·Vi² at the next turn-on.
  
  The TODO at lines 206–209 (scaling Coss from datasheet ref voltage to actual Vi) is real: for an 80V FET with Coss spec'd at 40V, using the raw value at a Vi=60V bus
  underestimates by ~√(60/40) ≈ 1.22×. Worth doing — it's a one-line fix.

  Misc
  
  - buck_hs() / buck_ls() totals: HS sum = P_sw + P_cl + P_gd + P_coss; LS sum = P_rr + P_cl + P_gd + P_dt + P_coss. Sum = full converter FET loss without double-counting.
  Good. The labeling convention (LS-attributed P_rr/P_coss are dissipated in HS) is consistent with CLAUDE.md and the CSV columns.
  - parallel(n): P_cl/n * 0.9 models thermal/Rds imbalance (one device runs hotter → slightly worse than ideal 1/n halving). Hand-tuned but defensible. P_sw unchanged
  (fastest device takes the switching event) is a known modelling choice — pessimistic for matched pairs but realistic. P_coss/P_rr/P_gd scale linearly with n. ✓
  - SwitchPowerLoss.__init__ docstring: says :param P_on: but the parameter is P_cl — stale.
  - Stale tests at line 620–683: dcdc_buck_hs(..., Rds_temp_rise=1) — that kwarg doesn't exist on the current signature, and the P_sw == 24*10*40e3*40e-9 assertion is based
  on the deprecated mosfet_switching_trf formula. These will TypeError if invoked. Either delete or rewrite.
  - mosfet_hs_sw_timings_lcsi has fallback_V_pl=math.nan default; when mf.V_pl is also NaN, vpl is NaN and the whole computation silently produces NaN. Trap.
  - use_datasheet_timings=True does max(computed, datasheet_tr) — odd, since datasheet tr/tf is measured under fixed conditions usually unrelated to your gate driver. Either
  trust the gate-charge model or override entirely; the max() mixes apples and oranges.

  Bottom line
  
  The structure (gate-charge timings, asymmetric Imin/Imax weighting, P_rr/P_coss "induced but not self-dissipated" convention) is sound and matches the references cited.
  Three concrete things to look at, in order of likely impact:

  1. P_gd 2× factor — verify this is intentional; if not, it's a 2× overestimate of gate-drive loss in every row of the CSV.
  2. Coss voltage scaling — the existing TODO is worth resolving; it shifts the ranking of high-Vds parts.
  3. Stale tests() at the bottom — they don't run against the current signatures.

✻ Brewed for 2m 55s

❯ review the coil loss in dcdc_buck_coil                                                                                                                                      

⏺ Searching for 1 pattern, reading 4 files… (ctrl+o to expand)
  ⎿  maglib/materials/__init__.py
                 5
✢ Ideating… (1m 14s · ↓ 769 tokens · almost done thinking)
  ⎿  Tip: Use /btw to ask a quick side question without interrupting Claude's current work
  3. Stale tests() at the bottom — they don't run against the current signatures.

✻ Brewed for 2m 55s

❯ review the coil loss in dcdc_buck_coil                                                                                                                                      

  Searched for 1 pattern, read 4 files (ctrl+o to expand)

⏺ Read through dcdc_buck_coil and the supporting maglib.powerloss / maglib.wire / maglib.materials pieces. Here's the review.

  DC resistance loss P_dcr

  I_ms = dc.Io**2 + dc.Iripple**2 / 12     # RMS² of DC + triangular ripple
  P_dcr = I_ms * coil.Rdc
  RMS² decomposition is right: a triangular ripple of peak-to-peak amplitude ΔI has AC RMS² = ΔI²/12. Correct.

  Caveats:
  - No temperature correction. coil.Rdc is whatever was supplied at construction time (presumably 20–25 °C). Copper TC ≈ 0.39 %/K, so at Tw=80 °C wire temperature Rdc is ~24
  % higher than the 25 °C value. For high-current designs this skews the loss ranking. copper_resistivity_tempco() exists in wire.py but isn't wired in here.
  - The assert math.isfinite(dc.Iripple) at line 421 makes the else: I_ms = dc.Io ** 2 branch at line 427 unreachable.
  
  AC resistance loss P_acr — double-counts the AC component

  F_se, F_pe = acr_factor_micrometals(...)           # excess factors, "Rac = Rdc·(1 + F_se + F_pe)"
  rac = (1 + F_se + F_pe) * coil.Rdc                 # full Rac (DC term + skin + prox)
  P_acr = dc.Il_ac_rms2 * rac                        # Il_ac_rms2 = Iripple²/12

  P_dcr already paid (Iripple²/12)·Rdc for the AC current's DC-resistance portion (because I_ms includes both DC and AC RMS²). Then P_acr pays for the AC current at the full
  Rac = Rdc·(1+F_se+F_pe) — so the 1·Rdc portion is billed twice. Algebraically:

  code total = Io²·Rdc + (Iripple²/12)·Rdc·(2 + F_se + F_pe)
  correct    = Io²·Rdc + (Iripple²/12)·Rdc·(1 + F_se + F_pe)
  overcount  =           (Iripple²/12)·Rdc

  Fix: either drop the AC term from I_ms (I_ms = Io**2, since P_acr already covers it with full rac), or use only the excess AC factor (P_acr = Il_ac_rms2 * (F_se + F_pe) * 
  coil.Rdc). The comment at line 441 ("notice that this is independent from duty cycle") is unrelated to the bug — P_acr correctly doesn't depend on duty.

  Practical magnitude: for a typical 30 % ripple-factor design the overcount is ~0.75 % of Io²·Rdc, small. For an aggressive 100 % ripple (BCM-adjacent) it's ~8 %, comparable
   to a typical core-loss budget. Discovered while ranking parts this can shift winners.

  Core loss P_core

  P_core1, Bpk1, cld1 = 0, 0, 0
  P_core2, Bpk2, cld2 = core_loss_from_dc_bias(dc, coil)
  P_core = max(P_core1, P_core2)

  Three things:

  1. Method 1 is dead-coded. With P_core1=0 and cld1=0, the max() and the mthd=2 if cld2 > cld1 else 1 selector both reduce to "always method 2". Either delete the comparison

  Fix: either drop the AC term from I_ms (I_ms = Io**2, since P_acr already covers it with full rac), or use only the excess AC factor (P_acr = Il_ac_rms2 * (F_se + F_pe) *
  coil.Rdc). The comment at line 441 ("notice that this is independent from duty cycle") is unrelated to the bug — P_acr correctly doesn't depend on duty.

  Practical magnitude: for a typical 30 % ripple-factor design the overcount is ~0.75 % of Io²·Rdc, small. For an aggressive 100 % ripple (BCM-adjacent) it's ~8 %, comparable
   to a typical core-loss budget. Discovered while ranking parts this can shift winners.

  Core loss P_core

  P_core1, Bpk1, cld1 = 0, 0, 0
  P_core2, Bpk2, cld2 = core_loss_from_dc_bias(dc, coil)
  P_core = max(P_core1, P_core2)

  Three things:

  1. Method 1 is dead-coded. With P_core1=0 and cld1=0, the max() and the mthd=2 if cld2 > cld1 else 1 selector both reduce to "always method 2". Either delete the comparison
   machinery or re-enable core_loss_from_dc_magnetization. Mag-inc's own guidance is that method 1 (B-H curve integration over the ripple range) is preferred for
  medium-to-high ripple; method 2 is the "small ΔH" approximation.
  2. Method 2's premise isn't enforced. Bpk_dc_bias uses Bpk = 0.5·µ0·μ(Hdc)·ΔH — i.e. it linearizes around the DC bias point and assumes ΔI ≪ Io. For powder cores at
  significant DC bias, μ drops sharply over the ripple span, so the linearized Bpk diverges from the true B(H) integral. No assertion on Iripple/Io ratio.
  3. core_loss_density(Bpk, f) has no DC-bias term. The Micrometals/Mag-Inc empirical fits in materials/__init__.py take Bpk and f only. For Sendust at moderate H_dc this is
  OK; newer powder materials (XFlux, MS-X) show 20–50 % core-loss elevation at high DC bias, which this model can't see.
  4. Triangular vs. sinusoidal excitation. The Steinmetz-like fit f/(a/Bpk³ + b/Bpk^2.3 + c/Bpk^1.65) + d·Bpk²·f² is calibrated against sinusoidal data per the Oliver paper.
  PWM-driven inductors have triangular flux. For powder cores with low β this difference is small; for higher-β materials iGSE-style correction would be more honest.
  Acceptable approximation but worth a TODO.

  Misc

  - Stale exploratory comments lines 446–480 (B_pk candidate formulas, "method 2" block, etc.) — dead text since the actual computation is delegated to
  core_loss_from_dc_bias. Worth deleting or moving to a design note.
  - No saturation/L-drop coupling. The function takes coil.L0 (small-signal L) and dc.Iripple as given. At high DC bias, μ_eff drops, L drops, and the actual ripple is larger
   than the nominal dc.Iripple — which in turn raises both P_acr and P_core. The TODO at line 487 acknowledges this. Could be addressed by coil.Ldc(dc.Io) (which already
  exists) and re-computing Iripple self-consistently before calling the loss math. BuckConverter.powerloss() in spec_models.py already does the first step (Ldc = 
  coil.Ldc(dcdc.Io)) but doesn't re-derive Iripple.
  - sd reporting. skin_depth() is called separately on line 439 just to report δ — acr_factor_micrometals already computes it internally. Two redundant calls is harmless but
  it could return δ alongside the factors.

  Bottom line
  
  Three concrete things in order of impact:

  1. AC double-count in P_dcr + P_acr — real bug, small (<1 %) for typical designs but grows with ripple. One-line fix.
  2. Core-loss method selection is misleading — max(0, method2) is always method 2; either restore method 1 as a comparison or delete the scaffolding.
  3. No Rdc temperature correction — for a parametric search ranking inductors, 20–30 % understatement of P_dcr at hot operating temperatures is more impactful than the AC
  double-count.

  Numerically the code is broadly correct for low-ripple, moderate-current designs; it gets less trustworthy as Iripple/Io rises, as DC-bias deepens, or as wire temperature
  rises above ambient.

✻ Cooked for 2m 4s

❯ P_acr tries to express the losses from increased ac resistance due to the skin effect and proximity effect. Are you sure it is double-counting?                             

⏺ Yes, I'll walk through it explicitly. The bug isn't in the concept — it's that the code mixes two different conventions and pays the AC current's "DC resistance share" in
  both terms.

  The decomposition the code attempts

  Total wire current i(t) = Idc + i_ac(t) with mean(i_ac)=0. So:
  RMS²(i) = Idc² + RMS²(i_ac) = Io² + Iripple²/12
  The correct total wire loss treats each spectral component at the resistance it actually sees:
  P_wire_correct = Idc²·Rdc + Iac_rms²·Rac
                = Io²·Rdc + (Iripple²/12)·Rdc·(1 + F_se + F_pe)
                
  What the code computes

  I_ms  = Io² + Iripple²/12                          # full RMS² (DC + AC)
  P_dcr = I_ms · Rdc           = Io²·Rdc + (Iripple²/12)·Rdc
  rac   = (1 + F_se + F_pe)·Rdc                       # full Rac
  P_acr = (Iripple²/12) · rac  = (Iripple²/12)·Rdc·(1 + F_se + F_pe)
  Sum:
  P_dcr + P_acr = Io²·Rdc + (Iripple²/12)·Rdc        ← from P_dcr (the AC term inside I_ms)
                + (Iripple²/12)·Rdc·(1 + F_se + F_pe) ← from P_acr (using full Rac)
                = Io²·Rdc + (Iripple²/12)·Rdc·(2 + F_se + F_pe)
  vs. correct Io²·Rdc + (Iripple²/12)·Rdc·(1 + F_se + F_pe).
  
  The AC component is billed Rdc once via I_ms·Rdc and again via the 1·Rdc inside rac = (1+F_se+F_pe)·Rdc. So the over-count is exactly (Iripple²/12)·Rdc.

  Why this is "double-counting" and not a naming issue

  You're right that the intent of P_acr is "loss from increased AC resistance due to skin+prox." If that's the semantics, the multiplier should be just the excess over Rdc —
  i.e. F_se + F_pe, not 1 + F_se + F_pe:

  P_acr = dc.Il_ac_rms2 * (F_se + F_pe) * coil.Rdc      # excess only

  With that, P_dcr handles all copper loss at DC resistance (DC current and the Rdc share of the AC current), and P_acr is the extra loss caused by skin+prox at the AC
  harmonics. Sum is correct.

  The alternative convention (which the variable name rac = Rdc·(1+F_se+F_pe) suggests the author had in mind) is:

  I_ms  = Io ** 2                # P_dcr handles only the DC current
  P_dcr = Io²·Rdc
  P_acr = Il_ac_rms2 · Rac       # P_acr handles the entire AC current at full Rac

  Either is fine; the bug is that the code does both simultaneously — I_ms includes the AC RMS² and rac includes the 1· term.

  Magnitude check
  
  For ripple_factor Iripple/Io = r:
  overcount / Io²·Rdc = r² / 12
  - r = 0.3  → 0.75 %  (negligible)
  - r = 0.5  → 2.1 %
  - r = 1.0  → 8.3 %   (high-ripple buck)
  
  Real bug, but only material for high-ripple designs. For typical 20–40 % ripple it's lost in the noise — which is probably why it has gone unnoticed.

✻ Baked for 1m 0s
