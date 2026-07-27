# Spot-check: parsed Qrr test conditions

4055 of 6040 datasheets yield a parsed test point. Check the parsed IF / di-dt against the datasheet PDF.

`x@op` = charge rescale the LM fit predicts at IF=33.3 A, di/dt=4000 A/us (the fugu3 point) -- a sanity number, not a claim.

Sample = 2 random parts from each of the 12 largest vendors, plus the 4 lowest and 4 highest
rescales (the tails are where a bad parse shows up). An empty "text captured" cell means the
condition came from a structured table cell rather than a free-text string, not that it was guessed.

**What to check, in priority order**

1. **IF and di/dt against the PDF.** These two set the charge; everything else is informational.
   Qrr goes as roughly di/dt^0.8, so a wrong di/dt is the expensive error.
2. **The two `Tj` outliers.** `st STD85N10F7AG` reads Tj=150 -- ST quotes some parts only at
   150 C, but confirm it is not the hot row's condition attached to the cold row's charge.
3. **`VR` on IXYS/Littelfuse rows** (`IXFN82N60Q3` shows VR=0.5). That is "VR = 0.5 * VDSS" with
   the multiplier captured. VR is informational and does not enter the Lauritzen-Ma fit, so it
   costs nothing today -- but the same pattern on `IF` is what the rating and IRRM guards exist
   to reject, and it confirms the pattern is real.
4. **The `ao` rows**, whose captured text is boilerplate ("AOS RESERVES..."). The values look
   right (20 A / 500 A/us) but the text came from the wrong cell, so the provenance is weak
   even where the number is not.

Known-good anchor: every entry in `dslib/qrr_conditions.py` (hand-read) is reproduced exactly
by this path, and all 79 `dslib/qrr_points.py` dies in the DB pair to a real datasheet row.

