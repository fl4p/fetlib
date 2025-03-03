import math
import re

from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, fetch_json_cached
from dslib.field import parse_field_value
from dslib.pdf.pdf2txt import whitespaces_to_space


def huayi_mosfets():
    from bs4 import BeautifulSoup
    parts = []
    page = 1
    while True:
        u = (f"http://en.hymexa.com/index.php?s=api&c=api&m=template&name=search_data.html&module=products"
             f"&catid=40&searchid=6932af211e291898af63e5d04ae75735&sototal=9999&order=&params=&format=json&page={page}")
        resp = fetch_json_cached(u)
        assert resp['code'] == 1
        ht = resp['msg']
        if not ht:
            break
        for row in BeautifulSoup(ht, 'html.parser').find_all('div', attrs={'class': 'tr_box_wai'}):
            mpn = row.find_next('div', attrs={'class': 'vg_title'}).text
            # vg_rdson_max_10vm
            # vg_ciss_typpf
            # vg_package
            vds = float(row.find_next('div', attrs={'class': 'vg_vds_min_v'}).text)
            rds = parse_field_value(row.find_next('div', attrs={'class': 'vg_rdson_max_10vm'}).text) * 1e-3
            qg = float(row.find_next('div', attrs={'class': 'vg_qg_typnc'}).text)
            if rds < 20e-3 and vds > 200:
                rds *= 1e3
            if qg < 1 and rds < 0.01:
                qg = math.nan

            m = re.search(r"<a href=\"/generic/web/viewer\.html\?file=\.\./\.\./(.+?\.pdf)", str(row))
            if not m:
                print(mpn, 'no DS url', whitespaces_to_space(str(row)))
            ds_url = ('http://en.hymexa.com/' + m[1]) if m else None
            parts.append(DiscoveredPart('huayi', mpn, ds_url=ds_url, specs=MosfetBasicSpecs(
                Vds_max=vds,
                Rds_on_10v_max=rds,
                Qg_max=math.nan,
                Qg_typ=qg,
                ID_25=float(row.find_next('div', attrs={'class': 'vg_idtc'}).text),
                Vgs_th_min=math.nan,
                Vgs_th_typ=math.nan,
                Vgs_th_max=math.nan,
                source=['en.hymexa.com'],
            ), package=row.find_next('div', attrs={'class': 'vg_package'}).text.strip()))
        page += 1

    return parts
