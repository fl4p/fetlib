"""Restore symbols a whole-record DB overwrite deleted, WITHOUT reintroducing known-bad values.

WHY THIS EXISTS, and why it is not recover_db_from_snapshot.py

A main.py run on 2026-07-27 14:57 wrote a narrower parse over the DB through the
then-unguarded `datasheets_db.add(dss)` (whole-record replacement; fixed since in
main.py by passing merge=). 88 records lost a symbol entirely -- Rg 42, Rds_on 26,
Id 23, Qsync 7, tDoff 5 -- while the same run legitimately ADDED 246 new records.

recover_db_from_snapshot.py is the wrong tool here and running it would lose work: it
takes the SNAPSHOT as base, which was right for the 12:03 incident (where "current" was a
stale-cache artifact) and is wrong for this one (where "current" is a legitimate fresh
parse holding 246 records the snapshot never had). Direction matters, so this script is
the other direction: base is the CURRENT db, and only symbols absent from it are restored.

That is exactly dslib.field.merge_keeping_absent_symbols(stored=snapshot, fresh=current),
i.e. the function committed for the live write, applied after the fact.

THE WITNESS GATE, which is the part that is not mechanical

A restore is not automatically an improvement. ~4.5% of stored Rds_on values are 1000x too
small (a unitless ohm-scale number read under the documented mOhm convention), and for
such a record the current DB having NO Rds_on is strictly better than having a plausible
wrong one -- a missing field is visibly missing, a 17 microOhm part silently wins every
ranking it enters.

So each candidate Rds_on is classified against an external witness (apps/audit_rds_witnesses:
MPN decode, else the vendor catalog value) and SKIPPED when it comes back 'scale-like',
meaning same digits, clean decade. Measured on the first run: 4 of 26 were scale-like --
SUP90140E 0.017 vs 17 mOhm, SUM90142E 0.015 vs 15, SUM90140E 0.017 vs 17, SUP90142E 0.0152
vs 15.2. Restoring those would have re-injected the corruption this session removed.

Symbols other than Rds_on have no witness mechanism, so they are restored unconditionally
and COUNTED SEPARATELY in the report. That is a real limit, not a clean bill of health:
absence of a witness is not evidence of correctness, and the report says so rather than
implying every restored field was checked.

    python3 apps/restore_lost_symbols.py            # dry run, prints every decision
    python3 apps/restore_lost_symbols.py --apply    # snapshot the db, then write
"""
import argparse
import math
import os
import pickle
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.field import merge_keeping_absent_symbols  # noqa: E402
from dslib.store import datasheets_db  # noqa: E402

DEFAULT_SNAPSHOT = 'data/datasheets-lib.pkl.bak-20260727-1419-pre-fugu150v'


def load_snapshot(path):
    """First-party file: a datasheets_db pickle this repo wrote on this machine."""
    with open(path, 'rb') as fh:
        return pickle.load(fh)


