# Nonlinear Coss/Qoss/Eoss loss model

`dclib.coss_loss` is the authoritative analytic model. It treats Coss as a
nonlinear energy-storage element and keeps stored, recovered, dissipated, and
measured hysteresis energy separate.

## State functions

For a drain-voltage trajectory, the model uses

```text
Qoss(V) = integral( Coss(v), v=0..V )
Eoss(V) = integral( v*Coss(v), v=0..V )
```

It never applies `0.5*Coss_table*V^2` across a large voltage swing.

The preferred source is `dslib.coss_curves.COSS_CURVES`: the digitized
datasheet Coss(V) graph, piecewise-linearly interpolated and analytically
integrated segment by segment. `COSS_CURVE_META` preserves measurement
frequency, temperature when stated, gate bias, provenance, and evidence
quality. Operation beyond the graph is a constant-C extension and is reported
as an extrapolation.

Parts without a curve use the legacy nonlinear assumption

```text
Coss(V) = Coss(Vanchor) * sqrt(Vanchor/V)
Qoss(V) = 2*Coss(Vanchor)*sqrt(Vanchor*V)
Eoss(V) = 2/3*Coss(Vanchor)*sqrt(Vanchor)*V^(3/2)
```

That fallback is always `UNVERIFIED` and warns. It is not a single-table
`1/2 CV^2` substitution.

## Transition ledger

Energy loss is a property of the circuit transition, not Eoss alone.
`CossTransition` stores a sampled Vds waveform as labelled segments. It also
names the topology, device and peer-device IDs, HS/LS role, switch node,
current direction, and cell event:

- `commutated`: reversible transfer to or from the source/load;
- `channel-discharge`: stored Eoss dissipated in the named channel;
- `resistive-charge`: source energy `Vsource*dQ` split into stored Eoss and
  dissipation in the named destination.

Energy sources/destinations are typed buckets (`dc-source`,
`load/inductor`, or `device:<id>:{coss,channel,body-diode,coss-hysteresis}`),
not free-form labels. A device endpoint outside the transition's device/peer
pair is rejected. Every transfer is emitted as a source → destination flow.
Every transition also names its event count, device count, model state,
evidence quality, and accounting owner. The energy balance for each event is

```text
Einitial + Esupplied = Efinal + Erecovered + Edissipated
```

and the residual is reported.

`CossSwitchingCellTransition` pairs complementary HS/LS waveforms for the
same synchronous-buck event. It validates reciprocal device identities,
distinct HS/LS devices, switch node, current direction, time grid, and
`Vds_hs + Vds_ls = Vbus` before either loss is evaluated.
The two device-side views of a Coss-to-Coss transfer must have equal
independently integrated energy; the cell report then emits that physical
transfer once. A mismatch produces a non-zero
`cross_device_transfer_residual_j_per_event` and `FAIL`. Reverse
(`load-to-source`) synchronous-buck commutation is rejected until its
different flow rules are implemented, rather than applying the forward-flow
ledger under a changed label.

The default synchronous-buck assumptions are explicit and `UNVERIFIED`
fragments of that paired event:

- HS Coss: `Vin -> 0`, discharged in the HS channel at turn-on;
- LS Coss: `0 -> Vin`, charged through the commutating HS channel.

They are not assumed equal. Parallel-device multiplicity and switching events
per cycle multiply the loss explicitly.

## Partial ZVS and deadtime

`CossTransition.partial_zvs()` consumes the sampled deadtime Vds waveform. It
accounts each sample interval as reversible commutation and dissipates only
the Eoss remaining at the final residual voltage when the channel turns on.
Reaching zero before turn-on therefore produces zero channel-dump energy;
stopping at a residual voltage produces exactly `Eoss(Vresidual)`. There is no
binary hard-switch multiplier.

The transition carries an explicit `turn_on_time_s`. Samples are truncated at
that deadline and Vds is linearly interpolated when it falls between samples;
the original `waveform_covered_until_s` is retained as coverage evidence. A
deadline outside the acquired waveform is rejected. The production buck path
also requires the transition deadline to equal `dc.tDead`, so the Coss ledger
cannot integrate a future sample while deadtime loss uses an earlier turn-on.
Falling intervals transfer Coss energy toward the commutating circuit; rising
rebound/ringing intervals reverse that source/destination pair and recharge
Coss before any residual channel discharge.

## Coss hysteresis/dielectric loss

Quasi-static Coss(V) defines reversible Qoss/Eoss only. It does not identify
Coss hysteresis or dielectric loss.

