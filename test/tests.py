import math
import os

import pandas as pd

import dslib.pdf2txt.parse
import dslib.pdf2txt.pipeline
from dslib.field import DatasheetFields, Field
from dslib.manual_fields import reference_data
from dslib.pdf2txt import strip_no_print_latin, ocr_post_subs
from dslib.pdf2txt.expr import dim_regs_csv
from dslib.pdf2txt.parse import tabula_read, parse_datasheet, parse_field_csv, detect_fields
from dslib.pdf2txt.tabular import tabula_browser

nan = na = math.nan


def test_parse_lines():
    r = dim_regs_csv['V'][0]
    m = next(r.finditer("Diode forward voltage,Vsp,-,0.89,1.2,V Ves=0 V, Ir=50 A, Tj=25 °C"), None)
    assert m.groupdict() == dict(max='1.2', min='-', typ='0.89', unit='V', minN_typ_maxN_unit=None), m.groupdict()

    r = dim_regs_csv['t'][6]
    m = next(r.finditer('Rise time,f,-,10 -,ns Re=1.60'), None)
    assert m.groupdict() == dict(typ='10', unit='ns', max=None), m.groupdict()

    # raise NotImplemented()
    n = math.nan
    cases = [
        # (CSV_ROW, DIM, (MIN,TYP,MAX))

        # "Gate resistance,Re,-,0.7 -,Q,-"
        # VSD source-drain voltage, IS = 25 A; VGS = 0 V; Tj = 25 °C; Fig. 16, , -, 0.81, 1.2, V # todo, where is this from?, pnji, nxp P/N nxp PSMN6R5-80PS,127?
        ("QGS1,QGS2,nan", 'Qgs2', (n, n, n)),
        # ("QgGate charge total (10 V),VDS = 40 V,ID = 100 A,76,nC,,", 'Qg', (n, 76, n)),
        ("Qrr Reverse recovery charge V nCDS = 40 V,I F= 100 A,,400,,", 'Qrr', (n, 400, n)),
        ("Qg,Total Gate Charge,---,200,300,,,VDS = 38V,", 'Qg', (n, 200, 300)),
        ('nC Qgd,Gate-to-Drain ("Miller") Charge,---,62,93,,,See Fig.11,', 'Qg', (n, 62, 93,)),
        ("Qrr Reverse recovery charge V nCDS = 40 V,I F= 100 A,,525,,", 'Qrr', (n, 525, n)),
        # ("Output capacitance,C oss 1274f =1 MHz,GS,=0 V,V DS=40 V,,- 980,,", 'Coss', (n, 980, n)),
        ("Qg,Total Gate Charge,---,81,120,,,VDS = 50V,", 'Qg', (n, 81, 120,)),
        ("Coss eff.,Effective Output Capacitance,,1040,,,,VGS = 0V,VDS = 0V to 80V,", 'Coss', (n, 1040, n)),

        # ("di,dt = 100A,s Qrr Reverse Recovery Charge,--- ---,63 88,--- ---,nC TJ = 125°C TJ = 25°C,", 'Qrr',
        # (n, 63, 88)),  # IRFS7730TRL7PP TODO this is not typ/max but diff. test conditions

        ("Qg,Total Gate Charge,---,285,428,ID = 100A", 'Qg', (n, 285, 428,)),
        ("Qg,Total Gate Charge,---,200,300,,,VDS = 50V,", 'Qg', (n, 200, 300)),

        ("Output capacitance ON- and LINFET,C oss,ON+LIN,,,-,2100,2730,", "Coss", (na, 2100, 2730)),
        ("Output capacitance ON- and LINFET,C oss,ON+LIN,-,2100,2730,,", "Coss", (na, 2100, 2730)),
        ("Gate to source charge ON- and LINFET,Q gs,ON+LIN,,-,51,66,nC", "Qgs", (na, 51, 66)),
        ("Gate charge total ON- and LINFET,Q g,ON+LIN,,-,178,231,", "Qg", (na, 178, 231)),

        (strip_no_print_latin('VSD,,Diode Forward Voltage,–––,–––,1.3,V,TJ = 25°C, IS = 96A, VGS = 0V \uf087,'), 'Vsd',
         (na, na, 1.3)),
        ("tr,Rise Time,,22,,", "tRise", (na, 22, na)),
        ("tr,Rise Time,nan,22,nan,nan", "tRise", (na, 22, na)),
        ("VSD,Source-to-Drain DiodeVoltage,ISD = 80 A,VGS = 0 VISD = 40 A,VGS = 0 V,,,1.251.2,V,", 'Vsd',
         (na, 1.2, 1.25)),
        ('Qgd,Gate-to-Drain "Miller" Charge,,11,,', "Qgd", (na, 11, na)),
        ('Switching charge,Qg -,56,74,,', 'Qsw', (na, 56, 74)),
        ("Threshold Gate Charge,QG(TH),,9.1,,", 'Qg_th', (na, 9.1, na)),
        # Gate-to-Source Charge,QGS,VGS = 10 V,VDS = 75 V; ID = 41 A,15,,"
        ("Gate-to-Drain Charge,QGD,,6.5,,", 'Qgd', (na, 6.5, na)),
        ("Total Gate Charge,QG(TOT),,37,,", 'Qg', (na, 37, na)),
        ("Forward Diode Voltage,VSD,VGS = 0 V,TJ = 25°C,,0.92,1.2,", 'Vsd', (na, 0.92, 1.2)),
        ('Qg(tot),Total Gate Charge at 10V,VDS = 80 V, ID = 75 A,,,- 160,210,nC', 'Qg', (na, 160, 210)),  # FDP047N10
        ('60,V SD (2)Forward on voltage,"VGS = 0,ISD = 90 A",,-,,1.2,V,,', 'Vsd', (na, na, 1.2)),
        ("VSD IF = 25 A, VGS = 0 V, Note 1,nan,nan,0.95,V,nan", "Vsd", (na, na, 0.95)),
        ("Qgs VGS= 10 V,VDS = 0.5 VDSS,ID = 25 A,,39 nC,,Min. Max.,Min. Max.", 'Qgs', (na, 39, na)),
        ('51,V SD,Source-to-Drain Diode Voltage,"ISD = 80 A, VGS = 0 V ISD = 40 A, VGS = 0 V",,,1.25 1.2,V,,,,,', 'Vsd',
         (na, 1.2, 1.25)),  # FDMS86368-F085
        ("Body diode reverse recovery charge Qr le = 20 A,di,dt = 100 A,ps,-,nan,67,134,nan,nan,nc", 'Qrr',
         (n, 67, 134)),
        # SIR580DP-T1
        ("Reverse recovery charge Q IF = 33.3 A,di,dt = 100 A,srr,-,0.182,0.275,", 'Qrr', (n, 182, 275)),  # SUP60020E
        ("Reverse recovery charge Q IF = 33.3 A,di,dt = 100 A,srr,-,0.182,0.275,C", 'Qrr', (n, 182, 275)),  # SUP60020E

        ("nan,tf,Fall time,nan,-,44 - ns", 'tFall', (na, 44, na)),
        ("Gate-drain charge Qga,-,9.1,-,nan,nan", "Qgd", (na, 9.1, na)),
        ("Gate-drain charge Qga,-,nan,9.1,-,nan,nan", "Qgd", (na, 9.1, na)),
        ("Body diode reverse recovery charge Qi ;,-,nan,115,230,nan,nan,nc", "Qrr", (n, 115, 230)),
        ("Qgs,Gaattee-- source ch arge,Ves = 10 V,- 30 - nc", "Qgs", (na, 30, na)),

        ("Rise time t Vp= p40 V,R= L4,Ip=10A,= 15,30,nan,nan", "tRise", (na, 15, 30)),
        # "Fall time t,- 16,30,nan,nan"

        ('63,V(2)SD,Source-drain curren,"ISD = 90 A,VGS = 0 V",-,,1.2,V,,,,,,,,,', "Vsd", (na, na, 1.2)),

        # ("Qg,Total Gate Charge,---,60,91,ID = 26A",'Qg',(na,60,91)),
        # ("Qgd,Gate-to-Drain Charge,---,28,42,VGS = 10V ", 'Qg', ()),
        # ("Qrr,Reverse Recovery Charge,--- 1.3,2.0,C,di,dt = 100A,s ","Qrr",()),
        # "Qg,Total Gate Charge ---,---,130,nan,ID = 28A,nan,nan"

        ("Output capacitance,V GS=0V, VC oss f =1MHz,DS,=25V,nan,-,940,1222,nan", 'Coss', (na, 940, 1222)),
        # AUIRF7759L2TR.pdf Qsw no value match in  "Qsw,Switch Charge (Qgs2 + Qgu),-,73 --,nan"
        ("ts,Fall Time,-- 33 --,nan", "tFall", (na, 33, na)),
        ("tr,nan,nan,Reverse Recovery Time,-. 64 96 ns,[Ty = 25°C, lr = 96A, Vpp = 38V", "tRise", (n, 64, 96)),
        (",Avalanche Rated,nan,Qg Gate Charge Total (10 V),76,nC", 'Qg', (n, 76, n)),
        ("QgGate charge total (10 V),VDS = 40 V, ID = 100 A,76,nC,nan,nan", 'Qg', (n, 76, n)),
        ("VSDDiode forward voltage,ISD = 100 A, VGS = 0 V,0.91.1,V,nan,nan", 'Vsd', (n, 0.9, 1.1)),

        ("Qgd,Gate-to-Drain Charge,23,nan,nan", "Qgd", (n, 23, n)),
        # ("tr,Rise Time,20,nan,ID = 46A,nan,nan", 'tRise', (n,20,n)),
        # "Rise time,t,Vpp=40 V, Ves=10V,",73 =,ns"

        ("Coss,Output Capacitance,460,nan,pF VDS = 25V,nan,nan", 'Coss', (n, 460, n)),

        # "Output capacitance,Cus,4 Kaz. ps,-,2890 3840,nan"
        # "Gate charge total,Q,nan,-,155.0,206,nan"
        ("Body diode reverse recovery charge Qn,.,nan,2,nan,108,220,nan,nan,nc", 'Qrr', (n, 108, 220)),  # !>2
        ("Body diode reverse recovery charge Qn .,nan,2,nan,110,225,nan,nan,nc", 'Qrr', (n, 110, 225)),
        ("Qg,Total gate charge,Vop = 40 V, Ip = 26A, - 103 -", "Qg", (na, 103, na)),  # STL135N8F7AG
        ("Qgs,Gate-source charge,Vics - 10 Vv (see Figure 14: - 35 - nc", "Qgs", (na, 35, na)),  # STL135N8F7AG
        (ocr_post_subs('Qgd,Gate-drain charge,behavior") - 28 -"'), "Qgd", (na, 28, na)),  # STL135N8F7AG

        ("165,VSD source-drain voltage,,IS = 25 A; VGS = 0 V; Tj = 25 °C; Fig. 17,-,0.82,1,V,,,,,,,,,,,,",
         "Vsd", (na, 0.82, 1)),  # PSMN3R9-100YSF

        (ocr_post_subs('52,Qoa,Gate-to-Drain (""Miller"") Charge,- | 62 93 nC See Fig.11,,,,,,,,,,,,,,,'), 'Qgd',
         (n, 62, 93)),
        (ocr_post_subs('72,Vsp Diode Forward Voltage,- | - 1.3 V,"|Ty = 25°C, Is = 96A, Ves = OV @",,,,,,,,,,,,,,,'),
         'Vsd', (na, na, 1.3)),
        # (ocr_post_subs('77,Msp,,Diode Forward Voltage,"- | - 1.3 V_ |Ty = 25°C, ls = 96A, Veg = OV ©",,,,'),
        # 'Vsd', (na, na, 1.3)),
        # (ocr_post_subs('70,Vsp,,Diode Forward Voltage,-_ | - 1.3 Vs,"|Ty = 25°C, Is = 96A, Veg = OV @",,,,'),
        # 'Vsd', (na, na, 1.3)),

        ("Output Capacitance Coss VDS = 50V, --,3042,--,pF", 'Coss', (n, 3042, n)),
        ("Output Capacitance Coss VDS = 50V, --,380,--,pF", 'Coss', (n, 380, n)),
        ("Reverse Recovery Charge Qrr nCIF = 80A, VGS = 0V--,297,--,nan", 'Qrr', (n, 297, n)),
        ("Reverse Recovery Charge Qrr nCIF = 50A, VGS = 0V--,87,--,nan", 'Qrr', (n, 87, n)),
        ("/dt = 100 A/μsReverse recovery charge,Q rr,-dI DR,nan,nan,35,nan,nC", 'Qrr', (n, 35, n)),

        ('tf fall time,nan,nan,- 49.5 - ns', 'tFall', (n, 49.5, n)),
        ('63,Gate charge total’,Qs,-,26 35,nC | Vop=50 V, />=10 A, Ves=0 to 10 V",,,', 'Qg', (n, 26, 35)),
        # ('63,Gate charge total’,Qs,-,26 35,"nC | Vop=50 V, />=10 A, Ves=0 to 10 V",,,', 'Qg', (n, 26, 35)),
        ("Fall time,t,.,14.0,.,ns,Von=75 V, Ves=10 V, [p=45 A", 'tFall', (n, 14, n)),
        ("43,Qgs,-,27,-,nC,,,,,", 'Qgs', (n, 27, n)),
        ("Gate charge at threshold,Qaitth),-,2.7 -,nC,Vop=50 V,,p=10 A, Ves=0 to 10 V", "Qg_th", (n, 2.7, n)),

        ("VSD,TJ = 25°C, IS = 34A,VGS = 0V  ,-,-,1.3", "Vsd", (n, n, 1.3)),  # TODO
        (strip_no_print_latin("VSD,TJ = 25°C, IS = 34A,VGS = 0V  ,-,-,1.3"), "Vsd", (n, n, 1.3)),  # TODO

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

        ("Gate-source charge 1,Qgs1,nan,7,nan,nan,nC", 'Qg_th', (n, 7, n)),  ## datasheets/toshiba/XPN1300ANC.pdf
        ("Output capacitance C oss,nan,nan,-,1152.0,1498,nan", 'Coss', (n, 1152, 1498)),
        # ("nan,nan,Coss,nan,102", 'Coss', (n,102,n)),
        ("Gate-source charge 1,Qgs1,nan,7,nan,nan,nC", 'Qg_th', (n, 7, n)),  # XPN1300ANC
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
        ("QgdGate charge gate-to-drain,11,nC,nan,nan,nan,nan,nan", 'Qgd', (n, 11, n)),
        ("Qrr,nan,VDD = 64 V (see Figure 15: \"Test,-,66,nan,nC", 'Qrr', (n, 66, n)),
        ("Qgd,Gate-drain charge,behavior\"),-,28,-,nC", 'Qgd', (n, 28, n)),
        # "COSS,Output Capacitance,nan,nan,1045.0,1465.0,nan"
        ("QgsGate charge gate-to-source,25,nC,nan,nan,nan,nan,nan", 'Qgs', (n, 25, n)),
        ('Gate plateau voltage,Vplate au,,,4.4,,V,"VDD 40 V, ID = 50 A, VGS = 0 to 10 V",,,,,', 'Vpl', (n, 4.4, n)),
        ("Gate plateau voltage,V plateau,nan,4.6,-,IV", 'Vpl', (n, 4.6, n)),
        ("Rise Time3,4 tr,VDD=75V, RG=3Ω, VGS=10V, -,90,-,nan", 'tRise', (n, 90, n)),
        ("COSS(ER),Effective Output Capacitance, Energy Related (Note 1),VDS = 0 to 50 V, VGS = 0 V,nan,1300,nan,nan",
         'Coss', (n, 1300, n)),
        ('Gate to drain charge1 ),Qgd,,,20,29,nC,"VDD =40 V, ID = 50 A, VGS = 0 to 10 V",,,,,', 'Qgd', (n, 20, 29)),
        # ("Gate-to-Source Charge,QGS,VGS = 10 V, VDS = 75 V; ID = 41 A,15.0,nan,nC", "Qgs", (n, 15, n)),
        ("Gate-Drain Charge,nan,Qgd,nan,nan,nan,13,nan,nan,nan,nC", 'Qgd', (n, 13, n)),
        ("Output capacitance,C oss,nan,-,231.0,300,nan", 'Coss', (n, 231, 300)),
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

        # ['Output Capacitance – Ausgangskapazität' nan nan nan nan] Output Capacitance - Ausgangskapazität,nan,nan,nan,nan Output Capacitance - Ausgangskapazität,Ciss,-,6800 pF,- Output Capacitance - Ausgangskapazität,Coss,-,350 pF,-
        # "Turn-On Delay & Rise Time - Einschaltverzögerung und Anstiegszeit,nan,nan,nan,nan" #DIT095N08

        ("Coss,Output Capacitance,---,340,---,nan,nan,nan", 'Coss', (n, 340, n)),
        ("Coss eff. (ER),Effective Output Capacitance (Energy Related),"
         "---,420,---,VGS = 0V, VDS = 0V to 80V,  See Fig.11,nan,nan", 'Coss', (n, 420, n)),
        ("Reverse Recovery Charge Qrr nCIF = 80A, VGS = 0V--,297,--,nan", 'Q', (n, 297, n)),
        ("Output Capacitance Coss VDS = 50V, --,2730,--,pF", 'C', (n, 2730, n)),
        ("Coss eff. (ER),Effective Output Capacitance (Energy Related),"
         "---,757,---,VGS = 0V, VDS = 0V to 80VSee Fig.11,nan", 'Coss', (n, 757, n)),
        ("Threshold Gate Charge,QG(TH),nan,9.1,nan,nC", "Qg_th", (n, 9.1, n)),

    ]

    for c in cases:
        assert len(c) == 3, c
        assert len(c[2]) == 3, c

    for rl, sym, (min, typ, max) in cases:
        dim = sym[:1]
        m, field_sym = detect_fields('any', rl.split(','))
        assert m and field_sym, 'no field detected in "%s" %s %s' % (rl, m, field_sym)
        assert field_sym[:len(sym)] == sym, ("DETECTED SYMBOL", field_sym, sym, rl)

        f, m = parse_field_csv(rl, dim, field_sym=sym, capture_match=True, mfr='any')
        if sum(map(math.isnan, (min, typ, max))) == 3:
            assert not f, "field value parsed where it should not %s" % (rl,)
        else:
            if not f:
                print('dim regs for', dim, ':')
                print('\n'.join(map(lambda r: r.pattern, dim_regs_csv[dim])))
            assert f, "field value not parsed '%s' (detected %s)" % (rl, field_sym)
        assert math.isnan(min) or min == f.min, (f, min, rl, m.re.pattern)
        assert math.isnan(typ) or typ == f.typ, (f, typ, rl, m.re.pattern)
        assert math.isnan(max) or max == f.max, (f, max, rl, m.re.pattern)
    # "Coss output capacitance,nan,VDS = 50 V; VGS = 0 V; f = 1 MHz;,-,380,-,pF"


