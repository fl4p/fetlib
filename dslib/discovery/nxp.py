import math

import xlrd

from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, download_parts_list
from dslib.field import parse_field_value


async def nexperia_mosfets():
    #
    fn = await download_parts_list(
        'nxp',
        url='https://www.nexperia.com/products/mosfets/power-mosfets',
        fn_ext='xls',
        # click='::-p-text(Download results as CSV)',
        click="button[data-event^='download-excel']",
    )

    b = xlrd.open_workbook(fn)
    b.sheets()
    sheet = b.sheets()[0]
    for i in range(20):
        if sheet.row(i)[0].value == 'Manufacturer':
            break
    else:
        raise Exception('No manufacturer found')

    cols = {}
    for j in range(len(sheet.row(i))):
        if not sheet.row(i)[j].value:
            break
        cols[sheet.row(i)[j].value] = j

    parts = []
    while True:
        i += 1
        try:
            row = sheet.row(i)
        except IndexError:
            break
        v = {cn: row[j].value for cn, j in cols.items()}
        ds_url = sheet.hyperlink_map[(i, cols['Datasheet'])].url_or_path
        if ds_url == 'https://assets.nexperia.comnull':
            ds_url = None
        parts.append(DiscoveredPart(
            mfr='nxp', mpn=v['Type number'],
            ds_url=ds_url,
            package=v['Package name'] + ',' + v['Package version'],
            specs=MosfetBasicSpecs(
                Vds_max=parse_field_value(v['VDS [max] (V)']),
                Rds_on_10v_max=parse_field_value(v['RDSon [max] @ VGS = 10 V (mΩ)']) * 1e-3,
                ID_25=parse_field_value(v['ID [max] (A)']),
                Vgs_th_typ=parse_field_value(v['VGSth [typ] (V)']),
                Vgs_th_min=math.nan,
                Vgs_th_max=math.nan,
                Qg_typ=parse_field_value(v['QG(tot) [typ] @ VGS = 10 V (nC)']),
                # text:'RDSon [typ] @ VGS = 10 V (mΩ)'
                # text:'Release date'
                Qg_max=math.nan,
                source=['nexperia.com'],
            ),
        ))

    return parts
