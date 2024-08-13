import math
import sys

from dslib.pdf2txt.parse import tabula_read, parse_datasheet, parse_row_value


def parse_line_tests():
    #raise NotImplemented()
    n = math.nan
    cases = [
        ("/dt = 100 A/μsReverse recovery charge,Q rr,-dI DR,nan,nan,35,nan,nC", 'Q' ,(n,35,n)),
        ("Output Capacitance Coss VDS = 50V,--,3042,--,pF", 'C' ,(n,3042,n)),
        # "Output capacitance,C oss,nan,-,523.0,696,nan"
        # "Output Capacitance,Coss,--,392,--,nan,nan"
        # "2000.0,Coss"
        # "Coss Output Capacitance,VGS = 0 V, VDS = 50 V, ƒ = 1 MHz,nan,560,728,pF"
        # C oss output capacitance,Tj = 25 °C; see Figure 16,-,700,-,pF
        # "Output Capacitance,COSS,nan,1690.0,nan"

        #datasheets/diotec/DIT095N08.pdf error parsing field with col_idx {'min': 2, 'max': 4, 'unit': 0} all nan Field("Coss", min=nan, typ=nan, max=nan, unit="None", cond={0: 'Output Capacitance – Ausgangskapazität'})
#['Output Capacitance – Ausgangskapazität' nan nan nan nan] Output Capacitance - Ausgangskapazität,nan,nan,nan,nan Output Capacitance - Ausgangskapazität,Ciss,-,6800 pF,- Output Capacitance - Ausgangskapazität,Coss,-,350 pF,-
#datasheets/diotec/DIT095N08.pdf tRise no value match in  "Turn-On Delay & Rise Time - Einschaltverzögerung und Anstiegszeit,nan,nan,nan,nan"

        # "Coss,Output Capacitance,---,340,---,nan,nan,nan"
        # "Coss eff. (ER),Effective Output Capacitance (Energy Related),---,420,---,VGS = 0V, VDS = 0V to 80V,  See Fig.11,nan,nan"
        # "Reverse Recovery Charge Qrr nCIF = 80A, VGS = 0V--,297,--,nan"
        # "Output Capacitance Coss VDS = 50V, --,2730,--,pF"
    ]

    for rl, dim,(min,typ, max) in cases:
        f = parse_row_value(rl, dim, field_sym=dim)
        assert math.isnan(min) or min == f.min
        assert math.isnan(typ) or typ == f.typ
        assert math.isnan(max) or max == f.max
    # "Coss output capacitance,nan,VDS = 50 V; VGS = 0 V; f = 1 MHz;,-,380,-,pF"

def parse_pdf_tests():
    # TODOå

    d = parse_datasheet('datasheets/goford/GT023N10TL.pdf')
#    assert d['Coss'] == 2730

    d = parse_datasheet('datasheets/vishay/SUD70090E-GE3.pdf')
    assert d['Coss'].typ == 845

    d = parse_datasheet('datasheets/goford/GT52N10D5.pdf')
    assert d['Coss'].typ == 380
    assert d['Qrr'].typ == 87

    d = parse_datasheet('datasheets/vishay/SIR622DP-T1-RE3.pdf')
    assert d['Qrr'].typ == 350 and d['Qrr'].max == 680

    # datasheets/onsemi/NTBLS1D1N08H.pdf
    # d = parse_datasheet('../datasheets/infineon/IPA050N10NM5SXKSA1.pdf')
    #assert d['Rdson'].max == 5.0

    d = parse_datasheet('datasheets/infineon/IRF100B202.pdf')
    assert d['tRise'].typ == 56
    assert d['tFall'].typ == 58
    assert d['Coss'].typ == 319
    # assert d['Qrr'].typ == 105 # or 133 TODO
    # TODO qrr

    #GT016N10TL
    d = parse_datasheet('datasheets/goford/GT016N10TL.pdf')
    assert d['Qrr'].typ == 166

    d = tabula_read('datasheets/toshiba/TPH5R60APL,L1Q.pdf')
    assert d['Qrr'].typ == 55

    #d = tabula_read('datasheets/vishay/SUM70042E-GE3.pdf')
    #assert d['Qrr'].typ == 126 # type in datasheet uC = nC

    d = tabula_read('datasheets/ts/TSM089N08LCR RLG.pdf')
    assert d['Qrr'].typ == 35
    assert d['tFall'].typ == 24
    assert d['tRise'].typ == 21

    d = tabula_read('datasheets/infineon/IAUZ40N08S5N100ATMA1.pdf')
    assert d['tRise'].typ == 1
    assert d['tFall'].typ == 5
    assert d['Qrr'].typ == 32

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


    d = tabula_read('datasheets/vishay/SUM60020E-GE3.pdf')
    assert d['Qrr'].typ == 182 and d['Qrr'].max == 275
    assert d['tRise'].typ == 13
    assert d['tFall'].typ == 15

    d = tabula_read('datasheets/onsemi/NVBGS1D2N08H.pdf') # discontinued NRFND
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

    d = tabula_read('datasheets/st/STL120N8F7.pdf')
    assert d['tRise'].typ == 16.8
    assert d['tFall'].min == 15.4
    assert d['Qrr'].typ == 65.6

    d = tabula_read('datasheets/infineon/BSC021N08NS5ATMA1.pdf')
    assert d['tRise'].typ == 17  # TODO should be typ
    assert d['tFall'].typ == 20  # tFall has typ because it doesnt match the regex
    assert d['Qrr'].typ == 80 and d['Qrr'].max == 160

    # rise 38.1 fall 18.4



    d = tabula_read('datasheets/nxp/PSMN8R2-80YS,115.pdf')
    # assert d # doenst work tabula doesnt find the tables right

    d = tabula_read('datasheets/infineon/BSZ075N08NS5ATMA1.pdf')
    assert d['tRise'].typ == 4
    assert d['tFall'].typ == 4

    d = tabula_read('datasheets/onsemi/FDP027N08B.pdf')
    assert d['tRise'].typ == 66 and d['tRise'].max == 142
    assert d['tFall'].typ == 41 and d['tFall'].max == 92

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

    d = parse_datasheet(mfr='vishay', mpn='SUM60020E-GE3')
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


if __name__ == '__main__':
    parse_line_tests()
    parse_pdf_tests()
    #tests()