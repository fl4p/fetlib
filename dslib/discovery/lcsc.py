import asyncio
import glob
import json
import math
import os
from typing import Union

# from html.parser import HTMLParser
from pyquery import PyQuery

from dslib import mfr_tag
from dslib.cache import disk_cache
from dslib.discovery import DiscoveredPart, MosfetBasicSpecs, parse_mosfet_polarity
from dslib.fetch import fetch_datasheet, get_browser_page

brands = {
    "Littelfuse": 110,
    "Littelfuse/IXYS": 817,
    "XNRUSEMI": 17409,
    "CRMICRO": 12027,
    "NCE": 1104,
    "Siliup": 15945,
    # "AGMSEMI": 15179, # weird
    # "UMW": 11853, # fake MPNs?
    # "HXY": 13437, # untrustworthy datasheets (same curves for most parts)
    "GOFORD": 11545,  # currently parse problems. gone?
    "Suzhou Good-Ark Elec": 979,
    "MCC": 889,
    # "huayi": 11756,
}


async def fetch(url, body):
    # LCSC's API sits behind an Akamai WAF that blocks aiohttp's request (403 Access Denied,
    # served from errors.edgesuite.net) even with fully browser-like headers - it's a
    # TLS/connection fingerprint check, not a header check. Routing the request through the
    # real browser's own fetch() gives it a genuine Chrome network stack, which passes.
    page = await get_browser_page()
    if 'lcsc.com' not in (page.url or ''):
        await page.goto('https://www.lcsc.com/', wait_until='commit')

    result = await page.evaluate('''
        async ({url, body}) => {
            const resp = await fetch(url, {
                method: 'POST',
                headers: {'content-type': 'application/json;charset=UTF-8'},
                body: JSON.stringify(body),
                credentials: 'include',
            });
            return {status: resp.status, text: await resp.text()};
        }
    ''', {'url': url, 'body': body})

    if result['status'] != 200:
        raise Exception(f'lcsc fetch {url} failed: {result["status"]} {result["text"][:300]}')

    return json.loads(result['text'])


async def fetch_list_page(brand_id: int, page: int):
    assert page >= 1

    return await fetch("https://wmsc.lcsc.com/ftps/wm/product/query/list", {
        "keyword": "",
        "catalogIdList": [1436],
        "brandIdList": [str(brand_id)],
        "encapValueList": [],
        "isStock": False,
        "isOtherSuppliers": False,
        "isAsianBrand": False,
        "isDeals": False,
        "isEnvironment": False,
        "paramNameValueMap": {},
        "currentPage": page,
        "pageSize": 100,
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


@disk_cache(ttl='7d', hash_func_code=True)
async def fetch_brand_rows_raw(brand_id: int) -> dict:
    """The UNPARSED catalog rows for one brand, with the ORIGIN fetch timestamp.

    Split from discover_mosfets_brand so the raw rows (incl. the price/stock fields the
    discovery parser ignores) survive caching -- the price harvester in
    dslib/prices/lcsc.py re-parses the same envelope without another browser fetch, and
    its records inherit `fetched_at` from here (never a cache-hit or DB-write time)."""
    import datetime
    rows = await fetch_list_all(brand_id)
    if len(rows) == 0:
        raise Exception('no data for brand ' + str(brand_id))
    return {'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'rows': rows}


async def discover_mosfets_brand(brand_id: Union[int, str]):
    raw = await fetch_brand_rows_raw(brands[brand_id] if isinstance(brand_id, str) else brand_id)
    data = raw['rows']

    print('lcsc brand', brand_id, 'fetched %d rows in total' % len(data))

    parts = []
    for r in data:
        if not r.get('productModel'):
            continue

        # spn = r['productCode']
        product_name = r.get('productNameEn') or ''
        try:
            polarity = parse_mosfet_polarity(product_name)
        except ValueError:
            polarity = None
        p_channel = polarity == 'P'
        pm = {p['paramNameEn']: p['paramValueEnForSearch'] for p in r["paramVOList"] or []}
        vds_max = pm.get("Drain to Source Voltage") or math.nan
        rds_max = pm.get("RDS(on)") or math.nan
        id = pm.get("Current - Continuous Drain(Id)") or math.nan
        if vds_max >= 1000 and rds_max < 0.6 and id < 2:
            rds_max *= 1000

        if vds_max > 0 and p_channel:
            vds_max *= -1

        try:
            specs = MosfetBasicSpecs(
                polarity=polarity,
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
                polarity=polarity,
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
