import datetime
import glob
import math
import os.path
import re
from typing import Literal

import numpy as np
import pandas as pd
import requests

from dslib import mfr_tag, round_to_n_dec
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
        if s.endswith('mOhm') or s.endswith('mΩ') or s.endswith('mO') or s.endswith('mW'):
            s = float(s[:s.index('m')].strip()) * 1e-3
        s = float(s)
    assert not (s < min or s > max), (min, s, max)
    return s


class MosfetBasicSpecs():
    def __init__(self, Vds_max, Rds_on_10v_max, ID_25,
                 Vgs_th_min, Vgs_th_typ, Vgs_th_max,
                 Qg_typ, Qg_max, source):
        self.Vds_max = Vds_max
        self.Rds_on_10v_max = ensure_ohm(Rds_on_10v_max, 1e-6, 500)
        self.ID_25 = ID_25
        self.Vgs_th_min = Vgs_th_min
        self.Vgs_th_max = Vgs_th_max
        self.Qg_typ_nC = ensure_nC(Qg_typ, .2, 2000, True)
        self.Qg_max_nC = ensure_nC(Qg_max, .2, 2000, True)
        self.source = source

        assert not (self.Vgs_th_max > 15)

        f = 1000 * self.Rds_on_10v_max / abs(self.Vds_max)
        assert not (0.002 > f or f > 1000), (f, Vds_max, self.Rds_on_10v_max)

        if Vds_max < 0:
            # p-ch
            assert math.isnan(f * ID_25) or 1 < abs(f * ID_25) < 60, (f * ID_25, f, ID_25)
        else:
            assert math.isnan(f * ID_25) or 0.1 < abs(f * ID_25) < 60, (f * ID_25, f, ID_25)

    @property
    def Qg_max_or_typ_nC(self):
        # assert not self.Qg_max or not isinstance(self.Qg_max, str), self.Qg_max
        if self.Qg_max_nC and not math.isnan(self.Qg_max_nC):
            return self.Qg_max_nC
        return self.Qg_typ_nC

    def update(self, specs: 'MosfetBasicSpecs'):
        assert self.Vds_max == specs.Vds_max

        def mean_chk_std(t, std, fn=np.nanmean):
            if sum(~np.isnan(t)) == 0:
                return math.nan
            assert not (np.nanstd(t) / np.nanmean(t) > std), (t, np.nanstd(t) / np.nanmean(t))
            return fn(t)

        mean_chk_std((self.Rds_on_10v_max, specs.Rds_on_10v_max), 0.45)
        if math.isnan(self.Rds_on_10v_max):
            self.Rds_on_10v_max = specs.Rds_on_10v_max
        self.ID_25 = mean_chk_std((self.ID_25, specs.ID_25), 0.45, fn=np.nanmin)
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

        return list(filter(bool, [
            f('Vds', n, n, self.Vds_max),
            f('Rds_on_10v', n, n, self.Rds_on_10v_max),
            f('ID_25', n, self.ID_25, n),
            f('Vgs_th', n, n, self.Vgs_th_max),
            f('Qg', n, self.Qg_typ_nC, self.Qg_max_nC, unit='nC')
        ]))

    def __str__(self):
        return f'{self.__class__.__name__}({self.Vds_max}V, {round_to_n_dec(self.Rds_on_10v_max, 2)}Ω, {round_to_n_dec(self.ID_25, 2)}A, Qg={round_to_n_dec(self.Qg_typ_nC, 2)}nC)'


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

    # def is_ganfet(self):
    #    from dslib.pdf2txt.parse import is_gan
    #    assert self.mfr
    #    return is_gan(self.mfr)


async def download_parts_list(mfr, url, fn_ext: Literal['csv', 'xlsx'], prefix='mosfet', **kwargs):
    from dslib.fetch import download_with_chromium

    os.makedirs('parts-lists/' + mfr, exist_ok=True)
    fn = datetime.datetime.now().strftime(f'parts-lists/{mfr}/{prefix}-%Y-%m.{fn_ext}')

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
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
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
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
                Vgs_th_max=math.nan,
                Qg_typ=float(cols['Qg(nC)'][i].value or 'nan'),  # nC
                Qg_max=math.nan,
                source='toshiba_products',
            ), package=cols['Toshiba Package Name'][i].value,
        ))

    return parts


