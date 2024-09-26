import datetime
import math
import time
import warnings
from copy import copy
from typing import List, Iterable, Dict, Literal, Tuple, Union, cast

from dslib.pdf2txt import normalize_dash


def first(a):
    return next((x for x in a if x and not math.isnan(x)), math.nan)


class Field():
    StatLiteral = Literal['min', 'max', 'typ']
    StatKeys = cast(List[StatLiteral], ['min', 'typ', 'max'])

    def __init__(self, symbol: str, min, typ, max, unit=None, mul=1, cond=None, source=None):
        self.symbol = symbol
        self._sources: Dict[Field.StatLiteral, str] = {k: source for k in Field.StatKeys}

        if unit and symbol in {'tFall', 'tRise'} and unit.lower() == 'ms':
            unit = 'ns'  # ocr confusion

        if unit in {'uC', 'μC'}:
            assert mul == 1
            mul = 1000
            unit = 'nC'

        if unit in {'nF', 'μF'}:
            assert mul == 1
            mul = 1e3
            unit = 'pF'

        if unit in {'uF', 'μF'}:
            assert mul == 1
            mul = 1e6
            unit = 'pF'

        min = parse_field_value(min) * mul
        typ = parse_field_value(typ) * mul
        max = parse_field_value(max) * mul

        fill_max_dims = {'Q', 't'}

        if symbol[0] in fill_max_dims and math.isnan(max) and not math.isnan(min) and not math.isnan(typ):
            max = typ
            typ = min
            min = math.nan

        if symbol[0] in fill_max_dims and math.isnan(max) and not math.isnan(min) and math.isnan(typ):
            typ = min
            min = math.nan
            max = math.nan

        if symbol == 'Vpl' and 30 < typ < 60:
            warnings.warn('Vpl %s out of range, assuming /10' % typ)
            typ /= 10

        mtm = (min, typ, max)

        if symbol == 'Qrr' and (not unit or unit.lower() == 'c'):
            # fix Qrr in uC -> nC
            if sum(math.isnan(v) or 0.1 < v < 0.9 for v in mtm) == 3:
                min *= 1e3
                typ *= 1e3
                max *= 1e3

        if symbol in {'Qgd', 'Qgs', 'Qg', 'tRise', 'tFall'}:
            if not math.isnan(max) and math.isnan(min) and math.isnan(typ):
                typ = max
                max = math.nan

        if symbol == 'Vsd' and max < typ and (typ/max) < 1.5:
            # Vsd confusion
            a = max
            max = typ
            typ = a


        if not math.isnan(max) and not math.isnan(typ):
            assert 1 < max/typ < 5, (typ, max)

        self.min = min
        self.typ = typ
        self.max = max

        self.unit = unit

        self.cond = cond

        self.timestamp = time.time()

        assert not math.isnan(self.typ) or not math.isnan(self.min) or not math.isnan(
            self.max), 'all nan ' + self.__repr__()

    def __repr__(self):
        return f'Field("{self.symbol}",{self.min},{self.typ},{self.max},"{self.unit}")'  # ,cond={repr(self.cond)}

    def __str__(self):
        return f'{self.symbol} = %5.1f,%5.1f,%5.1f [%s] (%s)' % (self.min, self.typ, self.max, self.unit, self.cond)

    def __len__(self):
        return 3 - math.isnan(self.min) - math.isnan(self.typ) - math.isnan(self.max)

    @property
    def typ_or_max_or_min(self):
        if not math.isnan(self.typ):
            return self.typ
        elif not math.isnan(self.max):
            return self.max
        elif not math.isnan(self.min):
            return self.min
        raise ValueError()

    @property
    def max_or_typ_or_min(self):
        if not math.isnan(self.max):
            return self.max
        elif not math.isnan(self.typ):
            return self.typ
        elif not math.isnan(self.min):
            return self.min
        raise ValueError()

    def fill(self, f: 'Field', update_min_max=False):
        if update_min_max:
            raise NotImplemented()
            # TODO min, max updates?

        # if f has more values, use all of them
        is_sup = len(f) > len(self)

        for s in Field.StatKeys:
            if is_sup or (math.isnan(getattr(self, s)) and not math.isnan(getattr(f, s))):
                setattr(self, s, getattr(f, s))
                self._sources[s] = f._sources[s]

    def __getitem__(self, item):
        assert item in {'min', 'max', 'typ'}
        return getattr(self, item)

    def values(self) -> List[float]:
        return [self.min, self.typ, self.max]


    def __eq__(self, other):
        if isinstance(other, Field):
            assert self.unit == other.unit
            if self.symbol != other.symbol:
                return False
            other = other.values()

        if isinstance(other, (tuple, list)):
            assert len(other) == 3, other
            ks = ('min', 'typ', 'max')
            for i in range(0, 3):
                v = self.__dict__[ks[i]]
                if math.isnan(v) and math.isnan(other[i]):
                    continue
                if v != other[i]:
                    return False
        return True


