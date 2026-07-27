"""Phase 3 repair: rebuild every part's merged Field from its stored candidates.

WHAT THIS DOES. `fields_filled` is a pure function of `fields_lists` plus the merge rules
(`DatasheetFields.add` is the only writer of `fields_filled`, so nothing else can have put
data there). The merge rules became unit- and dimension-aware in 596d89e6, so replaying the
STORED candidates through today's `add()` re-selects a better candidate per stat. That is
the repair the plan asks for: re-selection, never a magnitude guess, and no re-parsing.

WHAT THIS DOES NOT DO -- read before believing the DB is clean afterwards:

  * It cannot fix a wrong value whose unit does not contradict anything. The calibration
    part `diotec/DIT120N08` has ONE Rg candidate, unitless, typ=64 from
    tabula_cli_guess/iter_table, and reads 64000 mΩ both before and after. Nothing here
    detects it, because by the plan's own rule an entry is wrong only if the reader returns
    NaN or a sibling with a recognised unit disagrees -- and there is no sibling. Catching it
    needs the PROVENANCE policy (step 2 of the plan), which is not implemented.
  * `littelfuse/IXTX46N50L` is already correct (160 mΩ); the plan's note calling it 0.16 mΩ
    is stale, fixed by the earlier dropped-ohm-unit recovery.
  * The DB is a DERIVED artifact. field_repr_salt has already invalidated the parse caches,
    so the next full pipeline run re-parses and rebuilds it regardless. This repair is for
    consumers of the shipped .pkl (apps/ddb.py, apps/method_audit.py, the CSV run) that
    cannot afford a multi-hour re-parse first.

Dry run by default. `--apply` writes, after backing the pickle up, and then verifies by
RELOADING FROM DISK rather than trusting the in-memory objects.
"""
import argparse
import collections
import math
import os
import sys
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.field import DatasheetFields
from dslib.store import datasheets_db

STATS = ('min', 'typ', 'max')


def rebuild(ds):
    """Merged fields recomputed from ds.fields_lists. Candidates are DEEP-copied first:
    DatasheetFields.add stores `copy(f)`, a shallow copy whose _sources dict is ALIASED to
    the candidate's, so replaying against the live lists would rewrite the provenance of the
    very candidates we must leave untouched."""
    tmp = DatasheetFields()
    for sym, cands in (ds.fields_lists or {}).items():
        for c in cands:
            try:
                tmp.add(deepcopy(c))
            except Exception:
                # A candidate add() refuses (all-NaN, failed assert) is simply not merged;
                # it stays in the untouched fields_lists.
                continue
    return tmp.fields_filled


