"""Datasheet body-diode reverse-recovery TEST CONDITIONS, keyed by (mfr, mpn).

The parts DB stores `Qrr` and `trr` as flat scalars, but a scalar is meaningless without
the operating point it was measured at: Qrr scales STEEPLY with di/dt, and with IF and Tj.
The conditions live next to the Qrr/trr line in every datasheet ("VR=40V, IF=100A,
diF/dt=500A/us") but are not parsed into the pickle DB, so they are curated here.

How steeply, measured (2026-07-13): IPP022N12NM6 is the only part here whose datasheet quotes
Qrr at TWO di/dt points (IF=50A, Tj=25C): 155.2 nC @ 300 A/us and 412.1 nC @ 1000 A/us. That
is an exponent of **0.81**, NOT the 0.5 ("roughly sqrt") this docstring used to claim. The
Lauritzen-Ma fit reproduces it: fit on one point, predict the other, and Qrr lands within
3.5% / -4.9% with tau agreeing to 4% between the two rows.

Consumers:
  * dcdc-tools/loss lib/lm_diode.py — fits the Lauritzen-Ma charge-control body-diode
    subcircuit (tau, TM) from (Qrr, trr) AT THIS OPERATING POINT, so the transient deck
    reproduces the datasheet recovery SHAPE (which a one-time-constant TT diode cannot).
    NB: this is a FIDELITY fix, not a way to shrink Qrr. At a tight-loop converter's di/dt
    (~10x the datasheet's) the LM diode injects MORE charge than the TT diode it replaces,
    because Qrr grows with di/dt. The claim that TT "over-injects Qrr by ~5x and manufactures
    a fake avalanche" is RETRACTED (see the retraction block in lm_diode.py and
    fl4p/dcdc-tools#15): TT*IF = 15ns * 28A = 420 nC, only ~1.5x IPP019's 285 nC.
  * the analytic Qrr(di/dt) refinement (loss.py --qrr-didt-ref).

Fields per entry:
  IF    forward current the recovery was measured at [A]
  didt  commutation di/dt of the test [A/s]
  VR    reverse (blocking) voltage of the test [V] — informational
  Tj    junction temperature of the test [degC] (Infineon quotes 25C unless noted)

A part ABSENT here has no conditions: consumers MUST fail loud or fall back explicitly
rather than invent an operating point. See fl4p/fetlib#37.
"""

QRR_CONDITIONS = {
    # Infineon OptiMOS -- conditions read from the "Reverse recovery charge" row of each
    # datasheet's body-diode table (dslib/datasheets/infineon/<MPN>.pdf.txt).
    ("infineon", "IPP019N08NF2S"): dict(IF=100.0, didt=500e6, VR=40.0, Tj=25.0),
    ("infineon", "IPP024N08NF2S"): dict(IF=100.0, didt=500e6, VR=40.0, Tj=25.0),
    ("infineon", "IPP055N08NF2S"): dict(IF=60.0, didt=500e6, VR=40.0, Tj=25.0),
    ("infineon", "IPP026N10NF2S"): dict(IF=100.0, didt=500e6, VR=50.0, Tj=25.0),
    # 100 V StrongIRFET2, Fugu2 HS candidate (fl4p/dcdc-tools#15). Rev 2.1: Qrr=247nC,
    # trr=37ns at these conditions. Without this entry the loss tool silently fell back
    # to the flat datasheet Qrr for an LS built from this part.
    ("infineon", "IPP050N10NF2S"): dict(IF=60.0, didt=500e6, VR=50.0, Tj=25.0),
    # fisi HS FET (dcdc-tools loss/examples/fisi.yaml). Qrr=189nC, trr=33ns at these
    # conditions. Needed because --body-diode lm builds the LM diode for BOTH sides of a
    # curve-mode deck (the HS body diode barely matters for a buck's Qrr, but the fit
    # fails loud without an operating point).
    ("infineon", "IPP040N08NF2S"): dict(IF=80.0, didt=500e6, VR=40.0, Tj=25.0),
    ("infineon", "IPP018N10N5"): dict(IF=100.0, didt=100e6, VR=50.0, Tj=25.0),
    # IPP022N12NM6 quotes TWO di/dt points (300 and 1000 A/us) -- the primary Qrr/trr row
    # in the parts DB is the 300 A/us one. BOTH rows now live in the generated
    # dslib/qrr_points.py and Qrr_op prefers the per-part two-point (tau, TM, q0) fit;
    # this single-point entry remains as the explicit fallback.
    ("infineon", "IPP022N12NM6"): dict(IF=50.0, didt=300e6, VR=60.0, Tj=25.0),
}


def _cond_for(mfr, mpn):
    # exact key + the shared orderable-suffix fallback (dslib/mpn_match.py) —
    # strict so a family variant never inherits another die's conditions
    from dslib.mpn_match import lookup_base_variant
    hit = lookup_base_variant(QRR_CONDITIONS, mfr, mpn)
    return dict(hit) if hit else None


def qrr_conditions_for(mfr, mpn):
    """(mfr, mpn) -> dict(IF, didt, VR, Tj) or None if the part has no curated conditions."""
    return _cond_for(mfr, mpn)
