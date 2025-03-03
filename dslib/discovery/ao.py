import math

import pandas as pd

from dslib import mfr_tag
from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, download_parts_list
from dslib.field import parse_field_value


async def aosmd_medium_voltage_mosfets():
    fn = await download_parts_list(
        'ao',
        url='https://www.aosmd.com/products/mosfets/medium-voltage-mosfets-40v-400v',
        fn_ext='csv',
        # click='::-p-text(Download results as CSV)',
        click="ul[class^='ParametricSearch_headingControls'] li:nth-child(3)",
    )

    df = pd.read_csv(fn)

    #     # https://www.onsemi.com/download/data-sheet/pdf/ech8667-d.pdf

    parts = []
    for i, row in df.iterrows():
        mfr = mfr_tag('ao')
        mpn = str(row['Product'])
        ds_url = f'https://www.aosmd.com/sites/default/files/res/datasheets/{mpn}.pdf'

        rds_on = parse_field_value(row['RDS(ON) max (mΩ) at VGS=10V']) * 1e-3

        if mpn == 'AOK60N30L':
            rds_on *= .1  # mistake

        parts.append(DiscoveredPart(mfr, mpn, ds_url=ds_url, specs=MosfetBasicSpecs(
            Vds_max=parse_field_value(row['VDS (V)']),
            Rds_on_10v_max=rds_on,
            Qg_max=math.nan,
            Qg_typ=parse_field_value(row['Qg (10V)(nC)']),
            ID_25=parse_field_value(row['ID @ 25°C (A)']),
            Vgs_th_min=math.nan,
            Vgs_th_typ=math.nan,
            Vgs_th_max=parse_field_value(row['VGS(th) max (V)']),
            # qgs, qgd, ciss, coss, weight, qrr
            source=['aosmd.com'],
        ), package=row['Package']))  # Package Name

    # df = pd.read_csv(fn)

    return parts
