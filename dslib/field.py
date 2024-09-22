import math
from copy import copy
from typing import List, Iterable, Dict, Literal, Tuple, Union, cast

from dslib.pdf2txt import normalize_dash


def first(a):
    return next((x for x in a if x and not math.isnan(x)), math.nan)


class Field():
    StatLiteral = Literal['min', 'max', 'typ']
    Stats = cast(List[StatLiteral], ['min', 'typ', 'max'])

    def __init__(self, symbol: str, min, typ, max, mul=1, cond=None, unit=None):
        self.symbol = symbol

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

        self.min = min
        self.typ = typ
        self.max = max

        self.unit = unit

        self.cond = cond

        assert not math.isnan(self.typ) or not math.isnan(self.min) or not math.isnan(
            self.max), 'all nan ' + self.__repr__()

    def __repr__(self):
        return f'Field("{self.symbol}", min={self.min}, typ={self.typ}, max={self.max}, unit="{self.unit}", cond={repr(self.cond)})'

    def __str__(self):
        return f'{self.symbol} = %5.1f,%5.1f,%5.1f [%s] (%s)' % (self.min, self.typ, self.max, self.unit, self.cond)

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

        for s in ('min', 'max', 'typ'):
            if math.isnan(getattr(self, s)) and not math.isnan(getattr(f, s)):
                setattr(self, s, getattr(f, s))

    def __getitem__(self, item):
        assert item in {'min', 'max', 'typ'}
        return getattr(self, item)


def parse_field_value(s):
    if isinstance(s, (float, int)):
        return s
    if not s:
        return math.nan
    s = normalize_dash(s.strip().strip('\x03').rstrip('L'))
    if not s or s == '-' or set(s) == {'-'}:
        return math.nan
    return float(s)


class MpnMfr:
    def __init__(self, mfr, mpn):
        self.mfr = mfr
        self.mpn = mpn


class DatasheetFields():
    def __init__(self, mfr=None, mpn=None, fields: Iterable[Field] = None):
        self.part = MpnMfr(mpn, mfr)
        self.fields_filled: Dict[str, Field] = {}
        self.fields_lists: Dict[str, List[Field]] = {}
        if fields:
            self.add_multiple(fields)

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

    def get_mosfet_specs(self):
        mf_fields = [
            'Qrr', 'Vsd',  # body diode
            'Qgd', 'Qgs', 'Qgs2', 'Qg_th',  # gate charges
            'Coss', 'Qsw',
        ]
        field_mul = lambda sym: 1 if sym[0] == 'V' else 1e-9

        ds = self

        from dslib.spec_models import MosfetSpecs
        return MosfetSpecs(
            Vds_max=ds.get_max('Vds', True),
            Rds_on=ds.get_max('Rds_on_10v'),
            Qg=ds.get_typ_or_max_or_min('Qg') * 1e-9,
            tRise=ds.get_typ_or_max_or_min('tRise') * 1e-9,
            tFall=ds.get_typ_or_max_or_min('tFall') * 1e-9,
            **{k: ds.get_typ_or_max_or_min(k) * field_mul(k) for k in mf_fields},
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

    def all_fields(self):
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
            for stat in Field.Stats:
                min_err = float('inf')
                for f in b.fields_lists.get(sym, []):
                    rv = f[stat]
                    are = abs((a.get(sym, stat) - rv) / rv)
                    if are < min_err:
                        min_err = are

                if min_err < err_threshold:
                    n += 1

        return n

    def show_diff(self, a: 'DatasheetFields', symbols=None, err_threshold=0.05, title=''):
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
                    are = abs((a.get(sym, stat) - rv) / rv)
                    max_err = max(max_err, are)
                if max_err >= err_threshold:
                    print('')
                    print(title, self.part.mfr, self.part.mpn,
                          f'err {round(max_err, 3)} > {err_threshold}',
                          '\nref=', f,
                          '\noth=', a.fields_filled[sym]
                          )
                    n += 1

                if max_err < min_err:
                    min_err = max_err

        return n

    def rmse(self, b: 'DatasheetFields'):
        raise NotImplemented()

        ref = self

        rmse = {}
        for sym, fl in ref.fields_filled:
            if sym not in b:
                rmse[sym] = math.nan
            rmse[sym] = min(() / r[s] for f in fl)
