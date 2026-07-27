# Verification sheet: machine-read Qrr test conditions

`dslib/qrr_layout_conditions.py` holds 403 entries read from the datasheet TABLE
LAYOUT by `apps/emit_qrr_layout_conditions.py`. They are NOT human-verified. They rank
below the hand-curated `dslib/qrr_conditions.py` and carry `source="layout"`, surfacing
in the CSV as `Qrr_src=op-1pt-layout`.

**What to check:** the `IF` and `di/dt` below must match the datasheet block quoted
underneath each row. Those two set the charge; VR is informational and does not enter
the Lauritzen-Ma fit. Every entry already passed a value cross-check (the Qrr/trr in the
block matched what the DB parsed independently), an LM fit, and an IRRM <= 5x IF bound —
so what remains to check by eye is whether the block itself is the right one.

**Two things that look wrong but are not:**

- `A/ms` in the block is the m/µ glyph substitution this corpus shows throughout
  (see `dslib/pdf/fix_encoding.py`); it is read as A/µs. The reading is corroborated,
  not assumed: at the literal A/ms the Lauritzen-Ma fit is physically absurd and the
  IRRM bound rejects it, so a wrong reading here fails closed.
- blocks showing both a 25 °C and a 125 °C row: the entry takes the 25 °C one, and the
  value cross-check confirms it is the row the DB parsed its Qrr from.

2 random entries from each of the 10 largest vendors:

### infineon / IRFS4620TRLPBF
- read as: **IF = 15 A**, **di/dt = 100 A/µs**, VR = 100, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time ––– 78 ––– TJ = 25°C VR = 100V,
ns
––– 99 ––– TJ = 125°C IF = 15A
Qrr Reverse Recovery Charge ––– 294 ––– TJ = 25°C di/dt = 100A/µs f
nC
––– 432 ––– TJ = 125°C
```

### infineon / IRFP4227PBF
- read as: **IF = 46 A**, **di/dt = 100 A/µs**, VR = 50, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time ––– 100 150 ns TJ = 25°C, IF = 46A, VDD = 50V
Qrr Reverse Recovery Charge ––– 430 640 nC di/dt = 100A/µs e
```

### onsemi / NTB011N15MC
- read as: **IF = 41 A**, **di/dt = 300 A/µs**, VR = 75, Tj = 25 °C
- datasheet block:
```
Reverse Recovery Time tRR VGS = 0 V, VDD = 75 V 49 ns
Reverse Recovery Charge QRR dIS/dt = 300 A/ms, IS = 41 A 210 nC
Reverse Recovery Time tRR VGS = 0 V, VDD = 75 V 36 ns
Reverse Recovery Charge QRR dIS/dt = 1000 A/ms, IS = 41 A 421 nC
```

### onsemi / FDMS004N08C
- read as: **IF = 22 A**, **di/dt = 300 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time 26 41 ns
IF = 22 A, di/dt = 300 A/μs
Qrr Reverse Recovery Charge 48 76 nC
trr Reverse Recovery Time 19 31 ns
IF = 22 A, di/dt = 1000 A/μs
```

### huayi / HY1420P
- read as: **IF = 30 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time - 48 - ns
ISD=30A,dISD/dt=100A/μs
Qrr Reverse Recovery Charge - 78 - nC
```

### huayi / HYG200N12NS1P
- read as: **IF = 30 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time - 44 - ns
ISD=30A,dISD/dt=100A/μs
Qrr Reverse Recovery Charge - 81.1 - nC
```

### ao / AONS66908
- read as: **IF = 20 A**, **di/dt = 500 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Body Diode Reverse Recovery Time IF=20A, di/dt=500A/ms 40 ns
Qrr Body Diode Reverse Recovery Charge IF=20A, di/dt=500A/ms 260 nC
A. The value of RqJA is measured with the device mounted on 1in 2 FR-4 board with 2oz. Copper, in a still air environment with TA =25°C. The Power
```

### ao / AOT66914L
- read as: **IF = 20 A**, **di/dt = 500 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Body Diode Reverse Recovery Time IF=20A, di/dt=500A/ms 55 ns
Qrr Body Diode Reverse Recovery Charge IF=20A, di/dt=500A/ms 335 nC
A. The value of RqJA is measured in a still air environment with TA =25°C. The Power dissipation PDSM is based on R qJA t≤ 10s and the maximum
```

### xnrusemi / XRS50N15F
- read as: **IF = 20 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time IF=20A ,di/dt=100A / µs , --- 70 --- nS
Qrr Reverse Recovery Charge TJ= 2 5 C --- 154.7 --- nC
```

