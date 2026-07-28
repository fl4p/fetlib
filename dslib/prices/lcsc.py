"""LCSC price harvester: parse the price ladders out of the brand-catalog rows that
dslib/discovery/lcsc.py already fetches (and discovery discards), for the discovery
brands PLUS the major-manufacturer brands below.

This is a price-only path: it never feeds DiscoveredParts into discovery, so extending
EXTRA_PRICE_BRANDS cannot change the parts universe.

CLI (run from repo root, fetlib venv):
    python -m dslib.prices.lcsc --probe [--brand NAME]   # page 1 per brand: verify ids
                                                         # + price-field key names
    python -m dslib.prices.lcsc --find-brand 'Infineon'  # resolve a brand name -> id
    python -m dslib.prices.lcsc --harvest                # full harvest into prices_db

The probe is MANDATORY before the first batch harvest: it asserts each hardcoded brand
id really is the brand we think (brandNameEn match) and that the price keys
(productPriceList / ladder / usdPrice) still exist -- schema drift raises instead of
writing thousands of empty ladders.
"""

import asyncio
import datetime
from collections import Counter
from typing import Dict, List, Optional, Tuple

from dslib import mfr_tag
from dslib.prices import LCSC, Offer, PartOffers, prices_db

# Brand ids verified via `--probe` (each asserts brandNameEn). The discovery china
# brands come from dslib.discovery.lcsc.brands; these are the extra price-harvest-only
# brands. Keys are LCSC's own brandNameEn spellings (what the probe matches against);
# resolved 2026-07-28 via `--find-brand`. Add new entries the same way, then probe.
EXTRA_PRICE_BRANDS: Dict[str, int] = {
    'Infineon': 330,
    'onsemi': 94,
    'ST': 74,
    'VISHAY': 91,
    'TOSHIBA': 72,
    'Nexperia': 1101,
    'AOS': 189,       # Alpha & Omega -- mfr_tag('AOS') -> 'ao' (dslib.mfrs)
    'DIODES': 296,
    'TI': 100,
    'ROHM': 170,
}


def price_brands() -> Dict[str, int]:
    from dslib.discovery.lcsc import brands
    merged = dict(brands)
    merged.update(EXTRA_PRICE_BRANDS)
    return merged


def parse_lcsc_row(row: dict) -> Optional[Tuple[Tuple[str, str, str, str], Offer]]:
    """One catalog row -> (store key, Offer), or None for rows without an MPN.

    Uses usdPrice ONLY -- currencyPrice follows the browser profile's locale and would
    silently mix currencies. A row that has an MPN but lacks productPriceList raises
    (schema drift must be loud, not an empty ladder)."""
    mpn = row.get('productModel')
    if not mpn:
        return None
    ladder = [(p['ladder'], p['usdPrice']) for p in row['productPriceList']
              if p.get('ladder') and p.get('usdPrice')]
    if not ladder:
        return None
    mfr = mfr_tag(row['brandNameEn'])
    offer = Offer(
        sku=row.get('productCode') or '',
        packaging=row.get('encapStandard'),
        ladder=ladder,
        moq=row.get('minBuyNumber'),
        stock=row.get('stockNumber'),
    )
    return (mfr, mpn, LCSC, 'USD'), offer


def aggregate_lcsc_offers(rows_with_ts: List[Tuple[dict, datetime.datetime]]
                          ) -> List[PartOffers]:
    """Group offers by final store key GLOBALLY (across ALL brands) before writing.

    prices_db.add() dict-ifies lists by key and overwrites whole records, so per-row or
    per-brand batches would last-write-wins whenever the same (mfr, mpn, lcsc, USD) key
    appears twice (duplicate SKUs/packagings, or one part in two brand lists). Offers
    are deduped by SKU within a key; fetched_at is the OLDEST envelope timestamp that
    contributed (conservative staleness)."""
    grouped: Dict[Tuple[str, str, str, str], dict] = {}
    for row, fetched_at in rows_with_ts:
        parsed = parse_lcsc_row(row)
        if parsed is None:
            continue
        key, offer = parsed
        g = grouped.setdefault(key, {'offers': {}, 'fetched_at': fetched_at})
        g['offers'].setdefault(offer.sku, offer)  # dedupe by SKU, first wins
        if fetched_at < g['fetched_at']:
            g['fetched_at'] = fetched_at
    return [
        PartOffers(mfr=key[0], mpn=key[1], distributor=LCSC, currency='USD',
                   offers=list(g['offers'].values()), fetched_at=g['fetched_at'],
                   url=None, status='ok')
        for key, g in grouped.items()
    ]


