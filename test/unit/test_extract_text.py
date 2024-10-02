import math

test_stream_todo = """

Qgs
Test Condition
VDD ≈ 40 V, VGS = 10 V, ID = 35 A
-
77
100
nC
>Qgs=(n,77,100)


Total Gate Charge at 10 V
VDS = 75 V, ID = 100 A, VGS = 10 V
(Note 4)
-
77
100
nC
Qgs
Gate to Source Gate Charge
-
26
-
> Qgs=(n,77,100)



Total Gate Charge Sync. (Qg - Qgd)
---
275
---


#IRFS7730TRLPBF
Coss eff.(ER)
Effective Output Capacitance
(Energy Related)
---
1060
---
VGS = 0V, VDS = 0V to 60V
Coss eff.(TR)
> Coss=(n,1060,n)



Coss eff. (ER)
Effective Output Capacitance (Energy Related) ---
420
---
Coss eff. (TR)
Effective Output Capacitance (Time Related)
---
690
---
Diode Characteristics
"""

##########################################
test_stream = """

Qgs
VGS  = 10V, VDS = 0.5 * VDSS, ID = 0.5 * ID25
185

nC
> Qgs=(n,185,n)


Qgs
VGS = 10V, VDS = 0.5 * VDSS, ID = 0.5 * ID25
30
nC
> Qgs=(n,30,n)


VSD
IF = 100A, VGS = 0V, Note 1
1.4     V
trr
> Vsd=(n,n,1.4)


tf
fall time
VDS = 60 V; RL = 3 Ω; VGS = 10 V
RG(ext) = 5 Ω
-
34.3
-
ns
>tFall =(n,34.3,n)


Qgd
Gate-to-Drain ("Miller") Charge
---
27
Qsync
> Qgd=(n,27,n)


Gate resistance"
Re
-
1.2
1.8
Q
-
> Rg=(n,1.2,1.8)


Reverse recovery charge")
Qr
- 68 (136 nC | Vr=50 V, Ir=50A, dir/dt=100 A/uUs
) Defined by design. Not subject to production test.
Final Data Sheet
> Qrr=(n,68,136)


Gate to drain charge"
Qoa
11
16
nC | Vpp=50 V, /p=50 A, Ves=0 to 10 V
> Qgd=(n,11,16)


Gate to source charge
Qgs
-
16
-
nC | Vpp=50 V, /b=50 A, Ves=0 to 10 V
> Qgs=(n,16,n)


Gate Resistance
f = 1 MHz
-
2.8
-

VSD
> Rg=(n,2.8,n)


VSD
Source-to-Drain Diode Voltage
ISD = 80 A, VGS = 0 V
-
-
1.25
V
ISD = 40 A, VGS = 0 V
-
-
1.2
V
> Vsd=(n,n,1.25)


Total Gate Charge Sync. (Qg - Qgd)
---
275
---
nC
> Qg_sync = (n,275,n)




RG(int)
Internal Gate Resistance
---
0.80
---
Ω
td(on)
> Rg=(n,.8,n)



Diode Forward Voltage
---
---
1.3
V
> Vsd=(n,n,1.3)



Total Gate Charge
Qe
Vos = 50V
Ves = 10V
See Fig.8
28
42
nc
> Qg=(n,28,42)


# littelfuse/IXFX360N15T2.pdf
QRM
0.50
C
> Qrr=(n,n,500)



#
# set2
#


# datasheets/nxp/PSMN3R3-80BS,118.pdf
QG(tot)
total gate charge
-
111
-
nC
> Qg=(n,111,n)


Coss
output capacitance
-
701
-
pF
> Coss=(n,701,n)


QGS
gate-source charge
-
38
-
nC
> Qgs=(n,38,n)


QGS(th)
pre-threshold 
gate-source charge
-
24
-
nC
> Qg_th=(n,24,n)


QGS(th-pl)
post-threshold 
gate-source charge
-
14
-
nC
> Qgs2=(n,14,n)


QGD
gate-drain charge
-
28
-
nC
> Qgd=(n,28,n)


VGS(pl)
gate-source plateau 
voltage
ID = 75 A; VDS = 40 V;
see Figure 14; see Figure 15
-
6.1
-
V    
> Vpl=(n,6.1,n)


VSD
source-drain voltage
IS = 25 A; VGS = 0 V; Tj = 25 °C;
see Figure 17
-
0.8
1.2
V
> Vsd=(n,0.8,1.2)


Qr
recovered charge
-
109
-
nC
> Qrr=(n,109,n)


rise time
-
29
-
ns
> tRise=(n,29,n)


tf
fall time
-
33
-
ns
> tFall=(n,33,n)



gate-drain charge
 VGS = 10 V; ID = 75 A; VDS = 40 V; see Figure 14;
 see Figure 15
 -
 28
 -
 nC
> Qgd=(n,28,n)



Output Capacitance
Coss

460

pF
> Coss=(n,460,n)





# IRFS7730TRLPBF
Qrr
Reverse Recovery Charge
---
70
---
nC   TJ = 25°C     di/dt = 100A/μs
---
97
---
TJ = 125°C
IRRM
Reverse Recovery Current
> Qrr=(n,70,n)


"""


