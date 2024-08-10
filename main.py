import glob
import math
import os.path
import sys

import pandas as pd

from dslib import mfr_tag
from dslib.fetch import fetch_datasheet
from dslib.pdf2txt.parse import parse_datasheet, Field
from dslib.powerloss import dcdc_buck_hs, dcdc_buck_ls
from dslib.spec_models import MosfetSpecs, DcDcSpecs
from dslib.store import Part
from dslib.tests import tests


def read_digikey_results(csv_path, dcdc):
    df = pd.concat([pd.read_csv(fn) for fn in sorted(glob.glob(csv_path))], axis=0, ignore_index=True)
    #df = pd.read_csv(csv_path)

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

        ds = {}

        # place manual fields:
        import dslib.manual_fields
        man_fields = dslib.manual_fields.__dict__
        if mfr in man_fields:
            for mf in man_fields[mfr].get(mpn, []):
                if mf.symbol not in ds:
                    ds[mf.symbol] = mf

        # parse datasheet (tabula and pdf2txt):
        if os.path.isfile(datasheet_path):
            dsp = parse_datasheet(datasheet_path, mfr=mfr, mpn=mpn)
            for k, f in dsp.items():
                if k not in ds:
                    ds[k] = f

        # try nexar api:
        try:
            from dslib.nexar.api import get_part_specs_cached
            specs = get_part_specs_cached(mpn, mfr) or {}
        except Exception as e:
            print(mfr, mpn, 'get_part_specs_cached', e)
            specs = {}

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

        try:
            fet_specs = MosfetSpecs(
                Vds_max=row['Drain to Source Voltage (Vdss)'].strip(' V'),
                Rds_on=row['Rds On (Max) @ Id, Vgs'].split('@')[0].strip(),
                Qg=row['Gate Charge (Qg) (Max) @ Vgs'].split('@')[0].strip(),
                tRise=ds.get('tRise') and (ds.get('tRise').typ_or_max_or_min * 1e-9),
                tFall=ds.get('tFall') and (ds.get('tFall').typ_or_max_or_min * 1e-9),
                Qrr=ds.get('Qrr') and (ds.get('Qrr').typ_or_max_or_min * 1e-9),
            )
        except:
            print(mfr, mpn, 'error creating mosfetspecs')
            raise

        if 1:
            loss_spec = dcdc_buck_hs(dcdc, fet_specs)
            ploss = loss_spec.__dict__.copy()
            del ploss['P_dt']
            ploss['P_hs'] = loss_spec.buck_hs()
            ploss['P_2hs'] = loss_spec.parallel(2).buck_hs()

            loss_spec = dcdc_buck_ls(dcdc, fet_specs)
            ploss['P_rr'] = loss_spec.P_rr
            ploss['P_on_ls'] = loss_spec.P_on
            ploss['P_dt_ls'] = loss_spec.P_dt
            ploss['P_ls'] = loss_spec.buck_ls()
            ploss['P_2ls'] = loss_spec.parallel(2).buck_ls()
        # except Exception as e:
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
            FoMrr=fet_specs.Rds_on * 1000 * (fet_specs.Qrr * 1e9),

            **ploss,
        )

        result_rows.append(row)
        result_parts.append(Part(mpn=mpn, mfr=mfr, specs=fet_specs))

    df = pd.DataFrame(result_rows)
    df.to_csv('digikey-01.csv', index=False)

    dslib.store.add_parts(result_parts, overwrite=True)


if __name__ == '__main__':
    tests()

    mfr = 'onsemi'
    mpn = 'FDP090N10'
    datasheet_path = os.path.join('datasheets', mfr, mpn + '.pdf')
    fetch_datasheet('https://www.onsemi.com/pdf/datasheet/fdp090n10-d.pdf', datasheet_path, mfr=mfr, mpn=mpn)

    # parse_datasheet('datasheets/onsemi/FDP027N08B.pdf', 'onsemi', mpn='test')
    dcdc = DcDcSpecs(vi=62, vo=27, pin=800, f=40e3, Vgs=12, ripple_factor=0.3, tDead=500e-9)
    read_digikey_results(csv_path='digikey-results/*.csv',dcdc=dcdc)
