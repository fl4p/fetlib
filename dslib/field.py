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
