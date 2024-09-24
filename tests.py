import math
import os

import pandas as pd

import dslib.pdf2txt.parse
import dslib.pdf2txt.pipeline
from dslib.field import DatasheetFields, Field
from dslib.pdf2txt.parse import tabula_read, parse_datasheet, parse_field_csv, dim_regs, raster_ocr
from dslib.pdf2txt.pipeline import pdf2pdf

nan = na = math.nan


def parse_line_tests():
    r = dim_regs['V'][0]
    m = next(r.finditer("Diode forward voltage,Vsp,-,0.89,1.2,V Ves=0 V, Ir=50 A, Tj=25 °C"), None)
    assert m.groupdict() == dict(max='1.2', min='-', typ='0.89', unit='V')

    r = dim_regs['t'][7]
    m = next(r.finditer('Rise time,f,-,10 -,ns Re=1.60'), None)
    assert m.groupdict() == dict(typ='10', unit='ns')

    # raise NotImplemented()
    n = math.nan
    cases = [
        ("43,Qgs,-,27,-,nC,,,,,", 'Qgs', (n, 27, n)),
        ("Gate charge at threshold,Qaitth),-,2.7 -,nC,Vop=50 V,,p=10 A, Ves=0 to 10 V", "Qg_th", (n, 2.7, n)),
        # ("VSD,TJ = 25°C, IS = 34A,VGS = 0V  ,-,-,1.3", "Vsd", (n, n, 1.3)), # TODO
        ("Diode forward voltage,VDSF,IDR = 70 A, VGS = 0 V,-,-,-1.2,V", "Vsd", (n, n, -1.2)),
        ("Diode forward voltage,Vsp,>,-,1,1.2,IV", "Vsd", (n, 1, 1.2)),

        ("Output capacitance,C oss,-,204,265,nan,nan", 'Coss', (n, 204, 265)),
        ("Gate charge total,Qg,nan,nan,-,26,35,nan", 'Qg', (n, 26, 35)),
        ("Fall time,ff,-,8 -,MS,R6=1.6Q", 'tFall', (n, 8, n)),
        ("Gate to drain charge,Qoa,-,7 -,nC Vpp=50 V,,p=25 A, Ves=0 to 10 V", 'Qgd', (n, 7, n)),
        ("Diode forward voltage,Vsp,-,0.89,1.2,V Ves=0 V, Ir=50 A, Tj=25 °C", "Vsd", (n, 0.89, 1.2)),
        ("Gate to drain charge,Qga,-,7 -,nc Vop=50 V, Ipb=25 A, Ves=0 to 10 V", "Qgd", (n, 7, n)),
        ("Gate plateau voltage,Vplateau,-,4.3 -,V,Vpp=50 V, /p=25 A, Ves=0 to 10 V", "Vpl", (n, 4.3, n)),
        ("Gate plateau voltage,Vplateau,-,4.3 -,V,Vpp=50 V, /p=25 A, Ves=0 to 10 V", "Vpl", (n, 4.3, n)),
        ("Rise time,f,-,10 -,ns Re=1.60", "tRise", (n, 10, n)),
        ("Vsp,Diode Forward Voltage,-_- -_-,1.3,Vv,Ty=25°C, 15 =22A, Ves =0V @,nan", 'Vsd', (n, n, 1.3)),
        # (CSV_ROW, DIM, (MIN,TYP,MAX))
        # datasheets/toshiba/XPN1300ANC.pdf Qgs no value match in  "Gate-source charge 1,Qgs1,nan,7,nan,nan,nC"
        # "Output capacitance C oss,nan,nan,-,1152.0,1498,nan"
        # "nan,nan,Coss,nan,102"
        ("Gate-source charge 1,Qgs1,nan,7,nan,nan,nC", 'Qgs1', (n, 7, n)),  # XPN1300ANC
        ('Gate plateau voltage,Vplateau,nan,nan,4.7,nan,"VDD 40 V, ID= 20A, VGS = 0 toV",10 V,,,', 'Vpl', (n, 4.7, n)),
        # "Output capacitance,C oss,f= 1 MHz,nan,2890.0,3840,nan"
        # "Rise Time tr,VDS=50V, RG=3Ω, -,46,nan,-,nan"
        # "Fall Time tf,-,44,nan,-,nan"
        # "Output Capacitance Coss,F=1MHz -,1263,nan,-,pF"
        # ("Reverse Recovery Charge Q rr,di/dt=100A/μs -,0.26,nan,-,uC", 'Q', (n, 0.26, n)),
        # "V GS=0V, V DS=25V, Output capacitance C oss,f =1MHz,nan,-,2520,3276,nan"
        # "COSS(TR),Effective Output Capacitance, Time Related (Note 2),nan,1371,nan,nan,nan"
        # "QG(TH),Gate Charge at Threshold,nan,4.6,nan,nan,nC"
        # "Output capacitance,C oss-,240,320,nan,f=1 MHz"
        # "Gate-Drain Charge - Gate-Drain-Ladung Industrial /-Q,nan,-,4 nC,-"
        # "QgsGate charge gate-to-source,25,nC,nan,nan,nan,nan,nan"
        ("QgdGate charge gate-to-drain,11,nC,nan,nan,nan,nan,nan", 'Q', (n, 11, n)),
        ("Qrr,nan,VDD = 64 V (see Figure 15: \"Test,-,66,nan,nC", 'Q', (n, 66, n)),
        ("Qgd,Gate-drain charge,behavior\"),-,28,-,nC", 'Q', (n, 28, n)),
        # "COSS,Output Capacitance,nan,nan,1045.0,1465.0,nan"
        ("QgsGate charge gate-to-source,25,nC,nan,nan,nan,nan,nan", 'Q', (n, 25, n)),
        ('Gate plateau voltage,Vplate au,,,4.4,,V,"VDD 40 V, ID = 50 A, VGS = 0 to 10 V",,,,,', 'V', (n, 4.4, n)),
        ("Gate plateau voltage,V plateau,nan,4.6,-,IV", 'V', (n, 4.6, n)),
        ("Rise Time3,4 tr,VDD=75V, RG=3Ω, VGS=10V, -,90,-,nan", 't', (n, 90, n)),
        ("COSS(ER),Effective Output Capacitance, Energy Related (Note 1),VDS = 0 to 50 V, VGS = 0 V,nan,1300,nan,nan",
         'C', (n, 1300, n)),
        ('Gate to drain charge1 ),Qgd,,,20,29,nC,"VDD =40 V, ID = 50 A, VGS = 0 to 10 V",,,,,', 'Q', (n, 20, 29)),
        ("Gate-to-Source Charge,QGS,VGS = 10 V, VDS = 75 V; ID = 41 A,15.0,nan,nC", "Q", (n, 15, n)),
        ("Gate-Drain Charge,nan,Qgd,nan,nan,nan,13,nan,nan,nan,nC", 'Q', (n, 13, n)),
        ("Output capacitance,C oss,nan,-,231.0,300,nan", 'C', (n, 231, 300)),
        (
            "Coss eff.(TR) Output Capacitance (Time Related),---,385,---,VGS = 0V, VDS = 0V to 80V,nan", 'C',
            (n, 385, n)),
        ("Effective Output Capacitance,---,154,---,pF f = 1.0MHz,  See Fig.5,nan", 'C', (n, 154, n)),
        ("nan,Coss,nan,7.0,nan", 'C', (n, 7, n)),
        ("Threshold Gate Charge,QG(TH),nan,9.1,nan,nC", 'Q', (n, 9.1, n)),
        ("Qg(th),-,36,-,nC", 'Q', (n, 36, n)),
        ("Reverse recovery charge - Sperrverzugsladung,Qrr,-,-,106 nC", 'Q', (n, n, 106)),
        ("Reverse Recovery Charge Qrr nCIF = 80A, VGS = 0V--,297,--,nan", 'Q', (n, 297, n)),
        ("Coss Output Capacitance,---,319,---,VDS = 50V,nan", 'C', (n, 319, n)),
        ("tf fall time,nan,nan,- 49.5 - ns", 't', (n, 49.5, n)),
        ("/dt = 100 A/μsReverse recovery charge,Q rr,-dI DR,nan,nan,35,nan,nC", 'Q', (n, 35, n)),
        ("Output Capacitance Coss VDS = 50V,--,3042,--,pF", 'C', (n, 3042, n)),
        ("Diode forward voltage,VDSF,IDR = 120 A, VGS = 0 V,nan,nan,nan,-1.2,V", 'V', (n, n, -1.2)),

        # "Output capacitance,C oss,nan,-,523.0,696,nan"
        # "Output Capacitance,Coss,--,392,--,nan,nan"
        # "2000.0,Coss"
        # "Coss Output Capacitance,VGS = 0 V, VDS = 50 V, ƒ = 1 MHz,nan,560,728,pF"
        # C oss output capacitance,Tj = 25 °C; see Figure 16,-,700,-,pF
        # "Output Capacitance,COSS,nan,1690.0,nan"

        # datasheets/diotec/DIT095N08.pdf error parsing field with col_idx {'min': 2, 'max': 4, 'unit': 0} all nan Field("Coss", min=nan, typ=nan, max=nan, unit="None", cond={0: 'Output Capacitance – Ausgangskapazität'})
        # ['Output Capacitance – Ausgangskapazität' nan nan nan nan] Output Capacitance - Ausgangskapazität,nan,nan,nan,nan Output Capacitance - Ausgangskapazität,Ciss,-,6800 pF,- Output Capacitance - Ausgangskapazität,Coss,-,350 pF,-
        # datasheets/diotec/DIT095N08.pdf tRise no value match in  "Turn-On Delay & Rise Time - Einschaltverzögerung und Anstiegszeit,nan,nan,nan,nan"

        # "Coss,Output Capacitance,---,340,---,nan,nan,nan"
        # "Coss eff. (ER),Effective Output Capacitance (Energy Related),---,420,---,VGS = 0V, VDS = 0V to 80V,  See Fig.11,nan,nan"
        # "Reverse Recovery Charge Qrr nCIF = 80A, VGS = 0V--,297,--,nan"
        # "Output Capacitance Coss VDS = 50V, --,2730,--,pF"
        # "Coss eff. (ER),Effective Output Capacitance (Energy Related),---,757,---,VGS = 0V, VDS = 0V to 80VSee Fig.11,nan"
        # "Threshold Gate Charge,QG(TH),nan,9.1,nan,nC"
        #
    ]

    for rl, sym, (min, typ, max) in cases:
        dim = sym[:1]
        f = parse_field_csv(rl, dim, field_sym=sym)
        if not f:
            print('\n'.join(map(lambda r: r.pattern, dim_regs[dim])))
        assert f, (rl, dim)
        assert math.isnan(min) or min == f.min, f
        assert math.isnan(typ) or typ == f.typ, (f, typ)
        assert math.isnan(max) or max == f.max, f
    # "Coss output capacitance,nan,VDS = 50 V; VGS = 0 V; f = 1 MHz;,-,380,-,pF"


