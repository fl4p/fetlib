"""Curated V(BR)DSS(Tj) breakdown-onset lines from digitized datasheet charts.

Source: datasheet-chart-digitizer `dsdig digitize-breakdown-voltage` on the
Infineon "Drain-source breakdown voltage" charts (Diagram 15 / old numbered-
caption layout), run 2026-07-14, overlays HUMAN-VERIFIED by Fab, spec-table
anchor verdict "verified" on every part (manifest kept at
/Users/fab/dev/pv/ee/out/bv_digitization/breakdown_voltage_digitization.json).

PROVENANCE — read this before consuming (fetmodel channel consensus):
  * The chart is MIN-ANCHORED with a TYPICAL-DIE SLOPE: its 25 C value equals
    the parameter-table V(BR)DSS MINIMUM exactly (auto-verified per part),
    while the slope matches the vendor S5 behavioral `ab` tempco to 4
    significant figures. `bv_min_25c` is therefore the guaranteed floor, NOT
    a typical 25 C breakdown.
  * The vendor S5 models' typical avalanche knee (UB/lB/UT exponential; e.g.
    ~86.6 V @1 mA for the 80 V parts) is a DIFFERENT intercept model and is
    deliberately not stored here — a consumer must choose and report
    min-onset vs vendor-typical-knee explicitly, never mix them.
  * Onset/tempco only: the chart is taken at ID=1 mA. It says nothing about
    the high-current clamp voltage, dynamic resistance, or UIS energy, so it
    can improve an avalanche VOLTAGE anchor but cannot bench-validate
    avalanche WATTS.
  * All curves are linear within 15 mV RMS over Tj = -55..175 C.

Attached at load by dslib.store.load_parts() as `specs.bv_tj` (fill-if-absent),
same pattern as coss_curves/qrr_conditions/gate_specs.
"""

# (mfr, base MPN) -> dict:
#   bv_min_25c [V]   chart value at 25 C == parameter-table V(BR)DSS minimum
#   bv_tc      [V/K] typical-die temperature coefficient (chart slope)
#   tj_min/tj_max [C] digitized chart span (do not extrapolate far outside)
BV_SPECS = {
    ("infineon", "IPP040N08NF2S"): dict(bv_min_25c=80.0, bv_tc=0.040, tj_min=-55.0, tj_max=175.0),
    ("infineon", "IPP024N08NF2S"): dict(bv_min_25c=80.0, bv_tc=0.040, tj_min=-55.0, tj_max=175.0),
    ("infineon", "IPP055N08NF2S"): dict(bv_min_25c=80.0, bv_tc=0.040, tj_min=-55.0, tj_max=175.0),
    ("infineon", "IPP019N08NF2S"): dict(bv_min_25c=80.0, bv_tc=0.040, tj_min=-55.0, tj_max=175.0),
    ("infineon", "IPP022N12NM6"): dict(bv_min_25c=120.0, bv_tc=0.075, tj_min=-55.0, tj_max=175.0),
    ("infineon", "IPP040N06N"): dict(bv_min_25c=60.0, bv_tc=0.030, tj_min=-55.0, tj_max=175.0),
}


def bv_specs_for(mfr, mpn):
    """(mfr, mpn) -> dict(bv_min_25c, bv_tc, tj_min, tj_max) or None.

    Returns the curated entry only — no interpolation, no defaults: an
    uncurated part gets None, never a guessed breakdown line.
    """
    # exact key + the shared orderable-suffix fallback (dslib/mpn_match.py):
    # strict, because a bare startswith serves one part's breakdown line to a
    # DIFFERENT family member — IPP040N06N matched IPP040N06NF2S (live
    # 2026-07-14, the finding that motivated the shared helper).
    from dslib.mpn_match import lookup_base_variant
    hit = lookup_base_variant(BV_SPECS, mfr, mpn)
    return dict(hit) if hit else None
