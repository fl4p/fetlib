import datetime
import math
import os
import warnings
from typing import List, Callable, Optional, Literal

import numpy as np
import requests

from dslib import round_to_n_dec
from dslib.cache import disk_cache
from dslib.field import Field


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


class MosfetBasicSpecs():
    def __init__(self, Vds_max, Rds_on_10v_max, ID_25,
                 Vgs_th_min, Vgs_th_typ, Vgs_th_max,
                 Qg_typ, Qg_max, source: List[str], substrate: Optional[Substrate] = None):

        Rds_on_10v_max = ensure_ohm(Rds_on_10v_max, 1e-6, 800)

        p = ID_25 ** 2 * Rds_on_10v_max
        if Rds_on_10v_max > 0.5 and Vds_max < 100 and ID_25 > 100 and ID_25 < 1000 and p > 5000:
            Rds_on_10v_max *= 1e-3
            warnings.warn('correcting Rds_on_10v_max %s ID_25=%.1f' % (Rds_on_10v_max, ID_25))

        self.substrate: Optional[Substrate] = substrate
        self.Vds_max = Vds_max
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
        if self.substrate is None:
            return None
        return self.substrate == 'GaN'

    @property
    def Qg_max_or_typ_nC(self):
        # assert not self.Qg_max or not isinstance(self.Qg_max, str), self.Qg_max
        if self.Qg_max_nC and not math.isnan(self.Qg_max_nC):
            return self.Qg_max_nC
        return self.Qg_typ_nC

    def update(self, specs: 'MosfetBasicSpecs'):

        if math.isnan(self.Vds_max):
            self.Vds_max = specs.Vds_max

        if self.Vds_max != specs.Vds_max and abs(self.Vds_max) == abs(specs.Vds_max):
            self.Vds_max = min(self.Vds_max, specs.Vds_max)  # give preference to p-ch
        else:
            assert math.isnan(specs.Vds_max) or self.Vds_max == specs.Vds_max, (self.Vds_max, specs.Vds_max)

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

    def fields(self):
        n = math.nan

        def f(*args, **kwargs):
            try:
                return Field(*args, **kwargs, source=self.source)
            except:
                return None

        return list(filter(bool, [
            f('Vds', n, n, self.Vds_max),
            f('Rds_on_10v', n, n, self.Rds_on_10v_max),
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
        self.release_data = release_date
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


async def download_parts_list(mfr, url, fn_ext: Literal['csv', 'xlsx'], prefix='mosfet', **kwargs):
    from dslib.fetch import download_with_chromium

    fn = parts_list_file_name(mfr, fn_ext, prefix)

    if not os.path.isfile(fn):
        await download_with_chromium(
            url,
            filename=fn,
            **kwargs,
        )

    return fn


@disk_cache(ttl='90d')
def fetch_json_cached(u):
    return requests.get(u).json()


def benchmark_mpns():
    return {
        ('infineon', 'IPP65R420CFDXKSA2'),
        ('infineon', 'IMT40R036M2HXTMA1')
    }
