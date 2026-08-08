"""Distributor price records for parts (DigiKey API + LCSC catalog harvest).

Store: `prices_db` -- one `PartOffers` record per (mfr, mpn, distributor, currency),
`data/prices-lib.sqlite3`. Latest snapshot only (docs/Parts Prices.md's date index is
realized by `fetched_at` inside the record, not by exploding rows); price HISTORY is
the append-only side table in dslib/prices/history.py (`data/prices-history.sqlite3`),
written by both fetchers after every store write and healed on fresh-skip.

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


def norm_mpn(mpn: str) -> str:
    """Join-key normalization: casefold + strip ALL whitespace. Suppliers and
    discovery disagree on both -- LCSC lists 'BSC070N10NS3G' where Infineon
    discovery has 'BSC070N10NS3 G', and 'aot412' vs 'AOT412' (48 uniquely-mapping
    live keys never filled a CSV row before this). Store keys keep the RAW MPN;
    only lookups, freshness gates and match tiers normalize."""
    return ''.join(mpn.split()).casefold()


# Infineon ordering codes: the trailing block is a PACKING code ([A]mmo-pack/tube vs
# [X]=tape&reel, then a package/pack-size letter, then SA1/MA1/TA1/UA1...) -- the die
# is identical across the family. Discovery consolidates them (discover_parts
# normal_mpn strips these), so the ranked spelling is whichever code discovery saw
# first, while the distributor may only stock a SIBLING (IPP023N10N5AKSA1 with 0
# stock vs IPP023N10N5XKSA1 in stock).
#
# On the review concern that suffixed siblings sometimes show DIFFERENT Vds in
# parts_db (IPZ60R017C7 650V vs ...XKSA1 600V): CoolMOS datasheets rate V(BR)DSS at
# both 25C (600V) and 150C (650V) for the SAME part, and the two spellings' specs
# come from different scrape sources reading different rows -- a parsing/source
# artifact, not a voltage bin. Infineon's OPN docs define this block as packing.
#
# The leading letter is [axf], not [ax]: FKSA1 is a live code (IPW60R045CPFKSA1,
# IPW60R045CPAFKSA1 and 3 more), and while it was missing those parts consolidated
# with nothing and shipped as their own ranked CSV rows next to the bare spelling.
_INFINEON_PACKING = __import__('re').compile(r'(.{6,}?)[axf][ktu][sm]a\d$')


def family_mpn(mfr: str, mpn: str) -> str:
    """Consolidation key: norm_mpn plus manufacturer-scoped ordering-suffix stripping
    (currently Infineon packing codes only). Used to JOIN and QUERY across ordering
    siblings; store keys and record MPNs stay raw."""
    m = norm_mpn(mpn)
    if mfr == 'infineon':
        match = _INFINEON_PACKING.fullmatch(m)
        if match:
            return match.group(1)
    return m


# Reviewed distributor/vendor packing suffixes. Lives here (not in digikey_api) because
# BOTH the DigiKey match tiers and discovery's duplicate consolidation need it, and
# importing digikey_api pulls the optional DigiKey SDK.
#
# Deliberately NOT a pattern: every entry is a suffix somebody looked at. Generic
# letter/digit/separator continuations (X1 -> X10, X1 -> X1A, X1 -> X1-A) are DIFFERENT
# parts -- IRFB4110 vs IRFB4110G is a real example of a one-letter continuation that is
# a distinct orderable with its own datasheet.
#
# '-7' and '-13' were removed 2026-08-08. They are reel diameters for Diodes/Zetex,
# which is why they were listed, but for IXYS the same suffix is the LEAD COUNT:
# IXTA150N15X4 is TO-263-3 (2 leads + tab) and IXTA150N15X4-7 is TO-263-7 (6 leads
# + tab), a Kelvin-source package with its own parasitics. All 8 corpus pairs
# ending in '-7' are that IXYS case and none is a Diodes reel, so the entries only
# ever collapsed two real orderables into one ranked row and let DigiKey price one
# package off the other's listing. Re-add only per-manufacturer.
PACKAGING_SUFFIXES = (
    't1g', 't3g', 't1', 't3', 'tr', 'tl', 'tf', 'ct', 'trpbf', 'pbf',
    '-t1-ge3', '-t1-re3', '-e3', '-ge3', '-t1', '-t3', '-tr', '-tl',
    ',118', ',127', ',135',
)


def suffix_extends_mpn(candidate: str, mpn: str) -> bool:
    """True when `candidate` is `mpn` plus one COMPLETE reviewed packaging suffix
    (NTMFS5C628NL -> NTMFS5C628NLT1G, SUP70042E -> SUP70042E-GE3). Everything else --
    digit continuations, letter continuations, unknown separator-led continuations --
    is treated as a DIFFERENT part. Equality is False (do the exact lookup first)."""
    c, m = norm_mpn(candidate), norm_mpn(mpn)
    return c.startswith(m) and c[len(m):] in PACKAGING_SUFFIXES


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
        # audit trail: catalog MPN(s) that actually priced this part when a match
        # tier beyond exact equality was used (suffixed/base-number matches). Old
        # pickled records may lack the attribute -- read with getattr.
        self.matched_mpns = None
        # the currency the QUERY asked for (DigiKey may substitute the actual one,
        # which is the key/label): the freshness gate must match on this, or a
        # substituted response re-spends quota every run inside max_age. Old pickled
        # records lack it -- read with getattr, fall back to `currency`.
        self.requested_currency = None

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

    def total_stock(self) -> Optional[int]:
        """Sum of offer stocks (DigiKey: per packaging variation; LCSC: per SKU).
        None -- not 0 -- when no offer reports stock: unknown is not empty."""
        stocks = [o.stock for o in self.offers if o.stock is not None]
        return sum(stocks) if stocks else None

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
    foreign-currency record was ALSO skipped for the same part), and get() is
    MEMOIZED per (mfr, mpn) so both families count DISTINCT PARTS -- repeated
    lookups (the staged-HS loop is O(n^2)) are dict hits and tick nothing:
    - query outcomes: each distinct part is exactly one of hit / no-record / one
      most-specific no-price reason;
    - record-level skips: every record excluded from a distinct part's evaluation,
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
            # family key: ordering siblings (Infineon AKSA1/XKSA1/... packing codes)
            # consolidate, matching discovery's normal_mpn consolidation -- a ranked
            # AKSA1 row must surface the stocked XKSA1 sibling's offers
            self._by_part.setdefault((rec.mfr, family_mpn(rec.mfr, rec.mpn)),
                                     []).append(rec)
        self._n = dict(hit=0, miss=0, negative=0, stale=0, other_currency=0,
                       under_ladder=0)
        self._skipped = dict(negative=0, stale=0, other_currency=0, under_ladder=0)
        self._n_dist: Dict[str, int] = {}
        self._memo: Dict[Tuple[str, str], Optional[PriceResult]] = {}

    def get(self, mfr: str, mpn: str) -> Optional[PriceResult]:
        # memoized per DISTINCT part: stats() reports PART fill-rate, and callers like
        # the staged-HS loop query the same device O(n^2) times -- per-call counting
        # inflated 'parts priced' combinatorially (final review pass)
        if (mfr, mpn) in self._memo:
            return self._memo[(mfr, mpn)]
        result = self._get_uncounted(mfr, mpn)
        self._memo[(mfr, mpn)] = result
        return result

    def _get_uncounted(self, mfr: str, mpn: str) -> Optional[PriceResult]:
        recs = self._by_part.get((mfr, family_mpn(mfr, mpn)))
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

    def stocks(self, mfr: str, mpn: str) -> Dict[str, int]:
        """{distributor: total stock} from the same records get() would consider
        (currency match, fresh, status ok). Informational -- stock never gates a
        price. Distributors with no stock report are absent, never 0."""
        out: Dict[str, int] = {}
        seen = set()  # (distributor, sku): family-sibling RECORDS built from the same
        #               family search hold the SAME SKUs (live: byte-identical offer
        #               lists under AKSA1 and XKSA1 keys) -- summing per record would
        #               double/triple-count that stock. Dedupe across the family.
        for rec in self._by_part.get((mfr, family_mpn(mfr, mpn)), ()):
            if rec.currency != self.currency or rec.status != 'ok' \
                    or rec.age(self._now) > self.max_age:
                continue
            for o in rec.offers:
                if o.stock is None:
                    continue
                k = (rec.distributor, o.sku)
                if o.sku and k in seen:
                    continue
                seen.add(k)
                out[rec.distributor] = out.get(rec.distributor, 0) + o.stock
        return out

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


def run_lcsc_harvest(max_age='7d') -> dict:
    """The LCSC brand-catalog phase alone, with per-phase browser ownership. Cheap
    (raw lists are disk-cached 7d) and corpus-wide -- main.py runs it BEFORE the CSV
    generators so LCSC prices exist for every row, while the quota-bound DigiKey
    fetch afterwards targets only the top of the fresh ranking."""
    import asyncio

    async def _phase():
        from dslib.fetch import close_browser
        try:
            return await __import__('dslib.prices.lcsc', fromlist=['harvest_lcsc_prices']
                                    ).harvest_lcsc_prices(max_age=max_age)
        finally:
            await close_browser()

    return asyncio.run(_phase())


def interleave_top(rankings: List[List[Tuple[str, str]]], n: int) -> List[Tuple[str, str]]:
    """The n best DISTINCT parts drawn round-robin from several rankings (HS and LS
    lists rank different loss mechanisms -- pure best-of-one would starve the other).
    Order within the result follows rank, so a quota-limited fetch prices the most
    interesting parts first. n <= 0 means UNCAPPED (the priceTopN=0 contract lives
    here, not in a caller-side idiom that a direct call would miss)."""
    if n <= 0:
        n = sum(len(r) for r in rankings)
    out, seen = [], set()
    i = 0
    while len(out) < n and any(i < len(r) for r in rankings):
        for r in rankings:
            if i < len(r) and len(out) < n:
                p = r[i]
                if p not in seen:
                    seen.add(p)
                    out.append(p)
        i += 1
    return out


# NOTE deliberately no fetch_prices_for_parts(parts) convenience orchestrator here:
# the old one fetched DigiKey for an ARBITRARY candidate list in caller order, which
# is exactly the quota misuse the top-priceTopN flow in main.py replaced. Compose
# run_lcsc_harvest() + interleave_top(rankings, n) + digikey_api.fetch_digikey_prices
# instead, so the ranking decides where quota goes.
