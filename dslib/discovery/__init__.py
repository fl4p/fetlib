import datetime
import glob
import math
import os
import re
import warnings
from typing import List, Callable, Optional, Literal

import numpy as np
import requests

from dslib import round_to_n_dec
from dslib.cache import disk_cache
from dslib.field import Field
from dslib.mosfet import Polarity, normalize_mosfet_polarity


def ensure_nC(s, min, max, abs):
    if isinstance(s, str):
        if s.endswith('nC'):
            s = float(s[:-2].strip()) * 1
        elif s.endswith('uC') or s.endswith('μC'):
            s = float(s[:-2].strip()) * 1e3
        elif s.isnumeric():
            s = float(s)
        else:
            raise ValueError(s)
        s = float(s)
    if abs and s < 0:
        s *= -1
    assert not (s < min or s > max), (min, s, max)
    return s


def ensure_ohm(s, min, max):
    if isinstance(s, str):
        if s.endswith('mOhm') or s.endswith('mΩ') or s.endswith('mO') or s.endswith('mW'):
            s = float(s[:s.index('m')].strip()) * 1e-3
        s = float(s)
    assert not (s < min or s > max), (min, s, max)
    return s


Substrate = Literal['Si', 'SiC', 'GaN']


def parse_mosfet_polarity(value) -> Optional[Polarity]:
    """Normalize vendor channel-type labels to ``"N"`` or ``"P"``.

    Parts lists use spellings such as N, N-Channel, N-ch, and N+N. Same-
    polarity multi-die parts still have one well-defined polarity; mixed
    N+P/complementary parts do not fit the scalar MOSFET model and raise
    instead of being silently labelled from whichever signed Vds appears
    first.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip().strip(',').strip()
    if not text:
        return None
    if re.fullmatch(r'N\s+with\s+Schottky', text, re.IGNORECASE):
        return 'N'

    def names(channel: str) -> bool:
        return bool(re.search(
            rf'(?<![a-z]){channel}\s*'
            rf'(?:[- ]?ch(?:annel)?\b|(?=\s*(?:[+/x&]|\band\b|$)))',
            text, re.IGNORECASE))

    found = {p for p in ('N', 'P') if names(p.lower())}
    if len(found) == 1:
        return next(iter(found))
    if len(found) > 1:
        raise ValueError("mixed MOSFET polarity is unsupported: %r" % (value,))
    raise ValueError("unknown MOSFET polarity: %r" % (value,))


class MosfetBasicSpecs():
    def __init__(self, Vds_max, Rds_on_10v_max, ID_25,
                 Vgs_th_min, Vgs_th_typ, Vgs_th_max,
                 Qg_typ, Qg_max, source: List[str], substrate: Optional[Substrate] = None,
                 polarity: Optional[Polarity] = None):

        Rds_on_10v_max = ensure_ohm(Rds_on_10v_max, 1e-6, 800)

        p = ID_25 ** 2 * Rds_on_10v_max
        if Rds_on_10v_max > 0.5 and Vds_max < 100 and ID_25 > 100 and ID_25 < 1000 and p > 5000:
            Rds_on_10v_max *= 1e-3
            warnings.warn('correcting Rds_on_10v_max %s ID_25=%.1f' % (Rds_on_10v_max, ID_25))

        self.substrate: Optional[Substrate] = substrate
        self.Vds_max = Vds_max
        self.polarity: Optional[Polarity] = normalize_mosfet_polarity(
            polarity, self.Vds_max)
        self.Rds_on_10v_max = ensure_ohm(Rds_on_10v_max, 1e-6, 800)
        self.ID_25 = ID_25
        self.Vgs_th_min = Vgs_th_min
        self.Vgs_th_max = Vgs_th_max
        self.Qg_typ_nC = ensure_nC(Qg_typ, .04, 2000, True)
        self.Qg_max_nC = ensure_nC(Qg_max, .1, 2000, True)
        self.source = source

        assert not (self.Vgs_th_max > 15)

        f = 1000 * self.Rds_on_10v_max / abs(Vds_max)
        assert not (0.002 > f or f > 1000), (f, Vds_max, self.Rds_on_10v_max)

        if Vds_max < 0:
            # p-ch
            assert math.isnan(f * ID_25) or 1 < abs(f * ID_25) < 60, (f * ID_25, f, ID_25)
        else:
            assert math.isnan(f * ID_25) or 0.1 < abs(f * ID_25) < 95, (self.Rds_on_10v_max, Vds_max, f * ID_25, f,
                                                                        ID_25)

    @property
    def isGaN(self):
        # getattr guard: parts_db holds pickled specs, and unpickling bypasses
        # __init__, so records written before `substrate` existed lack the attr.
        # Same reason update() guards `polarity` with getattr below.
        substrate = getattr(self, 'substrate', None)
        if substrate is None:
            return None
        return substrate == 'GaN'

    @property
    def Qg_max_or_typ_nC(self):
        # assert not self.Qg_max or not isinstance(self.Qg_max, str), self.Qg_max
        if self.Qg_max_nC and not math.isnan(self.Qg_max_nC):
            return self.Qg_max_nC
        return self.Qg_typ_nC

    def update(self, specs: 'MosfetBasicSpecs'):

        own_polarity = getattr(self, 'polarity', None)
        incoming_polarity = getattr(specs, 'polarity', None)
        # With no signed Vds, polarity can only have come from an explicit
        # parts-list field. Preserve that distinction through the merge so
        # later signed data is validated against it.
        own_polarity_is_explicit = normalize_mosfet_polarity(
            None, self.Vds_max) is None
        incoming_polarity_is_explicit = normalize_mosfet_polarity(
            None, specs.Vds_max) is None

        if math.isnan(self.Vds_max):
            self.Vds_max = specs.Vds_max

        if self.Vds_max != specs.Vds_max and abs(self.Vds_max) == abs(specs.Vds_max):
            self.Vds_max = min(self.Vds_max, specs.Vds_max)  # give preference to p-ch
        else:
            assert math.isnan(specs.Vds_max) or self.Vds_max == specs.Vds_max, (self.Vds_max, specs.Vds_max)
        # Vds merge above deliberately gives a P-channel record precedence over
        # an otherwise-identical positive rating. Keep the explicit field tied
        # to that final signed value rather than to whichever source arrived first.
        inferred = normalize_mosfet_polarity(None, self.Vds_max)
        if inferred is not None:
            if own_polarity_is_explicit:
                normalize_mosfet_polarity(own_polarity, self.Vds_max)
            if incoming_polarity_is_explicit:
                normalize_mosfet_polarity(incoming_polarity, self.Vds_max)
            self.polarity = inferred
        else:
            assert (own_polarity is None or incoming_polarity is None
                    or own_polarity == incoming_polarity), (
                        own_polarity, incoming_polarity)
            self.polarity = own_polarity or incoming_polarity

        def mean_chk_std(t, std, fn: Callable = np.nanmean):
            if sum(~np.isnan(t)) == 0:
                return math.nan
            assert not (np.nanstd(t) / np.nanmean(t) > std), (t, np.nanstd(t) / np.nanmean(t))
            return fn(t)

        mean_chk_std((self.Rds_on_10v_max, specs.Rds_on_10v_max), 0.45)
        if math.isnan(self.Rds_on_10v_max):
            self.Rds_on_10v_max = specs.Rds_on_10v_max
        self.ID_25 = mean_chk_std((self.ID_25, specs.ID_25), 0.45, fn=np.nanmin)
        self.Vgs_th_max = mean_chk_std((self.Vgs_th_max, specs.Vgs_th_max), 0.3, fn=np.nanmax)
        self.Qg_typ_nC = mean_chk_std((self.Qg_typ_nC, specs.Qg_typ_nC), 0.01, fn=np.nanmean)
        self.Qg_max_nC = mean_chk_std((self.Qg_max_nC, specs.Qg_max_nC), 0.2, fn=np.nanmax)

    def __setstate__(self, state):
        """Backfill polarity when loading discovery caches created by older code."""
        self.__dict__.update(state)
        self.polarity = normalize_mosfet_polarity(
            state.get('polarity'), self.Vds_max)

    def fields(self):
        n = math.nan

        def f(*args, **kwargs):
            try:
                return Field(*args, **kwargs, source=self.source)
            except:
                return None

        return list(filter(bool, [
            f('Vds', n, n, self.Vds_max),
            # Ohms, stated rather than implied. `ensure_ohm` above has already forced this
            # attribute to ohms -- twice -- so the unit is known here with certainty, and
            # Field.__init__ converts it to the canonical mΩ on the way in.
            #
            # This is the ONLY constructor of Rds_on_10v fields anywhere: all 10908 in the
            # shipped DB came through here, via 13 vendor scrapers and no parse source.
            # Leaving the unit off meant the reader had to fall back to a guessed
            # 'unitless means ohms' default for every one of them, which is the mechanism
            # that put ~4.5% of Rds_on values in the DB out by 1000x. Same class of bug,
            # same fix: say what the number is instead of inferring it downstream.
            f('Rds_on_10v', n, n, self.Rds_on_10v_max, unit='Ω'),
            f('ID_25', n, self.ID_25, n),
            f('Vgs_th', n, n, self.Vgs_th_max),
            f('Qg', n, self.Qg_typ_nC, self.Qg_max_nC, unit='nC')
        ]))

    def __str__(self):
        return f'{self.__class__.__name__}({self.Vds_max}V, {round_to_n_dec(self.Rds_on_10v_max, 2)}Ω, {round_to_n_dec(self.ID_25, 2)}A, Qg={round_to_n_dec(self.Qg_typ_nC, 2)}nC)'


def is_nan(v):
    return isinstance(v, float) and math.isnan(v)


class DiscoveredPart:
    def __init__(self, mfr, mpn, ds_url, package, release_date=None,
                 status: Optional[Literal['active', 'preferred', 'obsolete']] = None,
                 specs: MosfetBasicSpecs = None, mpn2=None):
        self.mfr = mfr
        self.mpn = mpn
        self.ds_url = ds_url
        self.specs: MosfetBasicSpecs = specs
        self.mpn2 = mpn2
        self.package = package if not is_nan(package) else None  # aka case, housing
        self.release_date = release_date
        self.status = status

    def get_ds_path(self):
        return os.path.join('datasheets', self.mfr,
                            self.mpn.replace('/', '_').replace(' ', '_').replace(', ', ',') + '.pdf')

    def __repr__(self):
        return f'DiscoveredPart({self.mfr}, {self.mpn}, ({self.specs}))'

    # def is_ganfet(self):
    #    from dslib.pdf2txt.parse import is_gan
    #    assert self.mfr
    #    return is_gan(self.mfr)


def parts_list_file_name(mfr, fn_ext, prefix):
    os.makedirs('parts-lists/' + mfr, exist_ok=True)
    fn = datetime.datetime.now().strftime(f'parts-lists/{mfr}/{prefix}-%Y-%m.{fn_ext}')
    # fn = f'parts-lists/{mfr}/{prefix}-2025-03.{fn_ext}'
    return fn


def parts_list_content_error(fn, fn_ext):
    """Why `fn` is not a usable parts list, or None if it looks like one.

    Content, not existence. The manufacturer sites answer a scripted export with
    an anti-bot challenge or an error page roughly as often as with the file, and
    download_with_chromium saves whatever came back under the requested name --
    which os.path.isfile then accepts forever after. That is how an 8 MB HTML
    page ended up as parts-lists/onsemi/low-medium-voltage-mosfets-2026-08.csv and
    aborted every discovery run until someone deleted it by hand.
    """
    try:
        with open(fn, 'rb') as f:
            head = f.read(4096)
    except OSError as e:
        return 'unreadable: %s' % e
    if not head.strip():
        return 'empty file'
    if fn_ext == 'xlsx':
        # xlsx is a zip container; an HTML page obviously is not
        return None if head[:2] == b'PK' else 'not a zip/xlsx container'
    lead = head.lstrip()[:64].lower()
    for marker in (b'<!doctype', b'<html', b'<?xml', b'<head', b'<script'):
        if lead.startswith(marker):
            return 'HTML/XML page (anti-bot challenge or error page), not %s' % fn_ext
    return None


async def download_parts_list(mfr, url, fn_ext: Literal['csv', 'xlsx'], prefix='mosfet', **kwargs):
    from dslib.fetch import download_with_chromium

    fn = parts_list_file_name(mfr, fn_ext, prefix)

    err = None
    if not os.path.isfile(fn):
        try:
            await download_with_chromium(
                url,
                filename=fn,
                **kwargs,
            )
        except Exception as e:
            # The export control never appeared, the click timed out, the site is
            # down. Distinct from "a file arrived but is garbage" below, and it
            # must NOT abort the other manufacturers' discovery.
            err = '%s: %s' % (type(e).__name__, e)

    # Validate on BOTH paths: a fresh download can be a challenge page, and a
    # previously saved one can be a challenge page from an earlier run.
    if err is None:
        err = parts_list_content_error(fn, fn_ext)
    if not err:
        return fn

    # Delete whatever landed. Leaving it behind is what makes a transient block
    # permanent: the next run skips the download because the file exists, and
    # fails identically forever.
    if os.path.isfile(fn):
        os.remove(fn)

    # Fall back to the newest earlier export rather than dropping this
    # manufacturer. Skipping it would quietly shrink the corpus, and a part that
    # was never discovered is indistinguishable from a part that lost on merit --
    # exactly the failure this is supposed to avoid. A month-old list is bounded,
    # explicit staleness; say so loudly and never write it under today's name.
    prev = sorted(f for f in glob.glob(
        'parts-lists/%s/%s-*.%s' % (mfr, prefix, fn_ext))
        if f != fn and not parts_list_content_error(f, fn_ext))
    if not prev:
        raise RuntimeError(
            '%s parts list from %s is not usable (%s), removed %s, and no earlier '
            'export is available. The site most likely served an anti-bot page; '
            'retry, or export it by hand into that path.' % (mfr, url, err, fn))

    warnings.warn(
        '%s parts list %s could not be downloaded (%s) -- FALLING BACK to the '
        'stale %s. Discovery for this manufacturer is out of date; re-run later '
        'or export it by hand.' % (mfr, os.path.basename(fn), err, prev[-1]))
    return prev[-1]


@disk_cache(ttl='90d')
def fetch_json_cached(u):
    return requests.get(u).json()


def benchmark_mpns():
    return {
        ('infineon', 'IPP65R420CFDXKSA2'),
        ('infineon', 'IMT40R036M2HXTMA1')
    }