| mfr | mpn | Qrr nC | trr ns | IF A | di/dt A/us | Tj | VR | x@op | datasheet text captured |
|---|---|--:|--:|--:|--:|--:|--:|--:|---|
| infineon | IPW65R041CFD7 | 1200.0 | 177.0 | 24.8 | 100 | 25 | 400.0 | 3.8 | `VR=400V, IF=24.8A, di /dt=100A/μs;Reverse recovery charge` |
| infineon | IPT60R125CFD7XTMA1 | 380.0 | 95.0 | 8.1 | 100 | 25 | 400.0 | 7.5 | `VR=400V, IF=8.1A, diF/dt=100A/μs; Reverse recovery charge` |
| hxy | IPZA65R025CM8XKSA1-HXY | 184.0 | 16.0 | 40 | 3800 | 25 | 400.0 | 0.9 | `` |
| hxy | STWA65N023M9-HXY | 238.0 | 19.0 | 40 | 2200 | 25 | 400.0 | 1.2 | `GS = -4V, ISD = 40A , VR = 400V` |
| littelfuse | IXFN82N60Q3 | 1900.0 | 300.0 | 41 | 100 | 25 | 0.5 | 2.5 | `IF = 41A, -di/dt = 100A/μs` |
| littelfuse | IXTT220N20X4HV | 770.0 | 140.0 | 110 | 100 | 25 | 100.0 | 4.1 | `IF = 110A, -di/dt = 100A/μs` |
| toshiba | TK55S10N1,LQ | 73.0 | 75.0 | 55 | 50 | 25 | - | 15.4 | `-dIDR/dt = 50 A/μs` |
| toshiba | TK073E60Z5 | 690.0 | 126.0 | 16 | 100 | 25 | 400.0 | 5.1 | `IDR = 16 A, VGS = 0 V -dIDR/dt = 100 A/μs` |
| onsemi | NVMFS6H800NLT1G | 110.0 | 77.0 | 50 | 100 | 25 | - | 7.9 | `TYPICAL CHARACTERISTICS` |
| onsemi | NVTFS6H854NLTAG | 25.0 | 32.0 | 20 | 100 | 25 | - | 15.1 | `TYPICAL CHARACTERISTICS` |
| st | STD85N10F7AG | 125.0 | 70.0 | 70 | 100 | 150 | 80.0 | 8.2 | `` |
| st | STW35N65DM2 | 420.0 | 100.0 | 32 | 100 | 25 | 60.0 | 5.4 | `` |
| vishay | SUM60020E | 182.0 | 80.0 | 33.3 | 100 | 25 | - | 7.2 | `Reverse recovery charge Q IF = 33.3 A, di/dt = 100 A/μsrr` |
| vishay | SUM60N10-17 | 500.0 | 125.0 | 50 | 100 | 25 | - | 4.8 | `` |
| huayi | HY3008PM | 127.0 | 62.0 | 50 | 100 | 25 | - | 8.5 | `` |
| huayi | HYG012N08NS2B6 | 174.0 | 104.0 | 100 | 100 | 25 | - | 6.2 | `` |
| siliup | SP012N03BGHTF | 183.0 | 92.0 | 100 | 100 | 25 | 50.0 | 6.6 | `` |
| siliup | SP010N02GHTF | 328.0 | 106.0 | 50 | 100 | 25 | 50.0 | 5.6 | `` |
| nxp | PSMN1R8-80SSF | 59.0 | 56.0 | 25 | 100 | 25 | 40.0 | 10.3 | `IS = 25 A; dIS/dt = -100 A/μs; VGS = 0 V;VDS = 40 V; Tj = 25 °C; Fig. 17` |
| nxp | PSMN3R8-100BS,118 | 235.0 | 75.0 | 25 | 100 | 25 | 50.0 | 6.9 | `` |
| nce | NCEP033N85 | 147.0 | 80.0 | 80 | 100 | 25 | - | 7.4 | `di/dt = 100A/μs(Note3)` |
| nce | NCEP065N10AGU | 135.0 | 55.0 | 45 | 100 | 25 | - | 8.6 | `di/dt = 100A/μs(Note3)Reverse Recovery Charge Qrr` |
| ao | AOI296A | 150.0 | 30.0 | 20 | 500 | 25 | 50.0 | 3.4 | `NOT ASSUME ANY LIABILITY ARISING OUT OF SUCH APPLICATIONS OR USES OF ITS PRODUCTS.  AOS RE` |
| ao | AON6226 | 150.0 | 30.0 | 20 | 500 | 25 | - | 3.4 | `ASSUME ANY LIABILITY ARISING OUT OF SUCH APPLICATIONS OR USES OF ITS PRODUCTS.  AOS RESERV` |
| littelfuse | IXKN45N80C | 45.0 | 500.0 | 80 | 400 | 25 | 480.0 | 0.6 | `IF = 80 A; -diF /dt = 400 A/μs; VR = 480 V` |
| hxy | DIW065SIC015-HXY | 555.0 | 28.0 | 80 | 3000 | 25 | 400.0 | 0.7 | `` |
| nce | NCES075P013T | 597.0 | 22.4 | 60 | 3930 | 25 | 500.0 | 0.7 | `` |
| nce | NCES075P013LL | 597.0 | 22.4 | 60 | 3930 | 25 | 500.0 | 0.7 | `` |
| huayi | HYG040N04LS1D | 8.6 | 18.0 | 20 | 100 | 25 | - | 21.7 | `` |
| infineon | BSL296SN | 37.0 | 20.0 | 1.4 | 200 | 25 | 50.0 | 22.9 | `di F/dt =200 A/μsReverse recovery charge 2) Q rr` |
| infineon | IAUZN08S7L177 | 3.1 | 15.0 | 35 | 100 | 25 | 40.0 | 26.2 | `di F/dt = 100 A/μsReverse recovery charge 2) Q rr` |
| infineon | IAUCN08S7L110 | 2.9 | 15.0 | 40 | 100 | 25 | 40.0 | 26.3 | `di F/dt = 100 A/μsReverse recovery charge 2) Q rr` |

## Vendor spread of accepted test points

| mfr | parts |
|---|--:|
| infineon | 1293 |
| hxy | 297 |
| littelfuse | 296 |
| toshiba | 284 |
| onsemi | 280 |
| st | 274 |
| vishay | 236 |
| huayi | 154 |
| siliup | 151 |
| nxp | 141 |
| nce | 135 |
| ao | 131 |
| goford | 108 |
| mcc | 54 |
| crmicro | 39 |
| diodes | 38 |
| ts | 33 |
| xnrusemi | 31 |
| ti | 28 |
| good_ark | 11 |
| diotec | 11 |
| rohm | 11 |
| yageo_xsemi | 11 |
| panjit | 7 |
| renesas | 1 |
