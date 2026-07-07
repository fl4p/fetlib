"""
Inspector for dslib.store.datasheets_db.

Default: list all parts (mfr, mpn, #fields, date).

Filter expressions (positional args, AND-combined):
    SYM                       part has any Field for SYM
    SYM.ATTR                  part has at least one Field where ATTR is set (non-nan)
    SYM.ATTR OP VALUE         compare against any matching Field
    SYM.ATTR ~= /regex/       regex match (typically on .unit)
    SYM.cond.KEY OP VALUE     access cond dict key
    !<any of the above>       negate (no Field matches)

ATTR is one of: min, typ, max, unit, cond, source, n (variant count).
OP is one of: ==, !=, <, <=, >, >=, ~=.

Quote each expression in the shell (the ! and < > are special).

Examples:
    python apps/ddb.py
    python apps/ddb.py 'Qg.max > 50'
    python apps/ddb.py '!Qrr.max'
    python apps/ddb.py 'Vds.unit ~= /V/'
    python apps/ddb.py 'Qg.cond.Vgs == 10' -s Qg -c
    python apps/ddb.py -m infineon -L 20
    python apps/ddb.py -l
"""

import argparse
import math
import os
import re
import sys
from collections import Counter
from typing import Callable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dslib.store
from dslib.field import DatasheetFields, Field, conditions_to_str


def _attr_value(f: Field, attr: str, cond_key: Optional[str] = None):
    if attr == 'cond':
        if cond_key is None:
            return f.cond
        if isinstance(f.cond, dict):
            return f.cond.get(cond_key)
        return None
    if attr == 'source':
        srcs = set()
        for v in f._sources.values():
            if isinstance(v, list):
                srcs.update(str(x) for x in v if x)
            elif v:
                srcs.add(str(v))
        return ','.join(sorted(srcs))
    if attr == 'n':
        return None  # handled at parse time, not per-Field
    return getattr(f, attr, None)


_OPS = {
    '==': lambda a, b: a == b,
    '!=': lambda a, b: a != b,
    '<=': lambda a, b: a <= b,
    '>=': lambda a, b: a >= b,
    '<': lambda a, b: a < b,
    '>': lambda a, b: a > b,
}

_NAME = r'[A-Za-z_][A-Za-z_0-9]*'
_TOKEN = re.compile(
    r'^\s*(?P<neg>!)?\s*'
    r'(?P<sym>%s)'
    r'(?:\.(?P<attr>%s)(?:\.(?P<ckey>%s))?)?'
    r'\s*(?:(?P<op>==|!=|<=|>=|<|>|~=)\s*(?P<val>.+?))?\s*$' % (_NAME, _NAME, _NAME)
)


def _parse_value(s: str):
    s = s.strip()
    if len(s) >= 2 and s.startswith('/') and s.endswith('/'):
        return 'regex', re.compile(s[1:-1])
    if len(s) >= 2 and ((s.startswith('"') and s.endswith('"'))
                        or (s.startswith("'") and s.endswith("'"))):
        return 'str', s[1:-1]
    if s == 'nan':
        return 'nan', math.nan
    if s in ('None', 'null'):
        return 'none', None
    try:
        return 'num', float(s)
    except ValueError:
        return 'str', s


