import math

import pandas as pd

from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, download_parts_list


async def epc_gan():
    fn = await download_parts_list('epc', 'https://epc-co.com/epc/products/gan-fets-and-ics',
                                   'xlsx', 'ganfets', click='button.download')
    df = pd.read_excel(fn)

    parts = []

    for i, row in df.iterrows():
        mpn = row['PartNumber']
        if row['Configuration'] in {'Half Bridge', 'Half Bridge Driver IC'}:
            continue

        if not row['Configuration'].startswith('Single'):
            continue

        parts.append(DiscoveredPart(
            'epc', mpn,
            package=row['Package(mm)'],
            ds_url=f'https://epc-co.com/epc/documents/datasheets/{mpn}_datasheet.pdf',
            specs=MosfetBasicSpecs(
                substrate='GaN',
                Vds_max=float(row['VDSmax']),
                Rds_on_10v_max=float(str(row['MaxRDS(on)(mΩ)@5VGS']).split(',')[0]) * 1e-3,
                ID_25=float(str(row['ID (A)']).split(',')[0]),
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
                Vgs_th_max=math.nan,
                Qg_typ=float(str(row['QGtyp(nC)']).split(',')[0]),
                Qg_max=math.nan,
                source=['epc-co.com'],
            )))

    return parts