def parse_pdf_tests():
    # TODOå

    d = parse_datasheet('datasheets/mcc/MCB70N10YA-TP.pdf')
    assert len(d) >= 8

    d = parse_datasheet('datasheets/onsemi/FDP047N10.pdf')
    assert d.Qg == (na, 160, 210)
    assert d.Qgs == (na, 56, na)
    assert d.Qgd == (na, 36, na)
    assert len(d) >= 8

    d = parse_datasheet('datasheets/onsemi/FDD86367.pdf')
    assert d.Qg == (math.nan, 68, 88)
    assert d.Qg_th == (math.nan, 8.8, math.nan)
    assert d.Qgs == (math.nan, 22, math.nan)
    assert d.Qgd == (math.nan, 14, math.nan)
    mf = d.get_mosfet_specs()
    assert abs(mf.Qg_th - 8.8e-9) < 1e-15
    assert mf.Qgs2 == (mf.Qgs - mf.Qg_th)

    d = parse_datasheet('datasheets/nxp/PSMN5R5-100YSFX.pdf')
    assert d.Qg == (32, 64, 95)
    assert d.Qgs == (10.3, 17.1, 24)
    assert d.Qg_th.typ == 12
    assert d.Qgs2.typ == 4.8
    assert d.Qgd == (3.5, 11.8, 27.1)
    assert d.Qrr == (math.nan, 30, math.nan)

    d = parse_datasheet('datasheets/infineon/IQE050N08NM5CGATMA1.pdf', mfr='infineon')
    assert len(d) >= 9

    d = parse_datasheet('datasheets/infineon/IQDH88N06LM5CGSCATMA1.pdf', mfr='infineon')
    assert d.Qgs.typ == 27
    # missing Qgs
    miss = {'Coss', 'Qg', 'Qg_th', 'Qgd', 'Qgs', 'Qrr', 'Qsw', 'Vpl', 'Vsd', 'tFall', 'tRise'} - set(d.keys())
    assert len(miss) == 0, miss
    assert len(d) >= 11, d

    d = tabula_read('datasheets/infineon/IRFB4110PBF.pdf')
    assert d.Qgd.typ == 43

    d = parse_datasheet(
        'datasheets/infineon/ISC030N10NM6ATMA1.pdf')  # repair, produced not conform by http://activepdf.com
    assert len(d) >= 11

    d = tabula_read('datasheets/infineon/BSB056N10NN3GXUMA2.pdf')
    assert d.Qgd.typ == 20  # datasheet mistake! 9.7

    d = tabula_read('datasheets/infineon/BSC025N08LS5ATMA1.pdf')
    assert d.Vpl.typ == 2.8

    d = tabula_read('datasheets/infineon/IPB019N08N3GATMA1.pdf')
    assert d.Vpl.typ == 4.6

    d = tabula_read('datasheets/infineon/BSC021N08NS5ATMA1.pdf')
    assert d.tRise.typ == 17
    assert d.tFall.typ == 20  # tFall has typ because it doesnt match the regex
    assert d.Qrr.typ == 80 and d.Qrr.max == 160
    assert d.Qsw.typ == 29
    assert d.Qgd.typ == 20 and d.Qgd.max == 29
    assert d.Vpl.typ == 4.4
    assert d.Qgs.typ == 29

    d = tabula_read('datasheets/onsemi/NTP011N15MC.pdf')
    assert d.Qgs.typ == 15

    d = tabula_read('datasheets/diotec/DIT085N10-AQ.pdf')
    assert d.Qrr.max == 106

    d = tabula_read('datasheets/infineon/IAUA210N10S5N024AUMA1.pdf')
    assert d.Qgd.typ == 18 and d.Qgd.max == 27

    d = parse_datasheet('datasheets/infineon/IPF015N10N5ATMA1.pdf')
    assert d.Qg_th.typ == 36
    assert d.Qgs.typ == 53
    assert d.Qgd.typ == 34 and d.Qgd.max == 51

    d = parse_datasheet('datasheets/ti/CSD19532KTTT.pdf')
    assert d.Qgd.typ == 5.6
    assert d.Qgs.typ == 17
    assert d.Qg_th.typ == 9.6
    assert d.Qrr.typ == 326
    assert d.get_mosfet_specs().Qsw * 1e9 == d.Qgd.typ + d.Qgs.typ - d.Qg_th.typ

    d = parse_datasheet('datasheets/panjit/PSMP050N10NS2_T0_00601.pdf')
    assert d['Vpl'].typ == 5
    assert d['Qgs'].typ == 15
    assert d['Qrr'].typ == 85 and d['Qrr'].max == 170

    d = parse_datasheet('datasheets/goford/GT023N10TL.pdf')
    assert d['Qrr'].typ == 297
    #    assert d['Coss'] == 2730

    d = parse_datasheet('datasheets/vishay/SUD70090E-GE3.pdf')
    # assert d['Coss'].typ == 845

    d = parse_datasheet('datasheets/goford/GT52N10D5.pdf')
    # assert d['Coss'].typ == 380
    assert d['Qrr'].typ == 87

    d = parse_datasheet('datasheets/vishay/SIR622DP-T1-RE3.pdf')
    assert d['Qrr'].typ == 350 and d['Qrr'].max == 680

    # datasheets/onsemi/NTBLS1D1N08H.pdf
    # d = parse_datasheet('../datasheets/infineon/IPA050N10NM5SXKSA1.pdf')
    # assert d['Rdson'].max == 5.0

    d = parse_datasheet('datasheets/infineon/IRF100B202.pdf')
    assert d['tRise'].typ == 56
    assert d['tFall'].typ == 58
    assert d['Coss'].typ == 319  # (ER)=355 TODO
    assert d['Qrr'].typ in {133, 105}, d.Qrr  # or 105 TODO multi Qrr

    # GT016N10TL
    d = parse_datasheet('datasheets/goford/GT016N10TL.pdf')
    assert d['Qrr'].typ == 166

    d = tabula_read('datasheets/toshiba/TPH5R60APL,L1Q.pdf')
    assert d['Qrr'].typ == 55
    assert d['Qgs'].typ == 12
    assert d.Qsw.typ == 14

    # d = tabula_read('datasheets/vishay/SUM70042E-GE3.pdf')
    # assert d['Qrr'].typ == 126 # type in datasheet uC = nC

    d = tabula_read('datasheets/ts/TSM089N08LCR RLG.pdf')
    assert d['Qrr'].typ == 35
    assert d['tFall'].typ == 24
    assert d['tRise'].typ == 21

    d = tabula_read('datasheets/infineon/IAUZ40N08S5N100ATMA1.pdf')
    assert d['tRise'].typ == 1
    assert d['tFall'].typ == 5
    assert d['Qrr'].typ == 32
    assert d['Coss'].typ == 231 and d.Coss.max == 300

    d = tabula_read('datasheets/st/STL135N8F7AG.pdf')
    assert d['Qrr'].typ == 66

    d = tabula_read('datasheets/toshiba/TK6R9P08QM,RQ.pdf')
    assert d['Qrr'].typ == 35

    d = tabula_read('datasheets/toshiba/TPH2R408QM,L1Q.pdf')
    assert d['Qrr'].typ == 74

    d = tabula_read('datasheets/vishay/SIR826DP-T1-GE3.pdf')
    assert d['Qrr'].typ == 78
    assert d['Qrr'].max == 155

    d = tabula_read('datasheets/ti/CSD19505KTT.pdf')
    assert d['tRise'].typ == 5
    assert d['tFall'].typ == 3
    assert d['Qrr'].typ == 400
    assert d['Qg_th'].typ == 15

    d = parse_datasheet('datasheets/vishay/SUM60020E-GE3.pdf')  # special: Reverse recovery fall time
    assert len(d) >= 7
    assert d['Qrr'].typ == 182 and d['Qrr'].max == 275
    assert d['tRise'].typ == 13
    assert d['tFall'].typ == 15

    d = tabula_read('datasheets/onsemi/NVBGS1D2N08H.pdf')  # discontinued NRFND
    assert d['Qrr'].typ == 122

    d = tabula_read('datasheets/infineon/IAUA180N08S5N026AUMA1.pdf')
    assert d['tRise'].typ == 7
    assert d['tFall'].typ == 16
    assert d['Qrr'].typ == 85
    assert d

    d = tabula_read('datasheets/onsemi/NTMFSC004N08MC.pdf')
    assert d['tRise'].typ == 21.5
    assert d['tFall'].typ == 5.4

    # d = tabula_read('datasheets/onsemi/NVMFWS2D1N08XT1G.pdf') # fail
    # assert d['tRise'].typ == 7
    # assert d['tFall'].typ == 5
    # assert d['Qrr'].typ == 104

    d = tabula_read('datasheets/onsemi/NVMFWS4D5N08XT1G.pdf')
    assert d['tRise'].typ == 7
    assert d['tFall'].typ == 5
    assert d['Qrr'].typ == 104

    d = tabula_read('datasheets/nxp/PSMN4R4-80BS,118.pdf')  # multiple 'typ' headers
    assert d['tRise'].typ == 38.1
    assert d['tFall'].typ == 18.4
    assert d['Qrr'].typ == 130

    d = tabula_read('datasheets/onsemi/NVMFWS1D5N08XT1G.pdf')
    assert d['tRise'].typ == 10
    assert d['tFall'].typ == 9
    assert d['Qrr'].typ == 290

    tabula_read('datasheets/diotec/DIT095N08.pdf')

    d = tabula_read('datasheets/infineon/BSZ084N08NS5ATMA1.pdf')  # need OCR (pdf reader pro))
    assert d['tRise'].typ == 5
    assert d['tFall'].typ == 5
    assert d['Qrr'].typ == 44 and d['Qrr'].max == 88
    assert d.Vpl.typ == 4.7

    d = tabula_read('datasheets/infineon/IPB033N10N5LFATMA1.pdf')
    assert d.Vpl.typ == 6.9

    d = tabula_read('datasheets/st/STL120N8F7.pdf')
    assert d['tRise'].typ == 16.8
    assert d['tFall'].typ == 15.4
    assert d['Qrr'].typ == 65.6

    # rise 38.1 fall 18.4

    d = tabula_read('datasheets/nxp/PSMN8R2-80YS,115.pdf')
    # assert d # doenst work tabula doesnt find the tables right

    d = tabula_read('datasheets/infineon/BSZ075N08NS5ATMA1.pdf')
    assert d['tRise'].typ == 4
    assert d['tFall'].typ == 4

    d = tabula_read('datasheets/onsemi/FDP027N08B.pdf')
    assert d['tRise'].typ == 66 and d['tRise'].max == 142
    assert d['tFall'].typ == 41 and d['tFall'].max == 92
    assert d['Qgs'].typ == 56
    assert d['Qgs2'].typ == 25
    assert d['Qgd'].typ == 28

    d = tabula_read('datasheets/onsemi/FDBL0150N80.pdf')
    assert d['tRise'].typ == 73
    assert d['tFall'].typ == 48

    tabula_read('datasheets/diodes/DMTH8003SPS-13.pdf')

    #
    tabula_read('datasheets/vishay/SIR680ADP-T1-RE3.pdf')

    d = tabula_read('datasheets/vishay/SUM60020E-GE3.pdf')
    assert d['tRise'].typ == 13
    assert d['tRise'].max == 26
    assert d['tFall'].typ == 15
    assert d['tFall'].max == 30
    assert d['Qrr'].typ == 182

    d = parse_datasheet('datasheets/vishay/SUM60020E-GE3.pdf')
    assert d['Qrr'].typ == 182.
    assert d['Qrr'].max == 275.

    d = parse_datasheet(mfr='diodes', mpn='DMTH8003SPS-13')
    assert d['Qrr'].typ == 118.7

    d = parse_datasheet(mfr='toshiba', mpn='TK6R9P08QM,RQ')
    assert d['Qrr'].typ == 35

    d = parse_datasheet(mfr='toshiba', mpn='TK100E08N1,S1X')
    assert d['Qrr'].typ == 190

    d = parse_datasheet(mfr='onsemi', mpn='FDBL0150N80')
    assert d['Qrr'].typ == 205
    assert d['Qrr'].max == 269

    d = parse_datasheet(mfr='onsemi', mpn='FDP027N08B')
    assert d['Qrr'].typ == 112


