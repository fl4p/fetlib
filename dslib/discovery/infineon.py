import math

import pandas as pd

from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, download_parts_list


async def infineon_mosfets():
    fn = await download_parts_list(
        'infineon',
        'https://www.infineon.com/design-resources/finder-selection-tools/mosfet-finder',
        fn_ext='xlsx',
        # click='a[data-track-name="downloadLink"]',
        click='span.icon.icon-download'
        # close=True,
    )

    df = pd.read_excel(fn)  # ,  engine='openpyxl')
    df.to_csv(fn.replace('.xlsx', '.csv'), index=False)

    def parse_field(v, t):
        if isinstance(v, str):
            v = v.split('_x000d_')[0]
            if v.endswith(' mΩ'):
                return t(v[:-3]) * 1e-3
            else:
                return t(v)
        elif isinstance(v, float):
            if t == str and math.isnan(v):
                return ''
        return t(v)

    fixes = {
        'IRFR420TRPBF': {'RDS (on) (@10V) max': '3', }
    }

    parts = []
    for i, row in df.iterrows():
        mpn = str(row['Part number']).split('_x000d_')[0]
        row = {k: str(v).split('_x000d_')[0].split(',')[0] for k, v in row.items()}
        row.update(fixes.get(mpn, {}))
        vds = row['VDS max']
        if isinstance(vds, str):
            vds = float(vds.strip('V ').split('_')[0])
        parts.append(DiscoveredPart(
            mfr='infineon',
            mpn=mpn,
            mpn2=row['OPN'] if row['OPN'] != 'nan' else None,
            ds_url=row['Datasheet link'],
            specs=MosfetBasicSpecs(
                substrate='SiC' if 'CoolSiC' in row['Technology'] else 'Si', # infineon no GaN
                Vds_max=vds,
                Rds_on_10v_max=parse_field(str(row['RDS (on) (@10V) max']), float),
                ID_25=parse_field(str(row['ID  (@25°C) max']).strip('A '), float), # ID  (@25°C) max
                # ^ if this column is missing, open the infineon product finder page in another browser and manually download
                Vgs_th_min=parse_field(str(row['VGS(th) min']).strip('V '), float),
                Vgs_th_typ=parse_field(row['VGS(th)'].strip('V '), float),
                Vgs_th_max=parse_field(str(row['VGS(th) max']).strip('V '), float),
                Qg_typ=parse_field(str(row['QG (typ @10V)']).replace(' nC', ''), float),
                Qg_max=parse_field(str(row['QG (typ @10V) max']).replace(' nC', ''), float),
                source=['infineon_products'],
            ), package=parse_field(row['Package name'], str),
        ))

    return parts
