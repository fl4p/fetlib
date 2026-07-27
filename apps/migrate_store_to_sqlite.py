"""Convert a whole-file pickle store (data/<name>.pkl) to the sqlite blob store.

    python3 apps/migrate_store_to_sqlite.py --db parts             # dry run, verifies only
    python3 apps/migrate_store_to_sqlite.py --db parts --apply
    python3 apps/migrate_store_to_sqlite.py --db datasheets --apply
    python3 apps/migrate_store_to_sqlite.py --db datasheets --export-pkl OUT.pkl

WHY THE VERIFICATION IS THIS HEAVY. The corpus is irreplaceable in practice -- re-parsing it
means days of Tabula/OCR -- and this repo has already lost 65,631 fields to a write that
looked fine. So the conversion is gated on a comparison that must FAIL LOUDLY rather than
pass by default:

  * every record is compared structurally, not a sample. At ~1 ms each that is ~10 s.
  * the comparator RAISES on any type it does not know how to compare. A comparator that
    returns True for "I could not evaluate this" is the anti-monotone false PASS -- it
    disappears exactly when the data is strangest.
  * NaN is compared as equal to NaN (59% of all stat values are NaN, and `nan != nan`
    would otherwise make every record "differ", which is just as useless as always-True).
  * numpy scalars are compared by value AND dtype, so a silent demotion to float is caught.
  * the field COUNT is asserted per record and in aggregate, because that is the unit every
    data-loss incident in this repo has been measured in.
  * a consumer-level check (get_row(), all_errors()) runs too, because a structural walk
    can miss drift in what the consumers actually read.

Nothing is renamed onto the live path until all of that passes.
"""
import argparse
import datetime
import math
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.store import _SqliteBackend, _encode_key, ENC_PICKLE, ENC_ZLIB  # noqa: E402

DBS = {
    'parts': 'parts-lib',
    'datasheets': 'datasheets-lib',
}


# --------------------------------------------------------------------------- comparison
def _is_nan(x):
    return isinstance(x, float) and math.isnan(x)


def deep_eq(a, b, path='', _depth=0):
    """Structural equality that RAISES rather than guessing.

    Returns a list of difference descriptions (empty == equal). Raises TypeError if it
    meets a value it cannot compare -- that is a gap in this function, and it must surface
    as a failed migration rather than as a clean bill of health.
    """
    if _depth > 40:
        raise TypeError('%s: recursion limit -- cyclic object graph?' % path)

    if a is b:
        return []
    if type(a) is not type(b):
        # int/float mixing is real in this corpus (Vds: int x11504, float x55) and is not
        # something the migration introduces -- pickle round-trips it exactly. So a type
        # change here IS a defect.
        return ['%s: type %s != %s' % (path, type(a).__name__, type(b).__name__)]

    if a is None or isinstance(a, (str, bytes, bool, int)):
        return [] if a == b else ['%s: %r != %r' % (path, a, b)]

    if isinstance(a, float):
        if _is_nan(a) and _is_nan(b):
            return []
        return [] if a == b else ['%s: %r != %r' % (path, a, b)]

    # numpy scalars/arrays: value AND dtype, so a demotion to builtin float is a difference
    mod = type(a).__module__
    if mod == 'numpy':
        import numpy as np
        if getattr(a, 'dtype', None) != getattr(b, 'dtype', None):
            return ['%s: dtype %r != %r' % (path, a.dtype, b.dtype)]
        if getattr(a, 'shape', ()) == ():
            av, bv = a.item(), b.item()
            if _is_nan(av) and _is_nan(bv):
                return []
            return [] if av == bv else ['%s: %r != %r' % (path, av, bv)]
        return [] if np.array_equal(a, b, equal_nan=True) else ['%s: array differs' % path]

    if isinstance(a, (datetime.datetime, datetime.date, datetime.timedelta)):
        return [] if a == b else ['%s: %r != %r' % (path, a, b)]

    if isinstance(a, dict):
        out = []
        if set(a) != set(b):
            out.append('%s: keys differ (+%r -%r)'
                       % (path, sorted(map(str, set(a) - set(b)))[:5],
                          sorted(map(str, set(b) - set(a)))[:5]))
        for k in set(a) & set(b):
            out += deep_eq(a[k], b[k], '%s[%r]' % (path, k), _depth + 1)
        return out

    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return ['%s: len %d != %d' % (path, len(a), len(b))]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += deep_eq(x, y, '%s[%d]' % (path, i), _depth + 1)
        return out

    if isinstance(a, (set, frozenset)):
        return [] if a == b else ['%s: set differs' % path]

    if hasattr(a, '__dict__'):
        return deep_eq(vars(a), vars(b), path + '.' + type(a).__name__, _depth + 1)

    raise TypeError('%s: no comparison rule for %s -- extend deep_eq() rather than '
                    'letting an uncomparable value read as equal' % (path, type(a)))


