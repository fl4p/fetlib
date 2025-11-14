import asyncio
import glob
import json
import math
import os
from typing import Union

import aiohttp
# from html.parser import HTMLParser
from pyquery import PyQuery

from dslib import mfr_tag
from dslib.cache import disk_cache
from dslib.discovery import DiscoveredPart, MosfetBasicSpecs
from dslib.fetch import fetch_datasheet

_session: aiohttp.ClientSession = None

brands = {
    "Littelfuse": 110,
    "Littelfuse/IXYS": 817,
    "XNRUSEMI": 17409,
    "CRMICRO": 12027,
    "NCE": 1104,
    "Siliup": 15945,
    # "AGMSEMI": 15179, # weird
    # "UMW": 11853, # fake MPNs?
    "HXY": 13437,
    "GOFORD": 11545,  # currently parse problems. gone?
    "Suzhou Good-Ark Elec": 979,
    "MCC": 889,
    "huayi": 11756,
}


async def _get_session():
    global _session
    if _session is None:
        _session = aiohttp.ClientSession()
    return _session


async def fetch(url, options):
    options['headers'] = options.get('headers', {})
    if options.get('referrer'):
        options['headers']['referer'] = options['referrer']
    async with getattr(await _get_session(), options['method'].lower())(
            url, headers=options['headers'], json=json.loads(options['body'])) as response:  # Simulating a delay
        data = await response.json()
        return data


async def fetch_list_page(brand_id: int, page: int):
    assert page >= 1

    return await fetch("https://wmsc.lcsc.com/ftps/wm/product/query/list", {
        "headers": {
            "accept": "application/json, text/plain, */*",
            "accept-language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7,fr;q=0.6",
            "content-type": "application/json;charset=UTF-8",
            "priority": "u=1, i",
            "sec-ch-ua": "\"Not;A=Brand\";v=\"99\", \"Google Chrome\";v=\"139\", \"Chromium\";v=\"139\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"macOS\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        },
        "referrer": "https://www.lcsc.com/",
        "body": "{\"keyword\":\"\",\"catalogIdList\":[874],\"brandIdList\":[\"" + str(
            brand_id) + "\"],\"encapValueList\":[],\"isStock\":false,\"isOtherSuppliers\":false,\"isAsianBrand\":false,\"isDeals\":false,\"isEnvironment\":false,\"paramNameValueMap\":{},\"currentPage\":" + str(
            page) + ",\"pageSize\":100}",
        "method": "POST",
        "mode": "cors",
        "credentials": "include"
    })


async def fetch_list_all(brand_id: int):
    page = 1
    dataList = []
    while True:
        res = await fetch_list_page(brand_id, page)
        assert res['code'] == 200
        assert res['result']['currPage'] == page
        dataList += res['result']['dataList']
        if page < res['result']['totalPage']:
            page += 1
        else:
            assert len(dataList) == res['result']['totalRow']
            return dataList


def read_lcsc_search_results(html_glob_path):
    files = sorted(glob.glob(html_glob_path))

    for filename in files:
        with open(filename, 'r') as f:
            pq = PyQuery(f.read())
        for tr in pq('tr'):
            trq = pq(tr)

            links = list(pq(a) for a in
                         trq.find('a.hoverUnderline[target="_blank"][href^="https://www.lcsc.com/product-detail"]'))
            if not links:
                print('skip row')
                continue
            mpn = links[0].text()
            lcsc_num = links[1].text()

            mnf_links = list(pq(a) for a in
                             trq.find('a.hoverUnderline[target="_blank"][href^="https://www.lcsc.com/brand-detail"]'))
            assert len(mnf_links) == 1
            mfr = mfr_tag(mnf_links[0].text())
            ds_url = trq.find('a.datasheet').attr('href')

            if ds_url == 'https://www.lcsc.com/':
                ds_url = None

            print(mfr, mpn, lcsc_num, ds_url)

            if ds_url:
                ds_url = ds_url.replace('https://www.lcsc.com/datasheet/lcsc_datasheet_',
                                        'https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/')

                datasheet_path = os.path.join('../../datasheets', mfr, mpn + '.pdf')
                fetch_datasheet(ds_url, datasheet_path, mfr=mfr, mpn=mpn)


@disk_cache(ttl='7d')
async def discover_mosfets_brand(brand_id: Union[int, str]):
    data = await fetch_list_all(brands[brand_id] if isinstance(brand_id, str) else brand_id)
    if len(data) == 0:
        raise Exception('no data for brand ' + str(brand_id))

    print('lcsc brand', brand_id, 'fetched %d rows in total' % len(data))

    parts = []
    for r in data:
        # spn = r['productCode']
        pm = {p['paramNameEn']: p['paramValueEnForSearch'] for p in r["paramVOList"] or []}
        vds_max = pm.get("Drain to Source Voltage") or math.nan
        rds_max = pm.get("RDS(on)") or math.nan
        id = pm.get("Current - Continuous Drain(Id)") or math.nan
        if vds_max >= 1000 and rds_max < 0.6 and id < 2:
            rds_max *= 1000

        try:
            specs = MosfetBasicSpecs(
                Vds_max=vds_max,
                Rds_on_10v_max=rds_max,
                ID_25=id,
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
                Vgs_th_max=math.nan,
                Qg_typ=math.nan,
                Qg_max=math.nan,
                source=['lcsc'],
            )
        except Exception as e:
            print('%s %s failed to create mosfetBasicSpecs: %s' % (mfr_tag(r['brandNameEn']), r['productModel'], e))
            specs = MosfetBasicSpecs(
                Vds_max=vds_max,
                Rds_on_10v_max=math.nan,
                ID_25=id,
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
                Vgs_th_max=math.nan,
                Qg_typ=math.nan,
                Qg_max=math.nan,
                source=['lcsc'],
            )

        parts.append(DiscoveredPart(mfr_tag(r['brandNameEn']), r['productModel'],
                                    ds_url=r['pdfUrl'],
                                    package=r['encapStandard'], specs=specs))

    return parts


# @disk_cache(ttl='7d', salt='v06')
def discover_china_mosfets_cached():
    if asyncio.get_event_loop():
        # return asyncio.run(discover_china_mosfets())
        return asyncio.run(discover_china_mosfets())
        # return asyncio.get_event_loop().run_until_complete(discover_china_mosfets())
    else:
        return asyncio.run(discover_china_mosfets())


# @disk_cache(ttl='7d')
async def discover_china_mosfets():
    parts = []
    for brand, brand_id in brands.items():
        parts += await discover_mosfets_brand(brand)
    return parts


if __name__ == '__main__':
    # read_lcsc_search_results('../search-results/lcsc/80v 26a 10mohm p*.html')

    asyncio.run(fetch_list_all(17409))
