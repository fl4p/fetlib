"""Distributor price records for parts (DigiKey API + LCSC catalog harvest).

Store: `prices_db` -- one `PartOffers` record per (mfr, mpn, distributor, currency),
`data/prices-lib.sqlite3`. Latest snapshot only (docs/Parts Prices.md's date index is
realized by `fetched_at` inside the record, not by exploding rows); price history, if
ever wanted, is an append-only side table, not this store.

Guard semantics (deliberate, keep them):
- absent key            = never fetched. Distinct from every negative state.
- status='catalog_miss' = queried, the distributor has no such part. Only DigiKey can
  assert this (a per-MPN query); the LCSC brand-list harvest cannot prove absence and
  never writes it.
- status='no_eligible_offer' = product found but every variation was excluded
  (marketplace / Digi-Reel).
- fetch/parse/schema errors write NOTHING -- an error must never become a durable
  "no price".
- `fetched_at` is always the ORIGIN timestamp of the data (the HTTP fetch), never a
  DB-write or cache-hit time. prices_db is the freshness authority.
- One currency per lookup: PriceLookup skips-and-counts records in any other currency,
  it never mixes them into one result column.
"""

import datetime
from typing import Dict, List, NamedTuple, Optional, Tuple

from dslib.store import ObjectDatabase

DIGIKEY = 'digikey'
LCSC = 'lcsc'

VALID_STATUS = ('ok', 'catalog_miss', 'no_eligible_offer')


def _to_timedelta(v) -> datetime.timedelta:
    if isinstance(v, datetime.timedelta):
        return v
    import pandas as pd
    return pd.to_timedelta(v)


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class Offer:
    """One orderable variation (DigiKey: Cut Tape / Tape&Reel / ...; LCSC: the listing).

    `stock` is informational only -- it does not gate price_at(); a 0-stock offer still
    prices (distinguishable from catalog_miss by the record's status).
    """

    def __init__(self, sku: str, packaging: Optional[str],
                 ladder: List[Tuple[int, float]],
                 moq: Optional[int] = None, stock: Optional[int] = None):
        ladder = sorted((int(q), float(p)) for q, p in ladder)
        assert all(q >= 1 for q, _ in ladder), 'ladder qty must be >= 1: %r' % (ladder,)
        assert all(p > 0 for _, p in ladder), 'ladder price must be > 0: %r' % (ladder,)
        self.sku = sku
        self.packaging = packaging
        self.ladder = ladder
        self.moq = int(moq) if moq else None
        self.stock = int(stock) if stock is not None else None

    def price_at(self, qty: int) -> Optional[float]:
        """Unit price at qty, or None when this offer cannot be bought at qty.

        An offer with moq > qty does NOT price (returns None): comparing its per-unit
        price against buyable offers would rank an MOQ-3000 reel at $0.40 "cheaper"
        than a $0.60 cut tape for a 100-piece buy while actually forcing a $1,200
        minimum spend. Also None below the smallest ladder break -- never invent a
        price below the ladder, and never return 0."""
        q = int(qty)
        if self.moq and q < self.moq:
            return None
        price = None
        for break_qty, unit_price in self.ladder:
            if break_qty <= q:
                price = unit_price
            else:
                break
        return price

    def __repr__(self):
        return 'Offer(%s, %s, ladder=%r, moq=%s, stock=%s)' % (
            self.sku, self.packaging, self.ladder, self.moq, self.stock)


class PartOffers:
    """All offers of one distributor for one part in one currency.

    One store record per key (mfr, mpn, distributor, currency)."""

    def __init__(self, mfr: str, mpn: str, distributor: str, currency: str,
                 offers: List[Offer], fetched_at: datetime.datetime,
                 url: Optional[str] = None, status: str = 'ok'):
        assert status in VALID_STATUS, status
        assert not (status != 'ok' and offers), 'negative status must carry no offers'
        assert fetched_at.tzinfo is not None, 'fetched_at must be tz-aware (origin UTC)'
        self.mfr = mfr
        self.mpn = mpn
        self.distributor = distributor
        self.currency = currency
        self.offers = offers
        self.fetched_at = fetched_at
        self.url = url
        self.status = status

    @property
    def key(self):
        return self.mfr, self.mpn, self.distributor, self.currency

    def best_price(self, qty: int) -> Optional[Tuple[float, Offer]]:
        """Cheapest price_at(qty) across offers (the variation policy)."""
        best = None
        for o in self.offers:
            p = o.price_at(qty)
            if p is not None and (best is None or p < best[0]):
                best = (p, o)
        return best

    def age(self, now: Optional[datetime.datetime] = None) -> datetime.timedelta:
        return (now or utc_now()) - self.fetched_at

    def __repr__(self):
        return 'PartOffers(%s %s %s %s, %d offers, %s, %s)' % (
            self.mfr, self.mpn, self.distributor, self.currency,
            len(self.offers), self.status, self.fetched_at.date())


Mfr = str
Mpn = str
Distributor = str
Currency = str
def _price_key(o):
    # load_obj/del_obj pass raw key tuples through key_func, add() passes records
    return o if isinstance(o, tuple) else (o.mfr, o.mpn, o.distributor, o.currency)


prices_db = ObjectDatabase[Tuple[Mfr, Mpn, Distributor, Currency], PartOffers](
    'prices-lib', key_func=_price_key)