def pdf_ocr_tests():
    import subprocess
    res = subprocess.run(
        'tesseract tesseract-stuff/test2.png stdout --user-words tesseract-stuff/mosfet.user-words tesseract-stuff/tesseract.cfg'.split(
            ' '),
        check=True, capture_output=True).stdout.decode('utf-8')
    # assert 'Qgd' in res
    assert 'Qgs' in res
    assert 'Vplateau' in res  # only works with custom words!

    d = parse_datasheet('datasheets/infineon/BSZ150N10LS3GATMA1.pdf')  # takes a long time
    assert d.Qgs == (na, 5.2, na)
    assert d.Qg_th == (na, 2.7, na)
    assert d.Qsw == (na, 7.7, na)

    # IPB039N10N3GATMA1
    d = parse_datasheet('datasheets/infineon/IPP100N08N3GXKSA1.pdf')  # ocr
    assert d.Qg.typ == 26
    assert d.Qg.max == 35
    assert d.Qgd.typ == 5
    # assert d.Qgs.typ == 9
    assert d.Qsw.typ == 10
    assert d.Qrr.typ == 102
    mf = d.get_mosfet_specs()
    assert mf.Qsw == 10e-9
    assert abs((mf.Qgs + mf.Qgd - mf.Qsw) - mf.Qg_th) < 1e-20
    assert abs((mf.Qgs2 + mf.Qgd) - mf.Qsw) < 1e-20

    # multiple Qrr, multi Qrr
    # IPT025N15NM6ATMA1
    d = parse_datasheet('datasheets/infineon/IPT025N15NM6ATMA1.pdf', mfr='infineon',
                        tabular_pre_methods=('ocrmypdf_redo')
                        )
    assert d.Qrr.typ == 184 and d.Qrr.max == 368
    assert d.tRise.typ == 16
    assert d.tFall.typ == 19
    assert d.Qg_th.typ == 26
    assert d.Qsw.typ == 38
    assert d.Vsd.typ == 0.86 and d.Vsd.max == 1

    # same, but this time check fallback to `ocrmypdf_redo`
    d = parse_datasheet('datasheets/infineon/IPT025N15NM6ATMA1.pdf', mfr='infineon', )
    assert d.Qrr.typ == 184 and d.Qrr.max == 368
    assert d.tRise.typ == 16
    assert d.tFall.typ == 19
    assert d.Qg_th.typ == 26
    assert d.Qsw.typ == 38
    assert d.Vsd.typ == 0.86 and d.Vsd.max == 1

    d = tabula_read('datasheets/infineon/BSC070N10NS3GATMA1.pdf', 'ocrmypdf_r400')
    assert d.Vsd.typ == 0.89, d.Vsd
    assert d.Vsd.max == 1.2, d.Vsd
    assert d.Qgs.typ == 13
    assert d.Qgd.typ == 7
    assert d.Qsw.typ == 12
    assert d.Qg.typ == 42 and d.Qg.max == 55
    assert d.tRise.typ == 10
    assert d.tFall.typ == 8
    # raster_ocr('datasheets/infineon/BSC070N10NS3GATMA1.pdf', o,'ocrmypdf')