def n_fields(rec):
    """The metric every data-loss incident here is denominated in."""
    fl = getattr(rec, 'fields_lists', None)
    if fl is None:
        return None
    return sum(len(v) for v in fl.values())


def consumer_view(rec):
    """What the consumers actually read, as opposed to what the object holds."""
    out = {}
    for name in ('get_row', 'all_errors'):
        fn = getattr(rec, name, None)
        if callable(fn):
            try:
                out[name] = fn()
            except Exception as e:              # noqa: BLE001 - recorded, then compared
                out[name] = 'raised:%s:%s' % (type(e).__name__, e)
    return out


def verify(src: dict, dst_backend, label='') -> None:
    """Raise unless `dst_backend` holds exactly `src`."""
    got = dict(dst_backend.iter_all())

    if len(got) != len(src):
        raise SystemExit('%s: record count %d != %d' % (label, len(got), len(src)))
    missing, extra = set(src) - set(got), set(got) - set(src)
    if missing or extra:
        raise SystemExit('%s: key sets differ; missing=%r extra=%r'
                         % (label, sorted(missing)[:5], sorted(extra)[:5]))

    diffs, tot_a, tot_b = [], 0, 0
    for k, a in src.items():
        b = got[k]
        na, nb = n_fields(a), n_fields(b)
        if na != nb:
            # covers None-vs-int too: a record that lost its fields_lists entirely
            diffs.append('%r: field count %r != %r' % (k, na, nb))
        if na is not None:
            tot_a += na
            tot_b += nb if nb is not None else 0
        d = deep_eq(a, b, path=repr(k))
        if d:
            diffs.extend(d[:3])
        cv = deep_eq(consumer_view(a), consumer_view(b), path='%r.consumer' % (k,))
        if cv:
            diffs.extend(cv[:3])
        if len(diffs) > 40:
            break

    if tot_a != tot_b:
        raise SystemExit('%s: TOTAL field count %d != %d' % (label, tot_a, tot_b))
    if diffs:
        raise SystemExit('%s: %d difference(s):\n  %s'
                         % (label, len(diffs), '\n  '.join(diffs[:40])))
    print('  verified %d records%s, structurally identical'
          % (len(src), ', %d fields' % tot_a if tot_a else ''))


# --------------------------------------------------------------------------- safety
def refuse_if_busy(pkl_path):
    lock = pkl_path + '.lock'
    if os.path.exists(lock):
        try:
            with open(lock) as f:
                pid = int((f.read() or '0').strip() or 0)
        except (ValueError, OSError):
            pid = 0
        if pid:
            try:
                os.kill(pid, 0)
            except OSError:
                pid = 0                      # stale lock file, holder is gone
            else:
                raise SystemExit('refusing: %s is locked by live pid %d' % (pkl_path, pid))

    import subprocess
    try:
        out = subprocess.run(['pgrep', '-f', 'main\\.py'], capture_output=True, text=True)
    except OSError:
        return
    if out.stdout.strip():
        raise SystemExit('refusing: a main.py run is active (pids %s) and would write the '
                         'DB underneath this migration' % out.stdout.split())


# --------------------------------------------------------------------------- commands
def load_pickle(path):
    # local, self-produced artifact: data/*.pkl is written only by dslib.store from objects
    # this repo parsed, is gitignored, and never arrives over a network.
    with open(path, 'rb') as f:
        return pickle.load(f)