### xnrusemi / XRS30N10D
- read as: **IF = 10 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time IF=10A , di/dt=100A/µs , --- 39 --- nS
Reverse Recovery Charge TJ= 2 5 C 30 nC
Qrr --- ---
```

### toshiba / TK22A10N1
- read as: **IF = 22 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse recovery time (Note 6) trr IDR = 22 A, VGS = 0 V  54  ns
-dIDR/dt = 100 A/µs
Reverse recovery charge (Note 6) Qrr  94  nC
Note 5: Ensure that the channel temperature does not exceed 150.
```

### toshiba / TK72E12N1
- read as: **IF = 72 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse recovery time (Note 7) trr IDR = 72 A, VGS = 0 V  110  ns
-dIDR/dt = 100 A/µs
Reverse recovery charge (Note 7) Qrr  290  nC
Note 6: Ensure that the channel temperature does not exceed 150.
```

### siliup / SP020N09GHTO
- read as: **IF = 50 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Body Diode Reverse Recovery Time Trr 128 nS
IS = 50A, dIF/dt = 100A/us
Body Diode Reverse Recovery Charge Qrr 643 nC
```

### siliup / SP1012CP8
- read as: **IF = 3 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse Recovery Time Trr - 35 - nS
IS=3A, di/dt=100A/us, TJ=25℃
Reverse Recovery Charge Q rr - 26 - nC
```

### nce / NCEP02T10
- read as: **IF = 50 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse Recovery Time trr TJ = 25°C, IF = 50A - 140 nS
Reverse Recovery Charge Qrr di/dt = 100A/μs - 600 nC
```

### nce / NCE0140IA
- read as: **IF = 20 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse Recovery Time trr TJ = 25°C, IF = 20A - 33 nS
(Note3)
Reverse Recovery Charge Qrr di/dt = 100A/μs - 54 nC
Forward Turn-On Time ton Intrinsic turn-on time is negligible (turn-on is dominated by LS+LD)
```

### st / STP100N10F7
- read as: **IF = 80 A**, **di/dt = 100 A/µs**, VR = 80, Tj = 150 °C
- datasheet block:
```
trr Reverse recovery time ISD = 80 A, di/dt = 100 A/µs - 77 ns
Qrr Reverse recovery charge VDD = 80 V, TJ = 150 °C - 146 nC
(see Figure 18. Test circuit for inductive load
IRRM Reverse recovery current - 4 A
```

### st / STP80NF10FP
- read as: **IF = 80 A**, **di/dt = 100 A/µs**, VR = 50, Tj = 150 °C
- datasheet block:
```
trr Reverse recovery time 155 ns
ISD=80A, VDD = 50V
Qrr Reverse recovery charge 850 nC
di/dt = 100A/µs,Tj=150°C
IRRM Reverse recovery current 11 A
```

### vishay / SiDR570EP
- read as: **IF = 20 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Body diode reverse recovery time trr - 84 168 ns
Body diode reverse recovery charge Qrr IF = 20 A, di/dt = 100 A/μs, - 221 442 nC
Reverse recovery fall time ta TJ = 25 °C - 65 -
ns
```

### vishay / SIDR5102EP-T1-RE3
- read as: **IF = 10 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Body diode reverse recovery time trr - 53 106 ns
Body diode reverse recovery charge Qrr IF = 10 A, di/dt = 100 A/μs, - 67 134 nC
Reverse recovery fall time ta TJ = 25 °C - 25 -
ns
```


## Vendor spread

| mfr | entries |
|---|--:|
| infineon | 124 |
| onsemi | 75 |
| huayi | 38 |
| ao | 35 |
| xnrusemi | 33 |
| toshiba | 24 |
| siliup | 17 |
| nce | 16 |
| st | 11 |
| vishay | 11 |
| hxy | 4 |
| rohm | 4 |
| goford | 3 |
| good_ark | 3 |
| yageo_xsemi | 3 |
| crmicro | 1 |
| mcc | 1 |