def test_convertapi():
    from dslib.pdf2txt.pipeline import convertapi
    convertapi(
        'datasheets/infineon/./IPT025N15NM6ATMA1.pdf',
        'datasheets/infineon/IPT025N15NM6ATMA1.pdf.convertapi_pdf.pdf',
        'pdf'
    )
    d = parse_datasheet('datasheets/infineon/IPT025N15NM6ATMA1.pdf.convertapi_pdf.pdf', mfr='infineon',
                        tabular_pre_methods=('nop',))
    assert d

    convertapi(
        'datasheets/infineon/./IPT025N15NM6ATMA1.pdf',
        'datasheets/infineon/IPT025N15NM6ATMA1.pdf.convertapi_rasterize.pdf',
        'rasterize'
    )
    d = parse_datasheet('datasheets/infineon/IPT025N15NM6ATMA1.pdf.convertapi_rasterize.pdf',
                        mfr='infineon',
                        tabular_pre_methods=('convertapi_ocr',))
    assert d


def test_mosfet_specs():
    d = parse_datasheet('datasheets/infineon/IRF6644TRPBF.pdf')
    assert d.Qgs_th.typ == 7  # Qgs1
    assert d.Qgs2.typ == 3
    assert d.Qsw.typ == 16
    mf = d.get_mosfet_specs()
    assert mf.Qg_th == 3


