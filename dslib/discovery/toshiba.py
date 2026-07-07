import math

from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, download_parts_list


async def toshiba_mosfets():
    fn = await download_parts_list(
        'toshiba',
        "https://toshiba.semicon-storage.com/parametric/product?code=param_304",
        fn_ext='xlsx',
        click=[
            'button.funcBtn_item.funcBtn_item--last.funcBtn_item-download',
            # 'ul.funcBtn_item-download_accordion.funcBtn_item-download_accordion-file li:last-child button', # csv
            'ul.funcBtn_item-download_accordion.funcBtn_item-download_accordion-file li:first-child button',  # xlsx
        ]
    )

    import openpyxl

    wb = openpyxl.load_workbook(fn)
    ws = wb['param_304_en']

    cols = {}
    cl = list(ws.columns)
    for i in range(len(cl)):
        n = ws.cell(row=1, column=i + 1).value
        cols[n] = list(cl[i])

    parts = []
    for i in range(1, len(list(ws.rows))):
        parts.append(DiscoveredPart(
            mfr='toshiba',
            mpn=cols['Part Number'][i].value,
            # mpn2=row['Product'],
            ds_url=cols['Datasheet'][i].hyperlink and cols['Datasheet'][i].hyperlink.target,
            specs=MosfetBasicSpecs(
                Vds_max=float(cols['VDSS(V)'][i].value or 'nan'),
                Rds_on_10v_max=float(cols['RDS(ON)Max(\u03a9)|VGS|=10V'][i].value or 'nan'),  # ohm
                ID_25=float(cols['ID(A)'][i].value or 'nan'),
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
                Vgs_th_max=math.nan,
                Qg_typ=float(cols['Qg(nC)'][i].value or 'nan'),  # nC
                Qg_max=math.nan,
                source=['toshiba_products'],
            ), package=cols['Toshiba Package Name'][i].value,
        ))

    return parts
