"""Drop stale low-voltage v2 Vds candidates when a higher Vds rating is present.

A v2 header bug promoted chart/condition rows such as "Max. transient thermal impedance" into
headers, then read axis ticks (1 V / 10 V / 16 V) as Vds ratings. This repair is deliberately
narrow: it removes a low v2 Vds candidate only when the same record has another Vds candidate
at least 2x higher and at least 20 V. The higher sibling is then allowed to become the merged
Vds through the normal DatasheetFields.add rules.

Dry-run by default. `--apply` snapshots the store, rewrites only touched records, then reloads
from disk to verify the stale candidates are gone.
"""
import argparse
import collections
import math
import os
import sys
from copy import copy, deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.field import DatasheetFields
from dslib.store import datasheets_db

LOW_VDS_CUTOFF = 20.0
MIN_HIGH_RATIO = 2.0


def field_value(f):
    try:
        return f.max_or_min_or_typ
    except Exception:
        return math.nan


def is_v2(f):
    for v in getattr(f, '_sources', {}).values():
        vals = v if isinstance(v, list) else [v]
        if 'v2' in vals:
            return True
    return False


def should_drop_vds(f, fields):
    v = field_value(f)
    if math.isnan(v) or not is_v2(f) or abs(v) >= LOW_VDS_CUTOFF:
        return False
    for other in fields:
        if other is f:
            continue
        ov = field_value(other)
        if not math.isnan(ov) and abs(ov) >= LOW_VDS_CUTOFF and abs(ov) >= MIN_HIGH_RATIO * max(abs(v), 1.0):
            return True
    return False


def repair_record(ds):
    vds_fields = list((getattr(ds, 'fields_lists', None) or {}).get('Vds', []))
    drop_ids = {id(f) for f in vds_fields if should_drop_vds(f, vds_fields)}
    if not drop_ids:
        return None, []

    tmp = DatasheetFields(part=ds.part,
                          date_from_text=getattr(ds, 'date_from_text', None),
                          date_from_meta=getattr(ds, 'date_from_meta', None))
    dropped = []
    for sym, fields in (getattr(ds, 'fields_lists', None) or {}).items():
        for f in fields:
            if sym == 'Vds' and id(f) in drop_ids:
                dropped.append(f)
                continue
            tmp.add(deepcopy(f))

    repaired = copy(ds)
    repaired.fields_lists = tmp.fields_lists
    repaired.fields_filled = tmp.fields_filled
    repaired._field_keys = tmp._field_keys
    return repaired, dropped


def remaining_bad(ds):
    vds_fields = list((getattr(ds, 'fields_lists', None) or {}).get('Vds', []))
    return [f for f in vds_fields if should_drop_vds(f, vds_fields)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true', help='write the DB (default: dry run)')
    ap.add_argument('--limit', type=int, default=0, help='only inspect N records')
    ap.add_argument('--show', type=int, default=20, help='example changed parts to print')
    args = ap.parse_args()

    touched = {}
    dropped_count = 0
    by_mfr = collections.Counter()
    examples = []
    inspected = 0

    for key, ds in datasheets_db.iter_items():
        if args.limit and inspected >= args.limit:
            break
        inspected += 1
        repaired, dropped = repair_record(ds)
        if not dropped:
            continue
        assert repaired is not None
        touched[key] = repaired
        dropped_count += len(dropped)
        by_mfr[key[0]] += len(dropped)
        if len(examples) < args.show:
            examples.append((key, [(field_value(f), getattr(f, '_sources', None)) for f in dropped],
                             repaired.get_max_or_min_or_typ('Vds')))

    print('records inspected: %d' % inspected)
    print('records touched: %d' % len(touched))
    print('low v2 Vds candidates dropped: %d' % dropped_count)
    print()
    print('%-16s %8s' % ('mfr', 'dropped'))
    for mfr, n in by_mfr.most_common(20):
        print('%-16s %8d' % (mfr, n))
    print()
    print('=== examples ===')
    for key, dropped, new_vds in examples:
        print('  %-42s -> Vds %s dropped %s' % ('/'.join(map(str, key)), new_vds, dropped))

    if not args.apply:
        print('\nDRY RUN -- nothing written. Re-run with --apply to write.')
        return 0
    if not touched:
        print('\nNo stale v2 Vds candidates to write.')
        return 0

    lib = datasheets_db._lib_path
    backup = lib + '.pre-v2-vds-axis'
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
        bad = remaining_bad(got)
        if bad:
            problems.append('%s still has %d stale low v2 Vds candidates' % (key, len(bad)))
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
