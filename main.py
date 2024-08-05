import json
import json
import os.path

import pandas as pd

from dslib import mfr_tag
from dslib.fetch import fetch_datasheet
from dslib.parse import parse_datasheet


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
        #return

    with open(fn, 'w') as f:
        json.dump(specs, f)
    return specs


def read_digikey_results(csv_path):
    df = pd.read_csv(csv_path)
    n = len(df)

    result_rows = []

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

        try:
            specs = get_part_specs_cached(mpn, mfr) or {}
        except Exception as e:
            print(mfr, mpn, e)
            specs = {}



        datasheet_path = os.path.join('datasheets', mfr, mpn + '.pdf')
        fetch_datasheet(ds_url, datasheet_path, mfr=mfr, mpn=mpn)

        # if mfr in {'infineon', 'ti', 'st', 'nxp', 'toshiba'}:
        #    continue
        # if mfr not in {'mcc'}: #epc
        #    continue

        if os.path.isfile(datasheet_path):
            ds = parse_datasheet(datasheet_path, mfr=mfr, mpn=mpn)
        else:
            ds = {}

        row = dict(
            mfr=mfr,
            mpn=mpn,
            housing=row['Package / Case'],
            Vds=row['Drain to Source Voltage (Vdss)'],
            Rds='',
            Rds_max=row['Rds On (Max) @ Id, Vgs'].split('@')[0].strip(),
            Id=row['Current - Continuous Drain (Id) @ 25°C'],
            Idp='',
            Qg_max=row['Gate Charge (Qg) (Max) @ Vgs'],
            Qrr_typ=ds.get('Qrr') and ds.get('Qrr').typ,
            Qrr_max=ds.get('Qrr') and ds.get('Qrr').typ,
            tRise=specs.get('risetime') and pd.to_timedelta(specs['risetime']).nanoseconds,
            tFall=specs.get('falltime') and pd.to_timedelta(specs['falltime']).nanoseconds,
            Vth=row['Vgs(th) (Max) @ Id'].split('@')[0].strip(),
        )

        result_rows.append(row)

    df = pd.DataFrame(result_rows)
    df.to_csv('digikey-01.csv', index=False)



    pass


def tests():
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