`CossHysteresisCalibration` is a separate measured energy-per-event input with
its own voltage range, frequency, temperature, gate bias, provenance, and
evidence quality. The evaluator refuses condition mismatches rather than
implicitly extrapolating them. With no independent calibration,
`P_hysteresis` and `p_total_w` remain unknown. `P_coss`/`p_accounted_w` is
explicitly labelled
`commutation-only-lower-bound:hysteresis-unverified`; the ranking CSV carries
that scope and its evidence/validation states. It is not presented as a
complete total and hysteresis is not silently treated as zero.

With a calibration, its energy source and
`device:<id>:coss-hysteresis` destination enter the flow ledger
independently. A claimed hysteresis energy larger than the full reversible
Eoss excursion fails validation rather than receiving PASS from algebraic
conservation alone.

The calibration is not an effective package/copper/Cin/ring resistance.
Those damping terms belong to the switching-cell model and must not be fitted
into this material-loss bucket.

## Qrr ownership and exactly-once accounting

A measured Qrr integral can contain junction displacement charge. The Coss
bucket already owns that charge, so `dcdc_buck_ls` subtracts the calibrated
Qoss share when Qrr test voltage `VR` and Qoss(VR) are available. It reports
`Qrr_q0`, its `Qrr_q0_basis`, `Qrr_decont`, and the accounting state
`Qrr_double_booking=exactly-once`. Accounting ownership is separate from
confidence: `Qrr_double_booking_evidence`, `Qrr_qoss_model_state`,
`Qrr_qoss_evidence`, provenance, conditions, and extrapolation flags preserve
whether the subtraction used a validated curve, an extrapolated curve, or the
scalar fallback. These fields survive successful operating-point fits and
`datasheet-flat-nofit` fallbacks and are exported with ranking rows.

When VR or Qoss is unavailable, the raw result is labelled
`datasheet-flat-qoss-unverified` and `Qrr_double_booking=UNVERIFIED`; absence
of evidence never appears as a successful decontamination.

## Reporting and validation

The `P_coss` condition report includes:

- initial/final Vds and the full sampled waveform;
- initial/final/peak stored Eoss and initial/final Qoss;
- supplied, recovered, commutation-dissipated, and hysteresis energy;
- destination buckets;
- switching frequency, events per cycle, and device count;
- curve/hysteresis/transition model states;
- provenance, measurement/operating conditions, extrapolation flags;
- `PASS`, `FAIL`, or `UNVERIFIED`, plus conservation residual.

Production CSV rows retain this complete structure in the strict-JSON
`P_coss_audit` column; unknown numeric results become JSON `null`. The compact
adjacent `P_coss_*` columns are search/sort conveniences. Staged-switching
rows namespace their two complete reports as `switcher` and `conductor` in
the audit payload.

`validate_coss_report()` checks conservation, expected destination, and
evidence state. Total-watt agreement by itself is not a mechanism validation.
The unit suite exercises isolated charge/discharge fixtures, partial ZVS, and
synchronous switching-cell transitions at multiple bus voltages.

## Ownership contract with dcdc-tools

- **fetlib owns** datasheet Coss(V) data and metadata, Qoss/Eoss integration,
  analytic transition ledgers, Coss/Qrr exactly-once bookkeeping, and
  PASS/FAIL/UNVERIFIED reporting.
- **dcdc-tools owns** simulated device/node waveforms, topology timing,
  package/copper/Cin parasitics, ring damping, and waveform-derived device
  dissipation.

Ownership is term-specific. `accounting_owner="external-waveform"` hands off
commutation only; fetlib still books a nonzero independently calibrated
material-hysteresis term. Handing off both requires the separate explicit
`hysteresis_accounting_owner="external-waveform"`. Missing fetlib-owned
hysteresis remains `UNVERIFIED` with a named booked lower bound—it cannot
become a zero/PASS result merely because commutation is external.

dcdc-tools writes `coss_handoff` in `loss_budget.json` with the schema,
per-term owners, externally accounted terms, `coss_rser` value/source, and
whether intrinsic hysteresis was modeled. A nonzero `coss_rser` is labeled
`diagnostic-fit-not-datasheet`, counted as external ring damping, and
explicitly forbidden as a hysteresis calibration. Analytic and waveform
ownership of the same term must never overlap.

## References

- Erickson and Maksimovic, *Fundamentals of Power Electronics*, nonlinear
  capacitor energy and commutation.
- EPC AN030, hard-switching loss calculation.
- TI SLPA009A, MOSFET output-capacitance energy.
- Infineon guidance on energy-related versus time-related effective Coss.
