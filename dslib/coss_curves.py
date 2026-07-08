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
    # Infineon IPP024N08NF2S Rev 2.1, Diagram 11 (VGS=0, f=1 MHz). Digitized by the raster
    # dark-pixel column trace (dslib/coss_digitizer.py), verified point-by-point against a
    # datasheet overlay. Reproduce:
    #   python -m dslib.coss_digitizer datasheets/infineon/IPP024N08NF2S.pdf --page 8 \
    #     --dpi 600 --box 650,2473,3956,5948 --vspan 0,80 --cdec 1,4 \
    #     --mfr infineon --mpn IPP024N08NF2S --anchor-coss 40,1000 --anchor-qoss 40,105
    # Table anchors: Coss=1000pF@40V (tool 1006), Crss=44pF@40V. Qoss(0-40V)=110nC integrated
    # -- the graph itself integrates to ~109nC, ~4% above the 105nC Table value (datasheet
    # graph-vs-table inconsistency, not a digitization error). NB: the 19nC Qgd Table spec is
    # the gate-charge Miller plateau, NOT integral(Crss dV) -- do not use it to anchor Crss.
    # Behind the datasheet-curve ring model (~60 MHz old fixture, ~62.5 refreshed padland).
    ("infineon", "IPP024N08NF2S"): [
        (0, 6400, 1450), (5, 4420, 800), (10, 3660, 510), (15, 3140, 345),
        (20, 2565, 208), (25, 1950, 113), (30, 1435, 71), (35, 1106, 54),
        (40, 1000, 44), (50, 875, 35), (60, 800, 32), (70, 756, 31), (80, 733, 31),
    ],
    # Infineon IPP055N08NF2S Rev 2.1, Diagram 11 (VGS=0, f=1 MHz) -- Fugu2 HS device.
    # Digitized by dslib/coss_digitizer.py (same box/template as IPP024). Reproduce:
    #   python -m dslib.coss_digitizer datasheets/infineon/IPP055N08NF2S.pdf --page 8 \
    #     --dpi 600 --box 650,2473,3956,5948 --vspan 0,80 --cdec 1,4 \
    #     --mfr infineon --mpn IPP055N08NF2S --anchor-coss 40,420 --anchor-qoss 40,43
    # Anchors: Coss=420pF@40V (tool 412, snapped to spec), Crss=20pF@40V (tool 20, exact),
    # Ciss=2500pF@40V (tool 2476). Qoss(0-40V)=45nC integrated vs 43nC Table (~5% graph-over-
    # table, same as IPP024). Closes the HS curve gap -> both Fugu2 sides curve-faithful.
    ("infineon", "IPP055N08NF2S"): [
        (0, 2650, 600), (5, 1830, 320), (10, 1505, 205), (15, 1290, 140),
        (20, 1050, 85), (25, 800, 47), (30, 590, 31), (35, 455, 24),
        (40, 420, 20), (50, 355, 16), (60, 320, 15), (70, 305, 15), (80, 295, 15),
    ],
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
