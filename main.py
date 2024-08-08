import json
import math
import os.path

import pandas as pd

from dslib import mfr_tag
from dslib.fetch import fetch_datasheet
from dslib.pdf2txt.parse import parse_datasheet, tabula_read, Field
from dslib.powerloss import dcdc_buck_hs, dcdc_buck_ls
from dslib.spec_models import MosfetSpecs, DcDcSpecs
from dslib.store import Part


def get_part_specs_cached(mpn, mfr):
    dn = os.path.join('specs', mfr)
    fn = os.path.join(dn, mpn + '.json')
    os.path.isdir(dn) or os.makedirs(dn)
    if os.path.exists(fn):
        with open(fn, 'r') as f:
            return json.load(f)

    from dslib.nexar.api import get_part_specs
    specs = get_part_specs(mpn, mfr=mfr)

    if not specs:
        print(mfr, mpn, 'no specs found')
        # return

    with open(fn, 'w') as f:
        json.dump(specs, f)
    return specs


def read_digikey_results(csv_path):
    df = pd.read_csv(csv_path)
    n = len(df)

    result_rows = []
    result_parts = []

    uByp = dict()
    for i, row in df.iterrows():
        pn = row['Mfr Part #']
        u = row.Datasheet
        if pn in uByp:
            pass  # assert u == uByp[pn], (uByp[pn], u)
        uByp[pn] = u

    for i, row in df.iterrows():
        mfr = mfr_tag(row.Mfr)
        mpn = str(row['Mfr Part #'])
        ds_url = row.Datasheet

        datasheet_path = os.path.join('datasheets', mfr, mpn + '.pdf')
        fetch_datasheet(ds_url, datasheet_path, mfr=mfr, mpn=mpn)

        # if mfr in {'infineon', 'ti', 'st', 'nxp', 'toshiba'}:
        #    continue
        # if mfr not in {'mcc'}: #epc
        #    continue

        ds = {}

        import dslib.manual_fields
        man_fields = dslib.manual_fields.__dict__
        if mfr in man_fields:
            for mf in man_fields[mfr].get(mpn, []):
                if mf.symbol not in ds:
                    ds[mf.symbol] = mf

        if os.path.isfile(datasheet_path):
            dsp = parse_datasheet(datasheet_path, mfr=mfr, mpn=mpn)
            for k, f in dsp.items():
                if k not in ds:
                    ds[k] = f


        try:
            specs = get_part_specs_cached(mpn, mfr) or {}
        except Exception as e:
            print(mfr, mpn, 'get_part_specs_cached', e)
            specs = {}

        for sym, sn in dict(tRise='risetime', tFall='falltime').items():
            sv = specs.get(sn) and pd.to_timedelta(specs[sn]).nanoseconds
            if sv and sym not in ds:
                ds[sym] = Field(sym, min=math.nan, typ=sv, max=math.nan)

        for sym, sn in dict(tRise='risetime', tFall='falltime').items():
            sv = specs.get(sn) and pd.to_timedelta(specs[sn]).nanoseconds
            if sv and sym not in ds:
                ds[sym] = Field(sym, min=math.nan, typ=sv, max=math.nan)

        def fallback_specs(mfr, mpn):
            if mfr_tag(mfr) == 'epc':
                return dict(tRise=4, tFall=4)
            return dict()

        fs = fallback_specs(mfr, mpn)

        for sym, typ in fs.items():
            if sym not in ds:
                ds[sym] = Field(sym, min=math.nan, typ=typ, max=math.nan)

        dcdc = DcDcSpecs(vi=62, vo=27, pin=800, f=40e3, Vgs=12, ripple_factor=0.3, tDead=500)
        fet_specs = MosfetSpecs(
            Vds_max=row['Drain to Source Voltage (Vdss)'].strip(' V'),
            Rds_on=row['Rds On (Max) @ Id, Vgs'].split('@')[0].strip(),
            Qg=row['Gate Charge (Qg) (Max) @ Vgs'].split('@')[0].strip(),
            tRise=ds.get('tRise') and (ds.get('tRise').typ_or_max_or_min * 1e-9),
            tFall=ds.get('tFall') and (ds.get('tFall').typ_or_max_or_min * 1e-9),
            Qrr=ds.get('Qrr') and (ds.get('Qrr').typ_or_max_or_min * 1e-9),
        )

        if 1:
            loss_spec = dcdc_buck_hs(dcdc, fet_specs)
            ploss = loss_spec.__dict__.copy()
            ploss['P_hs'] = loss_spec.buck_hs()
            ploss['P_2hs'] = loss_spec.parallel(2).buck_hs()

            loss_spec = dcdc_buck_ls(dcdc, fet_specs)
            ploss['P_rr'] = loss_spec.P_rr
            ploss['P_on_ls'] = loss_spec.P_on
            ploss['P_dt_ls'] = loss_spec.P_dt
            ploss['P_ls'] = loss_spec.buck_ls()
            #ploss['P_2ls'] = loss_spec.parallel(2).buck_ls()
        #except Exception as e:
        #    print(mfr, mpn, 'dcdc_buck_hs', e)
        #    ploss = {}

        row = dict(
            mfr=mfr,
            mpn=mpn,
            housing=row['Package / Case'],

            Vds=row['Drain to Source Voltage (Vdss)'].strip('V '),
            # Rds='',
            Rds_max=fet_specs.Rds_on * 1000,
            Id=row['Current - Continuous Drain (Id) @ 25°C'],
            # Idp='',
            Qg_max=row['Gate Charge (Qg) (Max) @ Vgs'].split('@')[0].strip(),
            Qrr_typ=ds.get('Qrr') and ds.get('Qrr').typ,
            Qrr_max=ds.get('Qrr') and ds.get('Qrr').max,
            tRise_ns=round(fet_specs.tRise * 1e9, 1),
            tFall_ns=round(fet_specs.tFall * 1e9, 1),
            Vth=row['Vgs(th) (Max) @ Id'].split('@')[0].strip('V '),

            FoM=fet_specs.Rds_on * 1000 * (fet_specs.Qg * 1e9),

            **ploss,
        )

        result_rows.append(row)
        result_parts.append(Part(mpn=mpn, mfr=mfr, specs=fet_specs))

    df = pd.DataFrame(result_rows)
    df.to_csv('digikey-01.csv', index=False)

    dslib.store.add_parts(result_parts, overwrite=True)



def tests():
    # TODO
    # datasheets/onsemi/NTBLS1D1N08H.pdf

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
    tests()

    # parse_datasheet('datasheets/onsemi/FDP027N08B.pdf', 'onsemi', mpn='test')

    read_digikey_results(csv_path='digikey-results/80V 26A 10mOhm 250nC.csv')
