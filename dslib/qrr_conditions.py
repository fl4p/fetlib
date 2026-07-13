"""Datasheet body-diode reverse-recovery TEST CONDITIONS, keyed by (mfr, mpn).

The parts DB stores `Qrr` and `trr` as flat scalars, but a scalar is meaningless without
the operating point it was measured at: Qrr scales roughly as sqrt(di/dt) and with IF and
Tj. The conditions live next to the Qrr/trr line in every datasheet ("VR=40V, IF=100A,
diF/dt=500A/us") but are not parsed into the pickle DB, so they are curated here.

Consumers:
  * dcdc-tools/loss lib/lm_diode.py — fits the Lauritzen-Ma charge-control body-diode
    subcircuit (tau, TM) from (Qrr, trr) AT THIS OPERATING POINT, so the transient deck
    reproduces the datasheet recovery instead of a crude TT diode (which over-injects Qrr
    by ~5x and manufactures a fake avalanche; see fl4p/dcdc-tools#14).
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
    ("infineon", "IPP018N10N5"): dict(IF=100.0, didt=100e6, VR=50.0, Tj=25.0),
    # IPP022N12NM6 quotes TWO di/dt points (300 and 1000 A/us) -- the primary Qrr/trr row
    # in the parts DB is the 300 A/us one. The second point is the two-point fit fl4p/fetlib#37
    # wants; not used yet.
    ("infineon", "IPP022N12NM6"): dict(IF=50.0, didt=300e6, VR=60.0, Tj=25.0),
}


def _cond_for(mfr, mpn):
    if not mfr or not mpn:
        return None
    hit = QRR_CONDITIONS.get((mfr, mpn)) or QRR_CONDITIONS.get((str(mfr).lower(), mpn))
    if hit:
        return dict(hit)
    # Same base-MPN fallback as coss_curves: an orderable suffix (IPP024N08NF2S -> ...AKMA1)
    # still resolves to the base part's conditions.
    for (m, p), v in QRR_CONDITIONS.items():
        if str(m).lower() == str(mfr).lower() and str(mpn).startswith(p):
            return dict(v)
    return None


def qrr_conditions_for(mfr, mpn):
    """(mfr, mpn) -> dict(IF, didt, VR, Tj) or None if the part has no curated conditions."""
    return _cond_for(mfr, mpn)
