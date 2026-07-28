"""DigiKey v4 API price fetcher (per-MPN keyword search over the ranked candidates).

Replaces the abandoned dslib/pricing.py. Credentials come from the environment
(DIGIKEY_CLIENT_ID / DIGIKEY_CLIENT_SECRET) and/or the gitignored env-style files
data/.digikey-api, data/.digikey-api2, ... -- ONE KEY PER FILE. DigiKey limits are per
app (client id): 120 req/min burst and 1,000 req/day each
(developer.digikey.com/documentation#rate-limits), so every extra key adds its own
budget; jobs are spread across all live keys, each behind its own rate limiter. Each
key has its own OAuth token store (dslib/dk-cache, dk-cache2, ...) -- the FIRST use of
a new key opens a browser for the OAuth authorization-code flow.

The generated ProductSearchApi is called directly (not via digikey.keyword_search):
the SDK wrapper swallows ApiException AND drops the response headers, which is why the
X-RateLimit-Remaining tracking never armed through it. Direct calls give us status,
headers and exceptions first-hand.

No disk_cache here on purpose: prices_db (skip records younger than max_age) is the
single freshness authority -- a second cache layer with its own ttl would silently
override it.

Guard semantics (shared with dslib/prices): fetch errors write NOTHING; a key that
returns 2 consecutive post-backoff 429s is dead for the run (daily quota, resets
00:00 UTC) and its jobs move to the surviving keys; when every key is dead the
remaining parts are counted quota_stop and stay un-fetched for the next run.
"""

import datetime
import glob
import os
import queue
import threading
import time
from typing import Dict, List, Optional, Tuple

from dslib import mfr_tag
from dslib.prices import DIGIKEY, Offer, PartOffers, prices_db, utc_now

CREDS_GLOB = os.path.realpath(os.path.join(os.path.dirname(__file__),
                                           '..', '..', 'data')) + '/.digikey-api*'
_STORAGE_BASE = os.path.realpath(os.path.join(os.path.dirname(__file__), '..'))

_env_lock = threading.Lock()  # serializes client construction: the interactive OAuth
#                               flow binds the localhost callback port (creds are
#                               passed to TokenHandler directly, NOT via env)


class DkAuthFailed(RuntimeError):
    """A 401 that survived one client rebuild: this key's auth is broken for the run.
    The worker must retire the key GLOBALLY and re-queue the job -- booking the job as
    an error would let one bad key drain the whole queue as errors while a healthy
    key sits idle."""

    def __init__(self, mpn, client_id):
        super().__init__('digikey auth failed (401 after client rebuild) for %r on '
                         'key %s...' % (mpn, client_id[:6]))


class DkRateLimited(RuntimeError):
    """A 429 that survived the burst backoff -- almost certainly the key's 1,000/day
    quota (resets 00:00 UTC). Retrying on THIS key is pointless until then."""

    def __init__(self, mpn, client_id):
        super().__init__('digikey rate limited (429) for %r on key %s... -- likely the '
                         'DAILY quota, resets 00:00 UTC' % (mpn, client_id[:6]))


class _Key:
    def __init__(self, client_id: str, secret: str, storage: str, label: str):
        self.client_id = client_id
        self.secret = secret
        self.storage = storage
        self.label = label
        self.client = None          # {'api', 'auth'} once built
        self.client_batch = None    # BatchSearchApi variant, built alongside
        self.dead = False
        self.consecutive_429 = 0
        self.remaining = None       # last seen X-RateLimit-Remaining (daily)
        self.limiter_lock = threading.Lock()
        self.next_slot = 0.0


def _read_creds_file(path: str) -> Dict[str, str]:
    creds = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                creds[k.strip()] = v.strip()
    return creds