def test_pdf_parse():
    d = tabula_read('datasheets/onsemi/FDMS86368-F085.pdf')
    # assert d.Vsd.max == 1.2  # or 1.25

    d = tabula_read('datasheets/st/STP270N8F7.pdf')
    # assert d.Vsd

    d = parse_datasheet('datasheets/st/STP140N8F7.pdf', need_symbols={'Vsd'})
    assert d.Vsd.max == 1.2

    d = parse_datasheet('datasheets/st/STD110N8F6.pdf')
    assert d.Vsd.max == 1.2

    # d = parse_datasheet('datasheets/infineon/AUIRF7759L2TR.pdf')
    d = tabula_read('datasheets/./infineon/AUIRF7759L2TR.pdf', need_symbols={'Vsd'})
    ref = DatasheetFields("None", "None",
                          fields=[Field("Qgd", nan, 62.0, 93.0, "nC"), Field("Qsw", nan, 73.0, nan, "None"),
                                  Field("tRise", nan, 37.0, nan, "ns"),
                                  # Field("trr", nan, 64.0, 96.0, "ns"),
                                  Field("Qrr", nan, 150.0, 225.0, "nC"),
                                  Field("Qg_th", nan, 37.0, nan, "None"), Field("Coss", nan, 1465.0, nan, "None"),
                                  Field("Vsd", nan, nan, 1.3, "V")])
    assert ref.show_diff(d) == 0
    assert d.Qgd == (na, 62, 93)
    assert d.Vsd.max == 1.3

    d = parse_datasheet('datasheets/diodes/DMTH10H005SCT.pdf', need_symbols={'Vsd'})
    assert d.get_mosfet_specs().Vsd == 1.3
    assert d

    d = parse_datasheet('datasheets/vishay/SIR578DP-T1-RE3.pdf')
    assert d.Qg == (na, 24.5, 37) or d.Qg == (na, 32.5, 49)

    ref = DatasheetFields("SIR680ADP-T1-RE3", "vishay",
                          fields=[Field("Qrr", nan, 70.0, 140.0, "nC"),
                                  Field("Coss", nan, 614.0, nan, "pF"),
                                  # Field("Qg", nan, 43.0, 65.0, "nC"),  # <unit err
                                  Field("Qg", nan, 55.0, 83.0, "nC"),  # <unit err
                                  Field("Qgs", nan, 17.0, nan, "nC"),
                                  Field("Qgd", nan, 10.0, nan, "nC"),
                                  Field("tRise", nan, 8.0, 16.0, "ns"),
                                  Field("tFall", nan, 9.0, 18.0, "ns")])
    d = parse_datasheet('datasheets/vishay/SIR680ADP-T1-RE3.pdf')
    assert ref.show_diff(d, err_threshold=1e-9) == 0
    assert d.get_mosfet_specs().Qg in {43e-9, 55e-9}

    # fixable with maco Preview print as pdf (came as CUPS method?)
    df = tabula_read('datasheets/infineon/IRF7779L2TRPBF.pdf')
    assert len(df) > 5

    # fixable with gs:
    df = parse_datasheet('datasheets/onsemi/NVMFS6H800NWFT1G.pdf')
    assert len(df) > 5

    # parse_datasheet(mfr='diodes', mpn='DMTH8003SPS-13')
    d = parse_datasheet('datasheets/toshiba/XPW4R10ANB,L1XHQ.pdf')
    assert len(d) >= 7

    ds = parse_datasheet('datasheets/infineon/IPT025N15NM6ATMA1.pdf', mfr='infineon')
    ref = DatasheetFields("IPT025N15NM6ATMA1", "infineon",
                          fields=[Field("Qrr", nan, 184.0, 368.0, "None"), Field("Qg", nan, 105.0, 137.0, "nC"),
                                  Field("Coss", nan, 2300.0, 3000.0, "pF"), Field("tRise", nan, 16.0, nan, "ns"),
                                  Field("tFall", nan, 19.0, nan, "ns"), Field("Qgs", nan, 41.0, 53.0, "nC"),
                                  Field("Qg_th", nan, 26.0, nan, "nC"), Field("Qgd", nan, 23.0, 35.0, "nC"),
                                  Field("Qsw", nan, 38.0, nan, "nC"), Field("Vpl", nan, 5.4, nan, "V"),
                                  Field("Vsd", nan, 0.86, 1.0, "V")])
    assert ref.show_diff(ds, err_threshold=1e-3) == 0
    assert len(ds) > 8

    d = parse_datasheet('datasheets/infineon/AUIRFS4115.pdf')  # split rows
    assert d.Qrr.typ == 300

    d = parse_datasheet('datasheets/infineon/IPI072N10N3G.pdf')
    assert d.Qsw.typ == 16

    d = tabula_read('datasheets/infineon/BSC021N08NS5ATMA1.pdf', pre_process_methods='nop')
    assert d.tRise.typ == 17
    assert d.tFall.typ == 20  # tFall has typ because it doesnt match the regex
    assert d.Qrr.typ == 80 and d.Qrr.max == 160
    assert d.Qsw.typ == 29
    assert d.Qgd.typ == 20 and d.Qgd.max == 29
    assert d.Vpl.typ == 4.4
    assert d.Qgs.typ == 29

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

    d = tabula_read('datasheets/./onsemi/NTP011N15MC.pdf')
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
    assert abs((d.get_mosfet_specs().Qsw * 1e9) - (d.Qgd.typ + d.Qgs.typ - d.Qg_th.typ)) < 1e-6

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


