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

_env_lock = threading.Lock()  # SDK TokenHandler reads process-global env


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
    """(Re)build the per-key API client. Serialized via _env_lock because the SDK's
    TokenHandler reads env; may run the interactive OAuth flow (browser) on a key's
    first ever use. A 401 later (access token expired, ~30 min) re-enters here."""
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
        bcfg.host = 'https://api.digikey.com/BatchSearch/v4'
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
            if e.status == 401 and not retried_auth:
                retried_auth = True   # access token expired mid-run: rebuild, retry
                _build_client(key)
                continue
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


# Reviewed packaging/carrier suffixes only -- NOT a generic "any non-digit" rule:
# letter continuations can be distinct electrical/qualification variants (X1 vs X1A).
# T1G/T3G/T1/T3 = onsemi tape&reel; TR/TL/TF/CT = DigiKey carrier codes; TRPBF =
# Infineon/IR tape&reel lead-free. Extend deliberately, with a test.
PACKAGING_SUFFIXES = ('t1g', 't3g', 't1', 't3', 'tr', 'tl', 'tf', 'ct', 'trpbf')
_SUFFIX_SEPARATORS = '-_,/ '


def _suffix_extends_mpn(candidate: str, mpn: str) -> bool:
    """True when candidate is mpn plus a KNOWN packaging suffix (NTMFS5C628NL ->
    NTMFS5C628NLT1G) or a separator-led suffix (SIR104LDP -> SIR104LDP-T1-RE3, tape
    codes after '-'/'_' are carrier designators by convention). Anything else --
    digit continuations (X1 -> X10) and bare letter continuations (X1 -> X1A) -- is
    treated as a DIFFERENT part."""
    c, m = candidate.lower(), mpn.lower()
    if not (c.startswith(m) and len(c) > len(m)):
        return False
    suffix = c[len(m):]
    return suffix in PACKAGING_SUFFIXES or suffix[0] in _SUFFIX_SEPARATORS


