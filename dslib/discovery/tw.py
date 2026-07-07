import math

import pandas as pd

from dslib import mfr_tag
from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, download_parts_list


async def taiwansemi_nfets():
    # app._component.methods.exportProductTable()
    fn = await download_parts_list(
        'ts',
        url='https://www.taiwansemi.com/en/product-filter/?category=n-channel-mosfets-22',
        fn_ext='xlsx',
        click='div.table-box div.right-box>button.el-button.el-button--primary',
    )

    df = pd.read_excel(fn)
    df.to_csv(fn.replace('.xlsx', '.csv'), index=False)

    parts = []
    for i, row in df.iterrows():
        mfr = mfr_tag('taiwansemi')
        mpn = str(row['Part Number'])
        ds_url = row.Datasheet
        parts.append(DiscoveredPart(mfr, mpn, ds_url=ds_url, specs=MosfetBasicSpecs(
            Vds_max=float(row['VDS (V)']),
            Rds_on_10v_max=float(row['RDS(ON) @ 10V Max. (mΩ)']) * 1e-3,
            Qg_max=math.nan,
            Qg_typ=float(row['Qg (nC) @ 10V']),
            ID_25=float(row['ID Max. (A)']),
            Vgs_th_min=row['VGS(th) Min. (V)'],
            Vgs_th_typ=row['VGS(th) Typ. (V)'],
            Vgs_th_max=row['VGS(th) Max. (V)'],
            # qgs, qgd, ciss, coss, weight
            source=['taiwansemi.com'],
        ), package=row['Package']))

    # df = pd.read_csv(fn)

    return parts
