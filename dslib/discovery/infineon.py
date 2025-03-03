import math

import pandas as pd

from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, download_parts_list


async def infineon_mosfets():
    fn = await download_parts_list(
        'infineon',
        'https://www.infineon.com/cms/en/design-support/finder-selection-tools/product-finder/mosfet-finder/',
        fn_ext='xlsx',
        click='a[data-track-name="downloadLink"]',
        # close=True,
    )

    df = pd.read_excel(fn)
    df.to_csv(fn.replace('.xlsx', '.csv'), index=False)

    def parse_field(v, t):
        if isinstance(v, str):
            return t(v.split('_x000d_')[0])
        elif isinstance(v, float):
            if t == str and math.isnan(v):
                return ''
        return t(v)

    parts = []
    for i, row in df.iterrows():
        vds = row['VDS max [V]']
        if isinstance(vds, str):
            vds = float(vds.split('_')[0])
        parts.append(DiscoveredPart(
            mfr='infineon',
            mpn=row['OPN'].split('_x000d_')[0],
            mpn2=row['Product'].split('_x000d_')[0],
            ds_url=row['Data Sheet'],
            specs=MosfetBasicSpecs(
                Vds_max=vds,
                Rds_on_10v_max=parse_field(row['RDS (on) @10V max [\u2126]'], float) * 1e-3,
                ID_25=parse_field(row['ID  @25°C max [A]'], float),
                Vgs_th_min=parse_field(row['VGS(th) min [V]'], float),
                Vgs_th_typ=parse_field(row['VGS(th) [V]'], float),
                Vgs_th_max=parse_field(row['VGS(th) max [V]'], float),
                Qg_typ=parse_field(row['QG typ @10V [C]'], float),
                Qg_max=parse_field(row['QG typ @10V max [C]'], float),
                source=['infineon_products'],
            ), package=parse_field(row['Standard Package name'], str),
        ))

    return parts