def test_pdf_ocr():
    import subprocess

    ver = \
    subprocess.run(['tesseract', '-v'], check=True, capture_output=True).stdout.decode().splitlines()[0].split(' ')[-1]
    assert ver == '5.4.1'

    res = subprocess.run(
        'tesseract datasheets/_samples/test2.png stdout --user-words tesseract-stuff/mosfet.user-words tesseract-stuff/tesseract.cfg'.split(
            ' '),
        check=True, capture_output=True).stdout.decode('utf-8')
    # assert 'Qgd' in res
    assert 'Qgs' in res
    assert 'Vplateau' in res  # only works with custom words! tesseract 5.4.1

    d = parse_datasheet('datasheets/./infineon/BSC050N10NS5ATMA1.pdf', need_symbols={'Qrr'})
    assert d.Vsd == (na, 0.87, 1.1), d.print()
    assert d.Coss == (na, 490, 640), d.Coss
    assert d.Qrr == (na, 68, 136)  # ['BSC050N10NS5ATMA1.pdf.r400_ocrmypdf.pdf', 'tabula_cli_guess', 'parse_csv']

    d = parse_datasheet('datasheets/nxp/PSMN3R9-100YSFX.pdf', need_symbols={'Vsd'})
    assert d.Vsd == (na, 0.82, 1)
    assert DatasheetFields(
        "PSMN3R9-100YSFX", "nxp",
        fields=[Field("Qrr", nan, 44.0, nan, "None"), Field("Qgd", 5.0, 18.0, 41.0, "nC"),
                Field("Qg", 40.0, 80.0, 120.0, "nC"), Field("Qgs", 14.0, 23.6, 33.0, "nC"),
                Field("Qg_th", nan, 15.3, nan, "nC"), Field("Qgs2", nan, 8.3, nan, "nC"),
                Field("Coss", 800.0, 1335.0, 2140.0, "pF"), Field("tRise", nan, 18.0, nan, "ns"),
                Field("tFall", nan, 26.0, nan, "ns"),
                Field("Vsd", nan, 0.82, 1.0, "V")]
    ).show_diff(d) == 0

    d = parse_datasheet("datasheets/infineon/IPB072N15N3GATMA1.pdf")
    assert d.Vpl == (na, 5.5, na)

    ref = DatasheetFields("BSZ150N10LS3GATMA1", "infineon",
                          fields=[Field("Coss", nan, 280.0, 370.0, "pF"),
                                  Field("tRise", nan, 4.6, nan, "ns"),
                                  Field("tFall", nan, 3.9, nan, "ns"),
                                  Field("Qgs", nan, 5.2, nan, "nC"),
                                  Field("Qg_th", nan, 2.7, nan, "nC"),
                                  Field("Qgd", nan, 4.1, nan, "nC"),
                                  Field("Qsw", nan, 7.7, nan, "nC"),
                                  Field("Qg", nan, 26, 35, "nC"),
                                  Field("Vpl", nan, 2.7, nan, "V"),
                                  Field("Vsd", nan, 0.87, 1.2, "V"),
                                  Field("Qrr", nan, 84.0, nan, "nC")])

    # d = parse_datasheet('datasheets/infineon/./BSZ150N10LS3GATMA1.pdf')
    # assert ref.show_diff(d, symbols=set(ref.keys()) - {'Qd'}) == 0

    d = tabula_read('datasheets/infineon/BSZ150N10LS3GATMA1.pdf',
                    need_symbols=set(ref.keys()),
                    pre_process_methods=('ocrmypdf_r400',
                                         'r400_ocrmypdf',

                                         'ocrmypdf_r600',
                                         'r600_ocrmypdf',
                                         # 'r800_ocrmypdf',
                                         )
                    )  # takes a long time

    assert ref.show_diff(d, err_threshold=1e-3) == 0
    assert d.Qgs == (na, 5.2, na)
    assert d.Qg_th == (na, 2.7, na)
    assert d.Qsw == (na, 7.7, na)

    d = parse_datasheet('datasheets/././infineon/BSZ150N10LS3GATMA1.pdf')
    assert ref.show_diff(d, err_threshold=1e-3) == 0  # TODO try different text extraction methods with BSZ150N10LS3GATMA1

    # IPB039N10N3GATMA1
    d = parse_datasheet('datasheets/infineon/IPP100N08N3GXKSA1.pdf')  # ocr
    assert d.Qg.typ == 26
    assert d.Qg.max == 35
    assert d.Qgd.typ == 5
    assert d.Qsw.typ == 10
    assert d.Qrr.typ == 102
    mf = d.get_mosfet_specs()
    assert mf.Qsw == 10e-9
    assert mf.Qgs2 == 5e-9
    assert mf.V_pl == 5.2
    if 'Qgs' in d:
        assert d.Qgs.typ == 9
        assert mf.Qg_th == pytest.approx(4e-9, 1e-15)
    assert abs((mf.Qgs + mf.Qgd - mf.Qsw) - mf.Qg_th) < 1e-20
    assert abs((mf.Qgs2 + mf.Qgd) - mf.Qsw) < 1e-20

    from dslib.spec_models import DcDcSpecs
    dcdc = DcDcSpecs(40, 20, 40e3, 10, 200e-9, 20, ripple_factor=.2)
    from dslib.powerloss import dcdc_buck_hs, dcdc_buck_ls
    pl_hs = dcdc_buck_hs(dcdc, mf, 6)
    assert pl_hs.P_sw > 0.5
    pl_ls = dcdc_buck_ls(dcdc, mf)
    assert pl_ls.P_rr > 0.1
    assert pl_ls.P_dt > 0.3

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

    # ds = tabula_read('datasheets/infineon/IRF150DM115XTMA1.pdf',
    #                 pre_process_methods=('r400_ocrmypdf', 'r600_ocrmypdf',),
    #                 need_symbols={'tRise', 'tFall'},
    #                 )
    # assert ds.tRise and ds.tFall

    # macos preview fixes: (CUPS printer)
    ds = tabula_read(
        'datasheets/./infineon/IRF150DM115XTMA1.pdf',
        pre_process_methods=(
            'r600_ocrmypdf',
            'ocrmypdf_r400',
            'r400_ocrmypdf',

            'ocrmypdf_r600',
            # 'r600_ocrmypdf',
        ),
        need_symbols=('tRise', 'tFall'))  # OCR long
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


