"""Datasheet output-capacitance curves Coss(V)/Crss(V), digitized from each part's
output-capacitance graph (typ. "Diagram 11" / "Typical Capacitances vs V_DS"), keyed by
(mfr, mpn). This is the SOURCE OF TRUTH for the curve-faithful Coss used by
dcdc-tools/loss (SW-ring model + Eoss switching-loss attribution).

Each COSS_CURVES entry is a list of (Vds_V, Coss_pF, Crss_pF) points, low V -> high V.
Coss is the total output capacitance; Crss the reverse-transfer (gate-drain)
capacitance; the drain-source part is Cds = Coss - Crss. CISS_CURVES carries optional
input-capacitance points from the same graph for consumers that need a real Ciss(V).
Digitize from the log-C vs Vds graph and reconcile against the datasheet Table anchors
(Ciss/Coss/Crss at the stated Vds, Qoss integral, Qgd integral).

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
    # Infineon IPP019N08NF2S Rev 2.1, Diagram 11 (VGS=0, f=1 MHz).
    # Digitized with the dcdc-tools vector-first C(V) digitizer:
    #   python3 dcdc-tools/scratch/datasheet_charts/find_charts.py \
    #     /Users/fab/dev/pv/pwr-mosfet-lib/datasheets/infineon/IPP019N08NF2S.pdf \
    #     --out out/datasheet_charts/ipp019 --dpi 180
    #   python3 dcdc-tools/scratch/datasheet_charts/digitize_capacitance.py \
    #     out/datasheet_charts/ipp019/charts.json --out out/datasheet_charts/ipp019
    # Anchors: Coss=1400pF@40V (tool 1396, snapped to spec), Crss=61pF@40V (tool 60.5,
    # snapped to spec). Qoss(0-40V)=144.7nC integrated vs 145nC Table.
    ("infineon", "IPP019N08NF2S"): [
        (0, 8930, 2036), (5, 5817, 1022), (10, 4881, 665), (15, 4234, 450),
        (20, 3409, 271), (25, 2598, 146), (30, 1913, 96), (35, 1518, 74),
        (40, 1400, 61), (50, 1218, 49), (60, 1114, 45), (70, 1064, 43),
        (80, 1032, 43),
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
    # Infineon IPP026N10NF2S Rev 2.1, Diagram 11 (VGS=0, f=1 MHz) -- 100 V Fugu2 LS
    # candidate (dcdc-tools#14 avalanche mitigation). Digitized with the dcdc-tools
    # vector-first C(V) digitizer:
    #   python3 dcdc-tools/scratch/datasheet_charts/find_charts.py \
    #     datasheets/infineon/IPP026N10NF2S.pdf --out out/datasheet_charts/ipp026n10nf2s --dpi 180
    #   python3 dcdc-tools/scratch/datasheet_charts/digitize_capacitance.py \
    #     out/datasheet_charts/ipp026n10nf2s/charts.json --out out/datasheet_charts/ipp026n10nf2s
    # Anchors: Coss=1100pF@50V (tool 1115, snapped to spec), Crss=49pF@50V (tool 49.0, exact),
    # Ciss=7300pF@50V (tool 7276). Qoss(0-50V)=133.5nC sampled vs 131nC Table (+1.9%).
    ("infineon", "IPP026N10NF2S"): [
        (0, 6571, 1652), (5, 4051, 642), (10, 3479, 463), (15, 3040, 349),
        (20, 2716, 263), (25, 2426, 195), (30, 2217, 143), (35, 1936, 103),
        (40, 1635, 70.4), (45, 1358, 56.8), (50, 1100, 49), (55, 1040, 43.8),
        (60, 981, 39.9), (70, 886, 36.0), (80, 828, 34.1), (90, 792, 32.9),
        (100, 766, 32.6),
    ],
    # Infineon IPP018N10N5 Rev 2.3, Diagram 11 (VGS=0, f=1 MHz) -- 100 V OptiMOS5 Fugu2 LS
    # candidate. Same vector-first digitizer run (out/datasheet_charts/ipp018n10n5).
    # Anchors: Coss=1800pF@50V (tool 1808, snapped to spec), Crss=80pF@50V (tool 79.5,
    # snapped to spec), Ciss=12000pF@50V (tool 11895). Qoss(0-50V)=215.6nC sampled vs
    # 213nC Table (+1.2%). NB the dslib DB has Id=NaN for this part, so the recon
    # gate-charge model is unbuildable -- the curve model does not need Id.
    ("infineon", "IPP018N10N5"): [
        (0, 10543, 2671), (5, 6575, 1055), (10, 5584, 760), (15, 4914, 576),
        (20, 4390, 429), (25, 3922, 318), (30, 3557, 235), (35, 3154, 168),
        (40, 2633, 114), (45, 2215, 91.8), (50, 1800, 80), (55, 1687, 70.5),
        (60, 1597, 64.2), (70, 1460, 57.8), (80, 1354, 54.4), (90, 1295, 52.8),
        (100, 1256, 52.0),
    ],
    # Infineon IPP022N12NM6 Rev 2.0, Diagram 11 (VGS=0, f=1 MHz) -- 120 V OptiMOS6 Fugu2 LS
    # candidate. Same vector-first digitizer run (out/datasheet_charts/ipp022n12nm6).
    # Anchors: Coss=2400pF@60V (tool 2350, snapped to spec), Crss=40pF@60V (tool 40.0, exact),
    # Ciss=8100pF@60V (tool 8056). Qoss(0-60V)=266.9nC sampled vs 267nC Table (-0.0%).
    ("infineon", "IPP022N12NM6"): [
        (0, 8920, 1475), (5, 6535, 801), (10, 5796, 568), (15, 5337, 422),
        (20, 4952, 313), (25, 4571, 232), (30, 4278, 175), (35, 3927, 132),
        (40, 3561, 101), (45, 3227, 78.1), (50, 2909, 61.4), (55, 2623, 48.5),
        (60, 2400, 40), (70, 1847, 28.4), (80, 1492, 22.2), (90, 1334, 18.9),
        (100, 1176, 17.1), (110, 1063, 16.1), (120, 960, 15.6),
    ],
    # Infineon IPP050N10NF2S Rev 2.1 (2022-06-15), Diagram 11 (VGS=0, f=1 MHz) -- 100 V
    # StrongIRFET2 Fugu2 HS candidate (dcdc-tools#15: like-for-like IPP055N08NF2S
    # replacement, 2x parallel). Digitized with the dcdc-tools vector-first C(V) digitizer:
    #   python3 dcdc-tools/scratch/datasheet_charts/find_charts.py \
    #     datasheets/infineon/IPP050N10NF2S.pdf --out out/datasheet_charts/ipp050n10nf2s --dpi 180
    #   python3 dcdc-tools/scratch/datasheet_charts/digitize_capacitance.py \
    #     out/datasheet_charts/ipp050n10nf2s/charts.json --out out/datasheet_charts/ipp050n10nf2s
    # Anchors: Coss=570pF@50V (tool 565.2, snapped to spec), Crss=25pF@50V (tool 25.4,
    # snapped to spec), Ciss=3600pF@50V (tool 3607). Qoss(0-50V)=67.0nC sampled vs 67nC
    # Table (-0.0%). Vector extraction, axis residuals ~1e-6.
    ("infineon", "IPP050N10NF2S"): [
        (0, 3332, 838), (5, 2079, 321), (10, 1784, 230), (15, 1559, 174),
        (20, 1377, 132), (25, 1238, 98.2), (30, 1124, 71.9), (35, 983, 51.9),
        (40, 829, 35.7), (45, 689, 29.1), (50, 570, 25), (55, 527, 22.7),
        (60, 492, 20.9), (70, 449, 18.7), (80, 415, 17.9), (90, 397, 17.5),
        (100, 384, 17.3),
    ],
}


# Optional (Vds_V, Ciss_pF) input-capacitance curves from the same datasheet graph.
CISS_CURVES = {
    # Infineon IPP019N08NF2S Rev 2.1, Diagram 11. Anchors: Ciss=8700pF@40V
    # (tool 8665, snapped to spec).
    ("infineon", "IPP019N08NF2S"): [
        (0, 10543), (5, 9559), (10, 9204), (15, 8999),
        (20, 8800), (25, 8665), (30, 8665), (35, 8665),
        (40, 8700), (50, 8665), (60, 8665), (70, 8665),
        (80, 8665),
    ],
}


def _curve_for(curves, mfr, mpn):
    if not isinstance(mfr, str) or not isinstance(mpn, str):
        return None
    exact = curves.get((mfr, mpn)) or curves.get((mfr.lower(), mpn))
    if exact:
        return exact
    # orderable-suffix fallback: a curve key whose MPN is a prefix of the requested MPN.
    cand = [(k_mpn, v) for (k_mfr, k_mpn), v in curves.items()
            if k_mfr.lower() == mfr.lower() and mpn.startswith(k_mpn)]
    if cand:
        return max(cand, key=lambda kv: len(kv[0]))[1]   # longest base-MPN match
    return None


def coss_curve_for(mfr, mpn):
    """Return the digitized [(V, Coss_pF, Crss_pF), ...] curve for a part, or None if the
    part has no curve in the DB. Case-tolerant on mfr (matching dslib key lookups). Falls
    back to a base-MPN match so an orderable suffix (e.g. IPP024N08NF2S -> ...AKMA1) still
    resolves the base part's curve; longest matching base wins to avoid false positives."""
    return _curve_for(COSS_CURVES, mfr, mpn)


def ciss_curve_for(mfr, mpn):
    """Return the optional digitized [(V, Ciss_pF), ...] curve for a part, or None."""
    return _curve_for(CISS_CURVES, mfr, mpn)