def calibrate(sample):
    """Make the comparator FAIL before trusting it to pass.

    A verification never seen to fire is not a verification. Each case below is a defect
    the migration could plausibly introduce; if any of them slips through as "equal", the
    heavy verify() above is decorative and the migration must not proceed.
    """
    import copy as _copy

    def must_differ(mutate, what):
        a = _copy.deepcopy(sample)
        b = _copy.deepcopy(sample)
        if mutate(b) is False:
            return  # case not applicable to this record type
        if not deep_eq(a, b, path='calib'):
            raise SystemExit('CALIBRATION FAILED: deep_eq did not detect %s -- the '
                             'verification is not measuring anything' % what)

    def drop_a_field(rec):
        fl = getattr(rec, 'fields_lists', None)
        if not fl:
            return False
        fl.pop(sorted(fl)[0])

    def change_a_number(rec):
        for holder in (getattr(rec, 'fields_filled', None) or {}).values():
            holder.max = (holder.max or 0) + 1.0
            return
        d = vars(rec)
        for k, v in d.items():
            if isinstance(v, float) and not math.isnan(v):
                d[k] = v + 1.0
                return
        return False

    def nan_to_none(rec):
        d = vars(rec)
        for k, v in d.items():
            if _is_nan(v):
                d[k] = None
                return
        return False

    def demote_numpy(rec):
        d = vars(rec)
        for k, v in d.items():
            if type(v).__module__ == 'numpy':
                d[k] = float(v)
                return
        return False

    must_differ(drop_a_field, 'a dropped symbol')
    must_differ(change_a_number, 'a changed value')
    must_differ(nan_to_none, 'NaN replaced by None')
    must_differ(demote_numpy, 'a numpy scalar demoted to float')

    # ...and the converse: NaN must compare EQUAL to NaN, or every record "differs" and
    # the check is just as useless in the other direction.
    a, b = _copy.deepcopy(sample), _copy.deepcopy(sample)
    if deep_eq(a, b, path='calib'):
        raise SystemExit('CALIBRATION FAILED: a record differs from its own copy '
                         '(NaN handling?) -- verify() would reject every valid migration')
    print('  comparator calibrated: fires on drop/change/NaN-loss/dtype-loss, '
          'quiet on an identical copy')