def discover_keys() -> List[_Key]:
    """One _Key per creds source: the env pair (if set) plus every data/.digikey-api*
    file. Token stores are strictly per client id: .digikey-api -> dslib/dk-cache,
    .digikey-api2 -> dslib/dk-cache2, ..., env -> dslib/dk-cache-env. The env key must
    NOT share dk-cache with the base file: the SDK stores one unscoped
    token_storage.json per directory, so two different apps on one directory would
    read/overwrite each other's OAuth tokens. (Same client id in env and file still
    dedupes to one key below.)"""
    keys, seen = [], set()
    if os.environ.get('DIGIKEY_CLIENT_ID') and os.environ.get('DIGIKEY_CLIENT_SECRET'):
        cid = os.environ['DIGIKEY_CLIENT_ID']
        seen.add(cid)
        keys.append(_Key(cid, os.environ['DIGIKEY_CLIENT_SECRET'],
                         _STORAGE_BASE + '/dk-cache-env', 'env'))
    for path in sorted(glob.glob(CREDS_GLOB)):
        creds = _read_creds_file(path)
        cid = creds.get('CLIENT_ID')
        if not (cid and creds.get('CLIENT_SECRET')):
            print('digikey: %s lacks CLIENT_ID/CLIENT_SECRET, skipping' % path)
            continue
        if cid in seen:
            continue
        seen.add(cid)
        suffix = os.path.basename(path)[len('.digikey-api'):]  # '' | '2' | '3' ...
        keys.append(_Key(cid, creds['CLIENT_SECRET'],
                         _STORAGE_BASE + '/dk-cache' + suffix, os.path.basename(path)))
    if not keys:
        raise RuntimeError(
            'DigiKey API credentials missing: set DIGIKEY_CLIENT_ID/DIGIKEY_CLIENT_SECRET '
            'or create data/.digikey-api with CLIENT_ID=... / CLIENT_SECRET=... lines '
            '(create an app with the Product Information V4 scope at '
            'developer.digikey.com).')
    return keys


def _build_client(key: _Key) -> None:
    """(Re)build the per-key API client. Creds/storage are passed DIRECTLY to
    TokenHandler (no env mutation); construction is still serialized via _env_lock
    because a key's first ever use runs the interactive OAuth flow (browser), which
    binds the localhost callback port. A 401 later (access token expired, ~30 min)
    re-enters here."""
    import digikey.oauth.oauth2
    import digikey.v4.productinformation as dpi
    import digikey.v4.batchproductdetails as dbp
    with _env_lock:  # still serialized: enrolling two keys at once would collide on
        #              the OAuth callback port (localhost:8139)
        os.makedirs(key.storage, exist_ok=True)  # TokenHandler rejects a missing dir
        # creds/storage passed DIRECTLY -- mutating os.environ here left the process
        # env pointing at the LAST key, which made a later discover_keys() misclassify
        # that key as the env key and collide two apps on one token store
        token = digikey.oauth.oauth2.TokenHandler(
            a_id=key.client_id, a_secret=key.secret,
            a_token_storage_path=key.storage,
            version=3, sandbox=False).get_access_token()
        auth = token.get_authorization()
        cfg = dpi.Configuration()
        cfg.api_key['X-DIGIKEY-Client-Id'] = key.client_id
        cfg.host = 'https://api.digikey.com/products/v4'
        cfg.access_token = token.access_token
        key.client = {'api': dpi.ProductSearchApi(dpi.ApiClient(cfg)), 'auth': auth}
        bcfg = dbp.Configuration()
        bcfg.api_key['X-DIGIKEY-Client-Id'] = key.client_id
        # do NOT override bcfg.host: the fork's digikey.v4.batchproductdetails is an
        # alias of the v3 classes and its Configuration correctly defaults to
        # .../BatchSearch/v3 -- forcing /v4 manufactured a permanent 404 that was
        # indistinguishable from "endpoint not enabled on this app"
        bcfg.access_token = token.access_token
        key.client_batch = {'api': dbp.BatchSearchApi(dbp.ApiClient(bcfg)), 'auth': auth}


def _dk_keyword_search_raw(mpn: str, currency: str = 'USD',
                           key: Optional[_Key] = None) -> dict:
    """One keyword search on one key, returned as a plain dict envelope with the ORIGIN
    timestamp and the key's remaining DAILY quota (X-RateLimit-Remaining). Raises
    DkRateLimited after a failed burst backoff; plain exceptions for everything else.
    Never returns an error disguised as an empty result."""
    from digikey.v4.productinformation import KeywordRequest
    from digikey.v4.productinformation.rest import ApiException

    if key is None:
        key = discover_keys()[0]
    if key.client is None:
        _build_client(key)

    retried_auth = retried_burst = False
    while True:
        try:
            data, status, headers = key.client['api'].keyword_search_with_http_info(
                key.client_id, body=KeywordRequest(keywords=mpn, limit=10),
                authorization=key.client['auth'],
                x_digikey_locale_site='US', x_digikey_locale_language='en',
                x_digikey_locale_currency=currency)
        except ApiException as e:
            if e.status == 401:
                if not retried_auth:
                    retried_auth = True   # access token expired mid-run: rebuild, retry
                    try:
                        _build_client(key)
                    except Exception as be:
                        # a FAILING rebuild (refresh/OAuth/network) is itself proof the
                        # key is broken for this run -- surfacing it generically would
                        # book the JOB as an error and leave the bad key draining the
                        # queue (round-5 follow-up)
                        raise DkAuthFailed(mpn, key.client_id) from be
                    continue
                raise DkAuthFailed(mpn, key.client_id) from e
            if e.status == 429 and not retried_burst:
                retried_burst = True  # maybe just the 120/min burst: one 10s backoff
                time.sleep(10)
                continue
            if e.status == 429:
                raise DkRateLimited(mpn, key.client_id) from e
            raise
        rem = (headers or {}).get('X-RateLimit-Remaining')
        try:
            key.remaining = int(rem) if rem is not None else key.remaining
        except ValueError:
            pass
        return {'fetched_at': utc_now().isoformat(), 'response': data.to_dict(),
                'rate_limit_remaining': key.remaining}