def _is_missing(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if v == '' or v == {} or v == []:
        return True
    return False


def _cmp(v, op, val, kind) -> bool:
    if op == '~=':
        return bool(val.search('' if v is None else str(v)))
    if _is_missing(v):
        return op == '!='
    if kind == 'num' and isinstance(v, str):
        try:
            v = float(v)
        except ValueError:
            return False
    try:
        return _OPS[op](v, val)
    except TypeError:
        return False


def parse_filter(expr: str) -> Callable[[DatasheetFields], bool]:
    m = _TOKEN.match(expr)
    if not m:
        raise ValueError(f'cannot parse filter: {expr!r}')
    neg = bool(m.group('neg'))
    sym = m.group('sym')
    attr = m.group('attr')
    ckey = m.group('ckey')
    op = m.group('op')
    val_s = m.group('val')

    if ckey is not None and attr != 'cond':
        raise ValueError(f'sub-key only allowed under .cond: {expr!r}')

    kind = val = None
    if op:
        kind, val = _parse_value(val_s)
        if op == '~=' and kind != 'regex':
            raise ValueError(f'~= requires /regex/ value: {expr!r}')

    def pred(ds: DatasheetFields) -> bool:
        fields = ds.fields_lists.get(sym, [])

        if attr == 'n':
            n = len(fields)
            ok = (op is None and n > 0) or (op is not None and _cmp(n, op, val, kind))
            return (not ok) if neg else ok

        if attr is None:
            ok = bool(fields)
            return (not ok) if neg else ok

        ok = False
        for f in fields:
            v = _attr_value(f, attr, ckey)
            if op is None:
                if not _is_missing(v):
                    ok = True
                    break
            else:
                if _cmp(v, op, val, kind):
                    ok = True
                    break

        return (not ok) if neg else ok

    pred.__doc__ = expr
    return pred


def _sort_key(ds: DatasheetFields, keys: List[str]):
    out = []
    for k in keys:
        desc = k.startswith('-')
        if desc:
            k = k[1:]
        if k == 'mfr':
            v = ds.part.mfr or ''
        elif k == 'mpn':
            v = ds.part.mpn or ''
        elif k == 'nfields':
            v = len(ds)
        elif k == 'date':
            v = (ds.date_from_text or ds.date_from_meta)
            v = v.timestamp() if v else 0.0
        elif '.' in k:
            sym, attr = k.split('.', 1)
            f = ds.fields_filled.get(sym)
            v = _attr_value(f, attr) if f else None
            if _is_missing(v):
                v = -math.inf
        else:
            f = ds.fields_filled.get(k)
            v = f.typ_or_max_or_min if f else -math.inf
        if isinstance(v, (int, float)):
            out.append(-v if desc else v)
        else:
            out.append(v if not desc else _NegStr(v))
    return tuple(out)


class _NegStr:
    __slots__ = ('s',)

    def __init__(self, s):
        self.s = s

    def __lt__(self, other):
        return self.s > other.s

    def __eq__(self, other):
        return self.s == other.s


def _fmt_field(f: Field) -> str:
    def fv(v):
        return ' ⎵ ' if isinstance(v, float) and math.isnan(v) else f'{v:.3g}'
    return f'{fv(f.min):>8} {fv(f.typ):>8} {fv(f.max):>8} [{f.unit or ""}]'


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('filters', nargs='*', help='filter expressions, AND-combined')
    ap.add_argument('-m', '--mfr', help='manufacturer substring filter (case-insensitive)')
    ap.add_argument('-p', '--mpn', help='mpn substring filter (case-insensitive)')
    ap.add_argument('-s', '--show', action='append', default=[],
                    help='show field SYM for each matching part (repeatable)')
    ap.add_argument('-c', '--cond', action='store_true',
                    help='with -s, show all variants from fields_lists with conditions')
    ap.add_argument('-P', '--print', dest='print_ds', action='store_true',
                    help='call DatasheetFields.print() for each match')
    ap.add_argument('-l', '--list-symbols', action='store_true',
                    help='count symbols across the (filtered) db and exit')
    ap.add_argument('-L', '--limit', type=int, default=None, help='limit output rows')
    ap.add_argument('--sort', default='mfr,mpn',
                    help='comma-separated sort keys (mfr,mpn,nfields,date,SYM,SYM.attr); prefix - for descending')
    ap.add_argument('--count', action='store_true', help='print only matching count')
    args = ap.parse_args(argv)

    try:
        preds = [parse_filter(e) for e in args.filters]
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2

    if args.mfr:
        sub = args.mfr.lower()
        preds.append(lambda ds, s=sub: s in (ds.part.mfr or '').lower())
    if args.mpn:
        sub = args.mpn.lower()
        preds.append(lambda ds, s=sub: s in (ds.part.mpn or '').lower())

    db = dslib.store.datasheets_db.load()
    rows = [ds for ds in db.values() if all(p(ds) for p in preds)]

    if args.count:
        print(len(rows))
        return 0

    if args.list_symbols:
        c = Counter()
        for ds in rows:
            for sym in ds.fields_filled.keys():
                c[sym] += 1
        print(f'# symbols across {len(rows)} parts')
        print(f'{"symbol":<14} {"count":>6}  coverage')
        for sym, n in c.most_common():
            pct = 100.0 * n / max(len(rows), 1)
            print(f'{sym:<14} {n:>6}  {pct:5.1f}%')
        return 0

    sort_keys = [s.strip() for s in args.sort.split(',') if s.strip()]
    rows.sort(key=lambda ds: _sort_key(ds, sort_keys))

    if args.limit is not None:
        rows = rows[:args.limit]

    print(f'# {len(rows)} parts (of {len(db)})')
    print(f'{"mfr":<14} {"mpn":<32} {"nf":>3}  {"date":<8}')
    for ds in rows:
        d = ds.date_from_text or ds.date_from_meta
        d_str = d.strftime('%Y-%m') if d else ''
        print(f'{(ds.part.mfr or ""):<14} {(ds.part.mpn or ""):<32} {len(ds):>3}  {d_str:<8}')

        for sym in args.show:
            if args.cond:
                fs = ds.fields_lists.get(sym, [])
                if not fs:
                    print(f'    {sym:<10}   --')
                for f in fs:
                    print(f'    {f.symbol:<10} {_fmt_field(f)}   {conditions_to_str(f.cond)}')
            else:
                f = ds.fields_filled.get(sym)
                if f:
                    print(f'    {f.symbol:<10} {_fmt_field(f)}')
                else:
                    print(f'    {sym:<10}   --')

        if args.print_ds:
            ds.print(show_cond=True, show_sources=True)

    return 0


if __name__ == '__main__':
    sys.exit(main())
