import datetime
import math
import os.path
from typing import Literal

import pandas as pd

from dslib.fetch import download_with_chromium


class MosfetBasicSpecs():
    def __init__(self, Vds_max, Rds_on_10v_max, ID_25, Vgs_th_max, Qg_typ, Qg_max):
        self.Vds_max = Vds_max
        self.Rds_on_10v_max = Rds_on_10v_max
        self.ID_25 = ID_25
        self.Vgs_th_max = Vgs_th_max
        self.Qg_typ = Qg_typ
        self.Qg_max = Qg_max


class DiscoveredPart():
    def __init__(self, mfr, mpn, ds_url, specs: MosfetBasicSpecs, mpn2=None):
        self.mfr = mfr
        self.mpn = mpn
        self.ds_url = ds_url
        self.specs: MosfetBasicSpecs = specs
        self.mpn2 = mpn2

    def get_ds_path(self):
        return os.path.join('datasheets', self.mfr, self.mpn + '.pdf')


async def download_parts_list(mfr, url, fn_ext: Literal['csv', 'xlsx'], **kwargs):
    os.makedirs('parts-lists/' + mfr, exist_ok=True)
    fn = datetime.datetime.now().strftime(f'parts-lists/{mfr}/mosfet-%Y-%m.{fn_ext}')

    if not os.path.isfile(fn):
        await download_with_chromium(
            url,
            filename=fn,
            **kwargs,
        )

    return fn


async def ti_mosfets():
    import openpyxl.styles.colors
    import re
    openpyxl.styles.colors.aRGB_REGEX = re.compile("^([A-Fa-f0-9]{8}|[A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")

    fn = await download_parts_list(
        'ti',
        url='https://www.ti.com/power-management/mosfets/products.html',
        fn_ext='xlsx',
        click='ti-button.ti-selection-tool-action-bar-download')

    df = pd.read_excel(fn, engine_kwargs=dict(data_only=False)).iloc[9:]
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
                Rds_on_10v_max=row['Rds(on) at VGS=10 V (max) (mΩ)'],
                ID_25=row['ID - continuous drain current at TA=25°C (A)'],
                Vgs_th_max=row['VGS (V)'],
                Qg_typ=math.nan,
                Qg_max=math.nan,
            )
        ))
    return parts


async def infineon_mosfets():
    fn = await download_parts_list(
        'infineon',
        'https://www.infineon.com/cms/en/design-support/finder-selection-tools/product-finder/mosfet-finder/',
        fn_ext='xlsx',
        click='a[data-track-name="downloadLink"]',
        close=True,
    )

    df = pd.read_excel(fn)
    df.to_csv(fn.replace('.xlsx', '.csv'), index=False)

    parts = []
    for i, row in df.iterrows():
        vds = row['VDS max [V]']
        if isinstance(vds, str):
            vds = float(vds.split('_')[0])
        parts.append(DiscoveredPart(
            mfr='infineon',
            mpn=row['OPN'],
            mpn2=row['Product'],
            ds_url=row['Data Sheet'],
            specs=MosfetBasicSpecs(
                Vds_max=vds,
                Rds_on_10v_max=row['RDS (on) @10V max [Ω]'],
                ID_25=row['ID  @25°C max [A]'],
                Vgs_th_max=row['VGS(th) max [V]'],
                Qg_typ=row['QG typ @10V [C]'],
                Qg_max=row['QG typ @10V max [C]'],
            )
        ))

    return parts


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
                Rds_on_10v_max=float(cols['RDS(ON)Max(Ω)|VGS|=10V'][i].value or 'nan'),
                ID_25=float(cols['RDS(ON)Max(Ω)|VGS|=10V'][i].value or 'nan'),
                Vgs_th_max=math.nan,
                Qg_typ=float(cols['RDS(ON)Max(Ω)|VGS|=10V'][i].value or 'nan'),
                Qg_max=math.nan,
            )
        ))

    return parts


async def onsemi_mosfets():
    # 200V:
    #

    fn = await download_parts_list(
        'onsemi',
        url='https://www.onsemi.com/products/discrete-power-modules/mosfets/low-medium-voltage-mosfets',
        fn_ext='csv',
        click='button.btn-export',
    )

    df = pd.read_csv(fn)

    return []


    # https://www.onsemi.com/download/data-sheet/pdf/ech8667-d.pdf


if __name__ == '__main__':
    parts = infineon_mosfets(Vds_min=80, Rds_on_max=20e-3)
    print('parts matches', len(parts))