class IndeterminateMatch(RuntimeError):
    """The response had candidate products but every one was rejected (manufacturer
    mismatch / missing manufacturer). That is NOT evidence the part is absent from the
    catalog -- writing catalog_miss here would persist a false negative for max_age
    days. Raised so the caller books an error and writes NOTHING."""


# Reviewed, COMPLETE packaging/carrier suffixes only -- no generic rules. A generic
# "any non-digit" rule admitted X1A, and a "separator-led" branch admitted X1-A; both
# letter and separator continuations can be distinct electrical/qualification
# variants, and a wrong-part price in the ranking is worse than a missing one.
# T1G/T3G/T1/T3 = onsemi tape&reel; TR/TL/TF/CT = DigiKey carrier codes; TRPBF =
# Infineon/IR tape&reel lead-free; -T1-GE3/-T1-RE3/-E3/-GE3 = Vishay carrier/lead
# codes; -7/-13 = Diodes Inc 7"/13" reels; ,118/,127/,135 = Nexperia reel codes.
# Extend deliberately, with a test; parts whose only listing falls outside this list
# stay unpriced (indeterminate/catalog_miss) rather than risk a wrong attachment.
PACKAGING_SUFFIXES = (
    't1g', 't3g', 't1', 't3', 'tr', 'tl', 'tf', 'ct', 'trpbf',
    '-t1-ge3', '-t1-re3', '-e3', '-ge3', '-t1', '-t3', '-tr', '-tl',
    '-7', '-13', ',118', ',127', ',135',
)


def _suffix_extends_mpn(candidate: str, mpn: str) -> bool:
    """True when candidate is mpn plus one COMPLETE reviewed packaging suffix
    (NTMFS5C628NL -> NTMFS5C628NLT1G). Everything else -- digit continuations
    (X1 -> X10), letter continuations (X1 -> X1A), unknown separator-led
    continuations (X1 -> X1-A) -- is treated as a DIFFERENT part."""
    from dslib.prices import norm_mpn
    c, m = norm_mpn(candidate), norm_mpn(mpn)
    return c.startswith(m) and c[len(m):] in PACKAGING_SUFFIXES


def _iter_products(raw_response: dict, mfr: str, mpn: str):
    """Match tiers: exact_matches; MPN equality; DigiKey's own base_product_number
    equality; packaging-suffix extension (non-digit continuation only). Products whose
    manufacturer is missing or maps to a different mfr_tag are skipped with a warning
    -- if that rejects EVERY candidate, IndeterminateMatch is raised (see above);
    catalog_miss is reserved for a response with no candidate at all."""
    from dslib.prices import norm_mpn
    hits = raw_response.get('products') or []
    m = norm_mpn(mpn)  # whitespace/case-insensitive: ranked 'BSC070N10NS3 G' must
    #                    match catalog 'BSC070N10NS3G' (join/fill-rate review finding)
    products = (raw_response.get('exact_matches')
                or [p for p in hits
                    if norm_mpn(p.get('manufacturer_product_number') or '') == m]
                or [p for p in hits
                    if norm_mpn(((p.get('base_product_number') or {}).get('name')) or '') == m]
                or [p for p in hits
                    if _suffix_extends_mpn(p.get('manufacturer_product_number') or '', mpn)])
    accepted = 0
    for p in products:
        p_mfr_name = ((p.get('manufacturer') or {}).get('name')) or ''
        if not p_mfr_name:
            print('digikey %s: product %r lacks a manufacturer name, skipping'
                  % (mpn, p.get('manufacturer_product_number')))
            continue
        if mfr_tag(p_mfr_name) != mfr:
            print('digikey %s: manufacturer mismatch (%r -> %s != %s), skipping product'
                  % (mpn, p_mfr_name, mfr_tag(p_mfr_name), mfr))
            continue
        p_mpn = p.get('manufacturer_product_number')
        if p_mpn and p_mpn.lower() != mpn.lower():
            print('digikey %s: matched via %s' % (mpn, p_mpn))
        accepted += 1
        yield p
    if products and not accepted:
        raise IndeterminateMatch(
            'digikey %s: %d candidate product(s), all rejected by manufacturer checks '
            '-- indeterminate, writing nothing' % (mpn, len(products)))


