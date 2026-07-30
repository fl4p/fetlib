"""Datasheet output-capacitance curves Coss(V)/Crss(V), digitized from each part's
output-capacitance graph (typ. "Diagram 11" / "Typical Capacitances vs V_DS"), keyed by
(mfr, mpn). This is the SOURCE OF TRUTH for the curve-faithful Coss used by
dcdc-tools/loss (SW-ring model + Eoss switching-loss attribution).

Legacy COSS_CURVES entries are (Vds_V, Coss_pF, Crss_pF) triples. New imports may use
(Vds_V, Coss_pF) pairs and keep independently validated reverse-transfer curves in
CRSS_CURVES. Ciss is likewise independent in CISS_CURVES.
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
    # --- top-30 ranking coverage batch, dsdig auto pipeline (find -> digitize-capacitance
    # -> export-coss-dslib), digitized 2026-07-29 from the orderable-suffix PDFs; adaptive
    # knots (error-driven Vds points), all three table anchors within the 2% export gate,
    # trace/axis/Qoss validation pass, overlays human-verified 2026-07-29. ---
    # Infineon IPP052N08N5 Rev 2.0, Diagram 11 (VGS=0, f=1 MHz) -- 80 V OptiMOS5 fugu3
    # candidate. PDF datasheets/infineon/IPP052N08N5AKSA1.pdf p.9. Anchors @40V:
    # Coss=490pF (-1.3%), Crss=23pF (+0.9%), Ciss=2900pF (+1.1%). Qoss(0-80V)=50.8nC.
    ("infineon", "IPP052N08N5"): [
        (0, 3044, 675), (0.8457, 2827, 596.6), (1.882, 2437, 489.7), (5.879, 2000, 321.8),
        (14.17, 1525, 167.3), (17.57, 1348, 119.9), (21.87, 1092, 75.92), (27.79, 773.2, 39.95),
        (31.93, 582.1, 31.6), (34.74, 533.9, 27.59), (40, 483.7, 23.21), (53.54, 401.9, 18.36),
        (65.09, 368.6, 17.47), (79.74, 350.9, 17.26),
    ],
    # Infineon IPA050N10NM5S Rev 2.1 (2019-08-28), Diagram 11 (VGS=0, f=1 MHz) -- 100 V
    # OptiMOS5 fugu2 candidate. PDF datasheets/infineon/IPA050N10NM5SXKSA1.pdf p.7.
    # Anchors @50V: Coss=560pF (+1.0%), Crss=25pF (+0.4%), Ciss=3600pF (-0.9%).
    # Qoss(0-100V)=66.4nC.
    ("infineon", "IPA050N10NM5S"): [
        (0, 3143, 766.4), (0.6871, 2968, 675.6), (1.982, 2414, 441.9), (8.273, 1876, 254.8),
        (18.27, 1441, 146.9), (31.59, 1094, 64.3), (37.88, 889.7, 42.06), (43.8, 723.7, 30.15),
        (50, 565.5, 25.1), (50.46, 555.9, 24.81), (52.5, 537.1, 23.7), (73.04, 431.9, 18.2),
        (100.1, 380.7, 17.19),
    ],
    # Infineon IPP083N10N5 Rev 2.1 (2016-10-03), Diagram 11 (VGS=0, f=1 MHz) -- 100 V
    # OptiMOS5 fugu3 candidate. PDF datasheets/infineon/IPP083N10N5AKSA1.pdf p.8.
    # Anchors @50V: Coss=337pF (+0.7%), Crss=16pF (-2.0%), Ciss=2100pF (+0.2%).
    # Qoss(0-80V)=40.4nC.
    ("infineon", "IPP083N10N5"): [
        (0, 1941, 468), (0.5497, 1854, 426.9), (0.8457, 1771, 385), (2.03, 1474, 263.7),
        (8.543, 1132, 148.6), (17.72, 889.7, 89.68), (32.52, 645.3, 37.07), (37.11, 555.9, 27.2),
        (43.18, 447, 19.06), (50, 339.4, 15.68), (50.43, 335.5, 15.5), (63.61, 282.5, 12.46),
        (79.74, 249, 11.37),
    ],
    # Infineon ISC040N10NM7 Rev 1.0 (2025-10), Diagram 11 (VGS=0, f=1 MHz) -- 100 V
    # OptiMOS7 fugu2 LS candidate; first M7-template curve, unlocked by the dsdig
    # block-scoped anchor repair (unit+condition stated once per table block).
    # PDF datasheets/infineon/ISC040N10NM7ATMA1.pdf p.9. Anchors @50V: Coss=1170pF
    # (-0.6%), Crss=13pF (-4.0%, within the 8% export gate; 0.5 pF absolute),
    # Ciss=2800pF (+0.4%). Qoss(0-50V)=91.0nC vs 91nC Table (-0.0%).
    ("infineon", "ISC040N10NM7"): [
        (0, 3061, 550.8), (0.09456, 3061, 550.8), (1.058, 2959, 434.3), (2.022, 2718, 293.9),
        (7.032, 2413, 176.6), (15.51, 2036, 82.23), (28.42, 1661, 29.69), (37.48, 1450, 18.14),
        (50, 1163, 12.49), (53.48, 1105, 11.87), (71.4, 786.8, 10.54), (78.91, 675.3, 10.36),
        (83.54, 599.6, 10.36), (99.92, 550.8, 10.36),
    ],
    # Infineon IPP014N08NM6 Rev 2.01, Diagram 11 (VGS=0, f=1 MHz) -- 80 V OptiMOS6, fugu3 top candidate.
    # PDF datasheets/infineon/IPP014N08NM6AKSA1.pdf p.8. Anchors @40V: Coss=3700pF (-0.5%), Crss=84pF (+0.9%), Ciss=11000pF (-2.4%).
    # Qoss(full range)=301.6nC; qoss table validation pass (vint via PDF fallback).
    ("infineon", "IPP014N08NM6"): [
        (0, 13510, 2057), (0.6977, 13300, 1877), (3.362, 11770, 1242), (7.211, 10410, 900.7),
        (14.32, 8535, 503.6), (20.09, 7324, 318.3), (26.16, 6003, 204.2), (31.64, 4996, 139.3),
        (37.7, 4033, 95.05), (40, 3680, 84.74), (46.59, 2837, 60.99), (61.09, 2398, 38.55),
        (80.04, 2187, 31.59),
    ],
    # Infineon IPP016N08NF2S Rev 2.11, Diagram 11 (VGS=0, f=1 MHz) -- 80 V StrongIRFET2, fugu3.
    # PDF datasheets/infineon/IPP016N08NF2SAKMA1.pdf p.8. Anchors @40V: Coss=1900pF (+0.3%), Crss=83pF (-1.7%), Ciss=12000pF (-0.4%).
    # Qoss(full range)=197.1nC; qoss table validation pass (vint via PDF fallback).
    ("infineon", "IPP016N08NF2S"): [
        (0, 11770, 2628), (0.6977, 11070, 2398), (2.178, 9073, 1877), (6.175, 7668, 1261),
        (16.09, 5647, 552), (22.61, 4095, 273.1), (26.6, 3256, 164.9), (32.23, 2221, 114.2),
        (35.63, 2026, 96.52), (40, 1906, 81.57), (51.17, 1636, 64.84), (63.17, 1492, 59.16),
        (80.04, 1404, 58.26),
    ],
    # Infineon IPP082N10NF2S Rev 2.11, Diagram 11 (VGS=0, f=1 MHz) -- 100 V StrongIRFET2, fugu3.
    # PDF datasheets/infineon/IPP082N10NF2SAKMA1.pdf p.8. Anchors @50V: Coss=320pF (+0.7%), Crss=15pF (-1.3%), Ciss=2000pF (-0.7%).
    # Qoss(full range)=38.1nC; qoss table validation pass (vint via PDF fallback).
    ("infineon", "IPP082N10NF2S"): [
        (0, 1812, 431.9), (0.6871, 1711, 385), (1.982, 1392, 249), (8.273, 1081, 143.5),
        (17.71, 840.1, 84.68), (31.59, 623.4, 36.65), (37.88, 507.1, 24.25), (45.84, 380.7, 16.42),
        (50, 322.3, 14.81), (50.46, 316.8, 14.64), (54.53, 295.7, 13.51), (73.04, 243.3, 10.99),
        (100.1, 212, 10.37),
    ],
    # Infineon IQD020N10NM5SC Rev ?, Diagram 11 (VGS=0, f=1 MHz) -- 100 V OptiMOS5 source-down, fugu2.
    # PDF datasheets/infineon/IQD020N10NM5SCATMA1.pdf p.8. Anchors @50V: Coss=1000pF (+4.1%), Crss=42pF (-1.1%), Ciss=7300pF (-0.1%).
    # Qoss(full range)=125.0nC; qoss table validation pass (vint via PDF fallback).
    ("infineon", "IQD020N10NM5SC"): [
        (0, 6103, 1776), (0.09456, 6103, 1776), (0.8654, 5727, 1544), (2.022, 4672, 1040),
        (7.418, 3622, 594.2), (17.25, 2772, 302.6), (33.24, 1941, 101.3), (41.72, 1448, 53.59),
        (50, 1041, 41.55), (50.58, 1027, 41.02), (69.08, 837.9, 33.04), (99.92, 719.2, 31.4),
    ],
    # Infineon IRF100PW219 Rev 2.01, Diagram 11 (VGS=0, f=1 MHz) -- 100 V StrongIRFET2, fugu2.
    # PDF datasheets/infineon/IRF100PW219XKSA1.pdf p.9. Anchors @50V: Coss=1800pF (+0.2%), Crss=80pF (-1.0%), Ciss=12000pF (-1.1%).
    # Qoss(full range)=212.5nC; qoss table validation pass (vint via PDF fallback).
    ("infineon", "IRF100PW219"): [
        (0, 10010, 2405), (0.09456, 10010, 2405), (0.8654, 9357, 2136), (2.022, 7632, 1421),
        (8.959, 5816, 811.3), (13.01, 5253, 639.6), (20.14, 4432, 425.5), (32.28, 3495, 201.6),
        (42.11, 2488, 102.2), (48.27, 1962, 83.36), (49.43, 1833, 80.58), (50, 1803, 79.22),
        (51.55, 1742, 76.57), (60.99, 1600, 63.53), (69.08, 1445, 57.37), (99.92, 1262, 52.7),
    ],
    # Infineon IPP057N15NM6 Rev 1.01, Diagram 11 (VGS=0, f=1 MHz) -- 150 V OptiMOS6, fugu3.
    # PDF datasheets/infineon/IPP057N15NM6AKSA1.pdf p.8. Anchors @75V: Coss=990pF (-0.9%), Crss=15pF (-3.0%), Ciss=3100pF (+0.4%).
    # Qoss(full range)=131.4nC; qoss table validation pass (vint via PDF fallback).
    ("infineon", "IPP057N15NM6"): [
        (0, 3389, 480.9), (0.1418, 3389, 480.9), (1.298, 3276, 457), (5.634, 2718, 331),
        (9.681, 2373, 248), (15.46, 2180, 167.8), (21.24, 1968, 115.5), (28.76, 1871, 71.79),
        (44.95, 1526, 32.87), (64.31, 1183, 17.84), (75, 981.2, 14.55), (76.17, 964.7, 14.3),
        (82.53, 800.3, 13.14), (88.6, 631, 12.28), (95.53, 464.8, 11.47), (101.6, 405.8, 11.09),
        (117.2, 354.2, 10.36), (121, 354.2, 10.18), (125, 336.6, 10.01), (149.9, 298.9, 9.679),
    ],
    # Infineon IPP029N15NM6 Rev ?, Diagram 11 (VGS=0, f=1 MHz) -- 150 V OptiMOS6, fugu3.
    # PDF datasheets/infineon/IPP029N15NM6AKSA1.pdf p.8. Anchors @75V: Coss=2300pF (+1.4%), Crss=25pF (+0.2%), Ciss=7600pF (-0.9%).
    # Qoss(full range)=308.7nC; qoss table validation pass (vint via PDF fallback).
    ("infineon", "IPP029N15NM6"): [
        (0, 8058, 1124), (0.1418, 8058, 1124), (1.009, 7789, 1086), (4.478, 6685, 842.1),
        (9.681, 5546, 569.8), (15.46, 5095, 379.1), (19.8, 4680, 284.1), (28.76, 4373, 154.1),
        (46.97, 3506, 59.55), (60.27, 2959, 35.78), (73.56, 2413, 25.92), (75, 2333, 25.05),
        (83.68, 1808, 21.5), (89.75, 1402, 20.09), (95.53, 1068, 19.09), (99.58, 964.7, 18.45),
        (111.1, 856.6, 17.24), (114.9, 856.6, 16.95), (125, 786.8, 16.38), (149.9, 710.6, 15.57),
    ],
    # IQD020N10NM5CGSC (gate-source-clamp variant) shares the identical digitized
    # curve/anchors with IQD020N10NM5SC above -- same die, separate base MPN.
    ("infineon", "IQD020N10NM5CGSC"): [
        (0, 6103, 1776), (0.09456, 6103, 1776), (0.8654, 5727, 1544), (2.022, 4672, 1040),
        (7.418, 3622, 594.2), (17.25, 2772, 302.6), (33.24, 1941, 101.3), (41.72, 1448, 53.59),
        (50, 1041, 41.55), (50.58, 1027, 41.02), (69.08, 837.9, 33.04), (99.92, 719.2, 31.4),
    ],
}

# Structured conditions and source identity travel with the curve instead of being
# recoverable only by reading the comments above. All currently curated curves are
# Infineon typical capacitance graphs measured at VGS=0 V and f=1 MHz. The diagram
# caption states no temperature, but the datasheet's blanket characteristics condition
# ("at Tj=25 °C, unless otherwise specified" — verified on IPP022N12NM6 Rev 2.0 p.3;
# same template across these Rev 2.0/2.1/2.3 OptiMOS/StrongIRFET sheets) covers it, so
# temperature_c=25.0 is a datasheet-stated condition, not a silent promotion.
COSS_CURVE_SOURCE = {
    ("infineon", "IPP024N08NF2S"): dict(
        datasheet_revision="2.1", source_figure="Diagram 11", source_page=8,
        digitization_method="raster-dark-pixel-column-trace",
        validation_method="overlay + Coss/Crss@40V + Qoss(0-40V) table anchors"),
    ("infineon", "IPP019N08NF2S"): dict(
        datasheet_revision="2.1", source_figure="Diagram 11", source_page=None,
        digitization_method="dcdc-tools-vector-first",
        validation_method="Coss/Crss@40V + Qoss(0-40V) table anchors"),
    ("infineon", "IPP055N08NF2S"): dict(
        datasheet_revision="2.1", source_figure="Diagram 11", source_page=8,
        digitization_method="raster-dark-pixel-column-trace",
        validation_method="Coss/Crss/Ciss@40V + Qoss(0-40V) table anchors"),
    ("infineon", "IPP040N08NF2S"): dict(
        datasheet_revision="2.1 (2022-06-15)", source_figure="Diagram 11",
        source_page=None, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="human overlay + Coss/Crss@40V + Qoss(0-40V) anchors"),
    ("infineon", "IPP026N10NF2S"): dict(
        datasheet_revision="2.1", source_figure="Diagram 11", source_page=None,
        digitization_method="dcdc-tools-vector-first",
        validation_method="Coss/Crss/Ciss@50V + Qoss(0-50V) table anchors"),
    ("infineon", "IPP018N10N5"): dict(
        datasheet_revision="2.3", source_figure="Diagram 11", source_page=None,
        digitization_method="dcdc-tools-vector-first",
        validation_method="Coss/Crss/Ciss@50V + Qoss(0-50V) table anchors"),
    ("infineon", "IPP022N12NM6"): dict(
        datasheet_revision="2.0", source_figure="Diagram 11", source_page=None,
        digitization_method="dcdc-tools-vector-first",
        validation_method="Coss/Crss/Ciss@60V + Qoss(0-60V) table anchors"),
    ("infineon", "IPP050N10NF2S"): dict(
        datasheet_revision="2.1 (2022-06-15)", source_figure="Diagram 11",
        source_page=None, digitization_method="dcdc-tools-vector-first",
        validation_method="Coss/Crss/Ciss@50V + Qoss(0-50V) table anchors"),
    ("infineon", "IPP052N08N5"): dict(
        datasheet_revision="2.0", source_figure="Diagram 11", source_page=9,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@40V anchors <2% + human overlay"),
    ("infineon", "IPA050N10NM5S"): dict(
        datasheet_revision="2.1 (2019-08-28)", source_figure="Diagram 11", source_page=7,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@50V anchors <2% + human overlay"),
    ("infineon", "IPP083N10N5"): dict(
        datasheet_revision="2.1 (2016-10-03)", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@50V anchors <2% + human overlay"),
    ("infineon", "ISC040N10NM7"): dict(
        datasheet_revision="1.0 (2025-10)", source_figure="Diagram 11", source_page=9,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@50V anchors <8% (Crss -4.0%) "
                          "+ Qoss(0-50V) table -0.0% + human overlay"),
    ("infineon", "IPP014N08NM6"): dict(
        datasheet_revision="2.01", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@40V anchors <8% + Qoss table + human overlay"),
    ("infineon", "IPP016N08NF2S"): dict(
        datasheet_revision="2.11", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@40V anchors <8% + Qoss table + human overlay"),
    ("infineon", "IPP082N10NF2S"): dict(
        datasheet_revision="2.11", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@50V anchors <8% + Qoss table + human overlay"),
    ("infineon", "IQD020N10NM5SC"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@50V anchors <8% + Qoss table + human overlay"),
    ("infineon", "IRF100PW219"): dict(
        datasheet_revision="2.01", source_figure="Diagram 11", source_page=9,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@50V anchors <8% + Qoss table + human overlay"),
    ("infineon", "IPP057N15NM6"): dict(
        datasheet_revision="1.01", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@75V anchors <8% + Qoss table + human overlay"),
    ("infineon", "IPP029N15NM6"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@75V anchors <8% + Qoss table + human overlay"),
    ("infineon", "IQD020N10NM5CGSC"): dict(
        datasheet_revision="1.1", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss@50V anchors <8% + Qoss table + human overlay"),
}


COSS_CURVE_META = {
    key: dict(
        frequency_hz=1e6,
        temperature_c=25.0,
        gate_bias_v=0.0,
        curve_registry_id="%s:%s:coss-v1" % key,
        binding_state="registry-curve-and-metadata",
        # Per-entry, from the key + curated revision: a shared literal here silently
        # stamped "Infineon" onto whatever non-Infineon curve gets added next.
        source_document="%s %s datasheet rev %s" % (
            mfr, mpn, COSS_CURVE_SOURCE[key]["datasheet_revision"]),
        provenance="%s datasheet Coss(V) graph; digitized trace with table-anchor validation" % mpn,
        evidence_quality="PASS",
        **COSS_CURVE_SOURCE[key],
    )
    for key in COSS_CURVES
    for mfr, mpn in (key,)
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
    # --- top-30 batch 2026-07-29, same dsdig export gate as the Coss entries above. ---
    # IPP052N08N5 Rev 2.0, 80 V -- Ciss 2900pF@40V (digitized +1.1%).
    ("infineon", "IPP052N08N5"): [
        (0, 3574), (1.142, 3487), (25.12, 2933), (40, 2933), (79.74, 2897),
    ],
    # IPA050N10NM5S Rev 2.1, 100 V -- Ciss 3600pF@50V (digitized -0.9%).
    ("infineon", "IPA050N10NM5S"): [
        (0, 4284), (0.502, 4284), (1.982, 3954), (5.128, 3820), (37.14, 3566),
        (50, 3566), (100.1, 3566),
    ],
    # IPP083N10N5 Rev 2.1, 100 V -- Ciss 2100pF@50V (digitized +0.2%).
    ("infineon", "IPP083N10N5"): [
        (0, 2586), (3.51, 2306), (41.11, 2104), (50, 2104), (79.74, 2104),
    ],
    # ISC040N10NM7 Rev 1.0, 100 V -- Ciss 2800pF@50V (digitized +0.4%).
    ("infineon", "ISC040N10NM7"): [
        (0, 3332), (0.09456, 3332), (0.8654, 3276), (2.022, 3061),
        (13.01, 2860), (50, 2812), (99.92, 2812),
    ],
    # IPP014N08NM6 Rev 2.01 -- Ciss 11000pF@40V (digitized -2.4%).
    ("infineon", "IPP014N08NM6"): [
        (0, 12700), (4.842, 11950), (21.13, 10900), (40, 10740),
        (80.04, 10740),
    ],
    # IPP016N08NF2S Rev 2.11 -- Ciss 12000pF@40V (digitized -0.4%).
    ("infineon", "IPP016N08NF2S"): [
        (0, 14360), (0.6977, 14360), (23.05, 11950), (40, 11950),
        (80.04, 11770),
    ],
    # IPP082N10NF2S Rev 2.11 -- Ciss 2000pF@50V (digitized -0.7%).
    ("infineon", "IPP082N10NF2S"): [
        (0, 2387), (0.6871, 2359), (2.537, 2177), (33.07, 1986),
        (50, 1986), (100.1, 1964),
    ],
    # IQD020N10NM5SC Rev ? -- Ciss 7300pF@50V (digitized -0.1%).
    ("infineon", "IQD020N10NM5SC"): [
        (0, 8942), (0.09456, 8942), (0.8654, 8829), (2.022, 8284),
        (13.01, 7578), (35.17, 7294), (50, 7294), (99.92, 7294),
    ],
    # IRF100PW219 Rev 2.01 -- Ciss 12000pF@50V (digitized -1.1%).
    ("infineon", "IRF100PW219"): [
        (0, 14310), (0.09456, 14310), (1.058, 14060), (3.563, 12920),
        (6.839, 12920), (39.02, 11870), (50, 11870), (99.92, 11870),
    ],
    # IPP057N15NM6 Rev 1.01 -- Ciss 3100pF@75V (digitized +0.4%).
    ("infineon", "IPP057N15NM6"): [
        (0, 3628), (0.1418, 3628), (4.767, 3506), (25, 3167),
        (75, 3113), (149.9, 3113),
    ],
    # IPP029N15NM6 Rev ? -- Ciss 7600pF@75V (digitized -0.9%).
    ("infineon", "IPP029N15NM6"): [
        (0, 8624), (0.1418, 8624), (8.814, 8196), (39.17, 7529),
        (75, 7529), (149.9, 7529),
    ],
    ("infineon", "IQD020N10NM5CGSC"): [
        (0, 8942), (0.09456, 8942), (0.8654, 8829), (2.022, 8284),
        (13.01, 7578), (35.17, 7294), (50, 7294), (99.92, 7294),
    ],
}


# Optional independently validated (Vds_V, Crss_pF) reverse-transfer-capacitance curves.
# Legacy COSS_CURVES triples remain readable through crss_curve_for().
CRSS_CURVES = {
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
    """Return digitized Coss pairs or legacy Coss/Crss triples, or None.

    Case-tolerant on mfr (matching dslib key lookups). Falls back to a base-MPN match so
    an orderable suffix (e.g. IPP024N08NF2S -> ...AKMA1) still resolves the base part's
    curve; longest matching base wins to avoid false positives.

    Returns a COPY: handing out the module-level list let any consumer that mutates a
    specs' curve in place corrupt the registry process-wide."""
    curve = _curve_for(COSS_CURVES, mfr, mpn)
    return list(curve) if curve else None


def coss_curve_meta_for(mfr, mpn):
    """Return structured measurement conditions/provenance for ``coss_curve_for``."""
    meta = _curve_for(COSS_CURVE_META, mfr, mpn)
    return dict(meta) if meta else None


def ciss_curve_for(mfr, mpn):
    """Return the optional digitized [(V, Ciss_pF), ...] curve for a part, or None.
    Returns a copy for the same reason as ``coss_curve_for``."""
    curve = _curve_for(CISS_CURVES, mfr, mpn)
    return list(curve) if curve else None


def crss_curve_for(mfr, mpn):
    """Return independently stored [(V, Crss_pF), ...] pairs, or extract pairs from a
    legacy COSS_CURVES triple. A Coss-only pair curve never becomes Crss evidence."""
    curve = _curve_for(CRSS_CURVES, mfr, mpn)
    if curve:
        return list(curve)
    legacy = _curve_for(COSS_CURVES, mfr, mpn)
    if not legacy or any(len(knot) < 3 for knot in legacy):
        return None
    return [(knot[0], knot[2]) for knot in legacy]