def test_cases_from_stream():
    for case in test_stream.split('\n\n\n'):
        lines = [s.strip() for s in case.split('\n')]
        if len(list(filter(lambda s: s and not s.startswith('#'), lines))) == 0:
            continue
        refs = list(filter(lambda s: s and s[0] == '>', lines))
        assert len(refs) == 1, lines
        s, t = refs[0][1:].strip().split('=')
        sym = s.strip()
        ref_val = eval(t, dict(n=math.nan))

        lines = list(filter(lambda s: not s or s[0] != '>', lines))
        ds = extract_fields_from_text('\n'.join(lines), 'any', verbose='debug')
        assert sym in ds, lines
        ds[sym].assert_value(ref_val)


def test_catasthasthrophic():
    s = "'Figure 9. Diode Forward Voltage vs. Current\nVGS = 0V\nTJ= -55°C\nTJ= 25°C\nTJ= 85°C\nTJ= 125°C\nTJ= 150°C\nTJ= 175°C\n10\n100\n1000\n10000'"
    assert not extract_fields_from_text(s, 'any')

def test_extract_text():
    """

    :return:
    """

    # TODO assert 'IRF150DM115XTMA1.pdf.r400_ocrmypdf.pdf' == 1

    # tRise tFall

    def p(s):
        return extract_fields_from_text(s, 'any', verbose='debug')

    p("""
Coss
VGS = 0V, VDS = 25V, f = 1MHz
3060
 
pF
Crss
  """).Coss.assert_value()

    p("""
tr
                                                                             170
 
ns
    """).tRise.assert_value(typ=170)

    p("""
    VSD
    Drain to Source Diode Forward Voltage
    VGS = 0 V, ISD = 75 A
    -
    -
    1.3
    V
    trr
    """).Vsd.assert_values(max=1.3)

    p("""Reverse recovery charge 9)
    Q
    -
    256
    512
    nC
    V =30 V,  =50 A, d /d =1000 A/μs
    I
    i""").Qrr.assert_values(typ=256, max=512)

    p("""
    Rg
    Gate Resistance
    f = 1 MHz
    -
    2.2
    -
    
    Qg(ToT)
    Total Gate
    """).Rg.assert_values(typ=2.2)

    assert p("""Diode forward voltage
    Vsp
    -
    0.87
    {1.1
    V""").Vsd == (nan, .87, 1.1)

    assert p("""
    Qsw
    -
    16
    -
    nC | Vop=50 V, Ipb=50 A, Ves=0 to 10 V
        """).Qsw.typ == 16

    p("""
    Diode forward voltage
    Vsp
    0.87
    /|1.1
    V
    Ves=0 V, IF=50 A, Tj=25 °C
    Reverse recovery time")
        """).Vsd.assert_value(nan, 0.87, 1.1)

    assert p("""Output capacitance"
    Coss
    490
    |640
    |pF_
    |Ves=0 V, Vos=50 V, 1 MHz
    Reverse transfer capacitance""").Coss == (nan, 490, 640)

    assert p("""
    tf
    Fall Time
    ---
    55
    ---
    RD = 1.7Ω, See Fig. 10 
    Between lead,
    ---
    ---
    """).tFall.typ == 55

    assert p("""tr
        Rise Time
        -
        16
        -
        ns
        td(off)
        Turn-Off Delay
        -
        32
        -
        ns""").tRise.typ == 16

    d = p("""
    Qgs
    Gate-to-Source Gate Charge
    -
    22
    -
    nC
    Qgd
    Gate-to-Drain "Miller" Charge
    -
    17
    -
    nC
        """)
    assert d.Qgs.typ == 22
    assert d.Qgd.typ == 17

    assert p("""Qgs
    9.6
    Gate-Drain Charge
    Qgd
    4.2
    """).Qgs.typ == 9.6

    assert p("""
    Gate resistance
    R G
    -
    1
    -
    W
        """).Rg.typ == 1

    assert p("""Gate Charge Total (10 V)
    120
    nC
    Qgd
    Gate Charge Gate to Drain""").Qg == 120

    assert p("""RG(int)
    Internal Gate Resistance
    ---
    2.1
    ---
    Ω""").Rg.typ == 2.1

    assert p("""QG(TH)
                    VGS = 10 V, VDS = 40 V; ID = 50 A
                    15
                    Gate-to-Source Charge
        """).Qg_th.typ == 15

    assert p("""Diode forward voltage
    V SD
    V GS=0V, I F=70A,
    T j=25°C
    0.6
    1
    1.2
    V""").Vsd == (0.6, 1, 1.2)

    assert p("""
    VSD
    Source-Drain Forward Voltage#
    IS = 0.5 A, VGS = 0 V
    1.5
    V
    Gall    """).Vsd.max == 1.5

    assert extract_fields_from_text("""Gate resistance
    RG
    -
    0.62
    -
    Ω
    -
    """, 'any').Rg == 0.62

    assert extract_fields_from_text("""
    Gate Resistance
    ---
    2.4
    ---
    
    Notes:    """, 'any').Rg.typ == 2.4

    d = extract_fields_from_text("""QG
    71
    nC
        """, 'mfr')
    assert d.Qg.typ == 71

    d = extract_fields_from_text("""Diode forward voltage
    V SD
    V GS=0 V, I F=90 A,
    T j=25 °C
    -
    1.0
    1.2
    V
    Reverse recovery time
    t rr
    -
    72""", 'any')
    assert d.Vsd

    d = extract_fields_from_text("""
        Qgs
        VGS= 10 V, VDS = 0.5 VDSS, ID = 0.5 ID25
        40
        nC
        Qgd
        80
        nC
        RthJC    """, 'any')

    assert d.Qgs.typ == 40
    assert d.Qgd.typ == 80

    assert extract_fields_from_text(
        """
         Qg
         Total Gate Charge4
         ID=50A
         -
         159
         254.4
         nC
         """, mfr='any', pdf_path='').Qg == (nan, 159, 254.4)

    assert extract_fields_from_text(
        """
  Qg(TOT)
  Total Gate Charge at 10V
  VGS = 0V to 10V
  VDD = 75V
  ID = 33A
  Ig = 1.0mA
  -
  82
  107
  nC
  """, 'any', ''
    ).Qg == (nan, 82, 107)

    assert extract_fields_from_text("""Fall time
    t f
    -
    26
    -
    Gate Charge Characteristics5)""", 'any').tFall.typ == 26

    assert extract_fields_from_text("""
    Output Capacitance
    COSS
    1059
    Reverse Transfer Capacitance
    CRSS""", 'any').Coss.typ == 1059

    d = extract_fields_from_text("""Qg
    Total gate charge
    VDD = 50 V, ID = 107 A,
    VGS = 10 V
    (see Figure 14: "Test circuit for
    gate charge behavior")
    -
    72.5
    -
    nC""", 'any')
    assert d.Qg.typ == 72.5


from math import nan

from dslib.pdf2txt.parse import extract_fields_from_text


def test_fields_from_text():
    mfr = 'nxp'

    assert extract_fields_from_text("""
VSD
0.7
1
V
""", mfr, '').Vsd == (nan, 0.7, 1)

    assert extract_fields_from_text("""
Output capacitance
Coss
-
236
-
Reverse transfer capacitance
    """, mfr, '').Coss.typ == 236

    d = extract_fields_from_text("""
gate-drain charge
 VGS = 10 V; ID = 75 A; VDS = 40 V; see Figure 14;
 see Figure 15
 -
 28
 -
 nC
 QG(tot)
 """, mfr, '')
    assert d.Qgd.typ == 28


if __name__ == '__main__':
    test_from_stream()
    test_extract_text()
    test_fields_from_text()