def parse_digikey_offers(mfr: str, mpn: str, raw: dict,
                         requested_currency: str = 'USD') -> PartOffers:
    """Pure response->record transform (unit-testable, no I/O).

    Skips marketplace variations and Digi-Reel packaging (its reel fee is not in
    unit_price and would flatter the row). The record currency is what the API says it
    used (search_locale_used.currency) -- DigiKey may substitute the requested one.

    RAISES IndeterminateMatch when candidates existed but ALL were rejected by the
    manufacturer checks: the caller must then write NOTHING, because a catalog_miss
    there would persist a false "no such part" for max_age days.
    """
    resp = raw['response']
    fetched_at = datetime.datetime.fromisoformat(raw['fetched_at'])

    currency = ((resp.get('search_locale_used') or {}).get('currency')) or requested_currency
    if currency != requested_currency:
        print('digikey %s: requested currency %s but API used %s'
              % (mpn, requested_currency, currency))

    offers: List[Offer] = []
    url = None
    found_product = False
    matched_mpns = []
    for p in _iter_products(resp, mfr, mpn):
        found_product = True
        url = url or p.get('product_url')
        matched_mpns.append(p.get('manufacturer_product_number') or '')
        variations = p.get('product_variations')
        if variations is None:
            # a matched product without the variations field is a SCHEMA anomaly, not
            # an empty offer set -- writing no_eligible_offer here would turn a
            # response-shape change into a durable negative. Errors write nothing.
            raise ValueError('digikey %s: product %r lacks product_variations'
                             % (mpn, p.get('manufacturer_product_number')))
        for pv in variations:
            if pv.get('market_place'):
                continue
            # v4 PackageType is an object {'id', 'name'}, not a string
            pkg = (pv.get('package_type') or {}).get('name') or ''
            if 'digi-reel' in pkg.lower():
                continue
            pricing = pv.get('standard_pricing')
            if pricing is None:
                raise ValueError('digikey %s: variation %r lacks standard_pricing'
                                 % (mpn, pv.get('digi_key_product_number')))
            # all-or-error: ANY malformed entry (renamed/nulled fields) raises -- a
            # durable negative or a partially-persisted ladder would both misprice
            ladder = _parse_ladder(pricing, 'digikey %s variation %r'
                                   % (mpn, pv.get('digi_key_product_number')))
            if not ladder:  # explicitly empty pricing = a real, empty offer
                continue
            offers.append(Offer(
                sku=pv.get('digi_key_product_number') or '',
                packaging=pkg or None,
                ladder=ladder,
                moq=pv.get('minimum_order_quantity'),
                stock=pv.get('quantity_availablefor_package_type'),
            ))

    if offers:
        status = 'ok'
    elif found_product:
        status = 'no_eligible_offer'
    else:
        status = 'catalog_miss'
    rec = PartOffers(mfr=mfr, mpn=mpn, distributor=DIGIKEY, currency=currency,
                     offers=offers, fetched_at=fetched_at, url=url, status=status)
    # audit trail for the match tiers: which catalog MPN(s) actually priced this part
    rec.matched_mpns = [m for m in matched_mpns if m.lower() != mpn.lower()] or None
    rec.requested_currency = requested_currency  # freshness gate matches on THIS
    return rec


def _parse_ladder(pricing: list, ctx: str) -> List[Tuple[int, float]]:
    """ALL-OR-ERROR ladder parse: a pricing array mixing valid and malformed entries
    raises instead of silently persisting the valid subset -- a partially-parsed
    ladder is worse than none (a dropped 10-break makes price_at(100) read the
    1-break price, silently overstating cost; a dropped 100-break understates it).
    An explicitly empty array returns [] (a real, empty offer)."""
    ladder, bad = [], 0
    for pb in pricing:
        bq, up = pb.get('break_quantity'), pb.get('unit_price')
        if isinstance(bq, (int, float)) and bq >= 1 \
                and isinstance(up, (int, float)) and up > 0:
            ladder.append((int(bq), float(up)))
        else:
            bad += 1
    if bad:
        raise ValueError('%s: %d/%d pricing entries malformed' % (ctx, bad, len(pricing)))
    return ladder


def _pidvid_name(v) -> str:
    """Batch models wrap names as PidVid-ish dicts ({'value': ...} or {'name': ...})."""
    if isinstance(v, dict):
        return v.get('name') or v.get('value') or ''
    return v or ''


