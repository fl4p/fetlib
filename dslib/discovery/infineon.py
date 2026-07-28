import math
import re

import requests

from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, parse_mosfet_polarity

PRODUCT_TABLE_URL = 'https://www.infineon.com/dataApi/en/product-table/mosfet-finder0.product-table.en.json'


def _clean_param_name(name):
    return re.sub(r'<[^>]+>', '', name or '').strip()


def _find_param(params_by_name, name, remark_contains=None):
    for p in params_by_name.get(name, []):
        if remark_contains is None or (p.get('valueRemark') and remark_contains in p['valueRemark']):
            return p
    return None


def _num(p, *keys):
    if not p:
        return math.nan
    for k in keys:
        if p.get(k) is not None:
            return p[k]
    return math.nan


async def infineon_mosfets():
    # infineon's MOSFET Finder UI (a JS-heavy parametric search tool with an in-page cookie
    # consent modal) lazy-loads its product table from this JSON endpoint. Fetching it directly
    # avoids browser automation entirely and includes fields (e.g. ID) the xlsx export sometimes
    # omits depending on which columns are currently configured in the finder tool's UI state.
    resp = requests.get(PRODUCT_TABLE_URL, params={'collectionName': ''}, timeout=120,
                         headers={'User-Agent': 'Mozilla/5.0'})
    resp.raise_for_status()
    items = resp.json()

    parts = []
    for item in items:
        if not item.get('opns'):
            continue

        ds_url = (item.get('dataSheet') or {}).get('assetDmPath')

        technology = ''
        params_by_name = {}
        for p in item.get('parameterValues', []):
            name = _clean_param_name(p.get('parameterName'))
            params_by_name.setdefault(name, []).append(p)
            if name == 'Technology' and p.get('valueChar'):
                technology = p['valueChar']

        vds = _find_param(params_by_name, 'VDS')
        rds_10v = _find_param(params_by_name, 'RDS (on)', '10V') or _find_param(params_by_name, 'RDS (on)')
        qg_10v = _find_param(params_by_name, 'QG', '10V') or _find_param(params_by_name, 'QG')
        id_25 = _find_param(params_by_name, 'ID')
        vgs_th = _find_param(params_by_name, 'VGS(th)')
        polarity = _find_param(params_by_name, 'Polarity')

        for opn in item['opns']:
            if not opn.get('opnName'):
                continue
            try:
                parts.append(DiscoveredPart(
                    mfr='infineon',
                    mpn=opn['opnName'],
                    mpn2=item.get('ispnName'),
                    ds_url=ds_url,
                    specs=MosfetBasicSpecs(
                        polarity=parse_mosfet_polarity(
                            (polarity or {}).get('valueChar')),
                        substrate='SiC' if 'CoolSiC' in technology else 'Si',  # infineon no GaN
                        Vds_max=_num(vds, 'valueMax', 'valueNumber'),
                        Rds_on_10v_max=_num(rds_10v, 'valueMax', 'valueNumber') * 1e-3,
                        Qg_typ=_num(qg_10v, 'valueNumber', 'valueMax'),
                        Qg_max=math.nan,
                        ID_25=_num(id_25, 'valueMax', 'valueNumber'),
                        Vgs_th_min=_num(vgs_th, 'valueMin'),
                        Vgs_th_typ=_num(vgs_th, 'valueNumber'),
                        Vgs_th_max=_num(vgs_th, 'valueMax'),
                        source=['infineon_products'],
                    ),
                    package=((opn.get('packageDetails') or {}).get('packageNameMarketing')
                             or opn.get('packageNameMarketingOpn')
                             or opn.get('packageNameOpn')
                             or (opn.get('packageDetails') or {}).get('packageName')),
                ))
            except Exception as e:
                # e.g. dual complementary N+P-channel parts (like IRF7329) mix both channels'
                # specs in one parameterValues list, which can fail MosfetBasicSpecs' sanity checks
                print('SKIP', item['ispnName'], opn['opnName'], '-', e)

    return parts