async def _fetch_all_brand_rows(brand_names=None) -> List[Tuple[dict, datetime.datetime]]:
    """All (row, envelope fetched_at) pairs across brands. Per-brand failures are logged
    and skipped; a brand whose rows ALL lack the price key raises (schema drift)."""
    from dslib.discovery.lcsc import fetch_brand_rows_raw

    rows_with_ts = []
    fallthrough = Counter()
    todo = price_brands()
    if brand_names:
        todo = {k: v for k, v in todo.items() if k in brand_names}
        assert todo, 'no matching brands among %r' % (sorted(price_brands()),)

    for name, brand_id in todo.items():
        try:
            raw = await fetch_brand_rows_raw(brand_id)
        except Exception as e:
            print('lcsc harvest: brand %s (%d) FAILED, skipping: %s' % (name, brand_id, e))
            continue
        fetched_at = datetime.datetime.fromisoformat(raw['fetched_at'])
        rows = raw['rows']
        priced = [r for r in rows if r.get('productPriceList')]
        if rows and not priced:
            raise RuntimeError(
                'lcsc schema drift? brand %s (%d): %d rows, NONE has productPriceList'
                % (name, brand_id, len(rows)))
        for r in rows:
            bn = r.get('brandNameEn') or ''
            if bn and '_' in mfr_tag(bn) and ' ' in bn:
                # mfr_tag fell through to the space->underscore fallback: this brand
                # name is unknown to dslib.mfrs and will never join with ranked parts
                fallthrough[bn] += 1
        rows_with_ts += [(r, fetched_at) for r in rows]
        print('lcsc harvest: brand %s (%d): %d rows, %d priced' %
              (name, brand_id, len(rows), len(priced)))

    if fallthrough:
        print('lcsc harvest: brandNameEn values UNKNOWN to mfr_tag (records kept, but '
              'they will not join with ranked parts):', dict(fallthrough))
    return rows_with_ts


async def harvest_lcsc_prices(max_age='7d', brand_names=None) -> Dict[str, int]:
    """Fetch all brands' raw rows, aggregate globally, ONE prices_db.add.

    `max_age` is accepted for orchestrator symmetry but LCSC freshness is DEFINED by
    fetch_brand_rows_raw's disk_cache ttl (7d): records carry the raw envelope's
    fetched_at, so refreshing faster than 7d requires clearing that cache tree."""
    rows_with_ts = await _fetch_all_brand_rows(brand_names)
    records = aggregate_lcsc_offers(rows_with_ts)
    changed = 0
    if records:
        prices_db.add(records)
        from dslib.prices.history import record_history
        changed = record_history(records)  # appends only price-content CHANGES
    return {'rows': len(rows_with_ts), 'records': len(records), 'history_changed': changed}


async def _probe(brand_names=None):
    """Page 1 per brand: verify hardcoded ids + price key names. No DB writes.

    id-match is canonical mfr_tag equality between the configured brand key and the
    rows' brandNameEn -- NOT substring matching, which once would have let key 'TI'
    "match" 'Infineon Technologies' via the substring 'ti'. The probe also FAILS when
    row0 does not parse into a priced offer (price-schema check, the reason the probe
    is mandatory) and when --brand selects nothing."""
    from dslib.discovery.lcsc import fetch_list_page
    todo = price_brands()
    if brand_names:
        todo = {k: v for k, v in todo.items() if any(b.lower() in k.lower()
                                                     for b in brand_names)}
        assert todo, '--brand %r selects none of %r' % (brand_names, sorted(price_brands()))
    ok = True
    for name, brand_id in todo.items():
        res = await fetch_list_page(brand_id, 1)
        rows = (res.get('result') or {}).get('dataList') or []
        if not rows:
            print('PROBE %s (%d): NO ROWS' % (name, brand_id))
            ok = False
            continue
        r0 = rows[0]
        brand_names_seen = {r.get('brandNameEn') for r in rows}
        id_ok = all(mfr_tag(bn) == mfr_tag(name) for bn in brand_names_seen if bn)
        parsed = parse_lcsc_row(r0)
        print('PROBE %s (%d): %d rows, brandNameEn=%r id-match=%s' %
              (name, brand_id, len(rows), sorted(brand_names_seen), id_ok))
        print('  row0 keys:', sorted(r0.keys()))
        print('  row0 parsed:', parsed)
        if not id_ok:
            ok = False
        if parsed is None:
            print('PROBE %s (%d): row0 did NOT parse into a priced offer' % (name, brand_id))
            ok = False
    assert ok, 'probe found brand-id mismatches, unparseable rows or empty brands -- fix before harvest'


async def _find_brand(keyword: str):
    """Resolve a brand name -> brandId by searching the MOSFET catalog by keyword and
    counting the brand fields on the matching rows."""
    from dslib.discovery.lcsc import fetch
    res = await fetch("https://wmsc.lcsc.com/ftps/wm/product/query/list", {
        "keyword": keyword, "catalogIdList": [1436], "brandIdList": [],
        "encapValueList": [], "isStock": False, "isOtherSuppliers": False,
        "isAsianBrand": False, "isDeals": False, "isEnvironment": False,
        "paramNameValueMap": {}, "currentPage": 1, "pageSize": 100,
    })
    rows = (res.get('result') or {}).get('dataList') or []
    seen = Counter()
    for r in rows:
        bid = r.get('brandId') or r.get('brandID')
        if bid:
            seen[(r.get('brandNameEn'), int(bid))] += 1
    if not seen:
        print('no brand ids found; row0 keys:',
              sorted(rows[0].keys()) if rows else '(no rows)')
    for (bn, bid), cnt in seen.most_common():
        print('%6d  %-40s %d rows' % (bid, bn, cnt))


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--probe', action='store_true')
    ap.add_argument('--harvest', action='store_true')
    ap.add_argument('--find-brand', metavar='NAME')
    ap.add_argument('--brand', action='append', help='restrict --probe/--harvest')
    a = ap.parse_args()

    async def _main():
        from dslib.fetch import close_browser
        try:
            if a.find_brand:
                await _find_brand(a.find_brand)
            elif a.probe:
                await _probe(a.brand)
            elif a.harvest:
                print(await harvest_lcsc_prices(brand_names=a.brand))
            else:
                ap.print_help()
        finally:
            await close_browser()

    asyncio.run(_main())