import pytest


def test_mosfet_specs():
    d = parse_datasheet('datasheets/st/STP310N10F7.pdf')
    assert d.Qgd.typ == 34  # mistake in PDF "Qgd vs gate-source"
    assert d.Qgs.typ == 78
    assert d.get_mosfet_specs().Qsw > 0

    need_symbols = {
        'tRise', 'tFall',  # HS
        'Qgd',  # HS
        ('Qgs', 'Qg_th', 'Qgs2'),  # HS, need one of those.
        'Vsd',  # LS
    }

    d = parse_datasheet('datasheets/ao/AOT66811L.pdf', need_symbols=need_symbols)
    assert 'Qg_th' not in d
    assert DatasheetFields(
        "AOT66811L", "ao", fields=[
            Field("Qrr", nan, 175.0, nan, "None"),
            Field("Vsd", nan, 0.7, 1.0, "V"),
            Field("Coss", nan, 1580.0, nan, "pF"),
            Field("Qg", nan, 77.0, 110.0, "nC"),
            Field("Qgs", nan, 21.0, nan, "nC"),
            Field("Qgd", nan, 15.0, nan, "nC"),
            Field("tRise", nan, 7.0, nan, "ns"),
            Field("tFall", nan, 10.0, nan, "ns")]).show_diff(d) == 0

    # ref.show_diff()
    # assert ref.show_diff(d) == 0
    mf = d.get_mosfet_specs()
    assert mf.Qsw == pytest.approx(26.55e-9, 0.1e-9)

    d = parse_datasheet('datasheets/infineon/IRF6644TRPBF.pdf')
    assert d.Qg_th.typ == 7  # Qgs1
    assert d.Qgs2.typ == 3
    assert d.Qsw.typ == 16
    assert d.Qgs.typ != 7 # qgs_th confusion
    mf = d.get_mosfet_specs()
    assert mf.Qg_th == pytest.approx(7e-9, 1e-20)
    assert mf.Qgs2 == pytest.approx(3e-9, 1e-20)
    assert mf.Qsw == pytest.approx(16e-9, 1e-20)
    assert reference_data(d.part).show_diff(d) == 0


    d = parse_datasheet('datasheets/infineon/AUIRF7769L2TR.pdf')
    assert d.Qg == (na, 200, 300)
    assert d.Qg_th == (na, 30, na)
    assert d.Qgs2 == (na, 9, na)
    assert d.Qgd == (na, 110, 165)
    mf = d.get_mosfet_specs()
    assert mf

    d = parse_datasheet('datasheets/ao/AOT66811L.pdf')
    assert d.get_mosfet_specs()