async def onsemi_mosfets():
    parts = []

    urls = {
        'small-signal-mosfets': 'https://www.onsemi.com/products/discrete-power-modules/mosfets/small-signal-mosfets',
        'low-medium-voltage-mosfets': 'https://www.onsemi.com/products/discrete-power-modules/mosfets/low-medium-voltage-mosfets',
    }

    for prefix, url in urls.items():
        fn = await download_parts_list(
            'onsemi',
            url=url,
            prefix=prefix,
            fn_ext='csv',
            click='button.btn-export',
        )

        df = pd.read_csv(fn)

        for i, row in df.iterrows():
            if row['Channel Polarity'] == 'Complementary' or row['Configuration'] != 'Single' or 'Q1' in row[
                'RDS(on) Max @ VGS = 10 V  (mΩ)']:
                continue
            mfr = mfr_tag('onsemi')
            mpn = str(row['Product Group'])
            ds_fn = mpn.lower().replace('-', '_')  # .split("-")[0][:12]
            m = re.compile('([a-z]+[0-9]+[a-z]+[0-9]+)').match(ds_fn)
            if m:
                ds_fn = m[0]
            ds_url = f'https://www.onsemi.com/download/data-sheet/pdf/{ds_fn}-d.pdf'
            vgs_th = parse_field_value(row['Vgs(th) Max (V)'].strip('±'))
            rds_on = parse_field_value(row['RDS(on) Max @ VGS = 10 V  (mΩ)']) * 1e-3

            if mpn == 'NTMFS0D7N03CGT1G':
                rds_on = 0.65e-3  # mistake

            if mpn == 'BSS138-G':
                row['Id Max (A)'] = float(row['Id Max (A)']) / 1000

            parts.append(DiscoveredPart(mfr, mpn, ds_url=ds_url, specs=MosfetBasicSpecs(
                Vds_max=parse_field_value(row['V(BR)DSS Min (V)'].strip('±')),
                Rds_on_10v_max=rds_on if rds_on > 0.1e-3 else math.nan,
                Qg_max=math.nan,
                Qg_typ=parse_field_value(row['Qg Typ @ VGS = 10 V (nC)']),
                ID_25=parse_field_value(row.get('ID Max (A)') or row.get('Id Max (A)')),
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
                Vgs_th_max=vgs_th if vgs_th < 10 else math.nan,
                # qgs, qgd, ciss, coss, weight
                source='onsemi.com'
            ), package=row['Package Type']))  # Package Name

    return parts