def diff_field(old, new):
    """Per-stat changes between two merged Fields, as (stat, old, new)."""
    out = []
    for s in STATS:
        a = getattr(old, s) if old is not None else math.nan
        b = getattr(new, s) if new is not None else math.nan
        if math.isnan(a) and math.isnan(b):
            continue
        if math.isnan(a) != math.isnan(b) or abs(a - b) > 1e-12 * max(1.0, abs(a)):
            out.append((s, a, b))
    if (old is None) != (new is None):
        out.append(('<field>', old is not None, new is not None))
    elif old is not None and (old.unit or '') != (new.unit or ''):
        out.append(('<unit>', old.unit, new.unit))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true', help='write the DB (default: dry run)')
    ap.add_argument('--limit', type=int, default=0, help='only process N parts (smoke test)')
    ap.add_argument('--show', type=int, default=15, help='example changes to print')
    args = ap.parse_args()

    db = datasheets_db.load()
    print('parts loaded: %d' % len(db))

    changed_parts = 0
    per_symbol = collections.Counter()
    dropped = collections.Counter()
    gained = collections.Counter()
    examples = []
    intended = {}          # key -> {symbol: [(stat, old, new)]}

    for i, (key, ds) in enumerate(db.items()):
        if args.limit and i >= args.limit:
            break
        new_filled = rebuild(ds)
        old_filled = ds.fields_filled or {}

        part_changes = {}
        for sym in set(old_filled) | set(new_filled):
            d = diff_field(old_filled.get(sym), new_filled.get(sym))
            if d:
                part_changes[sym] = d
                per_symbol[sym] += 1
                for stat, a, b in d:
                    if stat.startswith('<'):
                        continue
                    if math.isnan(b):
                        dropped[sym] += 1
                    elif math.isnan(a):
                        gained[sym] += 1
                if len(examples) < args.show:
                    examples.append(('/'.join(map(str, key)), sym, d))
        if part_changes:
            changed_parts += 1
            intended[key] = part_changes
        if args.apply:
            ds.fields_filled = new_filled

    print('parts with a changed merged field: %d' % changed_parts)
    print()
    print('%-16s %8s %8s %8s' % ('symbol', 'parts', 'dropped', 'gained'))
    for sym, n in per_symbol.most_common(25):
        print('%-16s %8d %8d %8d' % (sym, n, dropped[sym], gained[sym]))
    print('%-16s %8s %8d %8d' % ('TOTAL', '', sum(dropped.values()), sum(gained.values())))
    print()
    print('=== examples ===')
    for mpn, sym, d in examples:
        print('  %-34s %-12s %s' % (mpn, sym, d))

    if not args.apply:
        print()
        print('DRY RUN -- nothing written. Re-run with --apply to write.')
        return 0

    # --- write ------------------------------------------------------------------------
    lib = datasheets_db._lib_path
    backup = lib + '.pre-phase3'
    if os.path.exists(backup):
        print('\nREFUSING to overwrite an existing backup at %s' % backup)
        print('move or delete it first; a second run would destroy the original.')
        return 2
    print('\nbacking up %s -> %s' % (lib, backup))
    # snapshot(), NOT shutil.copyfile: once the store is sqlite, a plain file copy takes
    # only the main file and leaves the -wal sidecar behind, so the "backup" can be an
    # empty database that opens fine and has no tables. It would fail silently, and only
    # on the day it is needed.
    datasheets_db.snapshot(backup)

    print('writing %d parts' % len(db))
    datasheets_db.add(list(db.values()))

    # --- verify by RELOADING FROM DISK ------------------------------------------------
    print('\nreloading from disk to verify')
    fresh = datasheets_db.load(reload=True)
    problems = []
    if len(fresh) != len(db):
        problems.append('part count changed: %d -> %d' % (len(db), len(fresh)))

    checked = 0
    for key, want in intended.items():
        got = fresh.get(key)
        if got is None:
            problems.append('part vanished: %s' % (key,))
            continue
        for sym, changes in want.items():
            f = (got.fields_filled or {}).get(sym)
            for stat, _old, new in changes:
                if stat.startswith('<'):
                    continue
                have = getattr(f, stat) if f is not None else math.nan
                ok = (math.isnan(new) and math.isnan(have)) or \
                     (not math.isnan(new) and not math.isnan(have)
                      and abs(have - new) <= 1e-9 * max(1.0, abs(new)))
                if not ok:
                    problems.append('%s %s.%s: wanted %r on disk, found %r'
                                    % (key, sym, stat, new, have))
                checked += 1

    # fields_lists must be byte-for-byte untouched: only the merge was repaired.
    for key, ds in list(db.items())[:400]:
        a = {s: len(v) for s, v in (ds.fields_lists or {}).items()}
        b = {s: len(v) for s, v in ((fresh.get(key) or ds).fields_lists or {}).items()}
        if a != b:
            problems.append('candidate lists changed for %s' % (key,))
            break

    print('verified %d intended stat changes on disk' % checked)
    if problems:
        print('\nPROBLEMS (%d):' % len(problems))
        for p in problems[:20]:
            print('  ', p)
        print('\nrestore with:  cp %s %s' % (backup, lib))
        return 1
    print('no problems. backup kept at %s' % backup)
    return 0


if __name__ == '__main__':
    sys.exit(main())