def _dk_batch_details_raw(mpns: List[str], currency: str, key: _Key) -> dict:
    """One BatchProductDetails call (<=50 MPNs, ONE request against the daily quota).
    Raises ApiException straight through -- the caller decides whether a 403/404 means
    'endpoint not enabled on this app' (fall back to keyword search) and a 429 means
    quota. Same envelope contract as the keyword path."""
    from digikey.v4.batchproductdetails import BatchProductDetailsRequest
    assert len(mpns) <= 50
    if key.client_batch is None:
        _build_client(key)
    data, status, headers = key.client_batch['api'].batch_product_details_with_http_info(
        key.client_batch['auth'], key.client_id,
        body=BatchProductDetailsRequest(products=list(mpns)),
        x_digikey_locale_site='US', x_digikey_locale_language='en',
        x_digikey_locale_currency=currency)
    rem = (headers or {}).get('X-RateLimit-Remaining')
    try:
        key.remaining = int(rem) if rem is not None else key.remaining
    except ValueError:
        pass
    d = data.to_dict()
    return {'fetched_at': utc_now().isoformat(),
            'details': d.get('product_details') or [],
            'errors': d.get('errors') or [],
            'rate_limit_remaining': key.remaining}


def parse_digikey_batch(mfr: str, mpn: str, raw: dict,
                        requested_currency: str = 'USD') -> Optional[PartOffers]:
    """Offers for ONE queried (mfr, mpn) from a batch envelope. Pure, unit-testable.

    Batch details are FLAT (one entry per DigiKey SKU, no variations array). Match
    tiers mirror the keyword path minus base_product_number (absent here): MPN
    equality, then reviewed-packaging-suffix extension; manufacturer must match. Returns None
    when nothing matches -- the batch phase NEVER writes negative records (its error
    list does not name the failing MPN reliably), unmatched parts fall through to the
    keyword path which owns catalog_miss semantics."""
    from dslib.prices import norm_mpn
    details = raw['details']
    m = norm_mpn(mpn)
    matched = ([d for d in details
                if norm_mpn(d.get('manufacturer_part_number') or '') == m]
               or [d for d in details
                   if _suffix_extends_mpn(d.get('manufacturer_part_number') or '', mpn)])
    offers: List[Offer] = []
    url = None
    currency = requested_currency
    matched_mpns = []
    for d in matched:
        d_mfr = _pidvid_name(d.get('manufacturer'))
        if not d_mfr or mfr_tag(d_mfr) != mfr:
            continue
        if d.get('supplier_direct_ship'):  # marketplace analog: not DigiKey stock
            continue
        pkg = _pidvid_name(d.get('packaging'))
        if 'digi-reel' in pkg.lower():
            continue
        pricing = d.get('standard_pricing')
        if pricing is None:
            # missing/None pricing on an accepted detail is a SCHEMA anomaly, same as
            # the keyword parser -- and one anomalous sibling must fail the WHOLE part
            # (returning the good subset would persist a partial offer set, possibly
            # omitting the cheapest variation, and the fresh record would then block
            # the keyword fallback for max_age days)
            print('digikey batch %s: detail %r lacks standard_pricing -- part falls '
                  'back to keyword search' % (mpn, d.get('digi_key_part_number')))
            return None
        try:
            ladder = _parse_ladder(pricing, 'digikey batch %s detail %r'
                                   % (mpn, d.get('digi_key_part_number')))
        except ValueError as e:
            print('%s -- part falls back to keyword search' % e)
            return None
        if not ladder:
            continue
        # search_locale_used is PER DETAIL: the record's currency is locked by the
        # first accepted priced detail, and any later detail in a different currency
        # is skipped -- overwriting the currency while accumulating ladders labeled a
        # USD price as EUR (no-currency-mixing invariant, final review pass)
        d_currency = ((d.get('search_locale_used') or {}).get('currency')) or requested_currency
        if not offers:
            currency = d_currency
        elif d_currency != currency:
            print('digikey batch %s: detail %r is %s but record is %s, skipping '
                  '(one currency per record)'
                  % (mpn, d.get('digi_key_part_number'), d_currency, currency))
            continue
        url = url or d.get('product_url')
        matched_mpns.append(d.get('manufacturer_part_number') or '')
        offers.append(Offer(
            sku=d.get('digi_key_part_number') or '',
            packaging=pkg or None,
            ladder=ladder,
            moq=d.get('minimum_order_quantity'),
            stock=d.get('quantity_available'),
        ))
    if not offers:
        return None
    rec = PartOffers(mfr=mfr, mpn=mpn, distributor=DIGIKEY, currency=currency,
                     offers=offers,
                     fetched_at=datetime.datetime.fromisoformat(raw['fetched_at']),
                     url=url, status='ok')
    # same audit contract as the keyword parser: which catalog MPN(s) priced this part
    rec.matched_mpns = [m for m in matched_mpns if m.lower() != mpn.lower()] or None
    rec.requested_currency = requested_currency
    return rec