def _iter_products(raw_response: dict, mfr: str, mpn: str):
    """Match tiers: exact_matches; MPN equality; DigiKey's own base_product_number
    equality; packaging-suffix extension (non-digit continuation only). Products whose
    manufacturer is missing or maps to a different mfr_tag are skipped with a warning
    -- if that rejects EVERY candidate, IndeterminateMatch is raised (see above);
    catalog_miss is reserved for a response with no candidate at all."""
    hits = raw_response.get('products') or []
    products = (raw_response.get('exact_matches')
                or [p for p in hits
                    if (p.get('manufacturer_product_number') or '').lower() == mpn.lower()]
                or [p for p in hits
                    if ((p.get('base_product_number') or {}).get('name') or '').lower() == mpn.lower()]
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
            ladder = [(pb['break_quantity'], pb['unit_price'])
                      for pb in pricing
                      if pb.get('break_quantity') and pb.get('unit_price')]
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
    return rec


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
    equality, then non-digit suffix extension; manufacturer must match. Returns None
    when nothing matches -- the batch phase NEVER writes negative records (its error
    list does not name the failing MPN reliably), unmatched parts fall through to the
    keyword path which owns catalog_miss semantics."""
    details = raw['details']
    matched = ([d for d in details
                if (d.get('manufacturer_part_number') or '').lower() == mpn.lower()]
               or [d for d in details
                   if _suffix_extends_mpn(d.get('manufacturer_part_number') or '', mpn)])
    offers: List[Offer] = []
    url = None
    currency = requested_currency
    for d in matched:
        d_mfr = _pidvid_name(d.get('manufacturer'))
        if not d_mfr or mfr_tag(d_mfr) != mfr:
            continue
        if d.get('supplier_direct_ship'):  # marketplace analog: not DigiKey stock
            continue
        pkg = _pidvid_name(d.get('packaging'))
        if 'digi-reel' in pkg.lower():
            continue
        ladder = [(pb['break_quantity'], pb['unit_price'])
                  for pb in d.get('standard_pricing') or []
                  if pb.get('break_quantity') and pb.get('unit_price')]
        if not ladder:
            continue
        currency = ((d.get('search_locale_used') or {}).get('currency')) or currency
        url = url or d.get('product_url')
        offers.append(Offer(
            sku=d.get('digi_key_part_number') or '',
            packaging=pkg or None,
            ladder=ladder,
            moq=d.get('minimum_order_quantity'),
            stock=d.get('quantity_available'),
        ))
    if not offers:
        return None
    return PartOffers(mfr=mfr, mpn=mpn, distributor=DIGIKEY, currency=currency,
                      offers=offers,
                      fetched_at=datetime.datetime.fromisoformat(raw['fetched_at']),
                      url=url, status='ok')


def _batch_phase(todo: List[Tuple[str, str]], keys: List[_Key], currency: str,
                 n: Dict[str, int], quota_floor: int) -> List[Tuple[str, str]]:
    """Price as much of `todo` as possible via BatchProductDetails (50 MPNs = ONE
    request against the daily quota, ~60 requests for the full fugu3 corpus) and
    return the leftovers for the keyword path.

    The endpoint must be enabled per app by DigiKey support: a 403/404 on the first
    chunk means 'not enabled (yet)' -- everything falls through to keyword search with
    one loud line. Only 'ok' records are ever written here (the batch error list does
    not name failing MPNs reliably); unmatched parts stay in the leftovers where the
    keyword path's catalog_miss/indeterminate semantics apply.

    NOTE errors are matched by SHAPE (getattr status), not by exception class: every
    generated SDK sub-package has its own rest.ApiException, and the fork's v4 batch
    package actually raises digikey.v3.batchproductdetails.rest.ApiException -- an
    isinstance check against the v4 productinformation class silently misses it."""
    from dslib.prices import prices_db as _db
    from dslib.prices.history import record_history

    alive = [k for k in keys if not k.dead]
    leftovers: List[Tuple[str, str]] = []
    chunks = [todo[i:i + 50] for i in range(0, len(todo), 50)]
    for ci, chunk in enumerate(chunks):
        raw = None
        while alive and raw is None:
            key = alive[0]
            if key.remaining is not None and key.remaining < quota_floor:
                print('digikey batch: key %s below quota floor, retiring' % key.label)
                key.dead = True
                alive.pop(0)
                continue
            try:
                raw = _dk_batch_details_raw([mpn for _, mpn in chunk], currency, key)
            except Exception as e:
                status = getattr(e, 'status', None)
                if status in (403, 404) and ci == 0:
                    print('digikey batch: endpoint not enabled on key %s (HTTP %s) -- '
                          'falling back to per-MPN keyword search. Ask DigiKey API '
                          'support to enable BatchProductDetails (50 MPNs/request).'
                          % (key.label, status))
                    return todo
                if status == 429:
                    print('digikey batch: key %s rate limited, retiring' % key.label)
                    key.dead = True
                    alive.pop(0)
                    continue
                raise
        if raw is None:  # every key retired mid-batch
            n['quota_stop'] += sum(len(c) for c in chunks[ci:]) - len(leftovers)
            print('digikey batch: STOPPED, all keys exhausted; %d parts stay '
                  'un-fetched' % n['quota_stop'])
            return leftovers
        for mfr, mpn in chunk:
            rec = parse_digikey_batch(mfr, mpn, raw, requested_currency=currency)
            if rec is None:
                leftovers.append((mfr, mpn))
            else:
                _db.add([rec])
                record_history([rec])
                n['fetched'] += 1
    if leftovers:
        print('digikey batch: %d/%d parts priced, %d fall through to keyword search'
              % (n['fetched'], len(todo), len(leftovers)))
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

    todo = []
    for mfr, mpn in parts:
        existing = prices_db.load_obj((mfr, mpn, DIGIKEY, currency))
        if existing is not None and (now - existing.fetched_at) <= max_age:
            n['fresh_skip'] += 1
        else:
            todo.append((mfr, mpn))
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

    n['quota_stop'] = len(todo) - accounted
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