def test_rasterize():
    from dslib.pdf2txt.pipeline import rasterize_pdf
    os.path.exists('datasheets/onsemi/FDP047N10.r.pdf') and os.remove('datasheets/onsemi/FDP047N10.r.pdf')
    rasterize_pdf('datasheets/onsemi/FDP047N10.pdf', 'datasheets/onsemi/FDP047N10.r.pdf')
    assert os.stat('datasheets/onsemi/FDP047N10.r.pdf').st_size > os.stat('datasheets/onsemi/FDP047N10.pdf').st_size


if __name__ == '__main__':

    #ds = tabula_read('datasheets/_samples/infineon/IRF150DM115XTMA1_cyn_char.pdf')
    #assert ds

    ds = tabula_read('datasheets/infineon/IRF150DM115XTMA1.pdf',
                     pre_process_methods=('ocrmypdf_r400', 'r400_ocrmypdf'),
                     need_symbols={'tRise','tFall'},
                    )
    assert ds.tRise and ds.tFall


    ds = dslib.pdf2txt.parse.extract_fields_from_dataframes(
        dfs=[pd.DataFrame(['43,Qgs,-,27,-,nC,,,,,'.split(',')])],
        mfr='infineon',
        ds_path='')
    assert ds.Qgs.typ == 27

    ds = dslib.pdf2txt.parse.extract_fields_from_dataframes(
        dfs=[pd.DataFrame(['56,Rise time te,,21,,ns,"Voo=75 V, Ves=10 V, Ib=45 A,",,,,'.split(',')])],
        mfr='infineon',
        ds_path='')
    assert ds.tRise.typ == 21

    parse_line_tests()

    d = parse_datasheet('datasheets/infineon/AUIRFS4115.pdf')  # split rows
    assert d.Qrr.typ == 300

    d = parse_datasheet('datasheets/infineon/IPI072N10N3G.pdf')
    assert d.Qsw.typ == 16

    # parse_datasheet(mfr='diodes', mpn='DMTH8003SPS-13')
    d = parse_datasheet('datasheets/toshiba/XPW4R10ANB,L1XHQ.pdf')
    assert len(d) >= 7

    ds = parse_datasheet('datasheets/infineon/IPT025N15NM6ATMA1.pdf', mfr='infineon')
    ref = DatasheetFields("IPT025N15NM6ATMA1", "infineon",
                          fields=[Field("Qrr", nan, 184.0, 368.0, "None"), Field("Qg", nan, 105.0, 137.0, "nC"),
                                  Field("Coss", 2300.0, 3000.0, nan, "pF"), Field("tRise", nan, 16.0, nan, "ns"),
                                  Field("tFall", nan, 19.0, nan, "ns"), Field("Qgs", nan, 41.0, 53.0, "nC"),
                                  Field("Qg_th", nan, 26.0, nan, "nC"), Field("Qgd", nan, 23.0, 35.0, "nC"),
                                  Field("Qsw", nan, 38.0, nan, "nC"), Field("Vpl", nan, 5.4, nan, "V"),
                                  Field("Vsd", nan, 0.86, 1.0, "V")])
    assert ref.show_diff(ds, err_threshold=1e-3) == 0
    assert len(ds) > 8

    # macos preview fixes: (CUPS printer)
    ds = parse_datasheet('datasheets/infineon/./IRF150DM115XTMA1.pdf', mfr='infineon')  # OCR long
    ref = DatasheetFields("IRF150DM115XTMA1", "infineon",
                          fields=[Field("tFall", nan, 14.0, nan, "ns"),
                                  Field("tRise", nan, 21.0, nan, "ns"),
                                  Field("Qgs", nan, 13.2, nan, "nC"),
                                  Field("Qg_th", nan, 8.7, nan, "nC"), Field("Qgd", nan, 8.0, 12.0, "nC"),
                                  Field("Qsw", nan, 12.5, nan, "nC"), Field("Qg", nan, 33.0, 50.0, "nC"),
                                  Field("Vpl", nan, 5.7, nan, "V"), Field("Vsd", nan, 0.9, 1.2, "V")])
    assert ref.show_diff(ds, err_threshold=1e-3) == 0
    assert len(ds) >= 8

    assert ds.get('Qgs', 'typ') == 13.2
    # assert len(ds) > 9

    # fixable with maco Preview print as pdf (came as CUPS method?)
    df = tabula_read('datasheets/infineon/IRF7779L2TRPBF.pdf')
    assert len(df) > 5

    # fixable with gs:
    df = parse_datasheet('datasheets/onsemi/NVMFS6H800NWFT1G.pdf')
    assert len(df) > 5

    test_rasterize()
    pdf_ocr_tests()
    parse_pdf_tests()
    test_mosfet_specs()


def failing():
    # TODO TODO
    # TODO use tabular browser?
    d = parse_datasheet('datasheets/littelfuse/IXTQ180N10T.pdf',
                        # tabular_pre_methods='nop'
                        )
    assert d.Qgd

    d = parse_datasheet('datasheets/littelfuse/IXTA160N10T7.pdf')
    assert d