def test_pdf_rasterize():
    from dslib.pdf2txt.pipeline import rasterize_pdf
    os.path.exists('datasheets/onsemi/FDP047N10.r.pdf') and os.remove('datasheets/onsemi/FDP047N10.r.pdf')
    rasterize_pdf('datasheets/onsemi/FDP047N10.pdf', 'datasheets/onsemi/FDP047N10.r.pdf')
    assert os.stat('datasheets/onsemi/FDP047N10.r.pdf').st_size > os.stat('datasheets/onsemi/FDP047N10.pdf').st_size


def test_extract_fields_from_dataframes():
    ds = dslib.pdf2txt.parse.extract_fields_from_dataframes(
        dfs=[pd.DataFrame(['63,Gate charge total’,Qs,-,26 35,"nC | Vop=50 V, />=10 A, Ves=0 to 10 V",,,'.split(',')])],
        mfr='infineon',
        ds_path='')
    assert ds.Qg == (na, 26, 35)

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


def test_substract_symbols():
    need = {'A', ('B', 'C')}
    assert dslib.pdf2txt.parse.subsctract_needed_symbols(need, {'D'}) is None
    assert need == {'A', ('B', 'C')}

    assert dslib.pdf2txt.parse.subsctract_needed_symbols(need, {'A'}) is None
    assert need == {('B', 'C')}

    assert dslib.pdf2txt.parse.subsctract_needed_symbols(need, {'C'}) is None
    assert not need

    assert dslib.pdf2txt.parse.subsctract_needed_symbols({'A', ('B', 'C')}, {'C', 'B'}, copy=True) == {'A'}


