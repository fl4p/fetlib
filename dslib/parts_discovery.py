import asyncio
import datetime
import math
import os.path
import time
from typing import Literal

import pandas as pd

from dslib.fetch import download_with_chromium


class MosfetBasicSpecs():
    def __init__(self, Vds_max, Rds_on_10v_max, ID_25, Vgs_th_max, Qg_typ, Qg_max):
        self.Vds_max = Vds_max
        self.Rds_on_10v_max = Rds_on_10v_max


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


async def ti_mosfets_async():
    parts = []
    vds_min = -100
    vds_max = 30

    import openpyxl.styles.colors
    import re
    openpyxl.styles.colors.aRGB_REGEX = re.compile("^([A-Fa-f0-9]{8}|[A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")

    link_reg = re.compile(r'=HYPERLINK\("(?P<url>.+)", "(?P<text>.+)"\)')

    while vds_max < 200:
        from dslib.fetch import download_with_chromium
        os.makedirs('parts-lists/ti', exist_ok=True)
        fn = datetime.datetime.now().strftime(f'parts-lists/ti/mosfet_{vds_min}-{vds_max}V_%Y-%m.xlsx')

        if not os.path.exists(fn):
            await download_with_chromium(
                f"https://www.ti.com/power-management/mosfets/products.html?t={time.time()}#267={vds_min}%3B{vds_max}&",
                filename=fn,
                click='ti-button.ti-selection-tool-action-bar-download',
                close='page',
            )

        df = pd.read_excel(fn, engine_kwargs=dict(data_only=False)).iloc[9:]
        df.columns = df.iloc[0]
        df = df.iloc[1:]
        if df['VDS (V)'].min() < vds_min and len(df) >= 200:
            break
        assert len(df) < 200
        assert df['VDS (V)'].min() >= vds_min
        assert df['VDS (V)'].max() <= vds_max

        df.to_csv(fn.replace('.xlsx', '.csv'), index=False)

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

        vds_min = vds_max + 1
        vds_max = vds_min + 40

    return parts


def ti_mosfets():
    return asyncio.run(ti_mosfets_async())


def infineon_mosfets(Vds_min, Rds_on_max):
    import pandas as pd

    os.makedirs('parts-lists/infineon', exist_ok=True)
    fn = datetime.datetime.now().strftime('parts-lists/infineon/mosfet-%Y-%m.xlsx')

    if not os.path.isfile(fn):
        from dslib.fetch import download_with_chromium
        f = download_with_chromium(
            'https://www.infineon.com/cms/en/design-support/finder-selection-tools/product-finder/mosfet-finder/',
            filename=fn,
            click='a[data-track-name="downloadLink"]',
            close=True,
        )
        asyncio.run(f)

        df = pd.read_excel(fn)
        df.to_csv(fn.replace('.xlsx', '.csv'), index=False)
    else:
        df = pd.read_excel(fn)

    parts = []
    for i, row in df.iterrows():
        vds = row['VDS max [V]']
        if isinstance(vds, str):
            vds = float(vds.split('_')[0])
        if Vds_min and abs(vds) < Vds_min:
            continue
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
    #
    # document.querySelector('button.funcBtn_item.funcBtn_item--last.funcBtn_item-download').click()
    # document.querySelector('ul.funcBtn_item-download_accordion.funcBtn_item-download_accordion-file li:last-child button').click()

    os.makedirs('parts-lists/infineon', exist_ok=True)
    fn = datetime.datetime.now().strftime('parts-lists/toshiba/mosfet-%Y-%m.xlsx')

    download_with_chromium(
        "https://toshiba.semicon-storage.com/parametric/product?code=param_304",
        fn,
        click=[
            'button.funcBtn_item.funcBtn_item--last.funcBtn_item-download',
            'ul.funcBtn_item-download_accordion.funcBtn_item-download_accordion-file li:last-child button',
        ]
    )

    return


def onsemi_mosfets():
    # 200V:
    #

    os.makedirs('parts-lists/onsemi', exist_ok=True)
    fn = datetime.datetime.now().strftime('parts-lists/onsemi/mosfet-%Y-%m.xlsx')

    if not os.path.isfile(fn):
        from dslib.fetch import download_with_chromium
        f = download_with_chromium(
            'https://www.onsemi.com/products/discrete-power-modules/mosfets/low-medium-voltage-mosfets',
            filename=fn,
            click='button.btn-export',
            close=True,
        )

    # https://www.onsemi.com/download/data-sheet/pdf/ech8667-d.pdf

    # document.querySelector('button.btn-export').click()


if __name__ == '__main__':
    parts = infineon_mosfets(Vds_min=80, Rds_on_max=20e-3)
    print('parts matches', len(parts))
