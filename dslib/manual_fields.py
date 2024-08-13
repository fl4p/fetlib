import math

from dslib.field import Field


def fallback_specs(mfr, mpn):
    from dslib import mfr_tag
    if mfr_tag(mfr) == 'epc':
        return dict(tRise=2, tFall=2)
    return dict()

infineon = {
    'BSZ070N08LS5ATMA1': [  # need OCR
        Field('Qrr', min=math.nan, typ=27, max=54, unit='nC'),
        Field('tRise', min=math.nan, typ=4.8, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=5.8, max=math.nan, unit='ns'),
    ],

    'BSC019N08NS5ATMA1': [  # tabula failure
        Field('tRise', min=math.nan, typ=17, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=20, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=80, max=160, unit='nC'),
    ],

    'IAUA250N08S5N018AUMA1': [  # tabula failure
        Field('tRise', min=math.nan, typ=11, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=23, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=84, max=math.nan, unit='nC'),
    ],

    'IAUMN08S5N013GAUMA1': [
        Field('tRise', min=math.nan, typ=15, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=51, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=55, max=109, unit='nC'),
    ],

    'IAUMN08S5N012GAUMA1': [
        Field('tRise', min=math.nan, typ=16, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=55, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=56, max=112, unit='nC'),
    ],

    'IST019N08NM5AUMA1': [
        Field('tRise', min=math.nan, typ=29, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=10, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=66, max=math.nan, unit='nC'),
    ],
}

onsemi = {
    'NVMFWS2D1N08XT1G': [  # tabula failure
        Field('tRise', min=math.nan, typ=10, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=6, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=189, max=math.nan, unit='nC'),
    ],

    'NVMFWS6D2N08XT1G': [  # tabula failure
        Field('tRise', min=math.nan, typ=6, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=5, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=88, max=math.nan, unit='nC'),
    ],
    'NTMFWS1D5N08XT1G': [  # tabula failure
        Field('tRise', min=math.nan, typ=9, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=9, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=224, max=math.nan, unit='nC'),
    ],

    'NVMFWS1D9N08XT1G': [  # tabula failure
        Field('tRise', min=math.nan, typ=12, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=7, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=211, max=math.nan, unit='nC'),
    ],
    'NVMFS6H800NT1G': [  # tabula failure
        Field('tRise', min=math.nan, typ=89, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=85, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=82, max=math.nan, unit='nC'),
    ],
    'NTMFS6H800NT1G': [  # tabula failure
        Field('tRise', min=math.nan, typ=89, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=85, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=82, max=math.nan, unit='nC'),
    ],

    'NVMFS6H800NWFT1G': [  # tabula failure
        Field('tRise', min=math.nan, typ=89, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=85, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=82, max=math.nan, unit='nC'),
    ],

    'FDMC008N08C': [  # tabula failure
        Field('tRise', min=math.nan, typ=3, max=10, unit='ns'),
        Field('tFall', min=math.nan, typ=3, max=10, unit='ns'),
        Field('Qrr', min=math.nan, typ=27, max=44, unit='nC', cond='IF = 10 A, di/dt = 300 A/ms'),
        Field('Qrr', min=math.nan, typ=65, max=105, unit='nC', cond='IF = 10 A, di/dt = 1000 A/ms'),
    ],

    'NTMFS08N2D5C': [
        Field('tRise', min=math.nan, typ=11, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=7, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=139, max=222, unit='nC'),
    ]

}

diotec = {
    'DI048N08PQ': [
        Field('tRise', min=math.nan, typ=21, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=45, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=45, max=math.nan, unit='nC'),
    ],
    'DI065N08D1-AQ': [
        Field('tRise', min=math.nan, typ=21, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=45, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=45, max=math.nan, unit='nC'),
    ]
}

diodes = {
    'DMT8008SCT': [
        Field('tRise', min=math.nan, typ=15, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=21, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=49, max=math.nan, unit='nC'),
    ],
}

rohm = {
    'RS6N120BHTB1':  [
        Field('tRise', min=math.nan, typ=47, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=35, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=115, max=math.nan, unit='nC'),
    ],
}

ao = {
    'AOTL66811': [
        Field('tRise', min=math.nan, typ=16, max=math.nan, unit='ns'),
        Field('tFall', min=math.nan, typ=21, max=math.nan, unit='ns'),
        Field('Qrr', min=math.nan, typ=233, max=math.nan, unit='nC'),
    ]
}


vishay = {
    'SUM70042E-GE3': [
        Field('Qrr', min=math.nan, typ=126, max=189, unit='nC'),
    ],

    'SUP70042E-GE3': [
        Field('Qrr', min=math.nan, typ=126, max=189, unit='nC'),
    ]
}