def migrate(name, apply_, force, enc):
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', name)
    pkl, sqlite_path, tmp = base + '.pkl', base + '.sqlite3', base + '.sqlite3.tmp'

    if not os.path.exists(pkl):
        raise SystemExit('no such pickle store: %s' % pkl)
    if os.path.exists(sqlite_path) and not force:
        raise SystemExit('%s already exists (pass --force to replace)' % sqlite_path)
    refuse_if_busy(pkl)

    import hashlib
    h = hashlib.sha256()
    with open(pkl, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    sha = h.hexdigest()

    print('reading %s (%.1f MB)' % (pkl, os.path.getsize(pkl) / 1e6))
    src = load_pickle(pkl)
    print('  %d records' % len(src))
    if not src:
        raise SystemExit('refusing to migrate an EMPTY store -- that is the shape of a '
                         'load failure, not a valid corpus')
    calibrate(src[max(src, key=lambda k: n_fields(src[k]) or 0)])

    for stale in (tmp, tmp + '-wal', tmp + '-shm'):
        if os.path.exists(stale):
            os.unlink(stale)

    be = _SqliteBackend(tmp, enc=enc)
    cx = be._conn()
    batch, n = 500, 0
    keys = list(src)
    for i in range(0, len(keys), batch):
        cx.execute('BEGIN IMMEDIATE')
        for k in keys[i:i + batch]:
            be._put(cx, k, _encode_key(k), src[k])
        cx.execute('COMMIT')
        n += len(keys[i:i + batch])
        print('\r  wrote %d/%d' % (n, len(keys)), end='', flush=True)
    print()

    be.set_meta('schema_version', be.SCHEMA_VERSION)
    be.set_meta('source_pkl', os.path.basename(pkl))
    be.set_meta('source_pkl_sha256', sha)
    be.set_meta('source_pkl_records', len(src))
    be.set_meta('migrated_at', datetime.datetime.now().isoformat())
    try:
        from dslib.field import field_repr_salt
        # informational ONLY: never gate on this. It moves on any edit to field.py, and a
        # store that refused to open after an unrelated comment change would be useless.
        be.set_meta('field_repr_salt_at_migration', field_repr_salt())
    except Exception as e:                                          # noqa: BLE001
        be.set_meta('field_repr_salt_at_migration', 'unavailable:%s' % e)

    cx.execute('VACUUM')
    cx.execute('PRAGMA optimize')
    be.close()

    print('verifying (reopened from disk)...')
    v1 = _SqliteBackend(tmp)
    verify(src, v1, label=name)
    v1.close()

    # round-trip: sqlite -> pickle -> compare, proving the codec lossless independently
    print('verifying round-trip back to pickle...')
    v2 = _SqliteBackend(tmp)
    rt = dict(v2.iter_all())
    v2.close()
    rt2 = pickle.loads(pickle.dumps(rt))
    v3 = _SqliteBackend(tmp)
    verify(rt2, v3, label=name + ' (round-trip)')
    v3.close()

    # Fold the WAL back into the main file and drop the sidecars, so what gets renamed is a
    # SINGLE self-contained database.
    #
    # The previous version renamed `-wal` and `-shm` alongside it. That is not safe: `-shm`
    # is a shared-memory index tied to the live connections (which were also never closed
    # here), and a `-wal` carries a salt bound to the database it was created against.
    # Moving them onto a different path can hand the next reader a store that is
    # transiently inconsistent rather than one that is obviously broken.
    ckpt = _SqliteBackend(tmp)._conn()
    ckpt.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    ckpt.execute('PRAGMA journal_mode = DELETE')   # collapses to one file
    ckpt.close()

    size = os.path.getsize(tmp)
    print('  %s: %.1f MB (was %.1f MB)' % (name, size / 1e6, os.path.getsize(pkl) / 1e6))

    if not apply_:
        for leftover in (tmp, tmp + '-wal', tmp + '-shm'):
            if os.path.exists(leftover):
                os.unlink(leftover)
        print('DRY RUN ok -- nothing written. Re-run with --apply.')
        return

    for stray in (tmp + '-wal', tmp + '-shm'):
        if os.path.exists(stray):
            raise SystemExit('refusing: %s still exists after the checkpoint; the store is '
                             'not self-contained and renaming it could corrupt it' % stray)
    os.replace(tmp, sqlite_path)
    # any sidecar left over from the PREVIOUS store at this path now describes a database
    # that no longer exists, so it must go rather than be reapplied to the new one
    for stale in (sqlite_path + '-wal', sqlite_path + '-shm'):
        if os.path.exists(stale):
            os.unlink(stale)
    print('wrote %s' % sqlite_path)
    print('the pickle is left untouched as the rollback snapshot: %s' % pkl)
    print('rollback: FETLIB_STORE=pickle, or delete the .sqlite3')


def export_pkl(name, dest):
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', name)
    sqlite_path = base + '.sqlite3'
    if not os.path.exists(sqlite_path):
        raise SystemExit('no sqlite store at %s' % sqlite_path)
    if os.path.exists(dest):
        raise SystemExit('refusing to overwrite %s' % dest)
    d = dict(_SqliteBackend(sqlite_path).iter_all())
    tmp = dest + '.tmp'
    with open(tmp, 'wb') as f:
        pickle.dump(d, f)
    os.replace(tmp, dest)
    print('exported %d records -> %s (%.1f MB)' % (len(d), dest, os.path.getsize(dest) / 1e6))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True, choices=sorted(DBS),
                    help='which store to convert')
    ap.add_argument('--apply', action='store_true',
                    help='actually write data/<name>.sqlite3 (default: dry run)')
    ap.add_argument('--force', action='store_true',
                    help='replace an existing .sqlite3')
    ap.add_argument('--compress', action='store_true',
                    help='zlib the blobs (~3.8x smaller, +0.5ms/write, +0.05ms/read)')
    ap.add_argument('--export-pkl', metavar='PATH',
                    help='write the sqlite store back out as a whole-file pickle')
    args = ap.parse_args()

    name = DBS[args.db]
    if args.export_pkl:
        return export_pkl(name, args.export_pkl)
    migrate(name, args.apply, args.force, ENC_ZLIB if args.compress else ENC_PICKLE)


if __name__ == '__main__':
    main()