def parse_field_value(s):
    if isinstance(s, (float, int)):
        return s
    if not s:
        return math.nan
    s = normalize_dash(s.strip().strip('\x03').rstrip('L'))
    if not s or s == '-' or s == '.' or set(s) == {'-'}:
        return math.nan
    return float(s)


class MpnMfr:
    def __init__(self, mfr, mpn):
        self.mfr = mfr
        self.mpn = mpn


class DatasheetFields():
    def __init__(self, mfr=None, mpn=None, part: 'DiscoveredPart' = None, fields: Iterable[Field] = None):
        from dslib.parts_discovery import DiscoveredPart
        self.part: Union[DiscoveredPart, MpnMfr] = part or MpnMfr(mpn, mfr)
        self.fields_filled: Dict[str, Field] = {}
        self.fields_lists: Dict[str, List[Field]] = {}
        if fields:
            self.add_multiple(fields)

        self.timestamp = datetime.datetime.now()

    @property
    def ds_path(self):
        return self.part.get_ds_path()

    def get_row(self):
        ds = self
        part = ds.part

        try:
            fet_specs = ds.get_mosfet_specs()
        except Exception as e:
            warnings.warn('failed to create fet specs: %s' %e)
            fet_specs = None

        return dict(
            mfr=part.mfr,
            mpn=part.mpn,
            housing=part.package,

            Vds_max=ds.get_max('Vds', True),
            Rds_max=ds.get_max('Rds_on_10v', True) * 1000,
            Id=ds.get_typ_or_max_or_min('ID_25', True),

            Qg_max=ds.get_max('Qg'),
            Qgs=ds.get_typ_or_max_or_min('Qgs'),
            Qgd=ds.get_typ_or_max_or_min('Qgd'),
            Qsw=fet_specs and (fet_specs.Qsw * 1e9),


            # C_oss_pF=ds.get('Coss') and ds.get('Coss').max_or_typ_or_min,

            Vsd=ds.get_typ_or_max_or_min('Vsd'),
            Qrr_typ=ds.get_typ('Qrr'),
            Qrr_max=ds.get_max('Qrr'),

            tRise_ns=round(fet_specs.tRise * 1e9, 1),
            tFall_ns=round(fet_specs.tFall * 1e9, 1),
        )

    def add(self, f: Field):
        assert not math.isnan(f.typ_or_max_or_min)
        if f.symbol not in self.fields_filled:
            self.fields_filled[f.symbol] = copy(f)
            self.fields_lists[f.symbol] = []
        self.fields_lists[f.symbol].append(f)
        self.fields_filled[f.symbol].fill(f)

    def add_multiple(self, fields: Iterable[Field]):
        for f in fields:
            self.add(f)

    def print(self, show_cond=False):
        print('')
        print(self.part.mfr, self.part.mpn)
        print('Symbol         min   typ   max   unit   source',  '   cond' if show_cond else '',)
        for f in self.fields_filled.values():
            l = '%-12s %5.0f %5.0f %5.0f %-4s %10s %-20s' % (f.symbol, f.min, f.typ, f.max, f.unit,
                                                          '/'.join(map(lambda s:str(s)[:2], f._sources.values())),
                                                         ', '.join(f.cond.values() if f.cond else []) if show_cond else '')
            l = l.replace('nan', ' - ')
            l = l.replace(' None', '  -  ')
            print(l)

    def get_mosfet_specs(self):
        mf_fields = [
            'Qrr', 'Vsd',  # body diode
            'Qgd', 'Qgs', 'Qgs2', 'Qg_th',  # gate charges
            'Coss', 'Qsw',
        ]

        field_mul = lambda sym, v: v if sym[0] == 'V' else (v * 1e-9)

        ds = self

        from dslib.spec_models import MosfetSpecs
        return MosfetSpecs(
            Vds_max=ds.get_max('Vds'),
            Rds_on=ds.get_max('Rds_on_10v'),
            Qg=ds.get_typ_or_max_or_min('Qg') * 1e-9,
            tRise=ds.get_typ_or_max_or_min('tRise') * 1e-9,
            tFall=ds.get_typ_or_max_or_min('tFall') * 1e-9,
            **{k: field_mul(k, ds.get_typ_or_max_or_min(k)) for k in mf_fields},
            Vpl=ds.get_typ_or_max_or_min('Vpl'),
        )

    def get(self, sym, stat: Union[Tuple[Field.StatLiteral], Field.StatLiteral], required=False):
        if isinstance(stat, str):
            stat = (stat,)
        r = self.fields_filled.get(sym)
        assert not required or r
        if not r:
            return math.nan
        for s in stat:
            v = getattr(r, s)
            if not math.isnan(v):
                return v
        return math.nan

    def get_typ_or_max_or_min(self, sym, required=False):
        r = self.fields_filled.get(sym)
        assert r or not required
        return math.nan if not r else r.typ_or_max_or_min

    def get_typ(self, sym):
        r = self.fields_filled.get(sym)
        return math.nan if not r else r.typ

    def get_max(self, sym, required=False):
        r = self.fields_filled.get(sym)
        assert not required or r
        return math.nan if not r else r.max

    def items(self):
        return self.fields_filled.items()

    def keys(self):
        return self.fields_filled.keys()

    def __contains__(self, item):
        return item in self.fields_filled

    def __len__(self):
        return len(self.fields_filled)

    def __bool__(self):
        return bool(self.fields_filled)

    def __getattr__(self, item) -> Field:
        if item != 'fields_filled':
            ff = getattr(self, 'fields_filled')
            if item in ff:
                return ff[item]
        raise AttributeError(item)

    def __getitem__(self, item) -> Field:
        return self.fields_filled[item]

    def all_fields(self) -> List[Field]:
        return sum(map(list, self.fields_lists.values()), [])

    # def _apply_on_values(self, symbols=None, reduce_field):
    #    if not symbols:
    #        symbols = b.fields_filled.keys()
    #    for sym in symbols:
    #        for f in b.fields_lists.get(sym, []):
    #
    #            (reduce_field(sym, stat, f[stat]) ):
    #                rv = f[stat]

    def count_equal(self, a: 'DatasheetFields', symbols=None, err_threshold=0.05):
        b = self
        n = 0
        if not symbols:
            symbols = b.fields_filled.keys()
        for sym in symbols:
            for stat in Field.StatKeys:
                min_err = float('inf')
                for f in b.fields_lists.get(sym, []):
                    rv = f[stat]
                    are = abs((a.get(sym, stat) - rv) / rv)
                    if are < min_err:
                        min_err = are

                if min_err < err_threshold:
                    n += 1

        return n

    def show_diff(self, a: 'DatasheetFields', symbols=None, err_threshold=0.001, title=''):
        assert 0 <= err_threshold < 0.2

        b = self
        n = 0
        if not symbols:
            symbols = b.fields_filled.keys()
        for sym in symbols:
            min_err = float('inf')
            for f in b.fields_lists.get(sym, []):
                max_err = 0
                for stat in cast(List[Field.StatLiteral], ['min', 'typ', 'max']):
                    # TODO iterate fields_list and take min err
                    rv = f[stat]
                    v = a.get(sym, stat)
                    if not math.isnan(rv) and math.isnan(v):
                        are = 1
                    else:
                        are = abs((v - rv) / rv)
                    max_err = max(max_err, are)
                if max_err >= err_threshold:
                    print('')
                    print(title, self.part.mfr, self.part.mpn,
                          f'err {round(max_err, 3)} > {err_threshold}',
                          '\nref=', f,
                          '\noth=', a.fields_filled.get(sym, None)
                          )
                    n += 1

                if max_err < min_err:
                    min_err = max_err

        return n

    def __str__(self):
        return f'DatasheetFields({self.part.mfr},{self.part.mpn}, count={len(self)})'

    def __repr__(self):
        return f'DatasheetFields("{self.part.mfr}","{self.part.mpn}",fields={list(self.fields_filled.values())})'

    def rmse(self, b: 'DatasheetFields'):
        raise NotImplemented()

        ref = self

        rmse = {}
        for sym, fl in ref.fields_filled:
            if sym not in b:
                rmse[sym] = math.nan
            rmse[sym] = min(() / r[s] for f in fl)
