import datetime
import glob
import math
import os.path
from typing import Literal

import numpy as np
import pandas as pd

from dslib import mfr_tag

from dslib.field import parse_field_value, Field


def ensure_nC(s, min, max, abs):
    if isinstance(s, str):
        if s.endswith('nC'):
            s = float(s[:-2].strip()) * 1
        elif s.endswith('uC') or s.endswith('μC'):
            s = float(s[:-2].strip()) * 1e3
        elif s.isnumeric():
            s = float(s)
        else:
            raise ValueError(s)
        s = float(s)
    if abs and s < 0:
        s *= -1
    assert not (s < min or s > max), (min, s, max)
    return s


def ensure_ohm(s, min, max):
    if isinstance(s, str):
        if s.endswith('mOhm') or s.endswith('mΩ')  or s.endswith('mO'):
            s = float(s[:s.index('m')].strip()) * 1e-3
        s = float(s)
    assert not (s < min or s > max), (min, s, max)
    return s


class MosfetBasicSpecs():
    def __init__(self, Vds_max, Rds_on_10v_max, ID_25, Vgs_th_max, Qg_typ, Qg_max, source):
        self.Vds_max = Vds_max
        self.Rds_on_10v_max = ensure_ohm(Rds_on_10v_max, 1e-6, 500)
        self.ID_25 = ID_25
        self.Vgs_th_max = Vgs_th_max
        self.Qg_typ_nC = ensure_nC(Qg_typ, .2, 2000, True)
        self.Qg_max_nC = ensure_nC(Qg_max, .2, 2000, True)
        self.source = source

        assert not (self.Vgs_th_max > 15)

        f = 1000 * self.Rds_on_10v_max / abs(self.Vds_max)
        assert not (0.002 > f or f > 1000), (f, Vds_max, self.Rds_on_10v_max)

        if Vds_max < 0:
            # p-ch
            assert math.isnan(f * ID_25) or 1 < abs(f * ID_25) < 60, (f*ID_25, f, ID_25 )
        else:
            assert math.isnan(f * ID_25) or 0.1 < abs(f * ID_25) < 60, (f * ID_25, f, ID_25)

    @property
    def Qg_max_or_typ_nC(self):
        # assert not self.Qg_max or not isinstance(self.Qg_max, str), self.Qg_max
        if self.Qg_max_nC and not math.isnan(self.Qg_max_nC):
            return self.Qg_max_nC
        return self.Qg_typ_nC

    def update(self, specs:'MosfetBasicSpecs'):
        assert self.Vds_max == specs.Vds_max
        def mean_chk_std(t, std, fn=np.nanmean):
            if sum(~np.isnan(t)) == 0:
                return math.nan
            assert not (np.nanstd(t)/np.nanmean(t)>std), (t, np.nanstd(t)/np.nanmean(t))
            return fn(t)

        mean_chk_std((self.Rds_on_10v_max, specs.Rds_on_10v_max), 0.2)
        if math.isnan(self.Rds_on_10v_max):
            self.Rds_on_10v_max = specs.Rds_on_10v_max
        self.ID_25 = mean_chk_std((self.ID_25, specs.ID_25), 0.4, fn=np.nanmin)
        self.Vgs_th_max = mean_chk_std((self.Vgs_th_max, specs.Vgs_th_max), 0.3, fn=np.nanmax)
        self.Qg_typ_nC = mean_chk_std((self.Qg_typ_nC, specs.Qg_typ_nC), 0.01, fn=np.nanmean)
        self.Qg_max_nC = mean_chk_std((self.Qg_max_nC, specs.Qg_max_nC), 0.2, fn=np.nanmax)

    def fields(self):
        n = math.nan
        def f(*args, **kwargs):
            try:
                return Field(*args, **kwargs, source=self.source)
            except:
                return None

        return filter(bool, [
            f('Vds', n, n, self.Vds_max ),
            f('Rds_on_10v', n, n, self.Rds_on_10v_max ),
            f('ID_25', n, self.ID_25, n ),
            f('Vgs_th', n, n,self.Vgs_th_max),
            f('Qg', n, self.Qg_typ_nC, self.Qg_max_nC, unit='nC')
        ])


def is_nan(v):
    return isinstance(v, float) and math.isnan(v)

