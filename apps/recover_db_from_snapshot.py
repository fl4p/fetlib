"""Rebuild datasheets_db from a richer snapshot, keeping fields only the current DB has.

WHY THIS EXISTS

A `main.py` run on 2026-07-27 12:03 served a stale/narrower `read_parts_datasheets` cache
entry and wrote it back over the DB with `overwrite=True` (main.py:326). Record keys were
unchanged (6040 both sides) but 1348 records lost 65,631 FIELDS within them -- Vds 6200,
Rg 5657, Rds_on 4192, Coss 4062, Qrr 3595, Qg 3152, tRise 2937 -- while 111 records gained
1398. `test_audit_rds_witnesses.py::test_corpus_membership_is_stable` caught it as 5282 ->
5046 comparable records.

Straight `cp` of the snapshot would throw away the 1398 gains, so this merges instead.

MERGE POLICY, deliberately narrow

Base is the snapshot. From the current DB it takes only fields whose SYMBOL IS ABSENT
ENTIRELY from the snapshot's record. It does NOT take a second candidate for a symbol the
snapshot already has, for two reasons:

  * such a candidate is a re-parse of the same row, so appending it piles near-duplicates
    into fields_lists and can shift the aggregate `fields_filled` in ways nothing here
    verifies;
  * the two sides are on DIFFERENT Rds_on_10v representations -- the snapshot predates the
    unit migration (unitless, ohm-scale) while the current DB is on canonical mΩ -- so
    comparing or merging candidates of that symbol by value is meaningless. The
    absent-symbol rule sidesteps it: the snapshot always has Rds_on_10v, so it is never
    merged, and `apps/migrate_rds_on_10v_unit.py` puts the result back on mΩ afterwards.

That is a lossy choice in one direction and it is stated rather than hidden: run with no
arguments to see exactly which symbols are merged and which candidates are skipped.

    python3 apps/recover_db_from_snapshot.py                      # dry run
    python3 apps/recover_db_from_snapshot.py --apply              # back up, merge, write
    python3 apps/migrate_rds_on_10v_unit.py --apply               # then re-migrate units
"""
import argparse
import os
import pickle
import shutil
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.store import datasheets_db  # noqa: E402

DEFAULT_SNAPSHOT = 'data/datasheets-lib.pkl.bak-r10v-unit'


def load_snapshot(path):
    """First-party file: a datasheets_db pickle this repo wrote on this machine. Pickle is
    the format the store already uses; nothing external is being deserialized here."""
    with open(path, 'rb') as fh:
        return pickle.load(fh)


def count_fields(db):
    return sum(sum(len(v) for v in ds.fields_lists.values()) for ds in db.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write the DB (default: dry run)')
    ap.add_argument('--snapshot', default=DEFAULT_SNAPSHOT)
    args = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    snap_path = args.snapshot if os.path.isabs(args.snapshot) \
        else os.path.join(repo, args.snapshot)
    if not os.path.exists(snap_path):
        print('no such snapshot: %s' % snap_path)
        return 1

    cur = datasheets_db.load()
    snap = load_snapshot(snap_path)

    n_cur, n_snap = count_fields(cur), count_fields(snap)
    print('current  : %d records, %d fields' % (len(cur), n_cur))
    print('snapshot : %d records, %d fields' % (len(snap), n_snap))
    print('snapshot is richer by %d fields' % (n_snap - n_cur))
    print()

    only_cur = set(cur) - set(snap)
    only_snap = set(snap) - set(cur)
    print('records only in current  : %d' % len(only_cur))
    print('records only in snapshot : %d' % len(only_snap))

    # Refuse the whole operation if the snapshot is not actually the richer state. Restoring
    # a POORER snapshot over the live DB is the failure mode this tool could most easily
    # cause, so it is checked rather than assumed.
    if n_snap <= n_cur:
        print('\nREFUSING: the snapshot has no more fields than the current DB (%d <= %d). '
              'That is not a recovery.' % (n_snap, n_cur))
        return 1

    merged_syms = Counter()
    skipped_cands = Counter()
    records_touched = 0
    kept_from_current = 0

    # Build the result: snapshot record, plus absent-symbol fields from current.
    out = {}
    for key, sds in snap.items():
        out[key] = sds
        cds = cur.get(key)
        if cds is None:
            continue
        added_here = 0
        for sym, lst in cds.fields_lists.items():
            if sym in sds.fields_lists:
                skipped_cands[sym] += len(lst)
                continue
            for f in lst:
                sds.add(f)
                merged_syms[sym] += 1
                added_here += 1
        if added_here:
            records_touched += 1
            kept_from_current += added_here

    # Records the snapshot never had at all: carry them over whole.
    carried = 0
    for key in only_cur:
        out[key] = cur[key]
        carried += 1

    print()
    print('records gaining an absent symbol from current : %d' % records_touched)
    print('fields merged in from current                 : %d' % kept_from_current)
    print('records present only in current, carried over : %d' % carried)
    print()
    print('merged symbols (absent from the snapshot record):')
    for s, n in merged_syms.most_common(20):
        print('   %-12s %d' % (s, n))
    if len(merged_syms) > 20:
        print('   ... %d more symbols' % (len(merged_syms) - 20))
    print()
    print('SKIPPED: extra candidates for symbols the snapshot already has')
    print('  (re-parses of the same rows; see the module docstring for why)')
    total_skipped = sum(skipped_cands.values())
    for s, n in skipped_cands.most_common(8):
        print('   %-12s %d' % (s, n))
    print('   total %d across %d symbols' % (total_skipped, len(skipped_cands)))

    result_fields = count_fields(out)
    print()
    print('result   : %d records, %d fields  (net %+d vs current)'
          % (len(out), result_fields, result_fields - n_cur))

    if not args.apply:
        print('\nDRY RUN -- nothing written. Re-run with --apply.')
        return 0

    if result_fields < n_snap:
        print('\nREFUSING: the merged result (%d) has fewer fields than the snapshot it was '
              'built from (%d). The merge lost data instead of recovering it.'
              % (result_fields, n_snap))
        return 1

    # Unique backup name -- a fixed one would let a second run copy the already-damaged DB
    # over the only good snapshot.
    base = datasheets_db._lib_path + '.bak-before-merge'
    backup, n = base, 1
    while os.path.exists(backup):
        backup = '%s.%d' % (base, n)
        n += 1
    if os.path.exists(datasheets_db._lib_path):
        shutil.copy2(datasheets_db._lib_path, backup)
        print('\nbacked up current -> %s' % backup)

    datasheets_db._lib_mem = out
    datasheets_db._write()
    print('wrote %d records, %d fields' % (len(out), result_fields))
    print('\nNEXT: run  python3 apps/migrate_rds_on_10v_unit.py --apply')
    print('The snapshot predates the Rds_on_10v unit migration, so that symbol is back on '
          'the unitless representation the reader now refuses.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