import urllib.parse


def http_build_query(data):
    parents = list()
    pairs = dict()

    def renderKey(parents):
        depth, outStr = 0, ''
        for x in parents:
            s = "[%s]" if depth > 0 or isinstance(x, int) else "%s"
            outStr += s % str(x)
            depth += 1
        return outStr

    def r_urlencode(data):
        if isinstance(data, list) or isinstance(data, tuple):
            for i in range(len(data)):
                parents.append(i)
                r_urlencode(data[i])
                parents.pop()
        elif isinstance(data, dict):
            for key, value in data.items():
                parents.append(key)
                r_urlencode(value)
                parents.pop()
        else:
            pairs[renderKey(parents)] = str(data)

        return pairs

    return urllib.parse.urlencode(r_urlencode(data))


def tests_failing():
    # TODO TODO
    # TODO use tabular browser?
    #  java -jar ~/dev/tabula-java/target/tabula-1.0.6-SNAPSHOT-jar-with-dependencies.jar --guess --pages all datasheets/littelfuse/IXTQ180N10T.pdf

    d = tabula_browser('datasheets/st/STD110N8F6.pdf')
    assert d

    tabula_browser('datasheets/littelfuse/IXTQ180N10T.pdf')
    d = parse_datasheet('datasheets/littelfuse/IXTQ180N10T.pdf',
                        tabular_pre_methods='nop'
                        )
    assert d.Qgd

    d = parse_datasheet('datasheets/littelfuse/IXTA160N10T7.pdf')
    assert d

    d = parse_datasheet('datasheets/infineon/AUIRF7759L2TR.pdf')
    assert d.Qgd == (na, 62, 93)
    assert d.tRise
    assert d.Vsd.max == 1.3


