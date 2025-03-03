import json
import math
import warnings

import pandas as pd

from dslib import mfr_tag
from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, parts_list_file_name, download_parts_list
from dslib.fetch import get_text_with_chromium
from dslib.field import parse_field_value


async def st_mosfets():
    """
    chromium has http2 issues

    query ` window.productHierarchy = "SC1165-CL824-FM100".split('-');`
    then use window.productHierarchy[0]
    for json product feed:
    https://www.st.com/bin/st/selectors/cxst/en.cxst-rs-grid.html/SC1165.all.json
    and
    https://www.st.com/bin/st/selectors/cxst/en.cxst-ps-grid.html/SC1165.json


    https://www.st.com/en/power-transistors/stpower-n-channel-mosfets-20-v-to-30-v/products.html
    ['SC1164', 'CL824', 'FM100']


    200-700v:
     ['SC1167', 'CL824', 'FM100']

    :return:
    """

    ids = [
        'SC1164',  # mosfets-20-v-to-30-v/
        'SC1165',  # 30-200v
        'SC1167',  # 200-700v:
    ]

    import re
    tag_re = re.compile(r'(<!--.*?-->|<[^>]*>)')

    parts = []
    for id in ids:
        url = f'https://www.st.com/bin/st/selectors/cxst/en.cxst-ps-grid.html/{id}.json'
        fn = parts_list_file_name('st', 'json', 'mosfet-' + id)
        if os.path.exists(fn):
            with open(fn, 'r') as f:
                r = json.load(f)
        else:
            s = await get_text_with_chromium(url)
            with open(fn, 'w') as f:
                f.write(s)
            r = json.loads(s)
        cols = {c['id']: c for c in r['columns']}
        for r in r['rows']:
            v = {tag_re.sub('', cols[cell['columnId']]['name']): cell['value'] for cell in r['cells']}
            mpn = v['Part Number']
            ds_url = f'https://www.st.com/resource/en/datasheet/{mpn.lower()}.pdf'

            parts.append(DiscoveredPart('st',
                                        mpn=mpn,  # r['cpnNames'][0],
                                        ds_url=ds_url,
                                        package=v['Package'],
                                        specs=MosfetBasicSpecs(
                                            Vds_max=float(v['VDSS']),
                                            Rds_on_10v_max=float(v.get('RDS(on)', math.nan)),
                                            ID_25=float(v.get('Drain Current (Dc)', math.nan)),
                                            Vgs_th_min=math.nan, Vgs_th_typ=math.nan, Vgs_th_max=math.nan,
                                            Qg_typ=float(v.get('Qg', math.nan)),
                                            Qg_max=math.nan, source=['st.com']))
                         )
    return parts

    # TODO
    warnings.warn('ST: using static xlsx file')
    df = pd.read_excel('parts-lists/st/stpower-nch-mosfet-30v-200v-to220.xlsx')
    parts = []

    urls = [
        "https://www.st.com/en/power-transistors/stpower-n-channel-mosfets-gt-30-v-to-200-v/products.html",

    ]
    # for url in urls:
    if 0:
        fn = await download_parts_list(
            'st',
            url=url,
            fn_ext='xlsx',
            click="a:has(> svg.st-svg--export)",
        )

        df = pd.read_excel(fn)

    if 1:
        hi = df.iloc[:, 0].str.startswith('Part').idxmax()
        df.columns = df.iloc[hi, :]
        df = df.iloc[(hi + 1):]

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

    return parts