def _batch_phase(todo: List[Tuple[str, str]], keys: List[_Key], currency: str,
                 n: Dict[str, int], quota_floor: int) -> List[Tuple[str, str]]:
    """Price as much of `todo` as possible via BatchProductDetails (50 MPNs = ONE
    request against the daily quota, ~60 requests for the full fugu3 corpus) and
    return the leftovers for the keyword path.

    Endpoint enablement is PER APP: a 403/404 retires that key from the batch set only
    (it stays alive for keyword work) and the next key is probed; global fallback
    happens only after every key rejected the endpoint. This phase never touches
    n['quota_stop'] -- every part it could not price (unmatched, or un-attempted after
    keys died) is RETURNED, and the keyword phase owns the final accounting (it
    quota-stops them if no key survives). Only 'ok' records are ever written here (the
    batch error list does not name failing MPNs reliably); unmatched parts fall
    through to the keyword path's catalog_miss/indeterminate semantics.

    NOTE errors are matched by SHAPE (getattr status), not by exception class: every
    generated SDK sub-package has its own rest.ApiException, and the fork's v4 batch
    package actually raises digikey.v3.batchproductdetails.rest.ApiException -- an
    isinstance check against the v4 productinformation class silently misses it."""
    from dslib.prices import prices_db as _db
    from dslib.prices.history import record_history

    batch_keys = [k for k in keys if not k.dead]  # batch-capable until proven otherwise
    leftovers: List[Tuple[str, str]] = []
    priced = 0
    auth_retried = set()  # key labels that already got one 401 client rebuild
    chunks = [todo[i:i + 50] for i in range(0, len(todo), 50)]
    for ci, chunk in enumerate(chunks):
        raw = None
        while batch_keys and raw is None:
            key = batch_keys[0]
            if key.dead:
                batch_keys.pop(0)
                continue
            if key.remaining is not None and key.remaining < quota_floor:
                print('digikey batch: key %s below quota floor, retiring' % key.label)
                key.dead = True
                batch_keys.pop(0)
                continue
            try:
                raw = _dk_batch_details_raw([mpn for _, mpn in chunk], currency, key)
            except Exception as e:
                status = getattr(e, 'status', None)
                body = str(getattr(e, 'body', '') or '')
                if status == 401 and 'subscribe' in body.lower():
                    # the OBSERVED live not-enabled signal at /BatchSearch/v3:
                    # 401 'You are not subscribed to this API' -- key stays alive
                    # for keyword work
                    print('digikey batch: key %s not subscribed to BatchSearch, '
                          'trying next key' % key.label)
                    batch_keys.pop(0)
                    continue
                if status == 401 and key.label not in auth_retried:
                    auth_retried.add(key.label)  # token expiry: one rebuild, retry
                    try:
                        _build_client(key)
                    except Exception as be:
                        # rebuild failure = broken auth: retire GLOBALLY (keyword
                        # would only re-prove it) instead of aborting the phase
                        print('digikey batch: key %s client rebuild failed, retiring: '
                              '%s' % (key.label, be))
                        key.dead = True
                        batch_keys.pop(0)
                    continue
                if status in (401, 403, 404):
                    # 403/404 = endpoint absent/forbidden for this app; second 401 =
                    # auth beyond repair here -- either way batch-incapable only
                    print('digikey batch: endpoint not usable on key %s (HTTP %s), '
                          'trying next key' % (key.label, status))
                    batch_keys.pop(0)
                    continue
                if status == 429:
                    print('digikey batch: key %s rate limited (daily quota), retiring'
                          % key.label)
                    key.dead = True
                    batch_keys.pop(0)
                    continue
                # anything unexpected (5xx, network, SDK decode): batch is an
                # OPTIONAL optimization and must fail OPEN -- retire the key from
                # the batch set only (keyword-alive) and let the raw-is-None branch
                # hand everything to the keyword path; re-raising here aborted the
                # whole DigiKey fetch over a batch-only hiccup
                print('digikey batch: unexpected error on key %s, retiring from '
                      'batch only: %r' % (key.label, e))
                batch_keys.pop(0)
                continue
        if raw is None:
            # no batch-capable key left. Everything not yet attempted goes back to the
            # keyword phase VERBATIM -- dropping or counting it here undercounted 50
            # parts per lost chunk in review reproduction.
            remaining = [p for c in chunks[ci:] for p in c]
            if priced == 0 and ci == 0:
                print('digikey batch: endpoint not enabled on any key -- falling back '
                      'to per-MPN keyword search. Ask DigiKey API support to enable '
                      'BatchProductDetails (50 MPNs/request).')
            else:
                print('digikey batch: no batch-capable key left after %d chunk(s); '
                      '%d parts fall back to keyword search'
                      % (ci, len(leftovers) + len(remaining)))
            return leftovers + remaining
        for mfr, mpn in chunk:
            try:
                rec = parse_digikey_batch(mfr, mpn, raw, requested_currency=currency)
            except Exception as e:
                print('digikey batch %s %s: parse error, falling back to keyword: %s'
                      % (mfr, mpn, e))
                rec = None
            if rec is None:
                leftovers.append((mfr, mpn))
            else:
                _db.add([rec])
                record_history([rec])
                n['fetched'] += 1
                priced += 1
    if leftovers:
        print('digikey batch: %d/%d parts priced, %d fall through to keyword search'
              % (priced, len(todo), len(leftovers)))
    return leftovers