class DiscoveredPart():
    def __init__(self, mfr, mpn, ds_url, package, specs: MosfetBasicSpecs, mpn2=None):
        self.mfr = mfr
        self.mpn = mpn
        self.ds_url = ds_url
        self.specs: MosfetBasicSpecs = specs
        self.mpn2 = mpn2
        self.package = package if not is_nan(package) else None  # aka case, housing

    def get_ds_path(self):
        return os.path.join('datasheets', self.mfr, self.mpn + '.pdf')

    def __repr__(self):
        return f'DiscoveredPart({self.mfr}, {self.mpn}, ({self.specs}))'

    #def is_ganfet(self):
    #    from dslib.pdf2txt.parse import is_gan
    #    assert self.mfr
    #    return is_gan(self.mfr)


async def download_parts_list(mfr, url, fn_ext: Literal['csv', 'xlsx'], **kwargs):
    from dslib.fetch import download_with_chromium

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
                Vgs_th_max=math.nan,
                Qg_typ=math.nan,
                Qg_max=math.nan,
                source='ti_products',
            ), package=row['Package type']
        ))
    return parts


async def infineon_mosfets():
    fn = await download_parts_list(
        'infineon',
        'https://www.infineon.com/cms/en/design-support/finder-selection-tools/product-finder/mosfet-finder/',
        fn_ext='xlsx',
        click='a[data-track-name="downloadLink"]',
        #close=True,
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
                Vgs_th_max=parse_field(row['VGS(th) max [V]'], float),
                Qg_typ=parse_field(row['QG typ @10V [C]'], float),
                Qg_max=parse_field(row['QG typ @10V max [C]'], float),
                source='infineon_products',
            ), package=parse_field(row['Standard Package name'], str),
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
                Rds_on_10v_max=float(cols['RDS(ON)Max(\u03a9)|VGS|=10V'][i].value or 'nan'),  # ohm
                ID_25=float(cols['ID(A)'][i].value or 'nan'),
                Vgs_th_max=math.nan,
                Qg_typ=float(cols['Qg(nC)'][i].value or 'nan'),  # nC
                Qg_max=math.nan,
                source='toshiba_products',
            ), package=cols['Toshiba Package Name'][i].value,
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

    #     # https://www.onsemi.com/download/data-sheet/pdf/ech8667-d.pdf

    return []


def digikey(csv_glob_path):
    df = pd.concat([pd.read_csv(fn) for fn in sorted(glob.glob(csv_glob_path))], axis=0, ignore_index=True)

    parts = []

    for i, row in df.iterrows():
        mfr = mfr_tag(row.Mfr)
        mpn = str(row['Mfr Part #'])
        ds_url = row.Datasheet
        parts.append(DiscoveredPart(mfr, mpn, ds_url=ds_url, specs=MosfetBasicSpecs(
            Vds_max=float(row['Drain to Source Voltage (Vdss)'].strip(' V')),
            Rds_on_10v_max=(row['Rds On (Max) @ Id, Vgs'].split('@')[0].strip()),
            Qg_max=(row['Gate Charge (Qg) (Max) @ Vgs'].split('@')[0].strip()),
            Qg_typ=math.nan,
            ID_25=float(row['Current - Continuous Drain (Id) @ 25°C'].strip(' ,').split(',')[-1].strip().split(' ')[0].strip(' A')),
            Vgs_th_max=parse_field_value(row['Vgs(th) (Max) @ Id'].split('@')[0].strip(' V')),
            source='digikey'
        ), package=row['Package / Case']))

    return parts


async def qorvo_sic_fets():
    # TODO https://www.qorvo.com/products/discrete-transistors/sic-jfets
    fn = await download_parts_list(
        'qorvo',
        url="https://www.qorvo.com/products/discrete-transistors/sic-fets",
        fn_ext='xlsx',
        click='a.pst-export',
    )

    raise NotImplementedError()

    #u =


def benchmark_mpns():
    return {
        ('infineon', 'IPP65R420CFDXKSA2'),
        ('infineon', 'IMT40R036M2HXTMA1')
    }


if __name__ == '__main__':
    parts = infineon_mosfets(Vds_min=80, Rds_on_max=20e-3)
    print('parts matches', len(parts))