def onsemi_ds_url(mpn):
    import requests
    resp = requests.post(
        "https://onsemiconductorcorporationproductionvs0bwvg1.org.coveo.com/rest/search/v2?organizationId=onsemiconductorcorporationproductionvs0bwvg1",
        data=f"actionsHistory=%5B%5D&referrer=https%3A%2F%2Fwww.onsemi.com%2Fproducts%2Fdiscrete-power-modules%2Fmosfets%2Flow-medium-voltage-mosfets&analytics=%7B%22clientId%22%3A%22%22%2C%22documentLocation%22%3A%22https%3A%2F%2Fwww.onsemi.com%2Fsearch-results%23q%3D{mpn}%26sort%3Drelevancy%26f%3A%40languagebysource%3D%5BEnglish%5D%22%2C%22documentReferrer%22%3A%22https%3A%2F%2Fwww.onsemi.com%2Fproducts%2Fdiscrete-power-modules%2Fmosfets%2Flow-medium-voltage-mosfets%22%2C%22pageId%22%3A%22%22%7D&isGuestUser=false&q={mpn}&aq=(%40pagetype%3D%3D%22Document%22)%20(%40languagebysource%3D%3D%22English%22)&searchHub=Website-Hub-Page&locale=en&wildcards=true&questionMark=true&firstResult=0&numberOfResults=10&excerptLength=200&enableDidYouMean=true&sortCriteria=relevancy&queryFunctions=%5B%5D&rankingFunctions=%5B%5D&groupBy=%5B%7B%22field%22%3A%22%40pagetype%22%2C%22maximumNumberOfValues%22%3A6%2C%22sortCriteria%22%3A%22occurrences%22%2C%22injectionDepth%22%3A1000%2C%22completeFacetWithStandardValues%22%3Atrue%2C%22allowedValues%22%3A%5B%22Product%22%2C%22Document%22%5D%2C%22queryOverride%22%3A%22{mpn}%22%2C%22advancedQueryOverride%22%3A%22%40languagebysource%3D%3D%5C%22English%5C%22%22%7D%2C%7B%22field%22%3A%22%40filetype%22%2C%22maximumNumberOfValues%22%3A6%2C%22sortCriteria%22%3A%22occurrences%22%2C%22injectionDepth%22%3A1000%2C%22completeFacetWithStandardValues%22%3Atrue%2C%22allowedValues%22%3A%5B%5D%7D%2C%7B%22field%22%3A%22%40year%22%2C%22maximumNumberOfValues%22%3A6%2C%22sortCriteria%22%3A%22occurrences%22%2C%22injectionDepth%22%3A1000%2C%22completeFacetWithStandardValues%22%3Atrue%2C%22allowedValues%22%3A%5B%5D%7D%2C%7B%22field%22%3A%22%40month%22%2C%22maximumNumberOfValues%22%3A6%2C%22sortCriteria%22%3A%22occurrences%22%2C%22injectionDepth%22%3A1000%2C%22completeFacetWithStandardValues%22%3Atrue%2C%22allowedValues%22%3A%5B%5D%7D%2C%7B%22field%22%3A%22%40languagebysource%22%2C%22maximumNumberOfValues%22%3A6%2C%22sortCriteria%22%3A%22occurrences%22%2C%22injectionDepth%22%3A1000%2C%22completeFacetWithStandardValues%22%3Atrue%2C%22allowedValues%22%3A%5B%22English%22%5D%2C%22queryOverride%22%3A%22{mpn}%22%2C%22advancedQueryOverride%22%3A%22%40pagetype%3D%3D%5C%22Document%5C%22%22%7D%5D&facetOptions=%7B%7D&categoryFacets=%5B%5D&retrieveFirstSentences=true&timezone=Europe%2FLisbon&enableQuerySyntax=true&enableDuplicateFiltering=false&enableCollaborativeRating=false&debug=false&allowQueriesWithoutKeywords=false",
        headers={
            "accept": "*/*",
            "accept-language": "de-DE,de;q=0.9,en-DE;q=0.8,en;q=0.7,en-US;q=0.6",
            "authorization": "Bearer xx4615964c-07cc-4d75-a028-26e3a920fecd",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "priority": "u=1, i",
            "sec-ch-ua": "\"Google Chrome\";v=\"129\", \"Not=A?Brand\";v=\"8\", \"Chromium\";v=\"129\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"macOS\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site"
        })

    def filt_res(r):
        u = r['uri'].lower()
        m = mpn.lower()
        subs = {'NTDV': 'NTD', 'NVMFWS': 'NVMFS', 'SVD': 'NVD', 'NVTFWS': 'NVTFS'}
        for k, v in subs.items():
            u = u.replace(k.lower(), v.lower())
            m = m.replace(k.lower(), v.lower())
        return u.endswith('.pdf') and m[:7].replace('_', '-') in u.replace('_', '-')

    res = resp.json()
    m = next(filter(filt_res, res["results"]), None)
    if not m:
        if res.get('queryCorrections'):
            mpn2 = res['queryCorrections'][0]['correctedQuery']
            cor = onsemi_ds_url(mpn2)
            return cor

        if mpn.endswith('TAG') or (len(mpn) >= 16 and mpn[-1] == 'G' and mpn[-3] == 'T'):
            return onsemi_ds_url(mpn[:-3])

        if '-' in mpn:
            return onsemi_ds_url(mpn.split('-')[0])

        return None
    uri: str = m['uri']
    return uri


async def vishay_mosfets():
    parts = []

    urls = [
        'https://www.vishay.com/en/mosfets/v-ds-gteq-31-v-lteq-80-v/',
        'https://www.vishay.com/en/mosfets/v-ds-gteq-81-v-lteq-250-v/',
        # https://www.vishay.com/en/mosfets/v-ds-gteq-251-v-lteq-400-v/
    ]

    for url in urls:
        html = requests.get(url).text
        import json
        js = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', html)[1]

        for r in json.loads(js)['props']['pageProps']['webtableResults']:
            pid = int(r['P1000'])
            mpn = r['P1001']
            ds_url = 'https://www.vishay.com/doc?' + str(pid)
            if mpn in {'SUP10250E'}:
                r['P7013'] /= 10

            if r['P7000'] == 'Dual':
                continue

            parts.append(DiscoveredPart('vishay', mpn, ds_url=ds_url, specs=MosfetBasicSpecs(
                Vds_max=float(r['P7002']),
                Rds_on_10v_max=float(r['P7013'] or math.nan), # @6v P7014
                Qg_max=math.nan,
                Qg_typ=r['P7023'] or math.nan,
                ID_25=r['P7006'] or math.nan,
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
                Vgs_th_max=math.nan,
                source='vishay.com'
            ),package=r['P7009']))

    return parts


async def nexperia_mosfets():
    # https://www.nexperia.com/products/mosfets/power-mosfets
    return


