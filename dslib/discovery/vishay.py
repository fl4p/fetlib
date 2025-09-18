import math
import re

import requests

from dslib.cache import mem_cache, disk_cache
from dslib.discovery import MosfetBasicSpecs, DiscoveredPart


@disk_cache(ttl='30d')
def vishay_mosfets():
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
                Rds_on_10v_max=float(r['P7013'] or math.nan),  # @6v P7014
                Qg_max=math.nan,
                Qg_typ=r['P7023'] or math.nan,
                ID_25=r['P7006'] or math.nan,
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
                Vgs_th_max=math.nan,
                source=['vishay.com']
            ), package=r['P7009']))

    return parts
