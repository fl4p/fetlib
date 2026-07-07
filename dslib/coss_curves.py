"""Datasheet output-capacitance curves Coss(V)/Crss(V), digitized from each part's
output-capacitance graph (typ. "Diagram 11" / "Typical Capacitances vs V_DS"), keyed by
(mfr, mpn). This is the SOURCE OF TRUTH for the curve-faithful Coss used by
dcdc-tools/loss (SW-ring model + Eoss switching-loss attribution).

Each entry is a list of (Vds_V, Coss_pF, Crss_pF) points, low V -> high V. Coss is the
total output capacitance; Crss the reverse-transfer (gate-drain) capacitance; the
drain-source part is Cds = Coss - Crss. Digitize from the log-C vs Vds graph and
reconcile against the datasheet Table anchors (Coss@40V, Qoss integral, Qgd integral).

A part ABSENT here has no curve: consumers (loss/params.py, loss/loss.py) MUST warn and
fall back to the scalar Coss@Coss_Vds rather than silently substitute a wrong curve.
Add a part by digitizing its graph; see fl4p/fetlib#37 (Qoss curve model).
"""

# (Vds_V, Coss_pF, Crss_pF)
COSS_CURVES = {
    # Infineon IPP024N08NF2S Rev 2.1, Diagram 11 (VGS=0, f=1 MHz). Reconciled to Table
    # anchors: Coss=1000pF@40V, Crss=45pF@40V, Qoss=105nC@40V, Qgd=19nC@40V. Ring region
    # (40-80 V) solid to ~3%; low-V region integral-constrained. Behind the _coss-handoff
    # curve-fit model that rings 60 MHz on the Fugu2 fixture.
    ("infineon", "IPP024N08NF2S"): [
        (0, 7500, 1600), (5, 4700, 780), (10, 3250, 380), (15, 2480, 210),
        (20, 1960, 130), (25, 1560, 85), (30, 1255, 60), (40, 1000, 45),
        (50, 880, 40), (60, 800, 37), (70, 760, 34), (80, 730, 32),
    ],
    # IPP055N08NF2S: TODO digitize Diagram 11 from the datasheet. Until then the HS side
    # has no real curve (the _coss-handoff MYHS model reused IPP024's fit) and consumers
    # warn + fall back to the scalar Coss for this part.
}


def coss_curve_for(mfr, mpn):
    """Return the digitized [(V, Coss_pF, Crss_pF), ...] curve for a part, or None if the
    part has no curve in the DB. Case-tolerant on mfr (matching dslib key lookups). Falls
    back to a base-MPN match so an orderable suffix (e.g. IPP024N08NF2S -> ...AKMA1) still
    resolves the base part's curve — longest matching base wins to avoid false positives."""
    if not isinstance(mfr, str) or not isinstance(mpn, str):
        return None
    exact = COSS_CURVES.get((mfr, mpn)) or COSS_CURVES.get((mfr.lower(), mpn))
    if exact:
        return exact
    # orderable-suffix fallback: a curve key whose MPN is a prefix of the requested MPN.
    cand = [(k_mpn, v) for (k_mfr, k_mpn), v in COSS_CURVES.items()
            if k_mfr.lower() == mfr.lower() and mpn.startswith(k_mpn)]
    if cand:
        return max(cand, key=lambda kv: len(kv[0]))[1]   # longest base-MPN match
    return None