async def st_mosfets():
    df = pd.read_excel('parts-lists/st/stpower-nch-mosfet-30v-200v-to220.xlsx')
    hi = df.iloc[:, 0].str.startswith('Part').idxmax()
    df.columns = df.iloc[hi, :]
    df = df.iloc[(hi + 1):]

    parts = []
    for i, row in df.iterrows():
        mfr = mfr_tag('st')
        mpn = str(row['Part Number'])
        ds_url = f'https://www.st.com/resource/en/datasheet/{mpn.lower()}.pdf'
        # RDS(on) (Ω) (@ 4.5/5V) max
        parts.append(DiscoveredPart(mfr, mpn, ds_url=ds_url, specs=MosfetBasicSpecs(
            Vds_max=parse_field_value(row['VDSS (V)']),
            Rds_on_10v_max=parse_field_value(row['RDS(on) (Ω) (@ VGS = 10V) max']),
            Qg_max=math.nan,
            Qg_typ=parse_field_value(row['Qg (nC) typ']),
            ID_25=parse_field_value(row['Drain Current (Dc) (A) max']),
            Vgs_th_min=math.nan,
            Vgs_th_typ=math.nan,
            Vgs_th_max=math.nan,
            source=mfr
        ), package=row['Package']))  # Package Name

    # url =
    # https://www.st.com/en/power-transistors/stpower-n-channel-mosfets-gt-30-v-to-200-v/products.html
    return parts


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
            source='aosmd.com'
        ), package=row['Package']))  # Package Name

    # df = pd.read_csv(fn)

    return parts


def digikey(csv_glob_path, no_obsolete=False):
    df = pd.concat([pd.read_csv(fn) for fn in sorted(glob.glob(csv_glob_path))], axis=0, ignore_index=True)

    parts = []

    for i, row in df.iterrows():
        if no_obsolete and row['Product Status'] == 'Obsolete':
            continue

        mfr = mfr_tag(row.Mfr)
        mpn = str(row['Mfr Part #'])
        ds_url = row.Datasheet
        parts.append(DiscoveredPart(mfr, mpn, ds_url=ds_url, specs=MosfetBasicSpecs(
            Vds_max=float(row['Drain to Source Voltage (Vdss)'].strip(' V')),
            Rds_on_10v_max=(row['Rds On (Max) @ Id, Vgs'].split('@')[0].strip()),
            Qg_max=(row['Gate Charge (Qg) (Max) @ Vgs'].split('@')[0].strip()),
            Qg_typ=math.nan,
            ID_25=float(
                row['Current - Continuous Drain (Id) @ 25°C'].strip(' ,').split(',')[-1].strip().split(' ')[0].strip(
                    ' A')),
            Vgs_th_min=math.nan,
            Vgs_th_typ=math.nan,
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

    # u =


async def taiwansemi_nfets():
    # app._component.methods.exportProductTable()
    fn = await download_parts_list(
        'ts',
        url='https://www.taiwansemi.com/en/product-filter/?category=n-channel-mosfets-22',
        fn_ext='xlsx',
        click='div.table-box div.right-box>button.el-button.el-button--primary',
    )

    df = pd.read_excel(fn)
    df.to_csv(fn.replace('.xlsx', '.csv'), index=False)

    parts = []
    for i, row in df.iterrows():
        mfr = mfr_tag('taiwansemi')
        mpn = str(row['Part Number'])
        ds_url = row.Datasheet
        parts.append(DiscoveredPart(mfr, mpn, ds_url=ds_url, specs=MosfetBasicSpecs(
            Vds_max=float(row['VDS (V)']),
            Rds_on_10v_max=float(row['RDS(ON) @ 10V Max. (mΩ)']) * 1e-3,
            Qg_max=math.nan,
            Qg_typ=float(row['Qg (nC) @ 10V']),
            ID_25=float(row['ID Max. (A)']),
            Vgs_th_min=row['VGS(th) Min. (V)'],
            Vgs_th_typ=row['VGS(th) Typ. (V)'],
            Vgs_th_max=row['VGS(th) Max. (V)'],
            # qgs, qgd, ciss, coss, weight
            source='taiwansemi.com'
        ), package=row['Package']))

    # df = pd.read_csv(fn)

    return parts


def benchmark_mpns():
    return {
        ('infineon', 'IPP65R420CFDXKSA2'),
        ('infineon', 'IMT40R036M2HXTMA1')
    }


if __name__ == '__main__':
    async def _main():
        await vishay_mosfets()

        u = onsemi_ds_url("NTDV20N06T4G")
        # parts = infineon_mosfets(Vds_min=80, Rds_on_max=20e-3)
        parts = await aosmd_medium_voltage_mosfets()
        print('parts', len(parts))

        for p in parts:
            if p.specs.Vds_max > 70 and p.specs.Vds_max <= 200 and p.specs.ID_25 > 30:
                print(p)


    import asyncio

    asyncio.run(_main())
