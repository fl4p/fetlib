import math
import re

import pandas as pd

from dslib import mfr_tag
from dslib.discovery import MosfetBasicSpecs, DiscoveredPart, download_parts_list
from dslib.field import parse_field_value


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


async def onsemi_mosfets():
    parts = []

    urls = {
        'small-signal-mosfets': 'https://www.onsemi.com/products/discrete-power-modules/mosfets/small-signal-mosfets',
        'low-medium-voltage-mosfets': 'https://www.onsemi.com/products/discrete-power-modules/mosfets/low-medium-voltage-mosfets',
        'high-voltage-mosfets': 'https://www.onsemi.com/products/discrete-power-modules/mosfets/high-voltage-mosfets',
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
            if row['Channel Polarity'] == 'Complementary' or row['Configuration'] != 'Single' or 'Q1' in str(row[
                                                                                                                 'RDS(on) Max @ VGS = 10 V  (mΩ)']):
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
                Vds_max=parse_field_value(str(row['V(BR)DSS Min (V)']).strip('±')),
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
