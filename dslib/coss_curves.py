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
        (0.0396554, 6217.56, 1391.24), (0.705956, 5904.71, 1294.24), (1.9053, 4954.12, 1031.24),
        (2.83812, 4704.84, 911.063), (8.96808, 3672.17, 521.674), (15.4978, 3018.02, 308.107),
        (21.8943, 2237.07, 157.48), (25.2258, 1838.56, 102.067), (25.8921, 1782.48, 92.0544),
        (28.5573, 1511.04, 77.2346), (32.0221, 1203.99, 62.1789), (43.0827, 949.48, 40.7182),
        (53.6102, 838.831, 34.5176), (79.9957, 741.077, 32.1108),
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
        (0.0396554, 8621.79, 1949.24), (0.572696, 8387.63, 1844.8), (1.9053, 6917.25, 1400.78),
        (4.5705, 5945.17, 1078.37), (8.30178, 5180.53, 764.351), (16.1641, 4099.5, 400.202),
        (22.2941, 3028.26, 209.54), (26.1586, 2396.35, 124.184), (29.8899, 1922.59, 96.9264),
        (32.2886, 1629.81, 84.4602), (42.8162, 1325.72, 55.8833), (51.6113, 1187.47, 47.3733),
        (79.9957, 1020.59, 43.021),
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
        (0.0396554, 2611.82, 578.418), (2.83812, 1956.07, 367.227), (8.96808, 1526.73, 210.274),
        (15.7644, 1241.87, 121.652), (22.1608, 901.705, 63.4763), (26.0254, 725.931, 38.6694),
        (29.7567, 584.421, 30.8116), (32.0221, 495.425, 27.2209), (42.2831, 398.849, 18.965),
        (53.6102, 345.167, 16.077), (79.9957, 298.71, 15.1112),
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
        (0.0495652, 6217.56, 1526.73), (0.715866, 5844.05, 1362.81),
        (2.21504, 4704.84, 856.334), (7.04572, 3787.7, 555.015), (27.5345, 2307.45, 167.545),
        (36.363, 1857.64, 93.9751), (41.0271, 1558.58, 66.1528), (46.3575, 1294.24, 54.3685),
        (50.3553, 1097.15, 48.5312), (53.8534, 1052.76, 44.6835), (67.5125, 911.063, 36.3464),
        (99.9947, 764.392, 32.7808),
    ],
    # Infineon IPP018N10N5 Rev 2.3, Diagram 11 (VGS=0, f=1 MHz) -- 100 V OptiMOS5 Fugu2 LS
    # candidate. Same vector-first digitizer run (out/datasheet_charts/ipp018n10n5).
    # Anchors: Coss=1800pF@50V (tool 1808, snapped to spec), Crss=80pF@50V (tool 79.5,
    # snapped to spec), Ciss=12000pF@50V (tool 11895). Qoss(0-50V)=215.6nC sampled vs
    # 213nC Table (+1.2%). NB the dslib DB has Id=NaN for this part, so the recon
    # gate-charge model is unbuildable -- the curve model does not need Id.
    ("infineon", "IPP018N10N5"): [
        (0.0495652, 10031.5, 2463.25), (1.21559, 8741.31, 1896.3), (2.04847, 7617.04, 1420.19),
        (5.71312, 6368.83, 1006.64), (7.54545, 6027.59, 877.168), (19.0391, 4452.51, 459.272),
        (29.0336, 3671.97, 247.181), (37.0293, 2946.02, 146.491), (40.1942, 2638.78, 112.775),
        (46.8572, 2059.59, 86.8181), (49.8555, 1794.7, 78.8419), (55.0194, 1675.31, 69.654),
        (69.0117, 1480.08, 57.4434), (99.9947, 1254.69, 52.1659),
    ],
    # Infineon IPP022N12NM6 Rev 2.0, Diagram 11 (VGS=0, f=1 MHz) -- 120 V OptiMOS6 Fugu2 LS
    # candidate. Same vector-first digitizer run (out/datasheet_charts/ipp022n12nm6).
    # Anchors: Coss=2400pF@60V (tool 2350, snapped to spec), Crss=40pF@60V (tool 40.0, exact),
    # Ciss=8100pF@60V (tool 8056). Qoss(0-60V)=266.9nC sampled vs 267nC Table (-0.0%).
    ("infineon", "IPP022N12NM6"): [
        (0.0594872, 8651.99, 1376.95), (1.05894, 8132.24, 1267.78), (2.05839, 7487.49, 1063.68),
        (5.45652, 6479.73, 772.326), (19.6487, 4954.12, 317.801), (31.0425, 4199.7, 164.12),
        (42.836, 3346.3, 87.4225), (52.4307, 2778.74, 54.3685), (68.222, 1956.07, 29.8718),
        (75.8179, 1591.1, 24.0487), (106.401, 1108.54, 16.4125), (119.994, 959.334, 15.5867),
    ],
    # Infineon IPP039N10N5 Rev 2.0 (2016-11-22), Diagram 11 (VGS=0, f=1 MHz) -- 100 V OptiMOS5.
    # THE PART ACTUALLY FITTED as Fugu2's low side, 2x parallel (Q2 + the D9 footprint),
    # confirmed by Fab 2026-08-11. HS is 2x IPP050N10NF2S, also 100 V.
    #
    # It was ABSENT from this registry, which is very likely why
    # dcdc-tools/loss/examples/fugu2-dualLS.yaml substitutes the 80 V IPP019N08NF2S -- the loss
    # tool cannot use a curve that is not here. That substitution is not cosmetic: every
    # avalanche warning that model raises is against an 80 V rating with BV_min(Tj)=82.2 V, and
    # the deck's ~83 V die peak is a 3 V VIOLATION against 80 V but a ~17 V MARGIN against
    # 100 V. The 5.8 W avalanche line at the 72 V golden point is an artefact of simulating 80 V
    # substitutes for 100 V hardware. NOTE dslib.bv_specs still has NO 100 V part curated (6
    # entries, all N08), so fixing the config alone does not fix the rating -- see fetlib TODO.
    #
    # Digitized with dsdig (datasheet-chart-digitizer), p.8 Diagram 11:
    #   dsdig find datasheets/infineon/IPP039N10N5.pdf --out OUT/IPP039N10N5
    #   dsdig digitize-capacitance OUT/IPP039N10N5/charts.json --out OUT/IPP039N10N5/cap \
    #     --datasheet-root datasheets/infineon
    #   dsdig export-coss-dslib OUT/IPP039N10N5/cap/capacitance_digitization.json --out .../dslib
    # Gates all green: status ok, axis_calibration_trusted, trace_validation pass,
    # shared_collapse_spans [] (no Ciss/Coss snap in the low-V approach, checked at 5x),
    # identity_diagnostics changed=False (ciss_already_flatter), qoss_validation pass, no
    # top-decade clip. OVERLAY HUMAN-VERIFIED by Fab, 2026-08-11.
    #
    # Anchors @50V: Coss=830pF (knot 849.8, +2.4%), Crss=37pF (36.6, -1.1%), Ciss=5400pF (-1.3%).
    # Qoss is anchored 0-50V -- the Table's Vint is 50 V, NOT the 100 V axis end: 98.3 nC
    # digitized vs 98.0 nC Table (+0.3%), and re-integrating the LANDED KNOTS gives 99.4 nC
    # (+1.5%), against +1.7% for the already-verified IPA050N10NM5S and IPP083N10N5 entries.
    # Integrating these knots to 100 V instead gives 132 nC and looks like a 35% error -- it is
    # not, it is the wrong upper limit, and EVERY entry in this file shows the same offset that
    # way. Co_er 1511 pF, Co_tr 1966 pF (Co_tr x 50 V = 98.3 nC, the same identity).
    # Knots are the dsdig ADAPTIVE set, dense where the curve is steep; uniform 5 V sampling
    # misrepresents the low-V knee badly (it over-integrated Qoss by 35% in a first attempt).
    ("infineon", "IPP039N10N5"): [
        (0, 4696, 1132), (0.6871, 4486, 1046), (1.4272, 4187, 909.9), (2.9075, 3566, 658.1),
        (3.8327, 3179, 532.1), (7.9034, 2770, 395.2), (16.230, 2228, 244.9),
        (26.037, 1791, 137.1), (32.513, 1561, 91.3), (39.729, 1227, 53.5),
        (50.0, 849.8, 36.6), (51.757, 802.4, 35.2), (55.642, 757.7, 32.1),
        (77.106, 623.4, 25.8), (100.05, 562.3, 24.5),
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
        (0.0495652, 3177.92, 772.326), (0.715866, 3018.02, 689.404),
        (2.21504, 2404.74, 428.744), (6.21285, 1996.88, 292.604), (27.5345, 1179.38, 83.8854),
        (31.6989, 1097.15, 64.8007), (36.363, 939.726, 47.5392), (40.8605, 804.892, 34.163),
        (49.689, 566.595, 25.5857), (53.8534, 532.559, 23.0757), (64.5142, 470.497, 19.5617),
        (99.9947, 382.711, 17.1045),
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

    # ---- landed 2026-07-29 from the fugu2 C(V) review packets: human GREEN
    # verdicts (newest export per review id) that ALSO pass the dsdig export
    # gate (spec-table Coss/Crss/Ciss anchors + Qoss integral). Greens that the
    # gate could not validate are deliberately NOT here -- see the worklist.
    # infineon BSC027N10NS5ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-head), export gate anchors: Ciss 6300 pF@50V (-0.7%), Coss 970 pF@50V (-0.0%), Crss 43 pF@50V (-1.1%).
    ("infineon", "BSC027N10NS5ATMA1"): [
        (0, 5389, 1299), (0.87, 4917, 1094), (1.98, 4092, 766.4),
        (7.9, 3216, 457.4), (18.27, 2470, 254.8), (32.14, 1854, 107.8),
        (37.88, 1543, 72.12), (43.8, 1241, 51.71), (49.72, 975.3, 43.03),
        (52.5, 920.9, 40.17), (71.19, 757.7, 30.85), (100.05, 660.2, 28.47),
    ],
    # infineon BSC034N10LS5ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-color), export gate anchors: Ciss 5000 pF@50V (-1.7%), Coss 770 pF@50V (+0.1%), Crss 34 pF@50V (-0.5%).
    ("infineon", "BSC034N10LS5ATMA1"): [
        (0, 4284, 1033), (0.69, 4046, 920.9), (1.98, 3291, 609.3),
        (10.12, 2414, 313.2), (18.27, 1964, 200.2), (31.59, 1491, 88.66),
        (37.32, 1241, 60.02), (43.8, 986.5, 41.1), (50, 770.8, 33.82),
        (50.46, 757.7, 33.43), (52.5, 732.1, 31.93), (75.07, 582, 24.25),
        (100.05, 524.9, 22.9),
    ],
    # infineon BSC0802LSATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-color), export gate anchors: Ciss 5000 pF@50V (-1.7%), Coss 770 pF@50V (+0.1%), Crss 34 pF@50V (-0.5%).
    ("infineon", "BSC0802LSATMA1"): [
        (0, 4284, 1033), (0.69, 4046, 920.9), (1.98, 3291, 609.3),
        (10.12, 2414, 313.2), (18.27, 1964, 200.2), (31.59, 1491, 88.66),
        (37.32, 1241, 60.02), (43.8, 986.5, 41.1), (50, 770.8, 33.82),
        (50.46, 757.7, 33.43), (52.5, 732.1, 31.93), (75.07, 582, 24.25),
        (100.05, 524.9, 22.9),
    ],
    # infineon IPA030N10NF2SXKSA1, Diagram 11 p.7 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28-refresh), export gate anchors: Ciss 7300 pF@50V (-0.5%), Coss 1100 pF@50V (+1.2%), Crss 49 pF@50V (-0.4%).
    ("infineon", "IPA030N10NF2SXKSA1"): [
        (0, 6185, 1508), (0.69, 5840, 1345), (1.98, 4750, 889.7),
        (8.64, 3649, 507.1), (18.27, 2835, 295.7), (32.14, 2128, 125.1),
        (41.76, 1543, 63.57), (50.09, 1106, 48.82), (54.53, 1033, 44.03),
        (75.07, 849.8, 34.6), (100.05, 766.4, 32.68),
    ],
    # infineon IPP023N10N5AKSA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28-refresh), export gate anchors: Ciss 12000 pF@50V (-0.4%), Coss 1810 pF@50V (-0.9%), Crss 80 pF@50V (-1.1%).
    ("infineon", "IPP023N10N5AKSA1"): [
        (0, 10100, 2435), (0.7, 9499, 2121), (2.18, 7552, 1404),
        (7.21, 6096, 900.7), (16.09, 4846, 535.4), (19.65, 4354, 438.9),
        (22.31, 4223, 376.6), (32.08, 3461, 204.2), (36.08, 3062, 152.7),
        (43.03, 2398, 99.51), (50, 1793, 79.11), (50.58, 1766, 77.91),
        (63.02, 1562, 61.93), (67.01, 1470, 59.16), (79.74, 1361, 54.8),
    ],
    # infineon IPP030N10N5AKSA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28-refresh), export gate anchors: Ciss 7920 pF@50V (-1.8%), Coss 1210 pF@50V (+1.4%), Crss 53 pF@50V (-0.2%).
    ("infineon", "IPP030N10N5AKSA1"): [
        (0, 6780, 1653), (0.55, 6626, 1561), (1.59, 5908, 1241),
        (3.07, 5031, 900), (3.95, 4537, 740.5), (8.54, 3909, 549.5),
        (18.16, 3072, 316.8), (32.08, 2306, 134), (41.55, 1672, 70.48),
        (50, 1227, 52.87), (51.92, 1158, 49.96), (79.89, 900, 36.65),
    ],
    # infineon IPP030N10NF2SAKMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28-refresh), export gate anchors: Ciss 6000 pF@50V (+0.4%), Coss 930 pF@50V (-0.2%), Crss 41 pF@50V (+0.1%).
    ("infineon", "IPP030N10NF2SAKMA1"): [
        (0, 5107, 1243), (0.09, 5107, 1243), (1.06, 4672, 1027),
        (2.02, 3959, 737.7), (7.03, 3189, 460.6), (18.21, 2380, 243.8),
        (32.28, 1776, 103.9), (38.83, 1430, 64.87), (50, 928.1, 41.02),
        (50.39, 916, 40.5), (52.51, 881.7, 38.49), (71.01, 728.4, 29.84),
        (99.92, 633.2, 27.3),
    ],
    # infineon IPP038N15NM6AKSA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28-refresh), export gate anchors: Ciss 4900 pF@75V (+0.3%), Coss 1500 pF@75V (+1.7%), Crss 19 pF@75V (+0.6%).
    ("infineon", "IPP038N15NM6AKSA1"): [
        (0, 5306, 747.2), (0.14, 5306, 747.2), (1.59, 5043, 692.2),
        (5.06, 4328, 536.7), (30.2, 2844, 98.73), (41.48, 2472, 54.28),
        (57.38, 2017, 28.72), (70.38, 1687, 20.89), (75, 1525, 19.11),
        (75.59, 1524, 18.63), (81.66, 1275, 17.04), (85.13, 1123, 16.41),
        (96.4, 692.2, 14.63), (99.58, 641.3, 14.26), (125.02, 523.2, 12.72),
        (149.88, 472.5, 12.09),
    ],
    # infineon IPP039N10N5AKSA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28-refresh), export gate anchors: Ciss 5400 pF@50V (-1.3%), Coss 830 pF@50V (+2.4%), Crss 37 pF@50V (-0.9%).
    ("infineon", "IPP039N10N5AKSA1"): [
        (0, 4696, 1132), (0.69, 4486, 1045), (1.43, 4187, 889.7),
        (2.91, 3566, 645.3), (3.83, 3179, 537.1), (7.9, 2770, 389.5),
        (16.23, 2228, 243.3), (26.04, 1791, 137.1), (32.51, 1561, 90.72),
        (39.73, 1227, 52.91), (50, 849.8, 36.65), (51.76, 802.4, 35),
        (55.64, 757.7, 32.3), (77.11, 623.4, 25.68), (100.05, 562.3, 24.53),
    ],
    # infineon IPT020N10N5ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-head), export gate anchors: Ciss 8700 pF@50V (-1.9%), Coss 1300 pF@50V (+0.8%), Crss 58 pF@50V (-1.1%).
    ("infineon", "IPT020N10N5ATMA1"): [
        (0, 7213, 1766), (0.69, 6785, 1539), (1.8, 5647, 1116),
        (8.27, 4354, 614.4), (17.71, 3409, 359.7), (25.48, 2881, 223.9),
        (32.7, 2472, 143.7), (40.1, 1935, 81.57), (46.21, 1539, 64.84),
        (50.09, 1300, 57.37), (75.07, 1002, 40.36), (100.05, 914.6, 38.55),
    ],
    # infineon IPT023N10NM5LF2ATMA1, Diagram 12 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-head), export gate anchors: Ciss 9100 pF@50V (-0.7%), Coss 1300 pF@50V (-1.4%), Crss 26 pF@50V (+0.9%).
    ("infineon", "IPT023N10NM5LF2ATMA1"): [
        (0, 6433, 1218), (0.05, 6433, 1218), (1.21, 5810, 944.2),
        (1.98, 5072, 719.6), (6.99, 4280, 470.7), (16.24, 3374, 246.9),
        (27.42, 2660, 100.4), (32.24, 2403, 62.39), (36.28, 2133, 49.19),
        (42.26, 1740, 36.24), (46.11, 1519, 30.58), (50, 1282, 26.24),
        (50.54, 1260, 25.8), (75.02, 960.4, 15.77), (78.87, 960.4, 15.5),
        (83.11, 912.7, 14.98), (100.07, 852.8, 14.48),
    ],
    # infineon IPT026N10N5ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-color), export gate anchors: Ciss 6800 pF@50V (-0.3%), Coss 1000 pF@50V (+3.9%), Crss 46 pF@50V (+0.2%).
    ("infineon", "IPT026N10N5ATMA1"): [
        (0, 5774, 1408), (0.69, 5452, 1255), (1.98, 4434, 830.5),
        (8.64, 3406, 473.4), (16.23, 2802, 306.1), (32.14, 1986, 116.8),
        (41.76, 1441, 60.02), (50, 1039, 46.1), (50.65, 1021, 45.57),
        (77.11, 784.2, 32.3), (100.05, 715.5, 30.5),
    ],
    # infineon IPTG018N10NM5ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-color), export gate anchors: Ciss 8700 pF@50V (-1.9%), Coss 1300 pF@50V (+0.8%), Crss 58 pF@50V (-1.1%).
    ("infineon", "IPTG018N10NM5ATMA1"): [
        (0, 7213, 1766), (0.69, 6785, 1539), (1.8, 5647, 1116),
        (8.27, 4354, 614.4), (17.71, 3409, 359.7), (25.48, 2881, 223.9),
        (32.7, 2472, 143.7), (40.1, 1935, 81.57), (46.21, 1539, 64.84),
        (50.09, 1300, 57.37), (75.07, 1002, 40.36), (100.05, 914.6, 38.55),
    ],
    # infineon IPTG025N10NM5ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28), export gate anchors: Ciss 6800 pF@50V (-0.3%), Coss 1000 pF@50V (+3.9%), Crss 46 pF@50V (+0.2%).
    ("infineon", "IPTG025N10NM5ATMA1"): [
        (0, 5774, 1408), (0.69, 5452, 1255), (1.98, 4434, 830.5),
        (8.64, 3406, 473.4), (16.23, 2802, 306.1), (32.14, 1986, 116.8),
        (41.76, 1441, 60.02), (50, 1039, 46.1), (50.65, 1021, 45.57),
        (77.11, 784.2, 32.3), (100.05, 715.5, 30.5),
    ],
    # infineon IQD020N10NM5ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28), export gate anchors: Ciss 7300 pF@50V (-0.5%), Coss 1000 pF@50V (+5.1%), Crss 42 pF@50V (-1.0%).
    ("infineon", "IQD020N10NM5ATMA1"): [
        (0, 6185, 1791), (0.69, 5774, 1579), (1.98, 4643, 1045),
        (7.9, 3566, 568.8), (16.23, 2835, 324.2), (31.59, 2032, 112.8),
        (37.32, 1692, 74.64), (43.8, 1345, 49.96), (50, 1051, 41.58),
        (50.46, 1033, 41.1), (52.5, 997.9, 39.71), (73.04, 811.7, 32.3),
        (100.05, 723.7, 31.21),
    ],
    # infineon IQD020N10NM5CGATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28), export gate anchors: Ciss 7300 pF@50V (-0.5%), Coss 1000 pF@50V (+5.1%), Crss 42 pF@50V (-1.0%).
    ("infineon", "IQD020N10NM5CGATMA1"): [
        (0, 6185, 1791), (0.69, 5774, 1579), (1.98, 4643, 1045),
        (7.9, 3566, 568.8), (16.23, 2835, 324.2), (31.59, 2032, 112.8),
        (37.32, 1692, 74.64), (43.8, 1345, 49.96), (50, 1051, 41.58),
        (50.46, 1033, 41.1), (52.5, 997.9, 39.71), (73.04, 811.7, 32.3),
        (100.05, 723.7, 31.21),
    ],
    # infineon IQD020N10NM5CGSCATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28), export gate anchors: Ciss 7300 pF@50V (-0.1%), Coss 1000 pF@50V (+4.1%), Crss 42 pF@50V (-1.1%).
    ("infineon", "IQD020N10NM5CGSCATMA1"): [
        (0, 6103, 1776), (0.09, 6103, 1776), (0.87, 5727, 1544),
        (2.02, 4672, 1040), (7.42, 3622, 594.2), (17.25, 2772, 302.6),
        (33.24, 1941, 101.3), (41.72, 1448, 53.59), (50, 1041, 41.55),
        (50.58, 1027, 41.02), (69.08, 837.9, 33.04), (99.92, 719.2, 31.4),
    ],
    # infineon IQD020N10NM5SCATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-28), export gate anchors: Ciss 7300 pF@50V (-0.1%), Coss 1000 pF@50V (+4.1%), Crss 42 pF@50V (-1.1%).
    ("infineon", "IQD020N10NM5SCATMA1"): [
        (0, 6103, 1776), (0.09, 6103, 1776), (0.87, 5727, 1544),
        (2.02, 4672, 1040), (7.42, 3622, 594.2), (17.25, 2772, 302.6),
        (33.24, 1941, 101.3), (41.72, 1448, 53.59), (50, 1041, 41.55),
        (50.58, 1027, 41.02), (69.08, 837.9, 33.04), (99.92, 719.2, 31.4),
    ],
    # infineon ISC022N10NM6ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-color), export gate anchors: Ciss 5400 pF@50V (-0.9%), Coss 1200 pF@50V (+1.1%), Crss 19 pF@50V (-2.7%).
    ("infineon", "ISC022N10NM6ATMA1"): [
        (0, 5433, 455.8), (1.24, 5433, 455.8), (1.43, 5270, 442.1),
        (3.46, 4957, 379.4), (5.87, 4522, 315.8), (9.38, 4001, 247.2),
        (15.49, 3230, 161.1), (24, 2452, 90.07), (32.14, 1920, 51.93),
        (50, 1213, 18.49), (71.74, 815.2, 8.41), (85.25, 699.6, 6.79),
        (98.94, 638.2, 6.1),
    ],
    # infineon ISC027N10NM6ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-color), export gate anchors: Ciss 4300 pF@50V (-1.1%), Coss 960 pF@50V (-0.3%), Crss 16 pF@50V (-1.6%).
    ("infineon", "ISC027N10NM6ATMA1"): [
        (0, 4386, 368), (1.24, 4386, 368), (1.43, 4386, 356.9),
        (1.8, 4126, 340.9), (3.83, 3881, 297), (8.09, 3330, 218.7),
        (15.86, 2529, 126.1), (23.45, 1980, 74.96), (29.37, 1648, 50.36),
        (41.02, 1195, 24.92), (50, 957.1, 15.75), (74.89, 619, 7.33),
        (98.94, 499.6, 5.92),
    ],
    # infineon ISC030N10NM6ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-color), export gate anchors: Ciss 4000 pF@50V (+0.0%), Coss 900 pF@50V (-0.7%), Crss 15 pF@50V (+2.6%).
    ("infineon", "ISC030N10NM6ATMA1"): [
        (0, 4319, 442.1), (1.06, 4126, 379.4), (4.2, 3595, 271),
        (8.27, 3085, 202.6), (12.16, 2688, 153.9), (18.64, 2170, 98.73),
        (19.75, 2041, 91.46), (26.78, 1673, 57.8), (41.58, 1107, 23.08),
        (50, 893.6, 15.39), (51.02, 866.6, 14.59), (63.41, 699.6, 9.08),
        (66.56, 648, 8.41), (70.44, 628.5, 7.67), (75.63, 573.4, 7),
        (87.1, 507.3, 6.1), (100.05, 462.9, 5.74),
    ],
    # infineon ISC040N10NM7ATMA1, Diagram 11 p.9 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet coss-review-top50-2026-07-29-color), export gate anchors: Ciss 2800 pF@50V (+0.4%), Coss 1170 pF@50V (-0.6%), Crss 13 pF@50V (-4.0%).
    ("infineon", "ISC040N10NM7ATMA1"): [
        (0, 3061, 550.8), (0.09, 3061, 550.8), (1.06, 2959, 434.3),
        (2.02, 2718, 293.9), (7.03, 2413, 176.6), (15.51, 2036, 82.23),
        (28.42, 1661, 29.69), (37.48, 1450, 18.14), (50, 1163, 12.49),
        (53.48, 1105, 11.87), (71.4, 786.8, 10.54), (78.91, 675.3, 10.36),
        (83.54, 599.6, 10.36), (99.92, 550.8, 10.36),
    ],

    # ---- landed 2026-07-29 (second pass): greens that became VALIDATABLE once the
    # spec-table anchors came from fetlib instead of the digitizer's own scraper.
    # Mostly EPC, whose printed "COSS" the scraper never matched.
    # epc EPC2022, Diagram 902 p.3 (VGS=0, f=1 MHz). dsdig adaptive-knot vector
    # trace, human overlay GREEN; anchors served BY FETLIB (dslib.coss_anchors)
    # -- the digitizer's own table scraper reads nothing on this vendor. Ciss 1400 pF@50V (+4.7%), Coss 840 pF@50V (+3.7%), Crss 7 pF@50V (-7.8%)
    ("epc", "EPC2022"): [
        (0, 2620, 295.5), (1.5, 2620, 262), (3.89, 2518, 194.1),
        (9.96, 2233, 75.73), (12.72, 2061, 47.78), (13.08, 1980, 45.91),
        (13.82, 1980, 40.71), (14.19, 1902, 39.11), (15.66, 1828, 32.01),
        (18.97, 1496, 20.61), (19.52, 1496, 19.8), (19.7, 1437, 19.02),
        (20.99, 1381, 16.87), (21.36, 1327, 16.21), (21.91, 1327, 15.57),
        (23.01, 1224, 14.37), (23.75, 1224, 13.81), (24.11, 1176, 13.27),
        (24.85, 1176, 12.74), (25.22, 1130, 12.24), (30.55, 1002, 9.63),
        (50, 871.2, 6.45), (63.09, 820.4, 5.61), (87.36, 727.5, 4.88),
        (100.78, 713.1, 4.68),
    ],
    # epc EPC2071, Diagram 902 p.3 (VGS=0, f=1 MHz). dsdig adaptive-knot vector
    # trace, human overlay GREEN; anchors served BY FETLIB (dslib.coss_anchors)
    # -- the digitizer's own table scraper reads nothing on this vendor. Ciss 2664 pF@50V (-7.7%), Coss 878 pF@50V (-2.8%), Crss 5.4 pF@50V (-10.7%)
    ("epc", "EPC2071"): [
        (0, 2867, 186.8), (0.02, 2867, 186.8), (2.39, 2805, 171),
        (6.4, 2626, 92.32), (8.41, 2352, 50.93), (9.32, 1972, 39.97),
        (9.87, 1728, 34.26), (10.6, 1548, 28.73), (11.69, 1417, 22.06),
        (23.91, 1188, 10.9), (34.13, 1018, 7.5), (36.87, 953.3, 6.86),
        (41.79, 932.5, 5.88), (43.98, 892.3, 5.51), (49.27, 872.9, 4.83),
        (50, 853.9, 4.83), (51.1, 835.3, 4.72), (54.02, 835.3, 4.52),
        (54.2, 817.1, 4.52), (63.5, 817.1, 4.23), (63.68, 799.3, 4.23),
        (69.52, 799.3, 4.04), (69.7, 781.9, 4.04), (99.99, 781.9, 3.96),
    ],
    # epc EPC2088, Diagram 902 p.3 (VGS=0, f=1 MHz). dsdig adaptive-knot vector
    # trace, human overlay GREEN; anchors served BY FETLIB (dslib.coss_anchors)
    # -- the digitizer's own table scraper reads nothing on this vendor. Ciss 1864 pF@50V (-9.4%), Coss 557 pF@50V (+2.6%), Crss 3.6 pF@50V (-10.1%)
    ("epc", "EPC2088"): [
        (0, 1886, 145.1), (3.05, 1845, 127.1), (7.81, 1689, 65.46),
        (9.09, 1616, 45.96), (10.37, 1479, 33.72), (12.93, 1062, 20.73),
        (14.21, 971.8, 17.76), (15.13, 971.8, 15.9), (17.14, 909.4, 14.24),
        (24.28, 851, 11.41), (27.02, 779, 9.78), (28.85, 682.2, 8.19),
        (30.13, 652.7, 6.86), (36.36, 624.4, 3.86), (36.54, 610.8, 3.78),
        (40.2, 610.8, 3.38), (40.38, 597.4, 3.38), (50, 571.6, 3.24),
        (62.34, 559.1, 3.24), (62.53, 546.9, 3.24), (99.86, 534.9, 3.24),
    ],
    # epc EPC2092, Diagram 902 p.3 (VGS=0, f=1 MHz). dsdig adaptive-knot vector
    # trace, human overlay GREEN; anchors served BY FETLIB (dslib.coss_anchors)
    # -- the digitizer's own table scraper reads nothing on this vendor. Ciss 1686 pF@50V (-3.6%), Coss 568 pF@50V (+1.0%), Crss 4.3 pF@50V (-4.3%)
    ("epc", "EPC2092"): [
        (0, 1662, 123), (2.93, 1589, 98.04), (5.93, 1451, 69.8),
        (12.29, 1131, 25.77), (26.14, 719.2, 7.25), (32.87, 687.3, 6.05),
        (37.55, 642.2, 5.4), (40.17, 642.2, 5.05), (40.36, 627.8, 5.05),
        (44.66, 627.8, 4.61), (48.4, 573.4, 4.31), (50, 573.4, 4.12),
        (52.52, 560.6, 3.93), (56.82, 523.8, 3.59), (100.23, 478.4, 1.78),
    ],
    # epc EPC2218, Diagram 902 p.3 (VGS=0, f=1 MHz). dsdig adaptive-knot vector
    # trace, human overlay GREEN; anchors served BY FETLIB (dslib.coss_anchors)
    # -- the digitizer's own table scraper reads nothing on this vendor. Ciss 1189 pF@50V (-0.3%), Coss 562 pF@50V (+1.7%), Crss 4.3 pF@50V (+4.9%)
    # Re-thinned 2026-08-15: the previous 21 knots left NO knot between 62 and 99 V, so the
    # interpolant bulged +13.4% over a flat Crss tail, and its repeated Coss values (1447,
    # 1384, 682.2 each held across a span where the ink still moves) were pixel-row
    # quantisation. 14 knots chosen jointly against the d902 ink: Crss 13.40% -> 2.89%,
    # Coss 3.48% -> 2.62%. Anchors held (Coss +0.8%, Crss +3.5%, both inside the documented
    # residual above).
    ("epc", "EPC2218"): [
        (0, 1570, 153),
        (0.046839, 1570, 153), (5.31751, 1479, 104.8), (7.62342, 1421, 79.35),
        (12.7294, 1261, 39.54), (17.1765, 973.9, 22.65), (22.9413, 847.3, 13.77),
        (27.8826, 767, 10.85), (31.6708, 708.3, 9.435), (33.9768, 680.7, 7.285),
        (36.7768, 641.2, 5.97), (44.024, 592.2, 5.091), (49.1299, 569.1, 4.518),
        (65.9302, 536.1, 3.63), (99.8601, 515.2, 3.221),
    ],
    # epc EPC2302, Diagram 905 p.3 (VGS=0, f=1 MHz). dsdig adaptive-knot vector
    # trace, human overlay GREEN; anchors served BY FETLIB (dslib.coss_anchors)
    # -- the digitizer's own table scraper reads nothing on this vendor. Ciss 3200 pF@50V (+3.0%), Coss 1000 pF@50V (+0.5%), Crss 7 pF@50V (-0.3%)
    ("epc", "EPC2302"): [
        (0, 3530, 173), (6.94, 3450, 102.3), (8.61, 3149, 74.31),
        (9.73, 2745, 56.49), (10.66, 2394, 44.95), (11.03, 2185, 41.03),
        (12.52, 1820, 29.12), (13.82, 1661, 23.71), (14.94, 1661, 20.21),
        (24.24, 1383, 12.8), (32.61, 1126, 10.42), (42.83, 1028, 8.1),
        (43.02, 1005, 8.1), (50, 1005, 6.98), (100.3, 982.1, 5.01),
    ],
    # infineon IPA030N10N3GXKSA1, Diagram 11 p.6 (VGS=0, f=1 MHz). dsdig adaptive-knot vector
    # trace, human overlay GREEN; anchors served BY FETLIB (dslib.coss_anchors)
    # -- the digitizer's own table scraper reads nothing on this vendor. Ciss 11100 pF@50V (+0.8%), Coss 1940 pF@50V (+1.1%), Crss 69 pF@50V (+0.8%)
    ("infineon", "IPA030N10N3GXKSA1"): [
        (0, 11010, 2492), (0.03, 11010, 2492), (0.73, 10170, 2025),
        (1.09, 9091, 1448), (2.15, 7749, 896.4), (6.05, 6711, 683.2),
        (9.23, 6001, 564), (14.01, 5115, 416.3), (20.92, 4090, 274.8),
        (28, 3323, 184.3), (41.11, 2376, 97.27), (50, 1961, 69.54),
        (63.77, 1543, 49.72), (80.06, 1294, 40.4),
    ],
    # infineon ISC0802NLSATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector
    # trace, human overlay GREEN; anchors served BY FETLIB (dslib.coss_anchors)
    # -- the digitizer's own table scraper reads nothing on this vendor. Ciss 3900 pF@50V (+0.2%), Coss 610 pF@50V (+0.4%), Crss 27 pF@50V (+0.7%)
    ("infineon", "ISC0802NLSATMA1"): [
        (0, 3406, 830.5), (0.69, 3216, 732.1), (1.98, 2616, 484.4),
        (8.64, 2009, 272.9), (16.23, 1653, 178.5), (32.14, 1172, 68.1),
        (37.88, 975.3, 46.1), (43.8, 784.2, 33.05), (49.72, 616.3, 27.51),
        (52.5, 582, 25.68), (77.11, 457.4, 19.28), (100.05, 417.2, 18.41),
    ],

    # ---- landed 2026-07-29 (third pass): packet fugu2-100v-LS2p-gan-coss-scalar-top50-001,
    # the first packet built by `main.py --coss-review`. 23 of its 25 cards are human
    # GREEN; these are the 7 whose export gate also PASSES. The other 16 stay OUT --
    # 6 EPC parts miss the Crss table anchor by 20-100%% (the reviewer flagged the
    # dashed line the Crss trace rides), 3 IAUTN parts have all_traces_left_edge_gap,
    # TPH2R70AR5 collapses Ciss/Coss, IXFN106N20 has no Qoss row. A human GREEN says
    # the OVERLAY looks right; it does not make an unvalidatable trace servable.
    # epc EPC2090, Diagram 902 p.3 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001,
    # exported 2026-07-29). Export gate on fetlib-served anchors: Ciss 1046 pF@50V (-3.4%), Coss 364 pF@50V (-3.1%), Crss 2.9 pF@50V (-5.4%).
    ("epc", "EPC2090"): [
        (0, 923.6, 73.65), (3.302, 903.2, 55.05), (7.333, 825.8, 32.9),
        (11.18, 706.1, 19.23), (11.55, 675.2, 18.39), (13.75, 617.4, 13.44),
        (15.58, 552, 10.99), (18.88, 493.6, 7.681), (48.19, 360.8, 2.869),
        (50, 352.8, 2.744), (54.42, 329.9, 2.399), (61.38, 322.6, 1.918),
        (61.57, 315.5, 1.918), (67.8, 308.5, 1.603), (67.98, 301.6, 1.603),
        (85.39, 288.4, 1.253), (85.57, 282.1, 1.226), (99.86, 282.1, 1.172),
    ],
    # epc EPC7018, Diagram 902 p.3 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001,
    # exported 2026-07-29). Export gate on fetlib-served anchors: Ciss 1828 pF@50V (-10.7%), Coss 1025 pF@50V (+6.6%), Crss 5.8 pF@50V (+4.3%).
    ("epc", "EPC7018"): [
        (0, 2787, 224.2), (4.052, 2726, 167.8), (9.398, 2493, 85.95), (11.61, 2280, 61.52),
        (14.01, 1908, 43.05), (17.33, 1460, 27.56), (20.64, 1306, 18.87),
        (49.4, 1117, 6.186), (49.59, 1092, 6.186), (50, 1092, 6.05), (61.39, 1045, 5.175),
        (61.57, 1022, 5.175), (73.74, 977.1, 4.629), (73.92, 955.6, 4.629),
        (78.35, 955.6, 4.527), (78.53, 934.5, 4.527), (83.14, 934.5, 4.427),
        (83.33, 913.9, 4.427), (100.1, 854.7, 4.33),
    ],
    # infineon IPF019N12NM6ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001,
    # exported 2026-07-29). Export gate on fetlib-served anchors: Ciss 8100 pF@60V (-0.9%), Coss 2400 pF@60V (-1.6%), Crss 40 pF@60V (-0.6%).
    ("infineon", "IPF019N12NM6ATMA1"): [
        (0, 8535, 1382), (1.047, 8152, 1223), (2.157, 7324, 1050), (6.153, 6382, 727),
        (16.37, 5231, 382.4), (30.36, 4288, 170), (44.12, 3306, 80.33),
        (56.11, 2588, 45.61), (60, 2361, 39.74), (66.33, 2057, 32.08),
        (77.65, 1539, 23.27), (96.52, 1242, 17.67), (120.1, 957.5, 15.63),
    ],
    # infineon IPT017N12NM6ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001,
    # exported 2026-07-29). Export gate on fetlib-served anchors: Ciss 8100 pF@60V (-0.9%), Coss 2400 pF@60V (-1.6%), Crss 40 pF@60V (-0.6%).
    ("infineon", "IPT017N12NM6ATMA1"): [
        (0, 8405, 1382), (1.269, 7906, 1186), (6.376, 6190, 716), (10.15, 5822, 560.6),
        (18.37, 5073, 338.4), (30.36, 4288, 167.4), (40.13, 3569, 99.51),
        (50.12, 2925, 60.07), (60, 2361, 39.74), (65.66, 2089, 32.58), (72.32, 1766, 26.7),
        (75.87, 1562, 23.99), (92.53, 1300, 18.22), (95.64, 1223, 17.67),
        (100.5, 1186, 16.87), (120.1, 957.5, 15.63),
    ],
    # infineon IPTC017N12NM6ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001,
    # exported 2026-07-29). Export gate on fetlib-served anchors: Ciss 8100 pF@60V (-0.9%), Coss 2400 pF@60V (-1.6%), Crss 40 pF@60V (-0.6%).
    ("infineon", "IPTC017N12NM6ATMA1"): [
        (0, 8405, 1382), (1.269, 7906, 1186), (5.709, 6285, 749.6), (10.15, 5822, 560.6),
        (18.37, 5073, 338.4), (30.36, 4288, 167.4), (40.13, 3569, 98),
        (50.12, 2925, 60.07), (60, 2361, 39.74), (65.66, 2089, 32.58), (72.32, 1766, 26.7),
        (75.87, 1562, 23.99), (88.53, 1361, 19.36), (91.64, 1280, 18.22),
        (100.5, 1186, 16.87), (120.1, 957.5, 15.63),
    ],
    # infineon IPTG017N12NM6ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001,
    # exported 2026-07-29). Export gate on fetlib-served anchors: Ciss 8100 pF@60V (-0.6%), Coss 2400 pF@60V (-1.7%), Crss 40 pF@60V (-0.2%).
    ("infineon", "IPTG017N12NM6ATMA1"): [
        (0, 8528, 1360), (1.491, 7780, 1132), (10.15, 5840, 562.3), (16.81, 5207, 376.3),
        (30.13, 4284, 172.5), (40.13, 3566, 99.44), (52.12, 2802, 54.76),
        (60, 2359, 39.94), (64.33, 2152, 33.82), (76.76, 1561, 23.7), (120.1, 964.1, 15.5),
    ],
    # infineon IPTG020N13NM6ATMA1, Diagram 11 p.8 (VGS=0, f=1 MHz). dsdig adaptive-knot vector trace,
    # human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001,
    # exported 2026-07-29). Export gate on fetlib-served anchors: Ciss 11000 pF@68V (-2.7%), Coss 2200 pF@68V (-2.4%), Crss 28 pF@68V (-2.0%).
    ("infineon", "IPTG020N13NM6ATMA1"): [
        (0, 7441, 1674), (0.9619, 7161, 1383), (3.034, 6385, 841.2), (10.55, 5693, 492.4),
        (23.5, 4526, 229.2), (39.56, 3463, 95.1), (42.41, 3208, 81.61),
        (46.55, 3087, 67.4), (49.66, 2860, 57.84), (53.55, 2753, 47.77),
        (56.4, 2550, 42.6), (60.54, 2454, 35.86), (63.65, 2274, 31.97), (68, 2147, 27.44),
        (76.34, 1914, 21.4), (78.42, 1807, 20.21), (90.33, 1551, 16.06),
        (99.66, 1331, 14.32), (110.5, 1187, 13.27), (113.1, 1121, 13.02),
        (117, 1099, 13.02), (123.2, 999.1, 12.53), (134.1, 908, 12.29),
    ],

    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 800 pF@50V (-1.4%), Crss 14 pF@50V (+5.8%), Ciss 1270 pF@50V (-1.7%).
    ('epc', 'EPC2032'): [
        (0, 2137, 222.6),
        (3.621674559, 2054, 148),
        (8.082787099, 1897, 57.99),
        (12.54389964, 1751, 27.74),
        (15.70385436, 1617, 21.84),
        (19.23556845, 1435, 19.77),
        (28.52955291, 1002, 17.89),
        (34.29182328, 889.4, 17.2),
        (50, 789.1, 14.81),
        (100.2791129, 633.8, 8.392),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 2200 pF@68V (-2.4%), Crss 28 pF@68V (-2.0%), Ciss 11000 pF@68V (-2.7%).
    ('infineon', 'IPT020N13NM6ATMA1'): [
        (0, 7441, 1674),
        (0.9619139454, 7161, 1383),
        (3.034295535, 6385, 841.2),
        (10.5466788, 5693, 492.4),
        (23.49906373, 4526, 229.2),
        (39.56002105, 3463, 95.1),
        (42.40954574, 3208, 81.61),
        (46.55430892, 3087, 67.4),
        (49.6628813, 2860, 57.84),
        (53.54859678, 2753, 47.77),
        (56.39812147, 2550, 42.6),
        (60.54288465, 2454, 35.86),
        (63.65145703, 2274, 31.97),
        (68, 2147, 27.44),
        (76.34479427, 1914, 21.4),
        (78.41717586, 1807, 20.21),
        (90.33337, 1551, 16.06),
        (99.65908715, 1331, 14.32),
        (110.5390905, 1187, 13.27),
        (113.1295675, 1121, 13.02),
        (117.015283, 1099, 13.02),
        (123.2324277, 999.1, 12.53),
        (134.1124311, 908, 12.29),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 2200 pF@68V (-2.4%), Crss 28 pF@68V (-2.0%), Ciss 11000 pF@68V (-2.7%).
    ('infineon', 'IPTC020N13NM6ATMA1'): [
        (0, 7441, 1674),
        (0.9619139454, 7161, 1383),
        (3.034295535, 6385, 841.2),
        (10.5466788, 5693, 492.4),
        (23.49906373, 4526, 229.2),
        (39.56002105, 3463, 95.1),
        (42.40954574, 3208, 81.61),
        (46.55430892, 3087, 67.4),
        (49.6628813, 2860, 57.84),
        (53.54859678, 2753, 47.77),
        (56.39812147, 2550, 42.6),
        (60.54288465, 2454, 35.86),
        (63.65145703, 2274, 31.97),
        (68, 2147, 27.44),
        (76.34479427, 1914, 21.4),
        (78.41717586, 1807, 20.21),
        (90.33337, 1551, 16.06),
        (99.65908715, 1331, 14.32),
        (110.5390905, 1187, 13.27),
        (113.1295675, 1121, 13.02),
        (117.015283, 1099, 13.02),
        (123.2324277, 999.1, 12.53),
        (134.1124311, 908, 12.29),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 1800 pF@50V (+1.7%), Crss 35 pF@50V (+0.1%), Ciss 13000 pF@50V (+1.0%).
    ('infineon', 'IPT017N10NM5LF2ATMA1'): [
        (0, 9347, 1711),
        (0.0544748377, 9347, 1711),
        (0.8253162413, 8733, 1519),
        (2.174288698, 7245, 1011),
        (9.689992382, 5712, 567.3),
        (11.80980624, 5247, 486.9),
        (17.01298572, 4739, 335.1),
        (32.23710344, 3491, 87.62),
        (33.77878624, 3262, 80.49),
        (36.28402081, 3100, 69.08),
        (42.64346239, 2486, 48.36),
        (48.61748326, 1960, 36.86),
        (49.77374537, 1831, 35.03),
        (52.47169028, 1800, 31.63),
        (55.5550559, 1682, 28.57),
        (59.02384221, 1654, 26.24),
        (61.52907677, 1572, 24.52),
        (79.0657187, 1349, 19.01),
        (100.071147, 1239, 17.76),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 1800 pF@50V (+1.7%), Crss 35 pF@50V (+0.1%), Ciss 13000 pF@50V (+1.0%).
    ('infineon', 'IPF018N10NM5LF2ATMA1'): [
        (0, 9347, 1682),
        (0.0544748377, 9347, 1682),
        (0.8253162413, 8733, 1493),
        (2.174288698, 7245, 1028),
        (9.689992382, 5712, 567.3),
        (17.01298572, 4739, 335.1),
        (32.23710344, 3491, 87.62),
        (33.77878624, 3262, 80.49),
        (36.28402081, 3100, 69.08),
        (42.64346239, 2486, 48.36),
        (48.61748326, 1960, 36.86),
        (49.77374537, 1831, 35.03),
        (52.47169028, 1800, 31.63),
        (55.5550559, 1682, 28.57),
        (59.02384221, 1654, 26.24),
        (61.52907677, 1572, 24.52),
        (79.0657187, 1349, 19.01),
        (100.071147, 1239, 17.76),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 2200 pF@68V (-2.4%), Crss 28 pF@68V (-2.0%), Ciss 11000 pF@68V (-2.7%).
    ('infineon', 'IPF021N13NM6ATMA1'): [
        (0, 7441, 1674),
        (0.9619139454, 7161, 1383),
        (3.034295535, 6385, 841.2),
        (10.5466788, 5693, 492.4),
        (23.49906373, 4526, 229.2),
        (39.56002105, 3463, 95.1),
        (53.54859678, 2753, 47.77),
        (56.91621686, 2550, 41),
        (58.47050306, 2550, 38.71),
        (63.65145703, 2274, 31.97),
        (68, 2147, 27.44),
        (76.34479427, 1914, 21.4),
        (81.00765284, 1740, 19.08),
        (82.56193904, 1740, 18.36),
        (83.59812983, 1674, 18.36),
        (90.33337, 1551, 16.06),
        (99.65908715, 1331, 14.32),
        (104.3219457, 1281, 13.78),
        (108.9848043, 1187, 13.52),
        (111.0571859, 1187, 13.27),
        (114.9429014, 1099, 13.02),
        (120.9009984, 1058, 12.77),
        (125.0457616, 980.2, 12.53),
        (134.1124311, 908, 12.53),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 1500 pF@60V (-1.7%), Crss 27 pF@60V (-1.0%), Ciss 5000 pF@60V (-0.5%).
    ('infineon', 'IPTC026N12NM6ATMA1'): [
        (0, 5267, 869.5),
        (0.8245068642, 5148, 793.3),
        (4.155119381, 4139, 518.9),
        (8.151854402, 3776, 394),
        (18.14369195, 3179, 214.5),
        (32.13226452, 2586, 97.18),
        (44.12246959, 2056, 51.71),
        (52.11593963, 1751, 36.23),
        (60, 1474, 26.73),
        (62.32981801, 1408, 24.53),
        (77.87267643, 953.1, 16.42),
        (104.5175766, 707.3, 12.46),
        (120.060435, 595.5, 11.91),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 1200 pF@60V (+2.2%), Crss 23 pF@60V (+1.3%), Ciss 4200 pF@60V (-1.4%).
    ('infineon', 'ISC030N12NM6ATMA1'): [
        (0, 4486, 723.7),
        (0.8245068642, 4284, 660.2),
        (11.48246692, 2968, 266.7),
        (22.14042697, 2499, 141.9),
        (30.13389701, 2228, 90.72),
        (36.12899955, 2009, 65.79),
        (50.11757212, 1526, 33.82),
        (60, 1227, 23.29),
        (64.32818552, 1119, 20.18),
        (76.76247225, 811.7, 14.98),
        (120.060435, 501.3, 10.86),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 1500 pF@60V (-2.2%), Crss 27 pF@60V (-1.4%), Ciss 5000 pF@60V (-0.4%).
    # Re-thinned 2026-08-15: 11 knots jumped 1.5 -> 14.2 V straight across the knee, reading
    # +12.4% high at 4 V on Crss and +7.1% on Coss. 13 knots chosen jointly against the d11
    # ink: Crss 12.43% -> 3.00%, Coss 7.05% -> 2.26%. Anchors held (Coss -1.9%, Crss -2.1%).
    ('infineon', 'IPT026N12NM6ATMA1'): [
        (0, 5296, 847.2),
        (0.150339, 5296, 847.2), (1.19125, 5002, 755.5), (2.02398, 4669, 658.4),
        (5.97944, 3977, 456.4), (18.8867, 3127, 204.7), (28.8795, 2694, 115.4),
        (40.954, 2167, 60.77), (50.1141, 1825, 39.32), (60.1068, 1468, 26.33),
        (68.2259, 1222, 20.7), (73.8468, 1041, 17.84), (104.45, 705.3, 12.51),
        (120.063, 600.8, 11.81),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 980 pF@60V (-1.9%), Crss 20 pF@60V (-2.8%), Ciss 3300 pF@60V (-0.9%).
    ('infineon', 'ISC037N12NM6ATMA1'): [
        (0, 3530, 563),
        (0.8245068642, 3397, 521.5),
        (3.711037712, 2860, 355.8),
        (5.709405223, 2599, 305.3),
        (10.37226275, 2408, 224.8),
        (15.47920194, 2147, 165.6),
        (18.36573279, 2106, 142.1),
        (32.35430536, 1707, 64.87),
        (50.11757212, 1210, 27.97),
        (51.67185796, 1142, 25.91),
        (56.33471548, 1058, 21.81),
        (60, 961.6, 19.45),
        (64.32818552, 890.8, 17.34),
        (77.65063559, 631.4, 12.77),
        (94.96982068, 521.5, 10.75),
        (97.63431069, 492.4, 10.55),
        (110.9567608, 439.1, 9.959),
        (113.6212508, 414.6, 9.959),
        (120.060435, 391.5, 9.77),
    ],

    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 1147 pF@50V (+1.1%), Crss 12 pF@50V (+0.0%), Ciss 4094 pF@50V (-8.5%).
    ('epc', 'EPC2361'): [
        (0, 3341, 287.6), (8.83593, 2535, 79.37), (12.3511, 1984, 49.35), (16.201, 1755, 34.16),
        (21.7248, 1552, 24.01), (29.4247, 1352, 17.41), (41.6441, 1234, 12.62),
        (57.7133, 1108, 10.82), (100.23, 936.1, 10.34),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 590 pF@50V (+7.2%), Crss 8 pF@50V (+0.0%), Ciss 2170 pF@50V (-5.9%).
    ('epc', 'EPC2367'): [
        (0, 1840, 211.7), (11.9684, 1566, 87.14), (16.5856, 1230, 56.92),
        (23.8412, 965.9, 28.97), (29.4478, 822.2, 18.58), (36.2087, 714, 12.12),
        (49.4007, 632.7, 8.068), (57.4808, 560.7, 7.459), (99.8602, 549.5, 7.006),
    ],

    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 616 pF@50V (-2.2%), Crss 5.8 pF@50V (+0.0%), Ciss 1777 pF@50V (-5.2%).
    # Re-curated 2026-08-15 from the d902 LOG panel.  The table and the chart disagree on
    # Crss at 50 V by -23.9% (table 5.8 pF, chart 4.413 pF), which is past the 15% Crss
    # anchor tolerance, so the library's documented treatment applies: the CHART supplies
    # the shape, the TABLE supplies the absolute position, joined by ONE additive offset of
    # +1.387 pF across the whole trace (tiny_crss_anchor_offset -- spec 5.8 pF is inside the
    # 15 pF regime and the digitized value sits below it, so the offset lifts, never cuts).
    # Additive and not multiplicative on purpose: a scale would multiply the tail error by
    # the same factor as the knee, and the tail is where Cgd sets the Miller plateau.  The
    # lift is +49.4% at the 100 V tail and +1.0% at the knee.  Coss is NOT corrected -- its
    # -2.4% residual is inside the 8% tolerance, so the exporter records agreement and
    # changes nothing.
    # 30 -> 14 knots, chosen jointly against the corrected ink: Coss 3.85% -> 2.83%,
    # Crss 4.04% -> 2.67%.  A knot is PINNED at the 50 V anchor: greedy thinning has no
    # reason to place one there and drifted it -1.7% on the first pass, which would have
    # quietly undone the offset.  After pinning it lands at 5.800 pF, +0.00%.
    ('epc', 'EPC2306'): [
        (0, 1715, 143.9),
        (0.0951853, 1715, 143.9),
        (0.761894, 1715, 141),
        (1.26193, 1680, 132.6),
        (3.76208, 1612, 99.8),
        (7.2623, 1455, 54.5),
        (11.5959, 1209, 26.72),
        (13.4294, 1091, 20.78),
        (15.5962, 984.3, 16.54),
        (19.4297, 835, 12.99),
        (24.43, 753.4, 10.45),
        (50, 600.9, 5.8),
        (57.9322, 576.7, 5.131),
        (99.9348, 489.3, 4.194),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 616 pF@50V (-2.2%), Crss 5.8 pF@50V (+0.0%), Ciss 1777 pF@50V (-5.2%).
    # Re-curated 2026-08-15 from the d902 LOG panel.  The table and the chart disagree on
    # Crss at 50 V by -23.9% (table 5.8 pF, chart 4.413 pF), which is past the 15% Crss
    # anchor tolerance, so the library's documented treatment applies: the CHART supplies
    # the shape, the TABLE supplies the absolute position, joined by ONE additive offset of
    # +1.387 pF across the whole trace (tiny_crss_anchor_offset -- spec 5.8 pF is inside the
    # 15 pF regime and the digitized value sits below it, so the offset lifts, never cuts).
    # Additive and not multiplicative on purpose: a scale would multiply the tail error by
    # the same factor as the knee, and the tail is where Cgd sets the Miller plateau.  The
    # lift is +49.4% at the 100 V tail and +1.0% at the knee.  Coss is NOT corrected -- its
    # -2.4% residual is inside the 8% tolerance, so the exporter records agreement and
    # changes nothing.
    # 30 -> 14 knots, chosen jointly against the corrected ink: Coss 3.85% -> 2.83%,
    # Crss 4.04% -> 2.67%.  A knot is PINNED at the 50 V anchor: greedy thinning has no
    # reason to place one there and drifted it -1.7% on the first pass, which would have
    # quietly undone the offset.  After pinning it lands at 5.800 pF, +0.00%.
    ('epc', 'EPC2306ENGRT'): [
        (0, 1715, 143.9),
        (0.0951853, 1715, 143.9),
        (0.761894, 1715, 141),
        (1.26193, 1680, 132.6),
        (3.76208, 1612, 99.8),
        (7.2623, 1455, 54.5),
        (11.5959, 1209, 26.72),
        (13.4294, 1091, 20.78),
        (15.5962, 984.3, 16.54),
        (19.4297, 835, 12.99),
        (24.43, 753.4, 10.45),
        (50, 600.9, 5.8),
        (57.9322, 576.7, 5.131),
        (99.9348, 489.3, 4.194),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 1600 pF@50V (-0.1%), Crss 61 pF@50V (-1.1%), Ciss 11000 pF@50V (+2.4%).
    ('infineon', 'IPM018N10NM5LF2AUMA1'): [
        (0, 7887, 1468),
        (0.0544748377, 7887, 1468),
        (0.8253162413, 7624, 1304),
        (1.788867996, 6433, 993.6),
        (9.689992382, 4903, 512.4),
        (15.66401326, 4208, 340.9),
        (20.48177203, 3673, 251.1),
        (23.3724273, 3551, 204.8),
        (33.00794484, 2946, 102.1),
        (42.25804168, 2170, 73.94),
        (50, 1598, 60.31),
        (50.54458677, 1572, 59.29),
        (79.0657187, 1177, 46.75),
        (100.071147, 1082, 45.96),
    ],

    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 1035 pF@50V (-3.7%).
    ('epc', 'EPC2091'): [
        (0, 2857),
        (0.0329251973, 2857),
        (2.65250088, 2741),
        (6.581864403, 2469),
        (9.014327537, 2256),
        (11.44679067, 2024),
        (21.5508683, 1384),
        (43.06881141, 1074),
        (50, 996.5),
        (75.06505724, 831.8),
        (99.95102622, 773.7),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 852 pF@75V (+1.9%).
    ('epc', 'EPC2305'): [
        (0, 2945),
        (0.2549606714, 2945),
        (4.396242922, 2724),
        (11.29838001, 2267),
        (12.40272194, 2157),
        (13.50706387, 1835),
        (14.88749129, 1665),
        (35.86998803, 1114),
        (70.65675894, 893.8),
        (75, 868.4),
        (97.71313631, 732.8),
        (149.3411217, 715.9),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 642 pF@50V (-0.1%).
    ('epc', 'EPC2053'): [
        (0, 1534),
        (0.0329251973, 1534),
        (3.213838526, 1490),
        (7.891652244, 1363),
        (11.07256557, 1223),
        (15.75037929, 895.2),
        (20.05396791, 803.3),
        (45.31416199, 650.2),
        (50, 641.4),
        (99.76391368, 610.8),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Coss 350 pF@50V (+5.4%).
    ('epc', 'EPC2619'): [
        (0, 1033),
        (2.9355578, 987.8),
        (4.951003437, 944.5),
        (5.68389276, 903.2),
        (8.065783059, 863.6),
        (12.82956366, 631.3),
        (16.49401027, 552),
        (17.59334425, 552),
        (20.15845688, 504.7),
        (23.45645884, 482.6),
        (29.13635109, 422),
        (39.9464686, 394.6),
        (40.12969093, 385.8),
        (43.97735987, 385.8),
        (44.1605822, 377.3),
        (47.64180649, 377.3),
        (47.82502882, 369),
        (50, 369),
        (57.902257, 360.8),
        (58.08547933, 352.8),
        (63.76537159, 345),
        (63.94859392, 337.4),
        (82.82049398, 308.5),
        (83.00371631, 301.6),
        (99.86017073, 288.4),
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
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="overlay + Coss/Crss@40V + Qoss(0-40V) table anchors"),
    ("infineon", "IPP039N10N5"): dict(
        datasheet_revision="2.0 (2016-11-22)", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-vector-first-adaptive-knots",
        validation_method="human overlay (Fab 2026-08-11) + Coss/Crss/Ciss@50V + Qoss(0-50V) "
                          "table anchor (98.3 vs 98.0 nC, +0.3%; landed knots 99.4, +1.5%)"),
    ("infineon", "IPP019N08NF2S"): dict(
        datasheet_revision="2.1", source_figure="Diagram 11", source_page=None,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="Coss/Crss@40V + Qoss(0-40V) table anchors"),
    ("infineon", "IPP055N08NF2S"): dict(
        datasheet_revision="2.1", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="Coss/Crss/Ciss@40V + Qoss(0-40V) table anchors"),
    ("infineon", "IPP040N08NF2S"): dict(
        datasheet_revision="2.1 (2022-06-15)", source_figure="Diagram 11",
        source_page=None, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="human overlay + Coss/Crss@40V + Qoss(0-40V) anchors"),
    ("infineon", "IPP026N10NF2S"): dict(
        datasheet_revision="2.1", source_figure="Diagram 11", source_page=None,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="Coss/Crss/Ciss@50V + Qoss(0-50V) table anchors"),
    ("infineon", "IPP018N10N5"): dict(
        datasheet_revision="2.3", source_figure="Diagram 11", source_page=None,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="Coss/Crss/Ciss@50V + Qoss(0-50V) table anchors"),
    ("infineon", "IPP022N12NM6"): dict(
        datasheet_revision="2.0", source_figure="Diagram 11", source_page=None,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="Coss/Crss/Ciss@60V + Qoss(0-60V) table anchors"),
    ("infineon", "IPP050N10NF2S"): dict(
        datasheet_revision="2.1 (2022-06-15)", source_figure="Diagram 11",
        source_page=None, digitization_method="dsdig-auto-vector-adaptive-knots",
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

    # ---- landed 2026-07-29 from the fugu2 C(V) review packets: human GREEN
    # verdicts (newest export per review id) that ALSO pass the dsdig export
    # gate (spec-table Coss/Crss/Ciss anchors + Qoss integral). Greens that the
    # gate could not validate are deliberately NOT here -- see the worklist.
    ("infineon", "BSC027N10NS5ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-head"),
    ("infineon", "BSC034N10LS5ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-color"),
    ("infineon", "BSC0802LSATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-color"),
    ("infineon", "IPA030N10NF2SXKSA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=7,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28-refresh"),
    ("infineon", "IPP023N10N5AKSA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28-refresh"),
    ("infineon", "IPP030N10N5AKSA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28-refresh"),
    ("infineon", "IPP030N10NF2SAKMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28-refresh"),
    ("infineon", "IPP038N15NM6AKSA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28-refresh"),
    ("infineon", "IPP039N10N5AKSA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28-refresh"),
    ("infineon", "IPT020N10N5ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-head"),
    ("infineon", "IPT023N10NM5LF2ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 12", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-head"),
    ("infineon", "IPT026N10N5ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-color"),
    ("infineon", "IPTG018N10NM5ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-color"),
    ("infineon", "IPTG025N10NM5ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28"),
    ("infineon", "IQD020N10NM5ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28"),
    ("infineon", "IQD020N10NM5CGATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28"),
    ("infineon", "IQD020N10NM5CGSCATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28"),
    ("infineon", "IQD020N10NM5SCATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-28"),
    ("infineon", "ISC022N10NM6ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-color"),
    ("infineon", "ISC027N10NM6ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-color"),
    ("infineon", "ISC030N10NM6ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-color"),
    ("infineon", "ISC040N10NM7ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=9,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate: Coss/Crss/Ciss anchors + Qoss table; human overlay review coss-review-top50-2026-07-29-color"),

    # ---- landed 2026-07-29 (second pass): greens that became VALIDATABLE once the
    # spec-table anchors came from fetlib instead of the digitizer's own scraper.
    # Mostly EPC, whose printed "COSS" the scraper never matched.
    ("epc", "EPC2022"): dict(
        datasheet_revision="?", source_figure="Diagram 902", source_page=3,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review"),
    ("epc", "EPC2071"): dict(
        datasheet_revision="?", source_figure="Diagram 902", source_page=3,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review"),
    ("epc", "EPC2088"): dict(
        datasheet_revision="?", source_figure="Diagram 902", source_page=3,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review"),
    ("epc", "EPC2092"): dict(
        datasheet_revision="?", source_figure="Diagram 902", source_page=3,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review"),
    ("epc", "EPC2218"): dict(
        datasheet_revision="?", source_figure="Diagram 902", source_page=3,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review"),
    ("epc", "EPC2302"): dict(
        datasheet_revision="?", source_figure="Diagram 905", source_page=3,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review"),
    ("infineon", "IPA030N10N3GXKSA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=6,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review"),
    ("infineon", "ISC0802NLSATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review"),

    # ---- landed 2026-07-29 (third pass): packet fugu2-100v-LS2p-gan-coss-scalar-top50-001,
    # the first packet built by `main.py --coss-review`. 23 of its 25 cards are human
    # GREEN; these are the 7 whose export gate also PASSES. The other 16 stay OUT --
    # 6 EPC parts miss the Crss table anchor by 20-100%% (the reviewer flagged the
    # dashed line the Crss trace rides), 3 IAUTN parts have all_traces_left_edge_gap,
    # TPH2R70AR5 collapses Ciss/Coss, IXFN106N20 has no Qoss row. A human GREEN says
    # the OVERLAY looks right; it does not make an unvalidatable trace servable.
    ("epc", "EPC2090"): dict(
        datasheet_revision="?", source_figure="Diagram 902", source_page=3,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001)"),
    ("epc", "EPC7018"): dict(
        datasheet_revision="?", source_figure="Diagram 902", source_page=3,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001)"),
    ("infineon", "IPF019N12NM6ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001)"),
    ("infineon", "IPT017N12NM6ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001)"),
    ("infineon", "IPTC017N12NM6ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001)"),
    ("infineon", "IPTG017N12NM6ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001)"),
    ("infineon", "IPTG020N13NM6ATMA1"): dict(
        datasheet_revision="?", source_figure="Diagram 11", source_page=8,
        digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method="export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50-001)"),

    ('epc', 'EPC2032'): dict(
        datasheet_revision="unknown", source_figure='Diagram 902',
        source_page=3, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),
    ('infineon', 'IPT020N13NM6ATMA1'): dict(
        datasheet_revision="unknown", source_figure='Diagram 11',
        source_page=8, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),
    ('infineon', 'IPTC020N13NM6ATMA1'): dict(
        datasheet_revision="unknown", source_figure='Diagram 11',
        source_page=8, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),
    ('infineon', 'IPT017N10NM5LF2ATMA1'): dict(
        datasheet_revision="unknown", source_figure='Diagram 12',
        source_page=8, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),
    ('infineon', 'IPF018N10NM5LF2ATMA1'): dict(
        datasheet_revision="unknown", source_figure='Diagram 12',
        source_page=8, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),
    ('infineon', 'IPF021N13NM6ATMA1'): dict(
        datasheet_revision="unknown", source_figure='Diagram 11',
        source_page=8, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),
    ('infineon', 'IPTC026N12NM6ATMA1'): dict(
        datasheet_revision="unknown", source_figure='Diagram 11',
        source_page=8, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),
    ('infineon', 'ISC030N12NM6ATMA1'): dict(
        datasheet_revision="unknown", source_figure='Diagram 11',
        source_page=8, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),
    ('infineon', 'IPT026N12NM6ATMA1'): dict(
        datasheet_revision="unknown", source_figure='Diagram 11',
        source_page=8, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),
    ('infineon', 'ISC037N12NM6ATMA1'): dict(
        datasheet_revision="unknown", source_figure='Diagram 11',
        source_page=8, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),

    ('epc', 'EPC2361'): dict(
        datasheet_revision="unknown", source_figure='Diagram 902',
        source_page=3, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),
    ('epc', 'EPC2367'): dict(
        datasheet_revision="unknown", source_figure='Diagram 902',
        source_page=3, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-29T10:27:33.961Z)'),

    ('epc', 'EPC2306'): dict(
        datasheet_revision="unknown", source_figure='Diagram 902',
        source_page=3, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-30T07:37:58.612Z)'),
    ('epc', 'EPC2306ENGRT'): dict(
        datasheet_revision="unknown", source_figure='Diagram 902',
        source_page=3, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-30T07:37:58.612Z)'),
    ('infineon', 'IPM018N10NM5LF2AUMA1'): dict(
        datasheet_revision="unknown", source_figure='Diagram 12',
        source_page=8, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='export gate on FETLIB-served anchors (dslib.coss_anchors): Coss/Crss/Ciss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-30T07:37:58.612Z)'),

    ('epc', 'EPC2091'): dict(
        datasheet_revision="unknown", source_figure='Diagram 901',
        source_page=3, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='per-trace export gate on FETLIB-served anchors (dslib.coss_anchors): Coss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-30T07:37:58.612Z)'),
    ('epc', 'EPC2305'): dict(
        datasheet_revision="unknown", source_figure='Diagram 904',
        source_page=3, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='per-trace export gate on FETLIB-served anchors (dslib.coss_anchors): Coss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-30T07:37:58.612Z)'),
    ('epc', 'EPC2053'): dict(
        datasheet_revision="unknown", source_figure='Diagram 901',
        source_page=3, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='per-trace export gate on FETLIB-served anchors (dslib.coss_anchors): Coss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-30T07:37:58.612Z)'),
    ('epc', 'EPC2619'): dict(
        datasheet_revision="unknown", source_figure='Diagram 902',
        source_page=3, digitization_method="dsdig-auto-vector-adaptive-knots",
        validation_method='per-trace export gate on FETLIB-served anchors (dslib.coss_anchors): Coss + Qoss; human overlay review GREEN (packet fugu2-100v-LS2p-gan-coss-scalar-top50 001, exported 2026-07-30T07:37:58.612Z)'),
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
    # EPC2361 Ciss from Diagram 902 (log panel). The part had NO Ciss entry; the linear
    # panel it was previously read from cannot resolve the small-capacitance end.
    ('epc', 'EPC2361'): [
        (0, 4077), (16.5358, 3776), (100.23, 3776),
    ],
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

    # ---- landed 2026-07-29 from the fugu2 C(V) review packets: human GREEN
    # verdicts (newest export per review id) that ALSO pass the dsdig export
    # gate (spec-table Coss/Crss/Ciss anchors + Qoss integral). Greens that the
    # gate could not validate are deliberately NOT here -- see the worklist.
    # infineon BSC027N10NS5ATMA1, same Diagram 11 graph.
    ("infineon", "BSC027N10NS5ATMA1"): [
        (0, 7517), (7.16, 6626), (35.1, 6256), (50, 6256),
        (100.05, 6256),
    ],
    # infineon BSC034N10LS5ATMA1, same Diagram 11 graph.
    ("infineon", "BSC034N10LS5ATMA1"): [
        (0, 5908), (0.5, 5908), (1.98, 5452), (5.13, 5267),
        (37.14, 4917), (50, 4917), (100.05, 4917),
    ],
    # infineon BSC0802LSATMA1, same Diagram 11 graph.
    ("infineon", "BSC0802LSATMA1"): [
        (0, 5908), (0.5, 5908), (1.98, 5452), (5.13, 5267),
        (37.14, 4917), (50, 4917), (100.05, 4917),
    ],
    # infineon IPA030N10NF2SXKSA1, same Diagram 11 graph.
    ("infineon", "IPA030N10NF2SXKSA1"): [
        (0, 8726), (2.54, 7961), (33.07, 7263), (50, 7263),
        (100.05, 7180),
    ],
    # infineon IPP023N10N5AKSA1, same Diagram 11 graph.
    ("infineon", "IPP023N10N5AKSA1"): [
        (0, 14360), (1.14, 13920), (5.14, 12700), (50, 11950),
        (79.74, 11770),
    ],
    # infineon IPP030N10N5AKSA1, same Diagram 11 graph.
    ("infineon", "IPP030N10N5AKSA1"): [
        (0, 9456), (1.29, 9241), (4.99, 8431), (50, 7780),
        (79.89, 7780),
    ],
    # infineon IPP030N10NF2SAKMA1, same Diagram 11 graph.
    ("infineon", "IPP030N10NF2SAKMA1"): [
        (0, 7202), (0.09, 7202), (5.11, 6422), (50, 6026),
        (99.92, 5950),
    ],
    # infineon IPP038N15NM6AKSA1, same Diagram 11 graph.
    ("infineon", "IPP038N15NM6AKSA1"): [
        (0, 5655), (0.14, 5655), (4.77, 5513), (29.05, 4979),
        (75, 4916), (149.88, 4916),
    ],
    # infineon IPP039N10N5AKSA1, same Diagram 11 graph.
    ("infineon", "IPP039N10N5AKSA1"): [
        (0, 6475), (1.24, 6329), (3.83, 5774), (38.06, 5328),
        (50, 5328), (100.05, 5328),
    ],
    # infineon IPT020N10N5ATMA1, same Diagram 11 graph.
    ("infineon", "IPT020N10N5ATMA1"): [
        (0, 10250), (3.09, 9355), (43.06, 8535), (50, 8535),
        (100.05, 8535),
    ],
    # infineon IPT023N10NM5LF2ATMA1, same Diagram 12 graph.
    ("infineon", "IPT023N10NM5LF2ATMA1"): [
        (0, 10180), (0.05, 10180), (31.08, 9035), (50, 9035),
        (100.07, 9035),
    ],
    # infineon IPT026N10N5ATMA1, same Diagram 11 graph.
    ("infineon", "IPT026N10N5ATMA1"): [
        (0, 8146), (7.16, 7180), (35.1, 6780), (50, 6780),
        (100.05, 6780),
    ],
    # infineon IPTG018N10NM5ATMA1, same Diagram 11 graph.
    ("infineon", "IPTG018N10NM5ATMA1"): [
        (0, 10250), (3.09, 9355), (43.06, 8535), (50, 8535),
        (100.05, 8535),
    ],
    # infineon IPTG025N10NM5ATMA1, same Diagram 11 graph.
    ("infineon", "IPTG025N10NM5ATMA1"): [
        (0, 8146), (7.16, 7180), (35.1, 6780), (50, 6780),
        (100.05, 6780),
    ],
    # infineon IQD020N10NM5ATMA1, same Diagram 11 graph.
    ("infineon", "IQD020N10NM5ATMA1"): [
        (0, 9032), (9.2, 7692), (38.99, 7263), (50, 7263),
        (100.05, 7263),
    ],
    # infineon IQD020N10NM5CGATMA1, same Diagram 11 graph.
    ("infineon", "IQD020N10NM5CGATMA1"): [
        (0, 9032), (9.2, 7692), (38.99, 7263), (50, 7263),
        (100.05, 7263),
    ],
    # infineon IQD020N10NM5CGSCATMA1, same Diagram 11 graph.
    ("infineon", "IQD020N10NM5CGSCATMA1"): [
        (0, 8942), (0.09, 8942), (0.87, 8829), (2.02, 8284),
        (13.01, 7578), (35.17, 7294), (50, 7294), (99.92, 7294),
    ],
    # infineon IQD020N10NM5SCATMA1, same Diagram 11 graph.
    ("infineon", "IQD020N10NM5SCATMA1"): [
        (0, 8942), (0.09, 8942), (0.87, 8829), (2.02, 8284),
        (13.01, 7578), (35.17, 7294), (50, 7294), (99.92, 7294),
    ],
    # infineon ISC022N10NM6ATMA1, same Diagram 11 graph.
    ("infineon", "ISC022N10NM6ATMA1"): [
        (0, 5776), (1.24, 5776), (50, 5351), (98.94, 5351),
    ],
    # infineon ISC027N10NM6ATMA1, same Diagram 11 graph.
    ("infineon", "ISC027N10NM6ATMA1"): [
        (0, 4522), (1.24, 4522), (3.28, 4592), (37.32, 4254),
        (50, 4254), (98.94, 4254),
    ],
    # infineon ISC030N10NM6ATMA1, same Diagram 11 graph.
    ("infineon", "ISC030N10NM6ATMA1"): [
        (0, 4386), (25.11, 4001), (50, 4001), (100.05, 4001),
    ],
    # infineon ISC040N10NM7ATMA1, same Diagram 11 graph.
    ("infineon", "ISC040N10NM7ATMA1"): [
        (0, 3332), (0.09, 3332), (0.87, 3276), (2.02, 3061),
        (13.01, 2860), (50, 2812), (99.92, 2812),
    ],

    # ---- landed 2026-07-29 (second pass): greens that became VALIDATABLE once the
    # spec-table anchors came from fetlib instead of the digitizer's own scraper.
    # Mostly EPC, whose printed "COSS" the scraper never matched.
    # epc EPC2022, same Diagram 902 graph.
    ("epc", "EPC2022"): [
        (0, 1756), (2.97, 1687), (15.84, 1466), (50, 1466),
        (100.78, 1466),
    ],
    # epc EPC2071, same Diagram 902 graph.
    ("epc", "EPC2071"): [
        (0, 2684), (0.02, 2684), (5.49, 2626), (8.59, 2512),
        (50, 2458), (99.99, 2458),
    ],
    # epc EPC2092, same Diagram 902 graph.
    ("epc", "EPC2092"): [
        (0, 1739), (4.8, 1739), (4.99, 1700), (7.8, 1700),
        (7.98, 1662), (14.91, 1662), (15.1, 1625), (50, 1625),
        (100.23, 1625),
    ],
    # epc EPC2218, same Diagram 902 graph.
    ("epc", "EPC2218"): [
        (0, 1354), (5.43, 1324), (5.61, 1295), (27.75, 1212),
        (27.94, 1186), (50, 1186), (71.68, 1186), (71.86, 1212),
        (99.86, 1186),
    ],
    # epc EPC2302, same Diagram 905 graph.
    ("epc", "EPC2302"): [
        (0, 3450), (8.8, 3450), (8.98, 3372), (13.08, 3372),
        (13.26, 3296), (50, 3296), (100.3, 3296),
    ],
    # infineon IPA030N10N3GXKSA1, same Diagram 11 graph.
    ("infineon", "IPA030N10N3GXKSA1"): [
        (0, 13770), (0.03, 13770), (0.56, 13560), (2.15, 11930),
        (50, 11190), (80.06, 11190),
    ],
    # infineon ISC0802NLSATMA1, same Diagram 11 graph.
    ("infineon", "ISC0802NLSATMA1"): [
        (0, 4696), (0.5, 4696), (2.54, 4284), (33.07, 3909),
        (50, 3909), (100.05, 3909),
    ],

    # ---- landed 2026-07-29 (third pass): packet fugu2-100v-LS2p-gan-coss-scalar-top50-001,
    # the first packet built by `main.py --coss-review`. 23 of its 25 cards are human
    # GREEN; these are the 7 whose export gate also PASSES. The other 16 stay OUT --
    # 6 EPC parts miss the Crss table anchor by 20-100%% (the reviewer flagged the
    # dashed line the Crss trace rides), 3 IAUTN parts have all_traces_left_edge_gap,
    # TPH2R70AR5 collapses Ciss/Coss, IXFN106N20 has no Qoss row. A human GREEN says
    # the OVERLAY looks right; it does not make an unvalidatable trace servable.
    # epc EPC2090, same Diagram 902 graph.
    ("epc", "EPC2090"): [
        (0, 1080), (2.203, 1080), (2.386, 1056), (15.03, 1033), (15.21, 1010), (50, 1010),
        (99.86, 1010),
    ],
    # infineon IPF019N12NM6ATMA1, same Diagram 11 graph.
    ("infineon", "IPF019N12NM6ATMA1"): [
        (0, 9355), (0.8245, 9355), (41.01, 8028), (60, 8028), (120.1, 8028),
    ],
    # infineon IPT017N12NM6ATMA1, same Diagram 11 graph.
    ("infineon", "IPT017N12NM6ATMA1"): [
        (0, 9355), (0.8245, 9355), (25.03, 8152), (60, 8028), (120.1, 8028),
    ],
    # infineon IPTC017N12NM6ATMA1, same Diagram 11 graph.
    ("infineon", "IPTC017N12NM6ATMA1"): [
        (0, 9355), (0.8245, 9355), (39.02, 8028), (60, 8028), (120.1, 8028),
    ],
    # infineon IPTG017N12NM6ATMA1, same Diagram 11 graph.
    ("infineon", "IPTG017N12NM6ATMA1"): [
        (0, 9348), (41.01, 8053), (60, 8053), (120.1, 8053),
    ],
    # infineon IPTG020N13NM6ATMA1, same Diagram 11 graph.
    ("infineon", "IPTG020N13NM6ATMA1"): [
        (0, 12470), (1.221, 12230), (1.739, 11770), (5.107, 11330), (68, 10700),
        (134.1, 10700),
    ],

    ('epc', 'EPC2032'): [
        (0, 1449),
        (2.878155802, 1407),
        (12.72977933, 1248),
        (50, 1248),
        (100.2791129, 1248),
    ],
    ('infineon', 'IPT020N13NM6ATMA1'): [
        (0, 12470),
        (1.220961644, 12230),
        (1.739057041, 11770),
        (5.106677124, 11330),
        (68, 10700),
        (134.1124311, 10700),
    ],
    ('infineon', 'IPTC020N13NM6ATMA1'): [
        (0, 12470),
        (1.220961644, 12230),
        (1.739057041, 11770),
        (5.106677124, 11330),
        (68, 10700),
        (134.1124311, 10700),
    ],
    ('infineon', 'IPT017N10NM5LF2ATMA1'): [
        (0, 14780),
        (0.0544748377, 14780),
        (25.10682045, 13130),
        (50, 13130),
        (100.071147, 13130),
    ],
    ('infineon', 'IPF018N10NM5LF2ATMA1'): [
        (0, 14780),
        (0.0544748377, 14780),
        (27.03392396, 13130),
        (50, 13130),
        (100.071147, 13130),
    ],
    ('infineon', 'IPF021N13NM6ATMA1'): [
        (0, 12470),
        (1.220961644, 12230),
        (1.739057041, 11770),
        (5.106677124, 11330),
        (68, 10700),
        (134.1124311, 10700),
    ],
    ('infineon', 'IPTC026N12NM6ATMA1'): [
        (0, 5774),
        (2.378792705, 5643),
        (31.02206035, 5031),
        (60, 4974),
        (120.060435, 4974),
    ],
    ('infineon', 'ISC030N12NM6ATMA1'): [
        (0, 4861),
        (23.02859031, 4236),
        (60, 4139),
        (120.060435, 4139),
    ],
    ('infineon', 'IPT026N12NM6ATMA1'): [
        (0, 5800),
        (0.1134685894, 5800),
        (29.01996519, 5043),
        (60, 4979),
        (119.9019905, 4979),
    ],
    ('infineon', 'ISC037N12NM6ATMA1'): [
        (0, 3810),
        (0.8245068642, 3810),
        (35.01879537, 3270),
        (60, 3270),
        (120.060435, 3270),
    ],

    ('epc', 'EPC2367'): [
        (0, 2251), (21.8624, 2035), (99.8602, 2035),
    ],

    ('epc', 'EPC2306'): [
        (0, 1803),
        (0.169264068, 1803),
        (5.169578351, 1763),
        (5.354775176, 1723),
        (8.503121206, 1723),
        (8.688318031, 1684),
        (50, 1684),
        (99.9903529, 1684),
    ],
    ('epc', 'EPC2306ENGRT'): [
        (0, 1803),
        (0.169264068, 1803),
        (5.169578351, 1763),
        (5.354775176, 1723),
        (8.503121206, 1723),
        (8.688318031, 1684),
        (50, 1684),
        (99.9903529, 1684),
    ],
    ('infineon', 'IPM018N10NM5LF2AUMA1'): [
        (0, 12480),
        (0.0544748377, 12480),
        (21.05990309, 11270),
        (50, 11270),
        (100.071147, 11080),
    ],

    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 2893 pF@50V (-3.9%).
    ('epc', 'EPC2091'): [
        (0, 2993),
        (0.0329251973, 2993),
        (2.278275782, 2964),
        (12.56946596, 2799),
        (50, 2779),
        (99.95102622, 2770),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 3060 pF@75V (-6.1%).
    ('epc', 'EPC2305'): [
        (0, 3078),
        (0.7114645507, 3078),
        (5.448327854, 3078),
        (5.726966872, 3008),
        (13.25022035, 2940),
        (13.52885937, 2874),
        (75, 2874),
        (150.6192561, 2874),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 1180 pF@50V (-1.4%).
    ('epc', 'EPC2619'): [
        (0, 1254),
        (16.30292206, 1167),
        (50, 1163),
        (100.2117409, 1160),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 16000 pF@50V (+3.1%).
    ('infineon', 'IPT009N10NM8ATMA1'): [
        (0, 18260),
        (0.0945558064, 18260),
        (50, 16490),
        (99.91835331, 16280),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 16000 pF@50V (+3.1%).
    ('infineon', 'IPF009N10NM8ATMA1'): [
        (0, 18260),
        (0.0945558064, 18260),
        (50, 16490),
        (99.91835331, 16280),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 7610 pF@75V (-4.2%).
    ('infineon', 'IAUTN15S6N025ATMA1'): [
        (0, 8490),
        (32.44733274, 7404),
        (75, 7292),
        (149.8364358, 7292),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 7610 pF@75V (-4.2%).
    ('infineon', 'IAUTN15S6N025GATMA1'): [
        (0, 8490),
        (32.44733274, 7404),
        (75, 7292),
        (149.8364358, 7292),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 7610 pF@75V (-4.2%).
    ('infineon', 'IAUTN15S6N025TATMA1'): [
        (0, 8490),
        (32.44733274, 7404),
        (75, 7292),
        (149.8364358, 7292),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 18168 pF@50V (-3.5%).
    ('nxp', 'PSMN1R3-100ASF'): [
        (0, 20580),
        (0.1090813557, 20580),
        (0.1540517028, 20580),
        (0.1567336696, 19660),
        (1.046405877, 19660),
        (1.332420646, 18780),
        (5.778089326, 18780),
        (5.878683112, 17930),
        (49.12055928, 17530),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 6970 pF@50V (-4.5%).
    ('onsemi', 'PCFA86062F'): [
        (0, 7605),
        (0.1003054949, 7605),
        (3.359755803, 7438),
        (3.416679816, 7275),
        (11.84541857, 7116),
        (12.04611433, 6960),
        (34.13770166, 6808),
        (34.71609339, 6658),
        (50, 6658),
        (98.38256603, 6370),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 6970 pF@50V (-1.2%).
    ('onsemi', 'PCFA86062WA'): [
        (0, 7862),
        (0.1003025575, 7862),
        (3.359192847, 7690),
        (3.416105061, 7521),
        (11.84284606, 7357),
        (12.04349027, 7195),
        (34.12886517, 7038),
        (34.70708422, 6884),
        (50, 6884),
        (98.35299996, 6585),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 4411 pF@50V (+7.7%).
    ('onsemi', 'NVMFS3D6N10MCLT1G'): [
        (0, 5263),
        (0.0865197464, 5263),
        (4.591908939, 5130),
        (4.655450392, 5000),
        (10.9145225, 5000),
        (11.06555438, 4874),
        (22.30300682, 4874),
        (22.61162911, 4750),
        (50, 4750),
        (99.75230749, 4630),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 10000 pF@50V (+2.9%).
    ('infineon', 'IPT014N10NM8ATMA1'): [
        (0, 11400),
        (0.0945558064, 11400),
        (50, 10290),
        (99.91835331, 10160),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 18168 pF@50V (-3.5%).
    ('nxp', 'PSMN1R4-100CSF'): [
        (0, 20580),
        (0.1090813557, 20580),
        (0.1540517028, 20580),
        (0.1567336696, 19660),
        (1.046405877, 19660),
        (1.332420646, 18780),
        (5.778089326, 18780),
        (5.878683112, 17930),
        (49.12055928, 17530),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 10000 pF@50V (+2.9%).
    ('infineon', 'IPF014N10NM8ATMA1'): [
        (0, 11400),
        (0.0945558064, 11400),
        (50, 10290),
        (99.91835331, 10160),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 6800 pF@50V (-0.6%).
    ('infineon', 'ISC019N10NM8SCATMA1'): [
        (0, 7578),
        (0.0945558064, 7578),
        (43.06889334, 6757),
        (50, 6757),
        (99.91835331, 6757),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 6800 pF@50V (-0.6%).
    ('infineon', 'ISC019N10NM8ATMA1'): [
        (0, 7578),
        (0.0945558064, 7578),
        (43.06889334, 6757),
        (50, 6757),
        (99.91835331, 6757),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 12614 pF@50V (-3.1%).
    ('crmicro', 'CRSZ016N10N4Z'): [
        (0, 13200),
        (2.012823595, 13200),
        (22.95842446, 12220),
        (50, 12220),
        (99.96430997, 11980),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Ciss 18588 pF@50V (-3.5%).
    ('nxp', 'PSMN1R4-100ASE'): [
        (0, 19210),
        (0.1090813557, 19210),
        (10.21281846, 18780),
        (10.39061877, 17930),
        (49.12055928, 17930),
    ],

    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Ciss 2530 pF@50V (+1.1%).
    ('goford', 'GT080N10T'): [
        (0, 2872),
        (0.5142975213, 2872),
        (19.79361192, 2577),
        (50, 2558),
        (59.46450886, 2558),
    ],
    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Ciss 2085 pF@50V (-0.7%).
    ('diodes', 'DMT10H9M9SCT'): [
        (0, 2351),
        (4.748349026, 2302),
        (19.21972468, 2160),
        (19.44583992, 2114),
        (29.62102593, 2114),
        (29.84714117, 2070),
        (50, 2070),
        (99.94286699, 2070),
    ],
    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Ciss 3330 pF@50V (-0.2%).
    ('vishay', 'SUP70060E'): [
        (0, 4014),
        (0.0961025031, 4014),
        (11.47335412, 3457),
        (50, 3323),
        (100.0533846, 3285),
    ],
    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Ciss 2785 pF@50V (+0.2%).
    ('ao', 'AOTF296L'): [
        (0, 2986),
        (1.144065977, 2986),
        (50, 2790),
        (98.85316509, 2769),
    ],
    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Ciss 2785 pF@50V (-0.1%).
    ('ao', 'AOT296L'): [
        (0, 3024),
        (50, 2783),
        (100.0565749, 2762),
    ],
    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Ciss 2429 pF@50V (-6.5%).
    ('mcc', 'MCP75N10Y-BP'): [
        (0, 2474),
        (6.735393465, 2405),
        (6.946187734, 2337),
        (24.86370062, 2337),
        (25.07449489, 2271),
        (50, 2271),
        (99.90646046, 2271),
    ],
}


# Optional independently validated (Vds_V, Crss_pF) reverse-transfer-capacitance curves.
# Legacy COSS_CURVES triples remain readable through crss_curve_for().
CRSS_CURVES = {

    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 8.8 pF@50V (+0.0%).
    ('epc', 'EPC2091'): [
        (0, 231.7),
        (0.0329251973, 231.7),
        (0.7813753922, 231.7),
        (1.342713038, 212.3),
        (1.716938136, 212.3),
        (1.904050685, 202.6),
        (2.278275782, 202.6),
        (2.839613428, 183.2),
        (3.213838526, 183.2),
        (3.400951075, 173.5),
        (3.588063623, 173.5),
        (3.775176172, 163.8),
        (3.962288721, 163.8),
        (4.14940127, 154.1),
        (4.523626367, 154.1),
        (4.710738916, 144.5),
        (5.084964013, 144.5),
        (5.272076562, 134.8),
        (5.459189111, 134.8),
        (5.646301659, 125.1),
        (6.020526757, 125.1),
        (6.207639306, 115.4),
        (6.581864403, 115.4),
        (6.768976952, 105.7),
        (7.143202049, 105.7),
        (7.330314598, 96.01),
        (7.891652244, 96.01),
        (8.078764793, 86.32),
        (8.45298989, 86.32),
        (8.640102439, 76.63),
        (9.014327537, 76.63),
        (9.201440085, 66.94),
        (9.949890281, 66.94),
        (10.13700283, 57.25),
        (11.07256557, 57.25),
        (11.25967812, 47.56),
        (12.56946596, 47.56),
        (12.75657851, 37.87),
        (14.06636635, 37.87),
        (14.2534789, 28.18),
        (18.18284243, 28.18),
        (18.36995497, 18.49),
        (34.64874671, 18.49),
        (34.83585926, 8.8),
        (50, 8.8),
        (99.95102622, 8.8),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 590 pF@25V (-6.0%).
    ('littelfuse', 'IXFN106N20'): [
        (0, 8199),
        (0.4860056586, 8199),
        (0.7192262539, 7138),
        (0.8358365516, 6076),
        (1.010751998, 4457),
        (1.069057147, 4165),
        (1.477193189, 3501),
        (1.768718933, 3023),
        (2.001939528, 2598),
        (2.643296165, 2200),
        (2.934821909, 1988),
        (6.258215393, 1218),
        (7.132792625, 1085),
        (7.482623518, 1085),
        (7.832454411, 1032),
        (8.823641941, 979.3),
        (8.88194709, 952.7),
        (9.231777983, 952.7),
        (9.290083132, 926.2),
        (9.698219174, 926.2),
        (9.756524322, 899.7),
        (10.22296551, 899.7),
        (10.28127066, 873.1),
        (10.6894067, 873.1),
        (10.74771185, 846.6),
        (11.27245819, 846.6),
        (11.33076334, 820),
        (11.97211998, 820),
        (12.03042513, 793.5),
        (12.61347661, 793.5),
        (12.67178176, 766.9),
        (14.47924138, 740.4),
        (14.53754653, 713.8),
        (15.47042891, 713.8),
        (15.52873406, 687.3),
        (16.46161644, 687.3),
        (16.51992159, 660.8),
        (17.45280397, 660.8),
        (17.51110912, 634.2),
        (18.4439915, 634.2),
        (18.50229665, 607.7),
        (19.95992537, 607.7),
        (20.01823052, 581.1),
        (22.46704677, 581.1),
        (22.52535192, 554.6),
        (23.98298064, 554.6),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 5 pF@75V (+0.0%).
    ('epc', 'EPC2305'): [
        (0, 199.9),
        (0.2549606714, 199.9),
        (1.083217122, 199.9),
        (1.359302605, 191.4),
        (2.187559055, 191.4),
        (2.463644539, 183),
        (3.291900989, 183),
        (4.120157439, 166),
        (4.396242922, 166),
        (4.672328406, 157.5),
        (4.948413889, 157.5),
        (5.224499373, 149.1),
        (5.500584856, 149.1),
        (5.776670339, 140.6),
        (6.052755823, 140.6),
        (6.328841306, 132.1),
        (6.60492679, 132.1),
        (6.881012273, 123.6),
        (7.157097756, 123.6),
        (7.43318324, 115.2),
        (7.709268723, 115.2),
        (7.985354207, 106.7),
        (8.26143969, 106.7),
        (8.537525173, 98.22),
        (8.813610657, 98.22),
        (9.08969614, 89.75),
        (9.365781624, 89.75),
        (9.641867107, 81.27),
        (9.91795259, 81.27),
        (10.19403807, 72.8),
        (10.47012356, 72.8),
        (10.74620904, 64.32),
        (11.29838001, 64.32),
        (11.85055097, 47.37),
        (12.67880742, 47.37),
        (12.95489291, 38.9),
        (15.16357677, 38.9),
        (15.43966226, 30.42),
        (16.82008968, 30.42),
        (17.09617516, 21.95),
        (28.13959449, 21.95),
        (28.41567998, 13.47),
        (48.84600575, 13.47),
        (49.12209123, 5),
        (75, 5),
        (149.3411217, 5),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 10.4 pF@50V (+0.0%).
    ('epc', 'EPC2053'): [
        (0, 124.1),
        (0.0329251973, 124.1),
        (1.15560049, 119.8),
        (1.342713038, 115.4),
        (2.65250088, 111),
        (2.839613428, 106.6),
        (3.213838526, 106.6),
        (3.400951075, 102.3),
        (4.14940127, 102.3),
        (4.336513818, 97.9),
        (4.710738916, 97.9),
        (5.272076562, 89.15),
        (5.646301659, 89.15),
        (6.207639306, 80.4),
        (6.581864403, 80.4),
        (6.768976952, 76.02),
        (7.143202049, 76.02),
        (7.330314598, 71.65),
        (7.704539696, 71.65),
        (7.891652244, 67.27),
        (8.078764793, 67.27),
        (8.265877342, 62.9),
        (8.640102439, 62.9),
        (8.827214988, 58.52),
        (9.201440085, 58.52),
        (9.388552634, 54.15),
        (9.762777732, 54.15),
        (9.949890281, 49.77),
        (10.69834048, 49.77),
        (10.88545302, 45.4),
        (11.25967812, 45.4),
        (11.44679067, 41.02),
        (12.00812832, 41.02),
        (12.19524087, 36.65),
        (12.56946596, 36.65),
        (12.75657851, 32.27),
        (13.31791616, 32.27),
        (13.50502871, 27.9),
        (14.06636635, 27.9),
        (14.2534789, 23.52),
        (16.49882949, 23.52),
        (16.68594204, 19.15),
        (19.30551772, 19.15),
        (19.49263027, 14.77),
        (26.41579457, 14.77),
        (26.60290712, 10.4),
        (50, 10.4),
        (99.76391368, 10.4),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 3 pF@50V (+0.0%).
    ('epc', 'EPC2619'): [
        (0, 97.45),
        (0.5236087727, 97.45),
        (0.8948867324, 90.18),
        (1.266164692, 90.18),
        (1.637442652, 82.92),
        (2.008720611, 82.92),
        (2.379998571, 75.65),
        (2.751276531, 75.65),
        (3.30819347, 68.39),
        (3.67947143, 68.39),
        (3.86511041, 64.75),
        (4.05074939, 64.75),
        (4.23638837, 61.12),
        (4.607666329, 61.12),
        (4.793305309, 57.49),
        (4.978944289, 57.49),
        (5.164583269, 53.86),
        (5.350222248, 53.86),
        (5.535861228, 50.22),
        (5.907139188, 50.22),
        (6.092778168, 46.59),
        (6.649695107, 46.59),
        (6.835334087, 42.96),
        (7.206612047, 42.96),
        (7.392251027, 39.33),
        (7.949167966, 39.33),
        (8.134806946, 35.69),
        (8.506084906, 35.69),
        (8.691723886, 32.06),
        (9.063001845, 32.06),
        (9.248640825, 28.43),
        (9.991196744, 28.43),
        (10.17683572, 24.8),
        (10.91939164, 24.8),
        (11.10503062, 21.16),
        (11.66194756, 21.16),
        (11.84758654, 17.53),
        (12.77578144, 17.53),
        (12.96142042, 13.9),
        (14.26089328, 13.9),
        (14.44653226, 10.27),
        (18.34495084, 10.27),
        (18.53058982, 6.633),
        (24.47103717, 6.633),
        (24.65667615, 3),
        (50, 3),
        (69.02439233, 3),
        (69.21003131, 1e-12),
        (100.2117409, 1e-12),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 450 pF@50V (-0.7%).
    ('infineon', 'IPT009N10NM8ATMA1'): [
        (0, 2315),
        (0.0945558064, 2315),
        (0.8653959416, 2172),
        (2.021656144, 1794),
        (5.87585682, 1540),
        (11.84986787, 1224),
        (17.05303878, 1024),
        (24.18331003, 814),
        (45.76683382, 476.5),
        (50, 447.1),
        (59.64195625, 393.5),
        (79.10566966, 342.1),
        (99.91835331, 325),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 450 pF@50V (+0.6%).
    ('infineon', 'IPF009N10NM8ATMA1'): [
        (0, 2315),
        (0.0945558064, 2315),
        (0.8653959416, 2172),
        (2.021656144, 1794),
        (5.297726719, 1579),
        (11.84986787, 1224),
        (17.05303878, 1024),
        (22.64162976, 856.5),
        (39.02198263, 555.3),
        (42.29805321, 507.9),
        (50, 452.8),
        (57.52214588, 403.7),
        (79.10566966, 342.1),
        (99.91835331, 325),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 40 pF@75V (-1.5%).
    ('infineon', 'IAUTN15S6N025ATMA1'): [
        (0, 1194),
        (0.031575049, 1159),
        (1.290439425, 1074),
        (4.122884272, 829.3),
        (5.381748649, 734.3),
        (9.473057872, 593.6),
        (12.30550272, 509.8),
        (18.91454069, 364.9),
        (28.04130742, 238.4),
        (32.13261665, 195.6),
        (37.16807415, 165.5),
        (39.37108681, 148.8),
        (41.88881556, 140),
        (46.60955697, 118.5),
        (54.79217542, 98.71),
        (61.4012134, 83.51),
        (65.80723871, 69.58),
        (70.21326403, 55.4),
        (75, 39.4),
        (76.82230201, 35.11),
        (78.08116638, 32.05),
        (80.28417904, 25.9),
        (83.11662389, 21.58),
        (86.89321702, 19.11),
        (106.7203309, 15.45),
        (128.1210253, 14.32),
        (149.8364358, 14.1),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 40 pF@75V (-1.5%).
    ('infineon', 'IAUTN15S6N025GATMA1'): [
        (0, 1194),
        (0.031575049, 1159),
        (1.290439425, 1074),
        (4.122884272, 829.3),
        (5.381748649, 734.3),
        (9.473057872, 593.6),
        (12.30550272, 509.8),
        (18.91454069, 364.9),
        (28.04130742, 238.4),
        (32.13261665, 195.6),
        (37.16807415, 165.5),
        (39.37108681, 148.8),
        (41.88881556, 140),
        (46.60955697, 118.5),
        (54.79217542, 98.71),
        (61.4012134, 83.51),
        (65.80723871, 69.58),
        (70.21326403, 55.4),
        (75, 39.4),
        (76.82230201, 35.11),
        (78.08116638, 32.05),
        (80.28417904, 25.9),
        (83.11662389, 21.58),
        (86.89321702, 19.11),
        (106.7203309, 15.45),
        (128.1210253, 14.32),
        (149.8364358, 14.1),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 40 pF@75V (-1.5%).
    ('infineon', 'IAUTN15S6N025TATMA1'): [
        (0, 1194),
        (0.031575049, 1159),
        (1.290439425, 1074),
        (4.122884272, 829.3),
        (5.381748649, 734.3),
        (9.473057872, 593.6),
        (12.30550272, 509.8),
        (18.91454069, 364.9),
        (28.04130742, 238.4),
        (32.13261665, 195.6),
        (37.16807415, 165.5),
        (39.37108681, 148.8),
        (41.88881556, 140),
        (46.60955697, 118.5),
        (54.79217542, 98.71),
        (61.4012134, 83.51),
        (65.80723871, 69.58),
        (70.21326403, 55.4),
        (75, 39.4),
        (76.82230201, 35.11),
        (78.08116638, 32.05),
        (80.28417904, 25.9),
        (83.11662389, 21.58),
        (86.89321702, 19.11),
        (106.7203309, 15.45),
        (128.1210253, 14.32),
        (149.8364358, 14.1),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 92 pF@50V (+3.8%).
    ('nxp', 'PSMN1R3-100ASF'): [
        (0, 1979),
        (0.1090813557, 1979),
        (0.2213493637, 1979),
        (0.2630487643, 1890),
        (0.4981737292, 1890),
        (0.5068466968, 1805),
        (0.8506493696, 1724),
        (0.9273198974, 1647),
        (1.08315789, 1647),
        (1.140720284, 1573),
        (1.28721104, 1573),
        (1.355617455, 1502),
        (1.529705203, 1502),
        (1.610998515, 1435),
        (2.123380971, 1370),
        (2.236224068, 1309),
        (2.847452582, 1250),
        (3.050982354, 1194),
        (3.269059996, 1194),
        (3.383876378, 1140),
        (3.688871123, 1140),
        (4.383807453, 1040),
        (4.697152559, 1040),
        (4.77892775, 993.5),
        (5.778089326, 948.9),
        (5.878683112, 906.3),
        (9.050551008, 754.2),
        (9.208116795, 720.4),
        (9.697464883, 688.1),
        (11.32714356, 657.2),
        (12.13678336, 599.5),
        (13.93381341, 572.6),
        (14.17639447, 546.9),
        (15.72318709, 498.9),
        (17.43875093, 476.5),
        (18.05123718, 444.8),
        (20.36936846, 396.5),
        (22.20529556, 378.7),
        (24.20669801, 330),
        (28.27468279, 274.6),
        (30.29569616, 239.3),
        (30.82312981, 239.3),
        (31.90570409, 218.3),
        (32.46116721, 218.3),
        (33.02630068, 203.7),
        (34.18625503, 199.1),
        (41.33379821, 137.9),
        (47.45387756, 99.99),
        (49.97572484, 95.5),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 29 pF@50V (-2.8%).
    ('onsemi', 'PCFA86062F'): [
        (0, 695.2),
        (0.1020049611, 695.2),
        (0.8055626477, 650.5),
        (0.9529388082, 622.3),
        (2.134520554, 569.5),
        (2.937211082, 521.2),
        (3.248737145, 521.2),
        (3.474568286, 498.6),
        (3.843087452, 498.6),
        (8.048766293, 373.9),
        (10.01347271, 320.2),
        (10.35566176, 320.2),
        (10.7095444, 306.3),
        (11.07552022, 306.3),
        (11.45400248, 293),
        (11.84541857, 293),
        (16.85692549, 214.9),
        (22.80954462, 147.5),
        (25.22876729, 126.3),
        (26.53296223, 113),
        (26.98250761, 113),
        (28.85815658, 101.2),
        (31.91890627, 82.9),
        (33.5689463, 72.58),
        (37.75840971, 56.89),
        (41.06733691, 44.58),
        (46.19261263, 33.43),
        (46.97524953, 31.28),
        (50, 28.18),
        (51.09188692, 27.39),
        (65.73557741, 24.51),
        (72.70761485, 24.51),
        (98.38256603, 22.44),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 29 pF@50V (+0.4%).
    ('onsemi', 'PCFA86062WA'): [
        (0, 718.7),
        (0.1020019064, 718.7),
        (0.8054729682, 672.5),
        (0.9528264175, 643.3),
        (2.134201023, 588.8),
        (2.936734472, 538.9),
        (3.24819709, 538.9),
        (3.473981495, 515.5),
        (3.842423171, 515.5),
        (8.047140775, 386.5),
        (10.01136428, 331),
        (10.35346759, 331),
        (10.70726108, 316.7),
        (11.07314422, 316.7),
        (11.45153013, 302.9),
        (11.84284606, 302.9),
        (16.85303044, 222.2),
        (22.80400253, 152.4),
        (25.22253726, 130.6),
        (26.52635749, 116.9),
        (26.97577311, 116.9),
        (28.85087758, 104.6),
        (31.91072856, 85.7),
        (33.56027924, 75.04),
        (37.74848614, 58.81),
        (41.05640788, 46.09),
        (46.18010574, 34.56),
        (46.96249966, 32.34),
        (50, 29.12),
        (51.07785075, 28.31),
        (65.71686603, 25.34),
        (72.68663033, 25.34),
        (98.35299996, 23.19),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 29 pF@50V (+1.5%).
    ('onsemi', 'NVMFS3D6N10MCLT1G'): [
        (0, 291.2),
        (0.0865197464, 291.2),
        (2.156399797, 249.7),
        (4.785183267, 214.1),
        (9.644702053, 165.8),
        (11.69087242, 149.6),
        (12.18294348, 142.1),
        (12.6957259, 142.1),
        (13.23009144, 135),
        (13.78694853, 135),
        (15.38918579, 121.9),
        (16.03691957, 121.9),
        (17.41532436, 110),
        (18.1483387, 110),
        (20.82194221, 94.35),
        (23.88941955, 85.16),
        (25.5886738, 76.87),
        (26.30175029, 76.87),
        (26.66570599, 73.03),
        (28.56243748, 69.38),
        (28.95767588, 65.92),
        (29.76463594, 65.92),
        (30.17651001, 62.62),
        (31.01743518, 62.62),
        (31.4466451, 59.5),
        (32.32296497, 59.5),
        (32.77024042, 56.53),
        (36.07934796, 51.02),
        (36.57860311, 48.47),
        (38.64567174, 46.05),
        (39.18043891, 43.75),
        (41.39453812, 41.57),
        (43.13684216, 37.52),
        (45.574519, 35.65),
        (50.17659034, 29.04),
        (55.24337446, 24.9),
        (58.36519533, 21.36),
        (60.82179758, 20.29),
        (62.51671128, 18.31),
        (65.14805164, 17.4),
        (66.96352454, 15.71),
        (67.89014562, 15.71),
        (72.71917123, 12.8),
        (73.72543722, 12.8),
        (80.06228361, 9.904),
        (86.94379441, 8.069),
        (90.60327538, 6.919),
        (94.41678461, 6.246),
        (99.75230749, 5.784),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 290 pF@50V (-1.3%).
    ('infineon', 'IPT014N10NM8ATMA1'): [
        (0, 1463),
        (0.0945558064, 1463),
        (0.8653959416, 1390),
        (2.021656144, 1148),
        (5.87585682, 985.5),
        (12.0425779, 773.5),
        (22.64162976, 541.3),
        (50, 286.1),
        (57.52214588, 255.1),
        (77.17856932, 218.9),
        (99.91835331, 205.4),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 92 pF@50V (+3.8%).
    ('nxp', 'PSMN1R4-100CSF'): [
        (0, 1979),
        (0.1090813557, 1979),
        (0.2213493637, 1979),
        (0.2630487643, 1890),
        (0.4981737292, 1890),
        (0.5068466968, 1805),
        (0.8506493696, 1724),
        (0.9273198974, 1647),
        (1.08315789, 1647),
        (1.140720284, 1573),
        (1.28721104, 1573),
        (1.355617455, 1502),
        (1.529705203, 1502),
        (1.610998515, 1435),
        (2.123380971, 1370),
        (2.236224068, 1309),
        (2.847452582, 1250),
        (3.050982354, 1194),
        (3.269059996, 1194),
        (3.383876378, 1140),
        (3.688871123, 1140),
        (4.383807453, 1040),
        (4.697152559, 1040),
        (4.77892775, 993.5),
        (5.778089326, 948.9),
        (5.878683112, 906.3),
        (9.050551008, 754.2),
        (9.208116795, 720.4),
        (9.697464883, 688.1),
        (11.32714356, 657.2),
        (12.13678336, 599.5),
        (13.93381341, 572.6),
        (14.17639447, 546.9),
        (15.72318709, 498.9),
        (17.43875093, 476.5),
        (18.05123718, 444.8),
        (20.36936846, 396.5),
        (22.20529556, 378.7),
        (24.20669801, 330),
        (28.27468279, 274.6),
        (30.29569616, 239.3),
        (30.82312981, 239.3),
        (31.90570409, 218.3),
        (32.46116721, 218.3),
        (33.02630068, 203.7),
        (34.18625503, 199.1),
        (41.33379821, 137.9),
        (47.45387756, 99.99),
        (49.97572484, 95.5),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 290 pF@50V (-1.3%).
    ('infineon', 'IPF014N10NM8ATMA1'): [
        (0, 1463),
        (0.0945558064, 1463),
        (0.8653959416, 1390),
        (2.021656144, 1148),
        (5.87585682, 985.5),
        (12.0425779, 773.5),
        (22.64162976, 541.3),
        (50, 286.1),
        (57.52214588, 255.1),
        (77.17856932, 218.9),
        (99.91835331, 205.4),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 190 pF@50V (+0.1%).
    ('infineon', 'ISC019N10NM8SCATMA1'): [
        (0, 973),
        (0.0945558064, 973),
        (0.8653959416, 924.6),
        (2.021656144, 763.7),
        (5.87585682, 655.4),
        (11.84986787, 521),
        (16.86032875, 435.8),
        (22.64162976, 359.9),
        (32.27713145, 275.4),
        (44.99599368, 205.4),
        (50, 190.3),
        (59.64195625, 167.5),
        (81.03277, 143.7),
        (99.91835331, 136.6),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 190 pF@50V (+0.1%).
    ('infineon', 'ISC019N10NM8ATMA1'): [
        (0, 973),
        (0.0945558064, 973),
        (0.8653959416, 924.6),
        (2.021656144, 763.7),
        (5.87585682, 655.4),
        (11.84986787, 521),
        (16.86032875, 435.8),
        (22.64162976, 359.9),
        (32.27713145, 275.4),
        (44.99599368, 205.4),
        (50, 190.3),
        (59.64195625, 167.5),
        (81.03277, 143.7),
        (99.91835331, 136.6),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 30 pF@50V (-9.3%).
    ('crmicro', 'CRSZ016N10N4Z'): [
        (0, 1010),
        (0.5753803988, 971.6),
        (4.066313875, 713.2),
        (6.73585124, 611),
        (10.02143569, 513.5),
        (14.53911431, 407.2),
        (16.38725556, 369.7),
        (21.72633029, 271.4),
        (26.86005599, 188),
        (30.35098946, 135.3),
        (32.19913072, 109.4),
        (34.86866808, 72.92),
        (35.27936614, 66.21),
        (37.9489035, 43.28),
        (40.41309184, 34.99),
        (43.0826292, 31.16),
        (50, 27.22),
        (53.96612769, 25.68),
        (99.96430997, 20.37),
    ],
    # human overlay review GREEN (fugu2-100v-LS2p-gan-coss-scalar-top50 001); export anchors: Crss 115 pF@50V (+4.5%).
    ('nxp', 'PSMN1R4-100ASE'): [
        (0, 1435),
        (0.1090813557, 1435),
        (0.2175617178, 1402),
        (0.2213493637, 1370),
        (0.4192015054, 1370),
        (0.5156706565, 1309),
        (0.6915140348, 1309),
        (0.7803179378, 1250),
        (1.028500178, 1250),
        (1.102015154, 1194),
        (1.28721104, 1194),
        (1.37921811, 1140),
        (1.610998515, 1140),
        (1.726149216, 1089),
        (2.437778887, 1040),
        (2.480219457, 993.5),
        (2.94746121, 993.5),
        (3.104098505, 948.9),
        (3.563706138, 948.9),
        (3.625748566, 906.3),
        (4.460127455, 865.7),
        (4.946773918, 826.8),
        (5.032894898, 789.7),
        (5.679216863, 789.7),
        (6.520108805, 754.2),
        (6.633620797, 720.4),
        (7.10777771, 720.4),
        (7.231520738, 688.1),
        (9.050551008, 657.2),
        (9.208116795, 627.7),
        (9.866293132, 627.7),
        (10.0380606, 599.5),
        (11.92910335, 572.6),
        (12.13678336, 546.9),
        (13.46103312, 522.3),
        (13.6953833, 498.9),
        (15.99692029, 476.5),
        (16.27541906, 455.1),
        (18.68523525, 415.2),
        (19.0105363, 396.5),
        (21.45186032, 378.7),
        (25.05688904, 301),
        (30.29569616, 250.5),
        (30.82312981, 239.3),
        (32.46116721, 228.5),
        (34.78142146, 199.1),
        (40.62651001, 165.7),
        (47.45387756, 120.2),
        (49.97572484, 120.2),
    ],

    # human overlay review GREEN (fugu2-coss-scalar-top25 001); export anchors: Crss 77 pF@50V (-4.5%).
    ('nce', 'NCEP023N10'): [
        (0, 1788),
        (0.9669343286, 1788),
        (1.409768177, 1747),
        (1.852602025, 1452),
        (2.295435873, 1324),
        (3.18110357, 1235),
        (4.361993832, 1050),
        (4.952438963, 1050),
        (5.690495377, 957.6),
        (7.609442052, 873),
        (7.757053335, 833.6),
        (8.495109749, 833.6),
        (8.642721031, 795.9),
        (10.70927899, 725.6),
        (10.85689027, 692.8),
        (15.7280626, 549.8),
        (15.87567389, 524.9),
        (20.59923493, 416.6),
        (20.74684622, 397.7),
        (26.50368624, 287.8),
        (27.38935394, 262.3),
        (28.12741035, 262.3),
        (28.27502164, 250.5),
        (31.67008114, 208.2),
        (32.40813755, 189.8),
        (33.14619397, 189.8),
        (33.29380525, 181.2),
        (35.65558577, 157.7),
        (35.80319706, 150.6),
        (36.39364219, 150.6),
        (36.54125347, 143.8),
        (37.57453245, 137.3),
        (37.72214373, 131.1),
        (40.82198067, 104),
        (41.56003708, 104),
        (41.70764837, 99.34),
        (43.03614991, 90.56),
        (44.21704017, 90.56),
        (44.51226274, 86.47),
        (47.16926583, 78.83),
        (48.49776737, 78.83),
        (48.64537866, 75.27),
        (50, 73.55),
        (55.58310894, 65.52),
        (55.73072023, 62.56),
        (60.74950384, 59.73),
        (61.04472641, 57.03),
        (64.29217463, 57.03),
        (64.43978591, 54.45),
        (79.20091418, 49.64),
    ],

    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Crss 13 pF@50V (+0.0%).
    ('goford', 'GT080N10T'): [
        (0, 3.48),
        (0.5142975213, 3.48),
        (25.47853796, 3.48),
        (25.60212331, 32.04),
        (27.0851475, 32.04),
        (27.20873284, 22.52),
        (30.66912261, 22.52),
        (30.79270796, 13),
        (50, 13),
        (59.46450886, 13),
    ],
    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Crss 95 pF@50V (+1.4%).
    ('vishay', 'SUP70060E'): [
        (0, 999.1),
        (0.0961025031, 999.1),
        (0.3669894464, 922.2),
        (0.6378763896, 826.2),
        (1.179650276, 749.4),
        (1.992311106, 614.9),
        (2.804971936, 557.3),
        (3.075858879, 518.9),
        (3.346745822, 518.9),
        (4.159406652, 461.3),
        (4.972067482, 442.1),
        (5.784728311, 403.7),
        (6.055615255, 403.7),
        (6.326502198, 384.5),
        (6.868276084, 384.5),
        (7.680936914, 346),
        (8.222710801, 346),
        (8.493597744, 326.8),
        (9.306258574, 326.8),
        (9.577145517, 307.6),
        (10.1189194, 307.6),
        (10.38980635, 288.4),
        (11.20246718, 288.4),
        (11.47335412, 269.2),
        (12.55690189, 269.2),
        (12.82778884, 250),
        (13.64044967, 250),
        (13.91133661, 230.8),
        (15.53665827, 230.8),
        (15.80754521, 211.6),
        (17.43286687, 211.6),
        (17.70375381, 192.4),
        (20.1417363, 192.4),
        (20.41262325, 173.2),
        (23.12149268, 173.2),
        (23.39237962, 154),
        (27.45568377, 154),
        (27.72657071, 134.8),
        (33.14430958, 134.8),
        (33.41519652, 115.6),
        (42.35446565, 115.6),
        (42.62535259, 96.36),
        (50, 96.36),
        (55.62792587, 96.36),
        (55.89881281, 77.15),
        (81.90395936, 77.15),
        (82.17484631, 57.94),
        (100.0533846, 57.94),
    ],
    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Crss 12 pF@50V (+0.0%).
    ('ao', 'AOTF296L'): [
        (0, 185.4),
        (1.144065977, 185.4),
        (1.891839695, 185.4),
        (2.141097601, 174.6),
        (2.390355507, 174.6),
        (2.639613413, 163.7),
        (2.888871319, 163.7),
        (3.138129225, 152.9),
        (3.636645036, 152.9),
        (3.885902942, 142),
        (5.879966189, 142),
        (6.129224095, 131.2),
        (6.378482001, 131.2),
        (6.627739907, 120.4),
        (8.87106106, 120.4),
        (9.369576872, 98.7),
        (12.11141384, 98.7),
        (12.60992965, 77.02),
        (15.85028243, 77.02),
        (16.09954033, 66.19),
        (16.34879824, 66.19),
        (16.59805614, 55.35),
        (19.58915101, 55.35),
        (19.83840892, 44.51),
        (20.08766683, 44.51),
        (20.33692473, 33.67),
        (23.57727751, 33.67),
        (23.82653541, 22.84),
        (24.32505123, 22.84),
        (24.57430913, 12),
        (50, 12),
        (98.85316509, 12),
    ],
    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Crss 12 pF@50V (+0.0%).
    ('ao', 'AOT296L'): [
        (0, 242.4),
        (0.3994478906, 242.4),
        (0.8774197226, 221.5),
        (1.355391555, 221.5),
        (1.594377471, 211),
        (1.833363387, 211),
        (2.072349303, 200.5),
        (2.550321135, 200.5),
        (2.789307051, 190.1),
        (3.028292967, 190.1),
        (3.267278883, 179.6),
        (4.223222546, 179.6),
        (4.462208462, 169.1),
        (5.418152126, 169.1),
        (5.657138042, 158.6),
        (6.613081707, 158.6),
        (6.852067622, 148.2),
        (7.808011287, 148.2),
        (8.046997203, 137.7),
        (9.241926783, 137.7),
        (9.480912698, 127.2),
        (10.67584228, 127.2),
        (10.91482819, 116.7),
        (12.34874369, 116.7),
        (12.58772961, 106.3),
        (14.26063102, 106.3),
        (14.49961693, 95.79),
        (15.93353243, 95.79),
        (16.17251835, 85.32),
        (18.08440567, 85.32),
        (18.32339159, 74.84),
        (19.75730709, 74.84),
        (19.996293, 64.37),
        (22.14716625, 64.37),
        (22.38615216, 53.9),
        (23.82006766, 53.9),
        (24.05905357, 43.42),
        (25.73195499, 43.42),
        (25.9709409, 32.95),
        (27.4048564, 32.95),
        (27.64384231, 22.47),
        (45.56778601, 22.47),
        (45.80677193, 12),
        (50, 12),
        (100.0565749, 12),
    ],
    # human overlay review GREEN (fugu2-coss-scalar-top30 001); export anchors: Crss 13 pF@50V (-2.8%).
    ('mcc', 'MCP75N10Y-BP'): [
        (0, 151.2),
        (0.4115653884, 142.8),
        (0.8331539268, 142.8),
        (2.097919542, 123.8),
        (2.308713811, 117),
        (5.049039311, 98.56),
        (6.313804927, 87.93),
        (6.735393465, 87.93),
        (7.156982003, 83.05),
        (7.578570542, 83.05),
        (8.843336157, 74.1),
        (9.264924696, 74.1),
        (9.686513234, 69.99),
        (12.84842727, 57.32),
        (14.11319289, 51.14),
        (14.53478143, 51.14),
        (14.95636996, 48.31),
        (15.3779585, 48.31),
        (15.79954704, 45.63),
        (18.75066681, 37.37),
        (20.2262267, 35.3),
        (22.96655219, 29.75),
        (23.598935, 29.75),
        (24.23131781, 28.1),
        (25.49608343, 27.31),
        (28.44720319, 23.68),
        (36.45738543, 18.32),
        (37.3005625, 18.32),
        (38.35453385, 17.3),
        (39.19771093, 17.3),
        (41.30565362, 15.88),
        (45.31074473, 14.58),
        (45.521539, 14.17),
        (46.57551035, 14.17),
        (49.94821866, 12.64),
        (51.00219, 12.64),
        (52.26695562, 11.94),
        (55.21807539, 11.6),
        (55.42886965, 11.28),
        (60.06634358, 10.96),
        (60.27713785, 10.65),
        (64.7038175, 10.65),
        (64.91461177, 10.35),
        (71.44923412, 10.35),
        (71.66002839, 10.06),
        (78.61623927, 10.06),
        (78.82703354, 9.78),
        (99.90646046, 9.237),
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
