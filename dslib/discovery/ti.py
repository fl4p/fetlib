import math

import openpyxl.styles
import pandas as pd

from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, download_parts_list


async def ti_mosfets():
    import openpyxl.styles.colors
    import re
    openpyxl.styles.colors.aRGB_REGEX = re.compile("^([A-Fa-f0-9]{8}|[A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")

    fn = await download_parts_list(
        'ti',
        url='https://www.ti.com/power-management/mosfets/products.html',
        fn_ext='xlsx',
        click='ti-button.ti-selection-tool-action-bar-download')

    df = pd.read_excel(fn, engine='openpyxl', engine_kwargs=dict(data_only=False)).iloc[9:]
    df.columns = df.iloc[0]
    df = df.iloc[1:]
    df.to_csv(fn.replace('.xlsx', '.csv'), index=False)

    parts = []
    link_reg = re.compile(r'=HYPERLINK\("(?P<url>.+)", "(?P<text>.+)"\)')

    for i, row in df.iterrows():
        parts.append(DiscoveredPart(
            mfr='ti',
            mpn=link_reg.match(row['Product or Part number']).groupdict().get('text'),
            # mpn2=row['Product'],
            ds_url=link_reg.match(row['PDF data sheet']).groupdict().get('url'),
            specs=MosfetBasicSpecs(
                Vds_max=row['VDS (V)'],
                Rds_on_10v_max=row['Rds(on) at VGS=10 V (max) (mΩ)'] * 1e-3,
                ID_25=row['ID - continuous drain current at TA=25°C (A)'],
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
                Vgs_th_max=math.nan,
                Qg_typ=math.nan,
                Qg_max=math.nan,
                source=['ti_products'],
            ), package=row['Package type']
        ))
    return parts