def _witness_verdict(mfr, mpn, cur_ds, value):
    """('skip'|'ok'|'unwitnessed', reference_or_None) for a candidate Rds_on in mOhm."""
    from apps.audit_rds_witnesses import mpn_milliohm, catalog_milliohm, classify

    if value is None or not math.isfinite(value) or value <= 0:
        # A non-finite candidate cannot be checked AND cannot be useful. Refuse it rather
        # than pass it through as "unwitnessed" -- unverifiable must not read as fine.
        return 'skip', None

    ref = mpn_milliohm(mfr, mpn)
    if ref is None:
        try:
            ref = catalog_milliohm(cur_ds)
        except Exception:
            ref = None
    if ref is None or not math.isfinite(ref) or ref <= 0:
        return 'unwitnessed', None

    cls, _k, _eq = classify(value, ref)
    return ('skip' if cls == 'scale-like' else 'ok'), ref


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

    def nf(db):
        return sum(sum(len(v) for v in ds.fields_lists.values()) for ds in db.values())

    print('snapshot : %d records %d fields  (%s)' % (len(snap), nf(snap), args.snapshot))
    print('current  : %d records %d fields' % (len(cur), nf(cur)))
    print()

    restored = Counter()
    skipped = Counter()
    unwitnessed = Counter()
    updates = {}
    skip_rows, ok_rows = [], []

    for key, sds in snap.items():
        cds = cur.get(key)
        if cds is None:
            # Not this script's job: a record absent from current was never overwritten,
            # it was never re-added. Reported by the caller's diff, not silently restored.
            continue
        missing = set(sds.fields_lists) - set(cds.fields_lists)
        if not missing:
            continue

        mfr, mpn = key
        donor_syms = {}
        for sym in missing:
            if sym == 'Rds_on':
                f = sds.fields_filled.get(sym)
                val = getattr(f, 'max', None) if f is not None else None
                if val is None or not math.isfinite(val):
                    val = getattr(f, 'typ_or_max_or_min', None) if f is not None else None
                verdict, ref = _witness_verdict(mfr, mpn, cds, val)
                if verdict == 'skip':
                    skipped[sym] += 1
                    skip_rows.append((mfr, mpn, val, ref))
                    continue
                if verdict == 'unwitnessed':
                    unwitnessed[sym] += 1
                else:
                    ok_rows.append((mfr, mpn, val, ref))
            else:
                unwitnessed[sym] += 1
            donor_syms[sym] = sds.fields_lists[sym]

        if not donor_syms:
            continue

        # Reuse the committed merge rather than re-implementing it: build a donor holding
        # only the approved symbols, so merge_keeping_absent_symbols' absent-symbol rule
        # does the actual splicing and this script cannot drift from the live write's
        # semantics.
        donor = type(sds)(part=sds.part)
        donor.fields_lists = donor_syms
        donor.fields_filled = {s: sds.fields_filled[s] for s in donor_syms
                               if s in sds.fields_filled}

        merged = merge_keeping_absent_symbols(donor, cds)
        for s, lst in donor_syms.items():
            restored[s] += len(lst)
        updates[key] = merged

    print('RESTORED (would be):')
    for s, n in restored.most_common():
        print('   %-12s %d fields' % (s, n))
    print('   %d records, %d fields total' % (len(updates), sum(restored.values())))
    print()
    print('SKIPPED by the witness gate -- restoring these would re-inject a 1000x error:')
    for mfr, mpn, val, ref in skip_rows:
        print('   %-10s %-20s stored %-10.5g vs witness %-8.4g mOhm' % (mfr, mpn, val, ref))
    print('   %d skipped' % sum(skipped.values()))
    print()
    print('Of the restored fields, checked against an external witness: %d' % len(ok_rows))
    print('NOT witness-checked (no mechanism for these symbols): %d fields across %s'
          % (sum(unwitnessed.values()), ', '.join('%s=%d' % kv for kv in
                                                  unwitnessed.most_common(8))))
    print('   ^ these are restored on the merge rule alone. Absence of a witness is not')
    print('     evidence that they are right.')

    if not args.apply:
        print('\nDRY RUN -- nothing written. Re-run with --apply.')
        return 0

    if not updates:
        print('\nnothing to do')
        return 0

    # Snapshot the live DB under a unique name before touching it. A fixed name would let a
    # second run copy the already-modified DB over the only good backup.
    backend = datasheets_db._backend_or_resolve()
    base = backend.path + '.bak-before-restore'
    dest, n = base, 1
    while os.path.exists(dest):
        dest = '%s.%d' % (base, n)
        n += 1
    backend.snapshot(dest)
    print('\nbacked up %s -> %s' % (backend.path, dest))

    before = nf(datasheets_db.load())
    # A list, not the dict: _items_to_dict asserts key_func is None for a dict, and this
    # store derives its key from the record. Passing merge= again is deliberate and a no-op
    # -- each value here already contains every symbol the stored record has -- but it keeps
    # this write on the same monotone path as the live one instead of a bare replacement.
    datasheets_db.add(list(updates.values()), merge=merge_keeping_absent_symbols)
    after = nf(datasheets_db.load(reload=True))
    print('fields %d -> %d  (%+d)' % (before, after, after - before))
    if after < before:
        print('WARNING: the field count DROPPED. Restore from %s and investigate.' % dest)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
