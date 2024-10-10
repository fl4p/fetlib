import os

all_paths = []


class BMRef():
    def __init__(self, file_path, fields=None, tags=None):
        self.file_path = file_path
        if file_path not in all_paths:
            assert os.path.isfile(file_path)
            all_paths.append(file_path)


# scrambled text (new)
BMRef('datasheets/infineon/IPP028N08N3GXKSA1.pdf', [

], tags='weirdEnc')

BMRef('datasheets/infineon/IPP180N10N3GXKSA1.pdf', [], tags='weirdEnc')

# scrambled text (old)
BMRef('datasheets/infineon/IPP057N08N3GHKSA1.pdf', [
], tags='weirdEnc')

BMRef('datasheets/infineon/IPP65R420CFDXKSA2.pdf')
BMRef('datasheets/infineon/IMT40R036M2HXTMA1.pdf')  # 400v, 2024-04
BMRef('datasheets/infineon/BSZ070N08LS5ATMA1.pdf')  # need ocr
BMRef('datasheets/infineon/IRL540NPBF.pdf')  # scanned, need OCR
BMRef('datasheets/infineon/IPB019N08N3GATMA1.pdf')  # scrambled

BMRef('datasheets/nxp/PSMN3R5-80PS,127.pdf')  # 2011
BMRef('datasheets/nxp/PSMN020-150W,127.pdf')  # 1999 philips
BMRef('datasheets/nxp/PSMN8R5-100ESQ.pdf')  # 2012 colored
BMRef('datasheets/nxp/PSMN7R2-100YSFX.pdf')  # 2023

BMRef('datasheets/diodes/DMT10H9M9LCT.pdf')
BMRef('datasheets/littelfuse/IXFP180N10T2.pdf')
BMRef('datasheets/onsemi/FDP047N10.pdf', tags='encrypted')
BMRef('datasheets/rohm/RX3P07CBHC16.pdf')
BMRef('datasheets/good_ark/GSFH9R015.pdf')
BMRef('datasheets/ti/CSD19503KCS.pdf')
BMRef('datasheets/ti/CSD19531Q5A.pdf')
BMRef('datasheets/ti/CSD19506KTT.pdf')

BMRef('datasheets/infineon/IPF015N10N5ATMA1.pdf')

BMRef('datasheets/ti/CSD19532KTTT.pdf')

BMRef('datasheets/panjit/PSMP050N10NS2_T0_00601.pdf')
BMRef('datasheets/goford/GT023N10TL.pdf')
BMRef('datasheets/vishay/SUD70090E-GE3.pdf')
BMRef('datasheets/goford/GT52N10D5.pdf')
BMRef('datasheets/vishay/SIR622DP-T1-RE3.pdf')
BMRef('datasheets/infineon/IRF100B202.pdf')  # multi Qrr
BMRef('datasheets/goford/GT016N10TL.pdf')  # from tests

BMRef('datasheets/vishay/SUM60020E-GE3.pdf', tags='trr')  # "reverse recovery fall time"
BMRef('datasheets/diodes/DMTH8003SPS-13.pdf')
BMRef('datasheets/toshiba/TK6R9P08QM,RQ.pdf')
BMRef('datasheets/toshiba/TK100E08N1,S1X.pdf')
BMRef('datasheets/onsemi/FDBL0150N80.pdf')
BMRef('datasheets/onsemi/FDP027N08B.pdf')
BMRef('datasheets/infineon/ISC046N13NM6ATMA1.pdf')

BMRef('datasheets/infineon/IQDH88N06LM5CGSCATMA1.pdf')  # 2024-05

BMRef('datasheets/epc_space/FBG10N30BC.pdf')  # qgs
BMRef('datasheets/onsemi/NTMFWS1D5N08XT1G.pdf')  # tabular failure
BMRef('datasheets/infineon/ISC030N10NM6ATMA1.pdf')  #

if 'v2':
    BMRef('datasheets/infineon/IPP100N08N3GXKSA1.pdf', tags='weirdEnc')
    BMRef('datasheets/infineon/AUIRFS4115.pdf', tags='splitRow')

    BMRef('datasheets/nxp/PSMN4R4-80BS,118.pdf', tags='borderless,multiTyp')
    BMRef('datasheets/infineon/IPT025N15NM6ATMA1.pdf', tags='multiQrr')
    BMRef('datasheets/toshiba/TPH5R60APL,L1Q.pdf')

    BMRef('datasheets/infineon/IRF6644TRPBF.pdf', tags='Qgs1')


    BMRef('datasheets/infineon/BSZ150N10LS3GATMA1.pdf', tags='ocr')

    BMRef('datasheets/nxp/PSMN5R5-100YSFX.pdf', tags='QGS(th-pl)')

    BMRef('datasheets/onsemi/FDD86367.pdf', tags='Qg(tot)')
    BMRef('datasheets/toshiba/TK34A10N1.pdf', tags='Qgs1')

    BMRef('datasheets/littelfuse/IXTQ180N10T.pdf', tags='tabulaDetectIssue,tabulaBrowser')

    #DMTH10H005SCT# Vsd 13
    # AUIRF7759L2TR # Qgd
    AUIRF7759L2TR
    AUIRF7769L2TR # qgs1,qgs2,Qgodr
    'datasheets/st/STP140N8F7.pdf'
    BMRef('datasheets/onsemi/FDMS86368-F085.pdf', tags='VsdStacked')
    # SIRS5800DP-T1-GE3.pdf
    # IXTQ180N10T # tabula detection issue, better in browser
    # IRF150DM115XTMA1 # tRise and tFall confusion? long ocr

    IQE050N08NM5CGATMA1 #ocr
    # IXFX360N15T2, 'Qrm
    # IR680ADP-T1-RE3 # complex structured tables
    # SIR578DP-T1-RE3.pdf # double Qg
    # STP310N10F7 # Qgd labeled as gate-source

    # datasheets/littelfuse/IXTA160N10T7.pdf
    # 'datasheets/mcc/MCB70N10YA-TP.pdf'

    # IAUTN08S5N012L lin
    # IRFS7730TRL7PP tags="QrrMulti"


    # BSC042NE7NS3GATMA1 vectorized text
    # PSMN3R3-80BS,118.pdf ,
    BMRef("datasheets/infineon/IPP048N12N3GXKSA1.pdf", tags='weirdEnc')

    BMRef('BSZ150N10LS3GATMA1.pdf', tags='trr')

    # IRFS7730TRLPBF multi qrr (temperature)

    # BSB028N06NN3GXUMA2 loos tables

# ISC046N13NM6ATMA1
# infineon/IQDH88N06LM5CGSCATMA1


# from tests


for fp in sorted(all_paths):
    print(fp)
