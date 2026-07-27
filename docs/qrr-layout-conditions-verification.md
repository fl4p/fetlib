# Verification sheet: machine-read Qrr test conditions

`dslib/qrr_layout_conditions.py` holds 409 entries read from the datasheet TABLE
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

### infineon / IRFB4620PBF
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

### infineon / IAUTN12S5N018GATMA1
- read as: **IF = 50 A**, **di/dt = 100 A/µs**, VR = 60, Tj = 25 °C
- datasheet block:
```
Reverse recovery time2) t rr V R=60 V, I F=50A, – 45 67 ns
di F/dt =100 A/µs
Reverse recovery charge2) Q rr – 34 68 nC
1)
Practically the current is limited by the overall system design including the customer-specific PCB.
```

### onsemi / FDBL86066-F085
- read as: **IF = 80 A**, **di/dt = 300 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time IF = 80 A, dISD/dt = 300 A/ms − 36 54 ns
Qrr Reverse Recovery Charge − 84 126 nC
trr Reverse Recovery Time IF = 80 A, dISD/dt = 1000 A/ms − 32 48 ns
Qrr Reverse Recovery Charge − 243 365 nC
```

### onsemi / NTBLS002N08MC
- read as: **IF = 40 A**, **di/dt = 300 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse Recovery Time tRR 35 nS
IF = 40 A, di/dt = 300 A/ms
Reverse Recovery Charge QRR 74 nC
Reverse Recovery Time tRR 27 nS
IF = 40 A, di/dt = 1000 A/ms
```

### huayi / HYG090N15NS1P
- read as: **IF = 50 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time - 87 - ns
ISD=50A,dISD/dt=100A/μs
Qrr Reverse Recovery Charge - 251 - nC
```

### huayi / HYG065N10LS1P
- read as: **IF = 20 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time - 44.1 - ns
ISD=20A,dISD/dt=100A/μs
Qrr Reverse Recovery Charge - 53.4 - nC
```

### ao / AOTL66811
- read as: **IF = 20 A**, **di/dt = 500 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Body Diode Reverse Recovery Time IF=20A, di/dt=500A/ms 40 ns
Qrr Body Diode Reverse Recovery Charge IF=20A, di/dt=500A/ms 233 nC
A. The value of RqJA is measured with the device mounted on 1in2 FR-4 board with 2oz. Copper, in a still air environment with TA =25°C. The
```

### ao / AONS66916T
- read as: **IF = 20 A**, **di/dt = 500 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Body Diode Reverse Recovery Time IF=20A, di/dt=500A/ms 42 ns
Qrr Body Diode Reverse Recovery Charge IF=20A, di/dt=500A/ms 215 nC
A. The value of RqJA is measured with the device mounted on 1in2 FR-4 board with 2oz. Copper, in a still air environment with TA =25°C. The
```

### xnrusemi / XRS125N12HT
- read as: **IF = 40 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
t rr Reverse Recovery time I S =40A, -- 60 -- ns
Q rr Reverse Recovery Charge dI/dt=100A/μs -- 109 -- nC
a1
：Repetitive rating; pulse width limited by maximum junction temperature
```

### xnrusemi / XRS150P10H
- read as: **IF = 22 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
trr Reverse Recovery Time IF=-22A , di/dt=100A/µs , --- 86 --- nS
Qrr Reverse Recovery Charge TJ= 2 5 C --- 271 --- nC
a1：Repetitive rating; pulse width limited by maximum junction temperature
```

### toshiba / TK34A10N1
- read as: **IF = 34 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse recovery time (Note 6) trr IDR = 34 A, VGS = 0 V  61  ns
-dIDR/dt = 100 A/µs
Reverse recovery charge (Note 6) Qrr  110  nC
Note 5: Ensure that the channel temperature does not exceed 150.
```

### toshiba / TK42A12N1
- read as: **IF = 42 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse recovery time (Note 6) trr IDR = 42 A, VGS = 0 V  80  ns
-dIDR/dt = 100 A/µs
Reverse recovery charge (Note 6) Qrr  190  nC
Note 5: Ensure that the channel temperature does not exceed 150.
```

### siliup / SP010P16GHTQ
- read as: **IF = 20 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse Recovery Time Trr - 96 - nS
IS=-20A, di/dt=100A/us, TJ=25℃
Reverse Recovery Charge Qrr - 205 - nC
Note :
```

### siliup / SP025N16GHTO
- read as: **IF = 20 A**, **di/dt = 200 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse Recovery Time Trr - 168 - nS
IS=20A, di/dt=200A/us, TJ=25℃
Reverse Recovery Charge Qrr - 795 - nC
Note :
```

### nce / NCEP02T10
- read as: **IF = 50 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse Recovery Time trr TJ = 25°C, IF = 50A - 140 nS
Reverse Recovery Charge Qrr di/dt = 100A/μs - 600 nC
```

### nce / NCEP02T10D
- read as: **IF = 50 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Reverse Recovery Time trr TJ = 25°C, IF = 50A - 140 nS
Reverse Recovery Charge Qrr di/dt = 100A/μs - 600 nC
```

### st / STD20NF20
- read as: **IF = 20 A**, **di/dt = 100 A/µs**, VR = 50, Tj = 25 °C
- datasheet block:
```
trr Reverse recovery time ISD = 20 A, di/dt = 100A/µs 155 ns
Qrr Reverse recovery charge VDD = 50 V - 775 nC
IRRM Reverse recovery current (see Figure 20) 10 A
trr Reverse recovery time ISD = 20 A, di/dt = 100 A/µs 183 ns
```

### st / STF100N10F7
- read as: **IF = 80 A**, **di/dt = 100 A/µs**, VR = 80, Tj = 150 °C
- datasheet block:
```
trr Reverse recovery time ISD = 80 A, di/dt = 100 A/µs - 77 ns
Qrr Reverse recovery charge VDD = 80 V, TJ = 150 °C - 146 nC
(see Figure 18. Test circuit for inductive load
IRRM Reverse recovery current - 4 A
```

### vishay / SIDR510EP-T1-RE3
- read as: **IF = 10 A**, **di/dt = 100 A/µs**, VR = None, Tj = 25 °C
- datasheet block:
```
Body diode reverse recovery time trr - 56 102 ns
Body diode reverse recovery charge Qrr IF = 10 A, di/dt = 100 A/μs, - 65 130 nC
Reverse recovery fall time ta TJ = 25 °C - 26 -
ns
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


## Vendor spread

| mfr | entries |
|---|--:|
| infineon | 130 |
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