class PriceResult(NamedTuple):
    price: float
    currency: str
    qty: int
    distributor: str
    sku: str
    fetched_at: datetime.datetime


class PriceLookup:
    """Read-side join for CSV row building: one prices_db.load(), then dict lookups.

    Two counter families, kept apart on purpose (a hit must not hide that a stale or
    foreign-currency record was ALSO skipped for the same part):
    - query outcomes: every get() is exactly one of hit / no-record / one
      most-specific no-price reason;
    - record-level skips: every record excluded from consideration is counted here,
      on hits and misses alike.
    get() returns None for absent / negative-status / under-ladder parts -- never 0,
    and never a value from another currency.
    """

    def __init__(self, qty: int = 100, currency: str = 'USD', max_age='30d'):
        self.qty = int(qty)
        self.currency = currency
        self.max_age = _to_timedelta(max_age)
        self._now = utc_now()
        self._by_part: Dict[Tuple[str, str], List[PartOffers]] = {}
        for rec in prices_db.load().values():
            self._by_part.setdefault((rec.mfr, rec.mpn), []).append(rec)
        self._n = dict(hit=0, miss=0, negative=0, stale=0, other_currency=0,
                       under_ladder=0)
        self._skipped = dict(negative=0, stale=0, other_currency=0, under_ladder=0)
        self._n_dist: Dict[str, int] = {}

    def get(self, mfr: str, mpn: str) -> Optional[PriceResult]:
        recs = self._by_part.get((mfr, mpn))
        if not recs:
            self._n['miss'] += 1
            return None
        best = None
        saw = dict(negative=0, stale=0, other_currency=0, under_ladder=0)
        for rec in recs:
            if rec.currency != self.currency:
                saw['other_currency'] += 1
                continue
            if rec.age(self._now) > self.max_age:
                saw['stale'] += 1
                continue
            if rec.status != 'ok':
                saw['negative'] += 1
                continue
            bp = rec.best_price(self.qty)
            if bp is None:
                saw['under_ladder'] += 1
                continue
            price, offer = bp
            if best is None or price < best.price:
                best = PriceResult(price=price, currency=rec.currency, qty=self.qty,
                                   distributor=rec.distributor, sku=offer.sku,
                                   fetched_at=rec.fetched_at)
        for k, v in saw.items():  # record-level: counted on hits and misses alike
            self._skipped[k] += v
        if best is not None:
            self._n['hit'] += 1
            self._n_dist[best.distributor] = self._n_dist.get(best.distributor, 0) + 1
        else:
            # query outcome: the most specific reason seen; miss only if no record
            # of this part was considered at all
            for k in ('under_ladder', 'negative', 'stale', 'other_currency'):
                if saw[k]:
                    self._n[k] += 1
                    break
            else:
                self._n['miss'] += 1
        return best

    def stats(self) -> str:
        n = self._n
        total = sum(n.values())
        dist = ', '.join('%s %d' % kv for kv in sorted(self._n_dist.items()))
        s = ('prices@%d: %d/%d parts priced (%s; no-record %d, negative %d, '
             'stale %d, other-currency %d, under-ladder %d)' % (
                 self.qty, n['hit'], total, dist or 'none', n['miss'], n['negative'],
                 n['stale'], n['other_currency'], n['under_ladder']))
        skipped = {k: v for k, v in self._skipped.items() if v}
        if skipped:
            s += '; records skipped: ' + ', '.join(
                '%s %d' % kv for kv in sorted(skipped.items()))
        return s


def fetch_prices_for_parts(parts: List[Tuple[str, str]], currency: str = 'USD',
                           max_age='7d') -> Dict[str, dict]:
    """Fetch-phase orchestrator for the ranked candidates.

    LCSC brand-catalog harvest first (async, own browser lifecycle), then the DigiKey
    per-MPN loop (sync; fail-fast setup validation inside). Each phase reports a
    summary; a phase failure is loud but does not zero out the other phase's writes.
    """
    import asyncio
    summaries = {}

    from dslib.prices.lcsc import harvest_lcsc_prices

    async def _lcsc_phase():
        # this asyncio.run phase owns its browser: it must not leak a context keyed to
        # this (about-to-die) event loop into a later phase (dslib/fetch.py:152 asserts)
        from dslib.fetch import close_browser
        try:
            return await harvest_lcsc_prices(max_age=max_age)
        finally:
            await close_browser()

    try:
        summaries['lcsc'] = asyncio.run(_lcsc_phase())
    except Exception as e:
        print('LCSC price harvest FAILED (continuing with DigiKey):', e)
        summaries['lcsc'] = {'error': str(e)}

    from dslib.prices.digikey_api import fetch_digikey_prices
    try:
        summaries['digikey'] = fetch_digikey_prices(parts, currency=currency,
                                                    max_age=max_age)
    except Exception as e:
        # loud but non-fatal: a dead DigiKey phase (quota exhausted, creds, OAuth) must
        # not cost the run its CSVs -- columns still fill from the store's records
        print('DigiKey price fetch FAILED (columns fill from existing records):', e)
        summaries['digikey'] = {'error': str(e)}

    for phase, s in summaries.items():
        print('price fetch [%s]: %s' % (phase, s))
    return summaries
