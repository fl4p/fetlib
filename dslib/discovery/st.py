import json
import math
import os

from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, parts_list_file_name
from dslib.fetch import get_text_with_chromium


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
