"""Remove exact duplicate Field candidates from datasheets_db.

`fields_lists` is an audit trail of parser/vendor candidates, but repeated identical vendor
records can make one part unreadable in apps/ddb.py and debug prints. This repair removes only
logical duplicates: same symbol, stats, unit, conditions and per-stat source. Same value from a
different source is kept.

Dry-run by default. `--apply` snapshots the store, rewrites only touched records, then reloads
from disk to verify the requested duplicate counts disappeared.
"""
import argparse
import collections
import os
import sys
from copy import copy, deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.field import DatasheetFields, field_dedup_key
from dslib.store import datasheets_db


def dedupe_record(ds):
    tmp = DatasheetFields(part=ds.part,
                          date_from_text=getattr(ds, 'date_from_text', None),
                          date_from_meta=getattr(ds, 'date_from_meta', None))
    seen = set()
    dropped = collections.Counter()
    for sym, fields in (getattr(ds, 'fields_lists', None) or {}).items():
        for f in fields:
            k = field_dedup_key(f)
            if k in seen:
                dropped[sym] += 1
                continue
            seen.add(k)
            tmp.add(deepcopy(f))

    if not dropped:
        return None, dropped

    repaired = copy(ds)
    repaired.fields_lists = tmp.fields_lists
    repaired.fields_filled = tmp.fields_filled
    repaired._field_keys = tmp._field_keys
    return repaired, dropped


def duplicate_counts(ds):
    out = collections.Counter()
    seen = set()
    for sym, fields in (getattr(ds, 'fields_lists', None) or {}).items():
        for f in fields:
            k = field_dedup_key(f)
            if k in seen:
                out[sym] += 1
            else:
                seen.add(k)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true', help='write the DB (default: dry run)')
    ap.add_argument('--limit', type=int, default=0, help='only inspect N records')
    ap.add_argument('--show', type=int, default=20, help='example changed parts to print')
    args = ap.parse_args()

    touched = {}
    by_symbol = collections.Counter()
    examples = []
    inspected = 0

    for key, ds in datasheets_db.iter_items():
        if args.limit and inspected >= args.limit:
            break
        inspected += 1
        repaired, dropped = dedupe_record(ds)
        if not dropped:
            continue
        touched[key] = repaired
        by_symbol.update(dropped)
        if len(examples) < args.show:
            examples.append((key, sum(dropped.values()), dict(dropped)))

    print('records inspected: %d' % inspected)
    print('records with duplicates: %d' % len(touched))
    print('duplicate fields: %d' % sum(by_symbol.values()))
    print()
    print('%-16s %8s' % ('symbol', 'dropped'))
    for sym, n in by_symbol.most_common(30):
        print('%-16s %8d' % (sym, n))
    print()
    print('=== examples ===')
    for key, n, dropped in examples:
        print('  %-42s %5d  %s' % ('/'.join(map(str, key)), n, dropped))

    if not args.apply:
        print('\nDRY RUN -- nothing written. Re-run with --apply to write.')
        return 0
    if not touched:
        print('\nNo duplicates to write.')
        return 0

    lib = datasheets_db._lib_path
    backup = lib + '.pre-dedup-fields'
    if os.path.exists(backup):
        print('\nREFUSING to overwrite existing backup at %s' % backup)
        return 2
    print('\nbacking up %s -> %s' % (lib, backup))
    datasheets_db.snapshot(backup)

    print('writing %d touched records' % len(touched))
    datasheets_db.add(list(touched.values()), overwrite=True)

    print('\nreloading touched records to verify')
    datasheets_db.unload()
    problems = []
    for key, repaired in touched.items():
        got = datasheets_db.load_obj(repaired.part)
        if got is None:
            problems.append('%s vanished' % (key,))
            continue
        remaining = duplicate_counts(got)
        if remaining:
            problems.append('%s still has duplicates: %s' % (key, dict(remaining)))
            continue
        before = sum(sum(len(v) for v in (repaired.fields_lists or {}).values())
                     for _ in [0])
        after = sum(len(v) for v in (got.fields_lists or {}).values())
        if before != after:
            problems.append('%s field count changed after write: %d -> %d'
                            % (key, before, after))

    if problems:
        print('\nPROBLEMS (%d):' % len(problems))
        for p in problems[:20]:
            print('  ', p)
        print('\nbackup kept at %s' % backup)
        return 1

    print('verified %d records; backup kept at %s' % (len(touched), backup))
    return 0


if __name__ == '__main__':
    sys.exit(main())