def test_tabular_browser():
    d = tabula_browser('datasheets/nxp/PSMN3R9-100YSFX.pdf')
    assert d

    # assert tabula_browser('datasheets/infineon/IQE050N08NM5CGATMA1.pdf') # fails need OCR

    dfs = tabula_browser('datasheets/vishay/SIR680ADP-T1-RE3.pdf', pad=20)
    d = dslib.pdf2txt.parse.extract_fields_from_dataframes(dfs, mfr='vishay')
    assert d.Qg
    ref = DatasheetFields("None", "None",
                          fields=[Field("Coss", nan, 614.0, nan, "pF"), Field("Qgs", nan, 17.0, nan, "nC"),
                                  Field("Qgd", nan, 10.0, nan, "nC"), Field("tRise", nan, 8.0, 16.0, "nC"),
                                  Field("tFall", nan, 9.0, 18.0, "nC"), Field("Qrr", nan, 70.0, 140.0, "nC"),
                                  Field("Qg", nan, 55.0, 83.0, "nC"), Field("Vsd", nan, 0.72, 1.1, "V")])
    assert ref.show_diff(d) == 0

    dfs = tabula_browser('datasheets/littelfuse/IXTQ180N10T.pdf')
    df = pd.concat(dfs, axis=0)
    d = dslib.pdf2txt.parse.extract_fields_from_dataframes(dfs, mfr='infineon', ds_path='')
    assert d.Qg == (na, 151, na)
    assert d.tRise == (na, 54, na)  # todo typ
    assert d.tFall == (na, 31, na)
    assert d.Qgd == (na, 45, na)
    assert d.Vsd.max == 0.95
    assert d.Coss.max == 923  # todo typ
    print('extrated', len(d), 'fields', set(d.keys()))


if __name__ == '__main__':
    d = parse_datasheet('datasheets/././littelfuse/IXFX360N15T2.pdf')
    assert d

    d = parse_datasheet('datasheets/./nxp/PSMN3R3-80BS,118.pdf', need_symbols={'Vsd', 'tRise'})
    assert d.Qgs2.typ > 5
    assert d.Vpl.typ == 6.1

    test_parse_lines()
    test_tabular_browser()
    test_extract_fields_from_dataframes()
    test_pdf_rasterize()
    test_pdf_parse()
    test_pdf_ocr()
    test_mosfet_specs()

    # ds = tabula_read('datasheets/_samples/infineon/IRF150DM115XTMA1_cyn_char.pdf')
    # assert ds