def fetch_digikey_prices(parts: List[Tuple[str, str]], currency: str = 'USD',
                         max_age='7d', workers_per_key: int = 4,
                         min_interval: float = 0.52,
                         quota_floor: int = 25, use_batch: bool = True) -> Dict[str, int]:
    """Fetch across ALL configured keys (see discover_keys): each key gets its own
    worker pool behind its own rate limiter (`min_interval` between request starts,
    0.52s ~= 115/min, just under the per-key 120/min burst limit). Skips parts whose
    record is younger than max_age. Clients are built up front (fail-fast: a key that
    cannot authenticate is dropped loudly; zero usable keys raises). A key die-off
    (2 consecutive post-backoff 429s = daily quota, or X-RateLimit-Remaining below
    quota_floor) re-queues its jobs onto surviving keys; with no keys left the
    remainder is counted quota_stop and stays un-fetched for the next run.
    Parsing and store/history writes happen ONLY on the calling thread (the sqlite
    connections are not thread-shared)."""
    from dslib.prices import _to_timedelta
    from dslib.prices.history import record_history
    max_age = _to_timedelta(max_age)
    now = utc_now()

    n = dict(fetched=0, catalog_miss=0, no_eligible_offer=0, indeterminate=0,
             errors=0, fresh_skip=0, quota_stop=0)

    # freshness gate matches on the REQUESTED currency: a USD query that DigiKey
    # answered in EUR lives under the (..., 'EUR') key, and probing only the
    # (..., 'USD') key re-spent quota on that part every run inside max_age
    from dslib.prices import norm_mpn
    dk_by_part: Dict[Tuple[str, str], List[PartOffers]] = {}
    for rec in prices_db.load().values():
        if rec.distributor == DIGIKEY:
            # normalized like the PriceLookup join: a discovery spelling change
            # across runs ('BSC070N10NS3G' stored, 'BSC070N10NS3 G' ranked now)
            # must not re-spend quota on an already-fresh part
            dk_by_part.setdefault((rec.mfr, norm_mpn(rec.mpn)), []).append(rec)

    todo = []
    fresh = []
    for mfr, mpn in parts:
        existing = [r for r in dk_by_part.get((mfr, norm_mpn(mpn)), ())
                    if (getattr(r, 'requested_currency', None) or r.currency) == currency
                    and (now - r.fetched_at) <= max_age]
        if existing:
            n['fresh_skip'] += 1
            fresh.extend(existing)
        else:
            todo.append((mfr, mpn))

    if fresh:
        # heal the history side table for fresh-skipped records: prices_db.add lands
        # BEFORE record_history by design, so a crash/error between them leaves a
        # fresh record whose history is unwritable until expiry (252 such keys found
        # in review). record_history is content-hash idempotent -- healthy records
        # cost one hash lookup, stranded ones get their snapshot appended now.
        healed = record_history(fresh)
        if healed:
            print('digikey: healed %d missing history snapshot(s) for fresh records'
                  % healed)

    if not todo:
        return n

    # fail-fast: build every key's client before any work is queued (interactive OAuth
    # for a brand-new key happens HERE, on the calling thread)
    keys = []
    for key in discover_keys():
        try:
            _build_client(key)
            keys.append(key)
        except Exception as e:
            print('digikey: key %s unusable, dropping: %s' % (key.label, e))
    if not keys:
        raise RuntimeError('digikey price fetch aborted: no usable API key '
                           '(auth/creds problem on all keys)')
    print('digikey: fetching %d parts on %d key(s): %s'
          % (len(todo), len(keys), ', '.join(k.label for k in keys)))

    if use_batch:
        todo = _batch_phase(todo, keys, currency, n, quota_floor)
        if not todo:
            return n

    jobs: 'queue.Queue' = queue.Queue()
    for j in todo:
        jobs.put(j)
    results: 'queue.Queue' = queue.Queue()
    done = threading.Event()

    def _worker(key: _Key):
        # An empty queue is NOT a reason to exit while other keys' workers are alive:
        # a dying key re-queues its in-flight jobs, and this key must still be around
        # to pick them up (the first two-key run lost exactly that race). Exit only on
        # key death or the main thread declaring the work accounted for.
        while not done.is_set():
            if key.dead:
                return
            try:
                job = jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            if key.remaining is not None and key.remaining < quota_floor:
                key.dead = True
                print('digikey: key %s below quota floor (%s remaining), retiring'
                      % (key.label, key.remaining))
                jobs.put(job)
                results.put(('key_dead', key, None))
                return
            with key.limiter_lock:  # per-key request-start spacing
                wait = key.next_slot - time.monotonic()
                key.next_slot = max(key.next_slot, time.monotonic()) + min_interval
            if wait > 0:
                time.sleep(wait)
            try:
                raw = _dk_keyword_search_raw(job[1], currency=currency, key=key)
            except DkAuthFailed as e:
                # auth-bad key: retire GLOBALLY and re-queue the job for a healthy
                # key -- this job is fine, the KEY is broken
                key.dead = True
                jobs.put(job)
                print('digikey: key %s retiring (%s)' % (key.label, e))
                results.put(('key_dead', key, None))
                return
            except DkRateLimited as e:
                key.consecutive_429 += 1
                jobs.put(job)  # this JOB is fine -- retry it on a surviving key
                if key.consecutive_429 >= 2:
                    key.dead = True
                    print('digikey: key %s daily quota exhausted, retiring (%s)'
                          % (key.label, e))
                    results.put(('key_dead', key, None))
                    return
                continue
            except Exception as e:
                results.put((job, None, e))
                continue
            key.consecutive_429 = 0
            results.put((job, raw, None))

    threads = [threading.Thread(target=_worker, args=(k,), daemon=True)
               for k in keys for _ in range(max(1, workers_per_key))]
    for t in threads:
        t.start()

    def _book(mfr, mpn, raw):
        try:
            rec = parse_digikey_offers(mfr, mpn, raw, requested_currency=currency)
        except IndeterminateMatch as e:
            # candidates existed but none was provably ours: NOT evidence of absence
            n['indeterminate'] += 1
            print(e)
            return
        except Exception as e:
            n['errors'] += 1
            print('digikey %s %s: parse error (nothing written): %s' % (mfr, mpn, e))
            return
        prices_db.add([rec])  # whole-record overwrite: a fresh ladder supersedes the old
        record_history([rec])  # AFTER the store write: history must never cost price data
        n['fetched'] += 1
        if rec.status != 'ok':
            n[rec.status] += 1

    accounted = 0
    try:
        while accounted < len(todo):
            try:
                item = results.get(timeout=1.0)
            except queue.Empty:
                if not any(t.is_alive() for t in threads):
                    break  # every key died: whatever is left in `jobs` was never fetched
                continue
            if item[0] == 'key_dead':
                continue
            job, raw, err = item
            accounted += 1
            if err is not None:
                n['errors'] += 1
                print('digikey %s %s: fetch error (nothing written): %s'
                      % (job[0], job[1], err))
            else:
                _book(job[0], job[1], raw)
    finally:
        done.set()  # release any workers idling on the empty queue

    n['quota_stop'] += len(todo) - accounted  # += so no other phase's count is clobbered
    if n['quota_stop']:
        print('digikey: STOPPED %d parts short -- every key hit its daily quota or '
              'floor; they stay un-fetched for the next run' % n['quota_stop'])
    rems = {k.label: k.remaining for k in keys if k.remaining is not None}
    if rems:
        n['rate_limit_remaining'] = rems
    return n


if __name__ == '__main__':
    import sys
    pairs = [tuple(a.split(':', 1)) for a in sys.argv[1:]] or [('infineon', 'IRFB4110PBF')]
    print(fetch_digikey_prices(pairs))
    from dslib.prices import PriceLookup
    lu = PriceLookup(100)
    for mfr, mpn in pairs:
        print(mfr, mpn, '->', lu.get(mfr, mpn))
