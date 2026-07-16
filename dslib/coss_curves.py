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
    # Infineon IPP040N08NF2S Rev 2.1 (2022-06-15), Diagram 11 (VGS=0, f=1 MHz).
    # First curve produced by the datasheet-chart-digitizer AUTO pipeline (adaptive knots,
    # so the Vds points are error-driven, not a fixed grid). Reproduce (dsdig venv):
    #   dsdig find datasheets/infineon/IPP040N08NF2S.pdf --out out/ipp040 --dpi 180
    #   dsdig digitize-capacitance out/ipp040/charts.json --out out/ipp040
    #   dsdig export-coss-dslib out/ipp040 --out out/ipp040
    # Anchors (tool values kept, NOT snapped): Coss=620pF@40V (tool 617, -0.4%),
    # Crss=29pF@40V (tool 28.7, -0.9%), Ciss=3800pF@40V. Qoss(0-40V)=65.5nC integrated vs
    # 65nC Table (+0.8%). Axis fit position_text, residuals ~1e-5 V / 3e-7 dec; trace +
    # axis-calibration overlays human-verified 2026-07-13. The 40V knot is the digitized
    # anchor point added by hand: the adaptive knots straddled 40V and LINEAR interp (what
    # dslib consumers use) read the convex knee +2.4% there.
    ("infineon", "IPP040N08NF2S"): [
        (0, 3905, 857.1), (0.78, 3648, 782.9), (1.95, 3044, 610.3),
        (3.41, 2844, 520.9), (6.48, 2483, 397.0), (14.21, 1958, 215.5),
        (17.57, 1729, 155.2), (22.24, 1363, 92.22), (27.64, 992.9, 51.2),
        (32.02, 748.2, 39.47), (34.79, 683.5, 34.85), (40, 617.3, 28.75),
        (51.58, 526.8, 22.93), (67.05, 470.5, 21.18), (80, 454.8, 20.94),
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
    # Infineon IPP055N08NF2S Rev 2.1, Diagram 11 (VGS=0, f=1 MHz) -- Fugu2 HS device.
    # dsdig full pipeline (find -> digitize-capacitance -> export-coss-dslib), export gate
    # PASS with all three anchors inside 2% (Coss -1.8%, Crss +0.9%, Ciss -1.2%). The
    # validated 542-pt Ciss trace was resampled onto this 5 V grid (median window), snapped
    # at the 40 V Table anchor (2500pF; tool 2470); knot-vs-raw median 0.01% / max 1.84%.
    # Axis calibration position_text, residuals ~1e-5 V / 3e-7 dec; trace + axis-tick
    # overlays human-verified 2026-07-16. Ciss>Crss holds at every knot.
    ("infineon", "IPP055N08NF2S"): [
        (0, 3002), (5, 2739), (10, 2646), (15, 2571), (20, 2527), (25, 2499),
        (30, 2470), (35, 2470), (40, 2500), (45, 2470), (50, 2470), (55, 2470),
        (60, 2470), (65, 2470), (70, 2470), (75, 2470), (80, 2470),
    ],
    # Infineon IPP024N08NF2S Rev 2.1, Diagram 11 (VGS=0, f=1 MHz) -- Fugu2 LS device.
    # Same dsdig pipeline; export gate PASS (Coss -0.2%, Crss -1.0%, Ciss -0.2%). Validated
    # 542-pt trace resampled onto the 5 V grid, snapped at the 40 V Table anchor (6200pF;
    # tool 6185); knot-vs-raw median 0.00% / max 1.65%. Axis position_text, residuals
    # ~1e-5 V / 3e-7 dec; trace + axis-tick overlays human-verified 2026-07-16.
    ("infineon", "IPP024N08NF2S"): [
        (0, 7431), (5, 6858), (10, 6626), (15, 6439), (20, 6329), (25, 6256),
        (30, 6185), (35, 6185), (40, 6200), (45, 6185), (50, 6185), (55, 6185),
        (60, 6185), (65, 6185), (70, 6185), (75, 6185), (80, 6185),
    ],
    # --- Fugu2 LS/HS swap candidates (dcdc-tools#14/#15). Same dsdig pipeline + curation as
    # the deck parts above: export gate PASS with every anchor inside 2%; validated 542-pt
    # Ciss trace resampled onto a 5 V grid, snapped at the Table anchor V; trace AND axis-tick
    # overlays human-verified 2026-07-16; Ciss > Crss at every knot. Per-part anchor + fit: ---
    # IPP026N10NF2S Rev 2.1, 100 V -- Ciss 7300pF@50V (digitized -0.5%), knot-vs-raw max 2.6%.
    ("infineon", "IPP026N10NF2S"): [
        (0, 8528), (5, 7825), (10, 7692), (15, 7517), (20, 7431), (25, 7389),
        (30, 7347), (35, 7263), (40, 7263), (45, 7263), (50, 7300), (55, 7263),
        (60, 7263), (65, 7263), (70, 7263), (75, 7263), (80, 7180), (85, 7180),
        (90, 7180), (95, 7180), (100, 7180),
    ],
    # IPP018N10N5 Rev 2.3, 100 V OptiMOS5 -- Ciss 12000pF@50V (digitized -0.4%), max 2.8%.
    ("infineon", "IPP018N10N5"): [
        (0, 14139), (5, 12802), (10, 12511), (15, 12321), (20, 12321), (25, 12134),
        (30, 11950), (35, 11950), (40, 11950), (45, 11950), (50, 12000), (55, 11950),
        (60, 11950), (65, 11950), (70, 11950), (75, 11768), (80, 11768), (85, 11768),
        (90, 11768), (95, 11768), (100, 11768),
    ],
    # IPP022N12NM6 Rev 2.0, 120 V OptiMOS6 -- Ciss 8100pF@60V (digitized -0.6%), max 1.4%.
    ("infineon", "IPP022N12NM6"): [
        (0, 9295), (5, 8827), (10, 8627), (15, 8431), (20, 8335), (25, 8240),
        (30, 8146), (35, 8146), (40, 8146), (45, 8053), (50, 8053), (55, 8053),
        (60, 8100), (65, 8053), (70, 8053), (75, 8053), (80, 8053), (85, 8053),
        (90, 8053), (95, 8053), (100, 8053), (105, 8053), (110, 8053), (115, 8053),
        (120, 8053),
    ],
    # IPP050N10NF2S Rev 2.1, 100 V StrongIRFET2 -- Ciss 3600pF@50V (digitized +0.2%), max 2.6%.
    ("infineon", "IPP050N10NF2S"): [
        (0, 4236), (5, 3886), (10, 3776), (15, 3733), (20, 3691), (25, 3649),
        (30, 3649), (35, 3607), (40, 3607), (45, 3607), (50, 3600), (55, 3586),
        (60, 3566), (65, 3566), (70, 3566), (75, 3566), (80, 3566), (85, 3566),
        (90, 3566), (95, 3566), (100, 3566),
    ],
    # IPP040N08NF2S Rev 2.1, 80 V -- Ciss 3800pF@40V (digitized -0.6%), knot-vs-raw max 1.8%.
    ("infineon", "IPP040N08NF2S"): [
        (0, 4537), (5, 4187), (10, 4046), (15, 3931), (20, 3864), (25, 3798),
        (30, 3776), (35, 3776), (40, 3800), (45, 3776), (50, 3776), (55, 3776),
        (60, 3776), (65, 3776), (70, 3776), (75, 3776), (80, 3776),
    ],
}


def _curve_for(curves, mfr, mpn):
    if not isinstance(mfr, str) or not isinstance(mpn, str):
        return None
    # exact key, then the SHARED orderable-suffix fallback (dslib/mpn_match.py):
    # a bare prefix match also hits FAMILY VARIANTS (IPP040N06N vs
    # IPP040N06NF2S) and would serve a different die's curve.
    from dslib.mpn_match import lookup_base_variant
    return lookup_base_variant(curves, mfr, mpn)


def coss_curve_for(mfr, mpn):
    """Return the digitized [(V, Coss_pF, Crss_pF), ...] curve for a part, or None if the
    part has no curve in the DB. Case-tolerant on mfr (matching dslib key lookups). Falls
    back to a base-MPN match so an orderable suffix (e.g. IPP024N08NF2S -> ...AKMA1) still
    resolves the base part's curve; longest matching base wins to avoid false positives."""
    return _curve_for(COSS_CURVES, mfr, mpn)


def ciss_curve_for(mfr, mpn):
    """Return the optional digitized [(V, Ciss_pF), ...] curve for a part, or None."""
    return _curve_for(CISS_CURVES, mfr, mpn)
