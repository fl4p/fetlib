import math
import asyncio
import math
import os.path
from typing import List

import numpy as np
import pandas as pd

import dslib.manual_fields
from discover_parts import discover_mosfets
from dslib import round_to_n
from dslib.fetch import fetch_datasheet
from dslib.field import Field
from dslib.parts_discovery import DiscoveredPart
from dslib.pdf2txt.parse import parse_datasheet
from dslib.powerloss import dcdc_buck_hs, dcdc_buck_ls
from dslib.spec_models import MosfetSpecs, DcDcSpecs
from dslib.store import Part


def main():
    dcdc = DcDcSpecs(vi=62, vo=27, pin=800, f=40e3, Vgs=12, ripple_factor=0.3, tDead=500e-9)
    print('DC-DC:', dcdc)

    parts = asyncio.run(discover_mosfets())
    parts = [p for p in parts if p.specs.Vds_max >= (dcdc.Vi * 1.25) and p.specs.Vds_max <= (dcdc.Vi * 4) and p.specs.ID_25 > dcdc.Io_max * 1.2]
    generate_parts_power_loss_csv(parts, dcdc=dcdc)


def generate_parts_power_loss_csv(parts: List[DiscoveredPart], dcdc: DcDcSpecs):
    result_rows = []  # csv
    result_parts = []  # db storage
    all_mpn = set()

    if not os.path.isdir('datasheets'):
        try:
            import subprocess
            subprocess.run(['git', 'clone', 'https://github.com/open-pe/fet-datasheets', 'datasheets'])
        except Exception as e:
            print('git clone error:', e)

    for part in parts:
        mfr = part.mfr
        mpn = part.mpn
        ds_url = part.ds_url
        ds_path = part.get_ds_path()

        if not os.path.exists(ds_path):
            fetch_datasheet(ds_url, ds_path, mfr=mfr, mpn=mpn)

        ds = {}

        # place manual fields:
        man_fields = dslib.manual_fields.__dict__
        if mfr in man_fields:
            for mf in man_fields[mfr].get(mpn, []):
                if mf.symbol not in ds:
                    ds[mf.symbol] = mf

        # parse datasheet (tabula and pdf2txt):
        if os.path.isfile(ds_path):

            k = (mfr, mpn)
            if k in all_mpn:
                continue
            all_mpn.add(k)

            dsp = parse_datasheet(ds_path, mfr=mfr, mpn=mpn)
            for k, f in dsp.items():
                if k not in ds:
                    ds[k] = f

        # try nexar api:
        try:
            from dslib.nexar.api import get_part_specs_cached
            specs = {} # get_part_specs_cached(mpn, mfr) or {}
        except Exception as e:
            print(mfr, mpn, 'get_part_specs_cached', e)
            specs = {}

        for sym, sn in dict(tRise='risetime', tFall='falltime').items():
            sv = specs.get(sn) and pd.to_timedelta(specs[sn]).nanoseconds
            if sv and sym not in ds:
                ds[sym] = Field(sym, min=math.nan, typ=sv, max=math.nan)

        # fallback specs for GaN etc (EPC tRise and tFall)
        fs = dslib.manual_fields.fallback_specs(mfr, mpn)
        for sym, typ in fs.items():
            if sym not in ds:
                ds[sym] = Field(sym, min=math.nan, typ=typ, max=math.nan)

        def first(a): return next((x for x in a if x and not math.isnan(x)), math.nan)

        # create specification for DC-DC loss model
        try:
            mf_fields = [
                'Qrr', 'Vsd',  # body diode
                'Qgd', 'Qgs', 'Qgs2', 'Qg_th',  # gate charges
                'Coss', 'Qsw',
            ]
            field_mul = lambda sym: 1 if sym[0] == 'V' else 1e-9

            fet_specs = MosfetSpecs(
                Vds_max=part.specs.Vds_max,
                Rds_on=part.specs.Rds_on_10v_max,
                Qg=first((ds.get('Qg') and ds.get('Qg').typ_or_max_or_min, part.specs.Qg_max_or_typ_nC)) * 1e-9,
                tRise=ds.get('tRise') and (ds.get('tRise').typ_or_max_or_min * 1e-9),
                tFall=ds.get('tFall') and (ds.get('tFall').typ_or_max_or_min * 1e-9),
                **{k: ds.get(k) and (ds.get(k).typ_or_max_or_min * field_mul(k)) for k in mf_fields},
                Vpl=ds.get('Vpl') and ds.get('Vpl').typ_or_max_or_min,
            )
        except:
            print(mfr, mpn, 'error creating mosfet specs')
            print(part, part.specs.__dict__)
            print('\n'.join(map(str, ds.items())))
            parse_datasheet.invalidate(ds_path, mfr=mfr, mpn=mpn)

            raise

        # compute power loss
        if 1:
            loss_spec = dcdc_buck_hs(dcdc, fet_specs, rg_total=6, fallback_V_pl=4.5)
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
            housing=part.package,

            Vds=part.specs.Vds_max,
            Rds_max=fet_specs.Rds_on * 1000,
            Id=part.specs.ID_25,

            Qg_max=fet_specs.Qg * 1e9,
            Qgs=ds.get('Qgs') and ds.get('Qgs').typ_or_max_or_min,
            Qgd=ds.get('Qgd') and ds.get('Qgd').typ_or_max_or_min,
            Qsw=fet_specs and (fet_specs.Qsw * 1e9),

            C_oss_pF=ds.get('Coss') and ds.get('Coss').max_or_typ_or_min,

            Qrr_typ=ds.get('Qrr') and ds.get('Qrr').typ,
            Qrr_max=ds.get('Qrr') and ds.get('Qrr').max,

            tRise_ns=round(fet_specs.tRise * 1e9, 1),
            tFall_ns=round(fet_specs.tFall * 1e9, 1),

            Vth=part.specs.Vgs_th_max,
            Vpl=fet_specs and fet_specs.V_pl,

            FoM=fet_specs.Rds_on * 1000 * (fet_specs.Qg * 1e9),
            FoMrr=fet_specs.Rds_on * 1000 * (fet_specs.Qrr * 1e9),
            FoMsw=fet_specs.Rds_on * 1000 * (fet_specs.Qsw * 1e9),

            **ploss,
        )

        result_rows.append(row)
        result_parts.append(Part(mpn=mpn, mfr=mfr, specs=fet_specs))

    # print('no P_sw')
    # for row in result_rows:
    #    if math.isnan(row.get('P_sw') or math.nan):
    ##        #no_psw.append((mfr, mpn))
    #        #print(os.path.join('datasheets', row['mfr'], row['mpn'] + '.pdf'))

    df = pd.DataFrame(result_rows)

    df.sort_values(by=['Vds', 'mfr', 'mpn'], inplace=True, kind='mergesort')

    for col in df.columns:
        if col.startswith('P_') or col.startswith('FoM'):
            df.loc[:, col] = df.loc[:, col].map(lambda v: round_to_n(v, 2) if isinstance(v, float) else v)

    os.path.exists('out') or os.makedirs('out', exist_ok=True)
    out_fn = f'out/fets-{dcdc.fn_str("buck")}.csv'
    df.to_csv(out_fn, index=False, float_format=lambda f: round_to_n(f, 4))
    print('written', out_fn)

    dslib.store.add_parts(result_parts, overwrite=True)

    print('stored', len(result_parts), 'parts')


if __name__ == '__main__':
    # parse_pdf_tests()
    main()
