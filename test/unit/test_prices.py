"""dslib.prices: ladder/MOQ contract, variation policy, negative-state semantics,
store key projection, currency isolation, staleness, LCSC aggregation.

Guard-checklist calibration lives here: every "no price" path must yield None (never
0), a negative record must be distinguishable from an absent key, and a stale or
foreign-currency record must be excluded loudly (counted), not silently served.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest  # noqa: E402

import dslib.prices as prices_mod  # noqa: E402
from dslib.prices import (DIGIKEY, LCSC, Offer, PartOffers, PriceLookup,  # noqa: E402
                          utc_now)
from dslib.prices.digikey_api import parse_digikey_offers  # noqa: E402
from dslib.prices.lcsc import aggregate_lcsc_offers, parse_lcsc_row  # noqa: E402
from dslib.prices import _price_key  # noqa: E402
from dslib.store import ObjectDatabase, _key_columns  # noqa: E402

NOW = utc_now()


def _offer(ladder, moq=None, stock=None, sku='SKU1', packaging='Cut Tape (CT)'):
    return Offer(sku=sku, packaging=packaging, ladder=ladder, moq=moq, stock=stock)


def _rec(mfr='infineon', mpn='X1', distributor=DIGIKEY, currency='USD', offers=None,
         fetched_at=None, status='ok'):
    return PartOffers(mfr=mfr, mpn=mpn, distributor=distributor, currency=currency,
                      offers=offers if offers is not None else [],
                      fetched_at=fetched_at or NOW, status=status)


@pytest.fixture
def db(tmp_path, monkeypatch):
    fresh = ObjectDatabase('prices-test', key_func=_price_key)
    fresh._lib_path = str(tmp_path / 'prices-test.pkl')  # no .pkl -> brand-new sqlite
    monkeypatch.setattr(prices_mod, 'prices_db', fresh)
    return fresh


# ------------------------------------------------------------------ 1. ladder contract
def test_price_at_picks_largest_break_leq_qty():
    o = _offer([(1, 1.0), (10, 0.8), (100, 0.5)])
    assert o.price_at(100) == 0.5
    assert o.price_at(50) == 0.8
    assert o.price_at(1) == 1.0
    assert o.price_at(99999) == 0.5


def test_price_at_below_moq_is_none():
    # an offer you cannot buy at this qty must not price at this qty: an MOQ-3000 reel
    # at $0.40 would otherwise "beat" a $0.60 cut tape for a 100-piece buy while
    # actually forcing a $1,200 minimum spend (review finding P1)
    o = _offer([(1, 1.0), (10, 0.8)], moq=10)
    assert o.price_at(5) is None
    assert o.price_at(10) == 0.8  # at/above MOQ it prices normally


def test_price_at_below_smallest_break_is_none_never_zero():
    o = _offer([(10, 0.8), (100, 0.5)])  # ladder starts at 10, no moq
    assert o.price_at(1) is None  # never invent a below-ladder price
    o2 = _offer([(50, 0.6)], moq=10)  # even moq-bumped qty below smallest break
    assert o2.price_at(1) is None
    assert 0 not in [o.price_at(q) for q in (1, 10, 100, 10 ** 6)]


def test_offer_rejects_zero_price_ladder():
    with pytest.raises(AssertionError):
        _offer([(1, 0.0)])


# ------------------------------------------------------- 2. DigiKey variation policy
def _dk_raw(products=None, exact=None, currency='USD'):
    return {'fetched_at': NOW.isoformat(),
            'response': {'products': products or [], 'exact_matches': exact or [],
                         'search_locale_used': {'currency': currency}}}


def _dk_product(mpn='X1', mfr_name='Infineon Technologies', variations=None):
    return {'manufacturer': {'name': mfr_name}, 'manufacturer_product_number': mpn,
            'product_url': 'https://dk/x1', 'product_variations': variations or []}


def _dk_var(sku='DK1', package='Cut Tape (CT)', pricing=None, marketplace=False,
            moq=1, stock=1000):
    return {'digi_key_product_number': sku,
            'package_type': {'id': 1, 'name': package},  # v4 shape: object, not string
            'market_place': marketplace, 'minimum_order_quantity': moq,
            'quantity_availablefor_package_type': stock,
            'standard_pricing': pricing or [{'break_quantity': 1, 'unit_price': 1.0}]}


def test_dk_variation_policy_drops_marketplace_and_digireel_keeps_cheapest():
    raw = _dk_raw(exact=[_dk_product(variations=[
        _dk_var(sku='CT', package='Cut Tape (CT)',
                pricing=[{'break_quantity': 100, 'unit_price': 0.60}]),
        _dk_var(sku='TR', package='Tape & Reel (TR)', moq=3000,
                pricing=[{'break_quantity': 3000, 'unit_price': 0.40}]),
        _dk_var(sku='DR', package='Digi-Reel®',
                pricing=[{'break_quantity': 1, 'unit_price': 0.01}]),
        _dk_var(sku='MP', marketplace=True,
                pricing=[{'break_quantity': 1, 'unit_price': 0.01}]),
    ])])
    rec = parse_digikey_offers('infineon', 'X1', raw)
    assert rec.status == 'ok'
    assert sorted(o.sku for o in rec.offers) == ['CT', 'TR']
    # at qty 100 the MOQ-3000 reel is not buyable -> CT wins despite the higher
    # unit price; at qty 3000 the reel prices and wins
    price, offer = rec.best_price(100)
    assert (price, offer.sku) == (0.60, 'CT')
    price, offer = rec.best_price(3000)
    assert (price, offer.sku) == (0.40, 'TR')


def test_dk_out_of_stock_still_prices_and_differs_from_catalog_miss():
    raw = _dk_raw(exact=[_dk_product(variations=[
        _dk_var(sku='CT', stock=0, pricing=[{'break_quantity': 1, 'unit_price': 2.0}])])])
    rec = parse_digikey_offers('infineon', 'X1', raw)
    assert rec.status == 'ok' and rec.best_price(1)[0] == 2.0  # stock is informational
    miss = parse_digikey_offers('infineon', 'X1', _dk_raw())
    assert miss.status == 'catalog_miss' and miss.best_price(1) is None


def test_dk_prefix_suffixed_mpn_is_not_a_catalog_miss():
    # DigiKey often lists only packaging-suffixed MPNs (base + T1G/T3G/TR). A response
    # with no exact match but a suffixed product must price, not become catalog_miss.
    raw = _dk_raw(products=[_dk_product(mpn='NTMFS5C628NLT1G', mfr_name='onsemi',
                                        variations=[_dk_var()])])
    rec = parse_digikey_offers('onsemi', 'NTMFS5C628NL', raw)
    assert rec.status == 'ok' and rec.best_price(1)[0] == 1.0


def test_dk_all_variations_excluded_is_no_eligible_offer_not_miss():
    raw = _dk_raw(exact=[_dk_product(variations=[_dk_var(marketplace=True)])])
    assert parse_digikey_offers('infineon', 'X1', raw).status == 'no_eligible_offer'


# --------------------------------------------- 3. mismatch / currency substitution
def test_dk_mfr_mismatch_is_indeterminate_never_catalog_miss():
    # candidates existed but none was provably ours: writing catalog_miss would
    # persist a false "no such part" for max_age days (review finding P1) -- the
    # parse must raise so the caller books an error and writes NOTHING
    from dslib.prices.digikey_api import IndeterminateMatch
    raw = _dk_raw(exact=[_dk_product(mfr_name='Vishay Intertech',
                                     variations=[_dk_var()])])
    with pytest.raises(IndeterminateMatch):
        parse_digikey_offers('infineon', 'X1', raw)
    # same for a candidate with NO manufacturer name: absence of evidence
    raw = _dk_raw(exact=[_dk_product(mfr_name='', variations=[_dk_var()])])
    with pytest.raises(IndeterminateMatch):
        parse_digikey_offers('infineon', 'X1', raw)


def test_dk_suffix_fallback_allowlist_only():
    from dslib.prices.digikey_api import _suffix_extends_mpn
    # known packaging suffixes and separator-led carrier codes extend the MPN
    assert _suffix_extends_mpn('NTMFS5C628NLT1G', 'NTMFS5C628NL')
    assert _suffix_extends_mpn('SIR104LDP-T1-RE3', 'SIR104LDP')
    assert _suffix_extends_mpn('IRFB4110TRPBF', 'IRFB4110')
    # digit continuations and bare letter continuations are DIFFERENT parts
    assert not _suffix_extends_mpn('X10', 'X1')
    assert not _suffix_extends_mpn('X1A', 'X1')     # re-review P1: not a variant
    assert not _suffix_extends_mpn('IRFB4110G', 'IRFB4110')


def test_dk_prefix_fallback_rejects_digit_and_letter_continuation():
    # X10/X1A are DIFFERENT parts than X1, not packaging variants: the response
    # holds no evidence about X1 at all -> catalog_miss (review finding P1)
    for other in ('X10', 'X1A'):
        raw = _dk_raw(products=[_dk_product(mpn=other, variations=[_dk_var()])])
        rec = parse_digikey_offers('infineon', 'X1', raw)
        assert rec.status == 'catalog_miss' and not rec.offers


def test_dk_matched_mpn_persisted_for_audit():
    raw = _dk_raw(products=[_dk_product(mpn='NTMFS5C628NLT1G', mfr_name='onsemi',
                                        variations=[_dk_var()])])
    rec = parse_digikey_offers('onsemi', 'NTMFS5C628NL', raw)
    assert rec.status == 'ok' and rec.matched_mpns == ['NTMFS5C628NLT1G']
    exact = parse_digikey_offers('onsemi', 'NTMFS5C628NLT1G', raw)
    assert exact.matched_mpns is None  # equality matches carry no audit note


def test_dk_missing_schema_fields_raise_never_negative():
    # a matched product missing product_variations (or a variation missing
    # standard_pricing) is a SCHEMA anomaly: raise -> caller writes nothing;
    # an explicitly empty pricing list is a real, empty offer (re-review P2)
    p = _dk_product(variations=None)
    p.pop('product_variations')
    with pytest.raises(ValueError):
        parse_digikey_offers('infineon', 'X1', _dk_raw(exact=[p]))
    v = _dk_var()
    v['standard_pricing'] = None
    with pytest.raises(ValueError):
        parse_digikey_offers('infineon', 'X1',
                             _dk_raw(exact=[_dk_product(variations=[v])]))
    v2 = _dk_var(pricing=[])
    v2['standard_pricing'] = []
    rec = parse_digikey_offers('infineon', 'X1',
                               _dk_raw(exact=[_dk_product(variations=[v2])]))
    assert rec.status == 'no_eligible_offer'


def test_dk_base_product_number_tier_matches():
    p = _dk_product(mpn='X1-T1G', variations=[_dk_var()])
    p['base_product_number'] = {'id': 7, 'name': 'X1'}
    rec = parse_digikey_offers('infineon', 'X1', _dk_raw(products=[p]))
    assert rec.status == 'ok' and rec.best_price(1)[0] == 1.0


def test_dk_search_locale_currency_overrides_requested():
    raw = _dk_raw(exact=[_dk_product(variations=[_dk_var()])], currency='EUR')
    rec = parse_digikey_offers('infineon', 'X1', raw, requested_currency='USD')
    assert rec.currency == 'EUR'  # what the API actually used, never the wish


# ------------------------------------------------------------------ 4. store semantics
def test_key_columns_projection_2_3_4_tuples():
    assert _key_columns(('mfr', 'mpn')) == ('mfr', 'mpn')
    assert _key_columns(('mfr', 'mpn', 'digikey')) == ('mfr', 'mpn')
    assert _key_columns(('mfr', 'mpn', 'digikey', 'USD')) == ('mfr', 'mpn')
    assert _key_columns(('solo',)) == (None, None)
    assert _key_columns(('mfr', 42)) == (None, None)
    assert _key_columns('plain') == (None, None)


def test_store_roundtrip_and_negative_record_vs_absent(db, tmp_path):
    usd = _rec(offers=[_offer([(1, 1.0)])])
    eur = _rec(currency='EUR', offers=[_offer([(1, 0.9)])])
    miss = _rec(mpn='GONE', status='catalog_miss')
    db.add([usd, eur, miss])

    again = ObjectDatabase('prices-test', key_func=db._key_func)
    # assign the .pkl-style base path (NOT db._lib_path, which now resolves to the
    # .sqlite3 file and would derive a fresh empty '*.sqlite3.sqlite3' store)
    again._lib_path = str(tmp_path / 'prices-test.pkl')
    got = again.load_obj(('infineon', 'X1', DIGIKEY, 'USD'))
    assert got.offers[0].ladder == [(1, 1.0)] and got.fetched_at == usd.fetched_at
    # EUR and USD coexist under distinct keys
    assert again.load_obj(('infineon', 'X1', DIGIKEY, 'EUR')).currency == 'EUR'
    # negative record is a RECORD; absence is None
    assert again.load_obj(('infineon', 'GONE', DIGIKEY, 'USD')).status == 'catalog_miss'
    assert again.load_obj(('infineon', 'NEVER', DIGIKEY, 'USD')) is None


def test_store_iter_items_mfr_filter_finds_4tuple_keys(db):
    db.add([_rec(), _rec(mfr='vishay', mpn='V1', offers=[_offer([(1, 1.0)])])])
    keys = [k for k, _ in db.iter_items(mfr='infineon')]
    assert keys == [('infineon', 'X1', DIGIKEY, 'USD')]


def test_negative_status_record_must_not_carry_offers():
    with pytest.raises(AssertionError):
        _rec(status='catalog_miss', offers=[_offer([(1, 1.0)])])


# ------------------------------------------------------------------ 5. PriceLookup
def test_lookup_absent_negative_priced_and_never_zero(db):
    db.add([_rec(offers=[_offer([(1, 1.0), (100, 0.5)])]),
            _rec(mpn='MISS', status='catalog_miss')])
    lu = PriceLookup(qty=100)
    hit = lu.get('infineon', 'X1')
    assert hit.price == 0.5 and hit.distributor == DIGIKEY
    assert lu.get('infineon', 'MISS') is None
    assert lu.get('infineon', 'NEVER') is None
    assert all(r is None or r.price > 0
               for r in [lu.get('infineon', m) for m in ('X1', 'MISS', 'NEVER')])
    # stats count DISTINCT parts (get is memoized): X1 queried twice counts once,
    # 3 distinct parts total -- per-call counting inflated the staged-HS loop's
    # fill-rate combinatorially (final review pass)
    s = lu.stats()
    assert '1/3' in s and 'digikey 1' in s


def test_lookup_excludes_and_counts_foreign_currency_and_stale(db):
    old = NOW - datetime.timedelta(days=90)
    db.add([_rec(mpn='EURONLY', currency='EUR', offers=[_offer([(1, 0.1)])]),
            _rec(mpn='OLD', offers=[_offer([(1, 0.2)])], fetched_at=old)])
    lu = PriceLookup(qty=100, max_age='30d')
    assert lu.get('infineon', 'EURONLY') is None  # never currency-mixed into USD
    assert lu.get('infineon', 'OLD') is None      # stale suppressed, not served forever
    s = lu.stats()
    assert 'other-currency 1' in s and 'stale 1' in s


def test_lookup_joins_whitespace_and_case_variant_mpns(db):
    # live gap: 48 price keys never filled a row because LCSC lists 'BSC070N10NS3G'
    # where discovery ranks 'BSC070N10NS3 G' (and 'aot412' vs 'AOT412') -- the join
    # normalizes case+whitespace on both sides; store keys stay raw
    db.add([_rec(mpn='BSC070N10NS3G', distributor=LCSC,
                 offers=[_offer([(100, 0.4)], sku='C7')]),
            _rec(mfr='ao', mpn='aot412', offers=[_offer([(100, 1.1)])])])
    lu = PriceLookup(qty=100)
    assert lu.get('infineon', 'BSC070N10NS3 G').price == 0.4
    assert lu.get('ao', 'AOT412').price == 1.1


def test_dk_equality_tier_ignores_whitespace_and_case():
    raw = _dk_raw(products=[_dk_product(mpn='BSC070N10NS3G', variations=[_dk_var()])])
    rec = parse_digikey_offers('infineon', 'BSC070N10NS3 G', raw)
    assert rec.status == 'ok' and rec.best_price(1)[0] == 1.0


def test_lookup_picks_cheapest_across_distributors(db):
    db.add([_rec(offers=[_offer([(100, 0.5)])]),
            _rec(distributor=LCSC, offers=[_offer([(100, 0.3)], sku='C1')])])
    assert PriceLookup(qty=100).get('infineon', 'X1').distributor == LCSC


def test_lookup_counts_skipped_records_even_on_hits(db):
    # a USD hit must not hide that a stale/foreign record was ALSO skipped for the
    # same part (review finding P2): record-level skips are counted independently
    # of the query outcome
    old = NOW - datetime.timedelta(days=90)
    db.add([_rec(offers=[_offer([(1, 1.0)])]),
            _rec(currency='EUR', offers=[_offer([(1, 0.9)])]),
            _rec(distributor=LCSC, offers=[_offer([(1, 0.8)], sku='C1')],
                 fetched_at=old)])
    lu = PriceLookup(qty=100)
    assert lu.get('infineon', 'X1').price == 1.0  # the hit
    s = lu.stats()
    assert '1/1 parts priced' in s
    assert 'records skipped: other_currency 1, stale 1' in s


# ------------------------------------------------------------------ 6. LCSC parsing
LCSC_ROW = {  # shape per plan; superseded by the captured probe fixture once live
    'productModel': 'IPB019N08N3 G', 'brandNameEn': 'Infineon Technologies',
    'productCode': 'C111111', 'encapStandard': 'TO-263',
    'minBuyNumber': 5, 'stockNumber': 250,
    'productPriceList': [{'ladder': 5, 'usdPrice': 1.2},
                         {'ladder': 100, 'usdPrice': 0.9}],
}


def test_parse_lcsc_row_ladder_and_key():
    key, offer = parse_lcsc_row(LCSC_ROW)
    assert key == ('infineon', 'IPB019N08N3 G', LCSC, 'USD')
    assert offer.ladder == [(5, 1.2), (100, 0.9)] and offer.moq == 5
    assert offer.sku == 'C111111'


def test_parse_lcsc_all_invalid_pricing_drops_row_and_brand_guard_fires():
    # all-invalid entries (renamed/nulled fields) must behave like the mixed case:
    # row dropped -- and the brand-level guard must count PARSED rows, so systematic
    # drift raises instead of silently aging the DB out with zero new records
    import asyncio
    import dslib.discovery.lcsc as dlcsc
    import dslib.prices.lcsc as plcsc
    bad_row = dict(LCSC_ROW, productPriceList=[{'tier': 5, 'price': 1.2}])
    assert parse_lcsc_row(bad_row) is None

    async def fake_raw(brand_id):
        return {'fetched_at': NOW.isoformat(), 'rows': [bad_row] * 3}

    def run(monkey_target):
        return asyncio.run(plcsc._fetch_all_brand_rows(brand_names=['NCE']))

    orig = dlcsc.fetch_brand_rows_raw
    dlcsc.fetch_brand_rows_raw = fake_raw
    try:
        with pytest.raises(RuntimeError, match='schema drift'):
            run(None)
    finally:
        dlcsc.fetch_brand_rows_raw = orig


def test_parse_lcsc_row_missing_price_key_raises():
    row = dict(LCSC_ROW)
    del row['productPriceList']
    with pytest.raises(KeyError):
        parse_lcsc_row(row)


def test_aggregate_merges_duplicate_and_cross_brand_rows():
    t1, t2 = NOW - datetime.timedelta(days=1), NOW
    dup = dict(LCSC_ROW, productCode='C222222')  # second SKU, same MPN, "other brand list"
    recs = aggregate_lcsc_offers([(LCSC_ROW, t1), (LCSC_ROW, t2), (dup, t2)])
    assert len(recs) == 1  # one record per key: no last-row/last-brand-wins
    rec = recs[0]
    assert sorted(o.sku for o in rec.offers) == ['C111111', 'C222222']
    assert rec.fetched_at == t1  # oldest contributing envelope (conservative)


# ------------------------------------------------------------------ DK batch
def _batch_raw(details):
    return {'fetched_at': NOW.isoformat(), 'details': details, 'errors': []}


def _batch_detail(mpn='X1', mfr_name='Infineon Technologies', sku='DK1',
                  packaging='Cut Tape', pricing=None, direct_ship=False,
                  moq=1, stock=500):
    return {'manufacturer_part_number': mpn, 'digi_key_part_number': sku,
            'manufacturer': {'value': mfr_name}, 'packaging': {'value': packaging},
            'supplier_direct_ship': direct_ship, 'minimum_order_quantity': moq,
            'quantity_available': stock, 'product_url': 'https://dk/x1',
            'search_locale_used': {'currency': 'USD'},
            'standard_pricing': pricing or [{'break_quantity': 1, 'unit_price': 1.0}]}


def test_batch_parse_prices_matched_part():
    from dslib.prices.digikey_api import parse_digikey_batch
    raw = _batch_raw([_batch_detail(),
                      _batch_detail(sku='DK2', packaging='Digi-Reel®'),   # excluded
                      _batch_detail(sku='DK3', direct_ship=True),         # excluded
                      _batch_detail(mpn='OTHER', sku='DK4')])             # not ours
    rec = parse_digikey_batch('infineon', 'X1', raw)
    assert rec.status == 'ok' and [o.sku for o in rec.offers] == ['DK1']
    assert rec.best_price(1)[0] == 1.0


def test_batch_parse_unmatched_returns_none_never_negative():
    # the batch error list does not name failing MPNs -> unmatched parts must fall
    # through to the keyword path (which owns catalog_miss), never write a negative
    from dslib.prices.digikey_api import parse_digikey_batch
    assert parse_digikey_batch('infineon', 'X1', _batch_raw([])) is None
    # same-MPN, wrong manufacturer: also None
    raw = _batch_raw([_batch_detail(mfr_name='Vishay Intertech')])
    assert parse_digikey_batch('infineon', 'X1', raw) is None


def test_batch_parse_suffix_tier_and_audit():
    from dslib.prices.digikey_api import parse_digikey_batch
    raw = _batch_raw([_batch_detail(mpn='X1TR', mfr_name='onsemi')])
    rec = parse_digikey_batch('onsemi', 'X1', raw)
    assert rec.status == 'ok' and rec.offers[0].sku == 'DK1'
    assert rec.matched_mpns == ['X1TR']  # audit contract, same as keyword parser
    assert parse_digikey_batch('onsemi', 'X9', raw) is None  # X1TR does not extend X9


def test_batch_parse_never_mixes_currencies_across_details():
    # search_locale_used is per detail: a EUR detail must not join a USD record's
    # ladder (nor relabel it) -- currency locks at the first accepted priced detail
    from dslib.prices.digikey_api import parse_digikey_batch
    usd = _batch_detail(sku='USD1', pricing=[{'break_quantity': 1, 'unit_price': 1.0}])
    eur = _batch_detail(sku='EUR1', pricing=[{'break_quantity': 1, 'unit_price': 0.5}])
    eur['search_locale_used'] = {'currency': 'EUR'}
    rec = parse_digikey_batch('infineon', 'X1', _batch_raw([usd, eur]))
    assert rec.currency == 'USD'
    assert [o.sku for o in rec.offers] == ['USD1']  # the EUR ladder stayed out


def test_batch_parse_invalid_pricing_entries_skip_detail():
    # nonempty pricing without valid breaks is a schema anomaly: the detail is
    # skipped so the part falls through to the keyword path -- never priced wrong,
    # never a durable negative
    from dslib.prices.digikey_api import parse_digikey_batch
    bad = _batch_detail(pricing=[{'quantity': 1, 'price': 1.0}])  # renamed fields
    assert parse_digikey_batch('infineon', 'X1', _batch_raw([bad])) is None


def test_batch_parse_anomalous_sibling_fails_whole_part():
    # [GOOD, BAD] must NOT persist just GOOD: the partial offer set may omit the
    # cheapest variation, and the fresh 'ok' record would block keyword fallback
    # for max_age days -- any anomaly bails the whole part to keyword
    from dslib.prices.digikey_api import parse_digikey_batch
    good = _batch_detail(sku='GOOD')
    bad = _batch_detail(sku='BAD', pricing=[{'quantity': 1, 'price': 0.1}])
    assert parse_digikey_batch('infineon', 'X1', _batch_raw([good, bad])) is None
    missing = _batch_detail(sku='M')
    missing['standard_pricing'] = None
    assert parse_digikey_batch('infineon', 'X1', _batch_raw([good, missing])) is None


def test_mixed_pricing_arrays_never_persist_partial_ladders():
    # round 4: [valid, malformed] must not store just the valid subset -- a dropped
    # break silently mis-prices at some qty. Keyword parser raises (writes nothing);
    # batch parser skips the detail (part falls through to keyword); LCSC drops the row
    from dslib.prices.digikey_api import parse_digikey_batch
    mixed = [{'break_quantity': 1, 'unit_price': 1.0}, {'quantity': 10, 'price': 0.8}]
    v = _dk_var()
    v['standard_pricing'] = mixed
    with pytest.raises(ValueError):
        parse_digikey_offers('infineon', 'X1',
                             _dk_raw(exact=[_dk_product(variations=[v])]))
    assert parse_digikey_batch('infineon', 'X1',
                               _batch_raw([_batch_detail(pricing=mixed)])) is None
    row = dict(LCSC_ROW, productPriceList=[{'ladder': 5, 'usdPrice': 1.2},
                                           {'ladder': 100, 'usdPrice': None}])
    assert parse_lcsc_row(row) is None


def test_dk_nonempty_invalid_pricing_raises_not_negative():
    # keyword parser: same anomaly must raise (writes nothing), not book
    # no_eligible_offer (re-review round 3)
    v = _dk_var()
    v['standard_pricing'] = [{'quantity': 1, 'price': 1.0}]
    with pytest.raises(ValueError):
        parse_digikey_offers('infineon', 'X1',
                             _dk_raw(exact=[_dk_product(variations=[v])]))


class _FakeKey:
    """Duck-typed stand-in for digikey_api._Key (real one wants creds)."""

    def __init__(self, label, remaining=None):
        self.label = label
        self.client_id = label
        self.dead = False
        self.remaining = remaining
        self.consecutive_429 = 0


class _Http(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__('HTTP %d' % status)


def _run_batch_phase(monkeypatch, db, todo, keys, responses):
    """responses: {key_label: callable(mpns) -> raw dict | raises}."""
    import dslib.prices.digikey_api as dk

    def fake_raw(mpns, currency, key):
        return responses[key.label](mpns)

    monkeypatch.setattr(dk, '_dk_batch_details_raw', fake_raw)
    monkeypatch.setattr('dslib.prices.history.record_history', lambda recs, path=None: 0)
    n = dict(fetched=0, quota_stop=0)
    left = dk._batch_phase(todo, keys, 'USD', n, quota_floor=25)
    return n, left


def test_batch_phase_probes_every_key_before_fallback(monkeypatch, db):
    # 403 on key1 must NOT trigger global fallback (enablement is per app): key2 is
    # probed, prices the chunk, and key1 stays alive for keyword work
    todo = [('infineon', 'X1')]
    k1, k2 = _FakeKey('k1'), _FakeKey('k2')

    def k1_resp(mpns):
        raise _Http(403)

    n, left = _run_batch_phase(monkeypatch, db, todo, [k1, k2],
                               {'k1': k1_resp,
                                'k2': lambda mpns: _batch_raw([_batch_detail()])})
    assert n['fetched'] == 1 and left == []
    assert not k1.dead  # batch-incapable, but keyword-capable


def test_batch_phase_all_keys_403_returns_full_todo_unwritten(monkeypatch, db):
    todo = [('infineon', 'X1'), ('infineon', 'X2')]
    k1, k2 = _FakeKey('k1'), _FakeKey('k2')

    def raise403(mpns):
        raise _Http(403)

    n, left = _run_batch_phase(monkeypatch, db, todo, [k1, k2],
                               {'k1': raise403, 'k2': raise403})
    assert left == todo and n['fetched'] == 0 and n['quota_stop'] == 0
    assert not k1.dead and not k2.dead
    assert db.count() == 0  # nothing written


def test_batch_phase_401_not_subscribed_retires_key_from_batch_only(monkeypatch, db):
    # the OBSERVED live signal at /BatchSearch/v3 for a not-enabled app is 401
    # 'You are not subscribed to this API' -- batch-incapable, keyword-alive
    todo = [('infineon', 'X1')]
    k1, k2 = _FakeKey('k1'), _FakeKey('k2')

    def not_subscribed(mpns):
        e = _Http(401)
        e.body = '{"ErrorMessage":"Invalid Client-Id","ErrorDetails":"You are not ' \
                 'subscribed to this API. Please subscribe and try again."}'
        raise e

    n, left = _run_batch_phase(monkeypatch, db, todo, [k1, k2],
                               {'k1': not_subscribed,
                                'k2': lambda mpns: _batch_raw([_batch_detail()])})
    assert n['fetched'] == 1 and left == [] and not k1.dead


def test_batch_phase_unexpected_error_fails_open_to_keyword(monkeypatch, db):
    # batch is an optional optimization: a 5xx/network/decode error must not abort
    # the DigiKey fetch -- the key leaves the batch set (keyword-alive) and all
    # parts go to the keyword path
    todo = [('infineon', 'X1'), ('infineon', 'X2')]
    k1 = _FakeKey('k1')

    def boom(mpns):
        raise RuntimeError('connection reset by peer')  # no .status at all

    n, left = _run_batch_phase(monkeypatch, db, todo, [k1], {'k1': boom})
    assert left == todo and n['fetched'] == 0 and n['quota_stop'] == 0
    assert not k1.dead  # keyword still gets to use it
    assert db.count() == 0


def test_batch_phase_quota_death_returns_all_unattempted(monkeypatch, db):
    # 100 parts: chunk 1 prices 40, leaves 10 unmatched; chunk 2 kills the only key.
    # EVERYTHING unpriced (10 + 50) must come back for the keyword phase; the batch
    # phase itself never touches quota_stop (review round 3 reproduction)
    todo = [('infineon', 'P%03d' % i) for i in range(100)]
    k1 = _FakeKey('k1')
    calls = []

    def k1_resp(mpns):
        calls.append(list(mpns))
        if len(calls) == 1:  # price the first 40 of the chunk, leave 10 unmatched
            return _batch_raw([_batch_detail(mpn=m) for m in mpns[:40]])
        raise _Http(429)

    n, left = _run_batch_phase(monkeypatch, db, todo, [k1], {'k1': k1_resp})
    assert n['fetched'] == 40 and n['quota_stop'] == 0
    assert len(left) == 60  # 10 unmatched + the whole second chunk
    assert k1.dead  # daily quota: dead for keyword too


def test_keyword_pool_retires_auth_bad_key_and_requeues(monkeypatch, db):
    # round 5: a key whose 401 survives the client rebuild must be retired GLOBALLY
    # with its job re-queued -- previously each job on it was booked as an error, so
    # one bad key could drain the whole queue while a healthy key sat idle
    import dslib.prices.digikey_api as dk
    k1, k2 = _FakeKey('k1'), _FakeKey('k2')
    k1.limiter_lock, k2.limiter_lock = __import__('threading').Lock(), __import__('threading').Lock()
    k1.next_slot = k2.next_slot = 0.0

    def fake_raw(mpn, currency='USD', key=None):
        if key.label == 'k1':
            raise dk.DkAuthFailed(mpn, 'k1xxxx')
        return {'fetched_at': NOW.isoformat(),
                'response': {'exact_matches': [_dk_product(mpn=mpn)],
                             'search_locale_used': {'currency': 'USD'}},
                'rate_limit_remaining': 900}

    monkeypatch.setattr(dk, 'discover_keys', lambda: [k1, k2])
    monkeypatch.setattr(dk, '_build_client', lambda key: None)
    monkeypatch.setattr(dk, '_dk_keyword_search_raw', fake_raw)
    monkeypatch.setattr(dk, 'prices_db', db)
    monkeypatch.setattr('dslib.prices.history.record_history',
                        lambda recs, path=None: 0)

    parts = [('infineon', 'A1'), ('infineon', 'A2'), ('infineon', 'A3')]
    n = dk.fetch_digikey_prices(parts, use_batch=False, min_interval=0.0)
    # every part priced via the healthy key; nothing lost to the auth-bad one
    assert n['fetched'] == 3 and n['errors'] == 0 and n['quota_stop'] == 0
    assert k1.dead and not k2.dead


def test_search_raw_failing_rebuild_is_auth_failed(monkeypatch):
    # round-5 follow-up: if the mid-run client REBUILD itself raises (refresh/OAuth/
    # network), that is proof of a broken key -- it must surface as DkAuthFailed
    # (global retirement + job re-queue), not as a generic per-job error
    import dslib.prices.digikey_api as dk
    from digikey.v4.productinformation.rest import ApiException

    key = _FakeKey('k1')

    class FakeApi:
        def keyword_search_with_http_info(self, *a, **kw):
            raise ApiException(status=401, reason='Unauthorized')

    key.client = {'api': FakeApi(), 'auth': 'Bearer x'}

    def broken_rebuild(k):
        raise RuntimeError('refresh token rejected')

    monkeypatch.setattr(dk, '_build_client', broken_rebuild)
    with pytest.raises(dk.DkAuthFailed):
        dk._dk_keyword_search_raw('X1', key=key)


# ------------------------------------------------------------------ history
def test_history_appends_changes_only_and_samples_stock_at_changes(tmp_path):
    from dslib.prices.history import read_history, record_history
    hp = str(tmp_path / 'hist.sqlite3')

    r1 = _rec(offers=[_offer([(1, 1.0), (100, 0.5)], stock=500)])
    assert record_history([r1], path=hp) == 1
    # identical content, new fetch (e.g. re-parse of a cached envelope): no append
    assert record_history([_rec(offers=[_offer([(1, 1.0), (100, 0.5)], stock=500)])],
                          path=hp) == 0
    # stock-only jitter is NOT a price change (documented contract)
    assert record_history([_rec(offers=[_offer([(1, 1.0), (100, 0.5)], stock=9)])],
                          path=hp) == 0
    # a real ladder change appends, and the new rows carry the current stock sample
    later = NOW + datetime.timedelta(days=7)
    assert record_history([_rec(offers=[_offer([(1, 1.1), (100, 0.6)], stock=9)],
                                fetched_at=later)], path=hp) == 1

    rows = read_history('infineon', 'X1', path=hp)
    assert len(rows) == 4  # 2 breaks x 2 snapshots
    assert [r[5] for r in rows] == [1.0, 0.5, 1.1, 0.6]
    assert rows[-1][7] == 9  # stock sampled at the change point
    assert 0 not in [r[5] for r in rows]


def test_history_hash_tolerates_none_packaging_and_dup_skus(tmp_path):
    # sorting offer tuples mixing None packaging with strings raised TypeError; the
    # crash happened AFTER prices_db.add succeeded, leaving the record fresh-skipped
    # and its history unwritable until expiry (re-review P2)
    from dslib.prices.history import read_history, record_history
    hp = str(tmp_path / 'hist.sqlite3')
    rec = _rec(offers=[_offer([(1, 1.0)], sku='', packaging=None),
                       _offer([(1, 2.0)], sku='', packaging='Tube'),
                       _offer([(10, 0.5)], sku='S1', packaging=None, moq=None)])
    assert record_history([rec], path=hp) == 1
    assert record_history([rec], path=hp) == 0  # and the hash is still stable
    assert len(read_history('infineon', 'X1', path=hp)) == 3


def test_fresh_gate_matches_requested_currency_after_substitution(monkeypatch, db,
                                                                  tmp_path):
    # a USD query DigiKey answered in EUR lives under the (..., 'EUR') key; probing
    # only the (..., 'USD') key re-spent quota on that part EVERY run inside max_age
    import dslib.prices.digikey_api as dk
    monkeypatch.setattr(dk, 'prices_db', db)
    monkeypatch.setattr('dslib.prices.history._PATH', str(tmp_path / 'h.sqlite3'))

    eur = _rec(currency='EUR', offers=[_offer([(1, 0.9)])])
    eur.requested_currency = 'USD'  # what the query asked for
    db.add([eur])

    n = dk.fetch_digikey_prices([('infineon', 'X1')])  # USD run: must fresh-skip
    assert n['fresh_skip'] == 1 and n.get('fetched', 0) == 0


def test_fresh_skip_heals_missing_history(monkeypatch, db, tmp_path):
    # a crash between prices_db.add and record_history leaves a fresh record whose
    # history cannot be written until expiry (fresh_skip short-circuits) -- the
    # fresh-skip path now reconciles via the idempotent content hash
    import dslib.prices.digikey_api as dk
    from dslib.prices.history import read_history
    hp = str(tmp_path / 'hist.sqlite3')
    monkeypatch.setattr(dk, 'prices_db', db)
    monkeypatch.setattr('dslib.prices.history._PATH', hp)

    db.add([_rec(offers=[_offer([(1, 1.0)])])])  # store write WITHOUT history (crash)
    assert read_history('infineon', 'X1', path=hp) == []

    n = dk.fetch_digikey_prices([('infineon', 'X1')])  # all fresh: no keys needed
    assert n['fresh_skip'] == 1
    assert len(read_history('infineon', 'X1', path=hp)) == 1  # healed
    # second run: hash matches, nothing re-appended
    dk.fetch_digikey_prices([('infineon', 'X1')])
    assert len(read_history('infineon', 'X1', path=hp)) == 1


def test_history_negative_status_is_a_datapoint(tmp_path):
    from dslib.prices.history import read_history, record_history
    hp = str(tmp_path / 'hist.sqlite3')
    record_history([_rec(offers=[_offer([(1, 1.0)])])], path=hp)
    # the part vanishing from the catalog is recorded as a row with NULL price
    assert record_history([_rec(status='catalog_miss',
                                fetched_at=NOW + datetime.timedelta(days=7))],
                          path=hp) == 1
    rows = read_history('infineon', 'X1', path=hp)
    assert rows[-1][2] == 'catalog_miss' and rows[-1][5] is None


# ------------------------------------------------------- 7. browser lifecycle
def test_browser_lifecycle_two_sequential_asyncio_runs():
    """get_browser_page asserts no context of a DEAD event loop lingers
    (dslib/fetch.py:152-153). Each asyncio.run phase must therefore close the browser
    before its loop exits (main.py's _discover_and_close_browser, the harvest phase) --
    this exercises that invariant with a fake context, without launching Chrome."""
    import asyncio
    import dslib.fetch as fetch

    class FakeCtx:
        pages = []

        async def close(self):
            pass

    async def phase():
        evl_id = id(asyncio.get_event_loop())
        # phase-1 precondition == what get_browser_page asserts before launching
        assert not fetch.browser_contexts
        fetch.browser_contexts[evl_id] = FakeCtx()
        try:
            return 'worked'
        finally:
            await fetch.close_browser()

    assert asyncio.run(phase()) == 'worked'
    assert not fetch.browser_contexts  # nothing leaks into the next loop
    assert asyncio.run(phase()) == 'worked'  # second loop passes the same assert
    assert not fetch.browser_contexts


def test_aggregate_duplicate_sku_newest_envelope_wins_any_order():
    # a stale ladder must never beat fresher data by input order (review finding)
    t1, t2 = NOW - datetime.timedelta(days=3), NOW
    old = dict(LCSC_ROW, productPriceList=[{'ladder': 5, 'usdPrice': 0.5}])
    new = dict(LCSC_ROW, productPriceList=[{'ladder': 5, 'usdPrice': 1.0}])
    for order in ([(old, t1), (new, t2)], [(new, t2), (old, t1)]):
        rec = aggregate_lcsc_offers(order)[0]
        assert rec.offers[0].ladder == [(5, 1.0)]  # the t2 ladder, both orders
        assert rec.fetched_at == t1  # record ts stays the oldest contributor


def test_aggregate_then_single_add_keeps_union(db):
    recs = aggregate_lcsc_offers([(LCSC_ROW, NOW),
                                  (dict(LCSC_ROW, productCode='C2'), NOW)])
    db.add(recs)
    stored = db.load_obj(('infineon', 'IPB019N08N3 G', LCSC, 'USD'))
    assert len(stored.offers) == 2
