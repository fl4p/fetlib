"""Re-parse the whole datasheet corpus and merge the results back into datasheets_db.

WHY A FULL SWEEP. Fixing an extractor does not fix the stored numbers: a record keeps the
value from whichever cache generation wrote it. After the 2026-07-27 v2 header-guard fix,
seven ST parts still served Rds_on = 10000 mOhm, and st/STP150N10F7AG still served 55 mOhm
against a 4.2 mOhm witness, until each was individually re-parsed. Those were only FINDABLE
because they have external witnesses; the audit compares 5562 of 6286 records, so anything
without a witness that still holds a pre-fix parse is invisible. This sweep is how the
invisible remainder gets corrected.

The parse cache is NOT disabled. dslib/pdf/parse.py now lists dslib/v2 in
_PARSE_DERIVATION_SOURCES, so the outer parse_datasheet key already changed and every entry
misses; the expensive inner caches (tabula_read, ocrmypdf, rasterize_pdf, keyed on the pdf's
own content) stay warm. Passing --no-cache instead would re-run Tabula per part, which is
~298 s in the worst case observed -- days rather than hours, for no additional correctness.

SAFETY

  * every write goes through merge=merge_keeping_absent_symbols, so a part whose fresh parse
    is narrower than the stored record cannot cost fields. Fresh values still win where the
    parse produced them -- that is the point of the sweep;
  * results are written in BATCHES, so a crash keeps the work already done rather than
    losing hours of it;
  * --state records completed keys, so a re-run resumes instead of restarting;
  * a per-part exception is caught and counted, never allowed to kill its batch. A datasheet
    that cannot be parsed today is a skip, not a reason to abandon the other 6285.

Run a --limit smoke test first and read the rate it reports before starting the full sweep.

    python3 apps/reparse_all.py --limit 20            # smoke test, no write
    python3 apps/reparse_all.py --limit 20 --apply
    python3 apps/reparse_all.py --apply --jobs 8
"""
import argparse
import json
import os
import subprocess
import sys
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.field import merge_keeping_absent_symbols  # noqa: E402
from dslib.store import datasheets_db  # noqa: E402

DEFAULT_STATE = 'data/reparse_all.state.json'


def _pdf_path(mfr, mpn):
    p = os.path.join('datasheets', mfr, mpn + '.pdf')
    return p if os.path.exists(p) else None


def parse_one(mfr, mpn, path):
    """Worker. Returns (key, DatasheetFields|None, error_str|None).

    Catches everything: one unparseable sheet must not abort the sweep. The error is
    RETURNED rather than swallowed so the caller can count and report it -- a part that
    failed must not be indistinguishable from a part that produced nothing interesting.
    """
    warnings.simplefilter('ignore')
    try:
        from dslib.pdf.parse import parse_datasheet
        ds = parse_datasheet(pdf_path=path, mfr=mfr, mpn=mpn)
        if ds is None or not len(ds.fields_filled):
            return (mfr, mpn), None, 'empty'
        return (mfr, mpn), ds, None
    except Exception as e:
        return (mfr, mpn), None, '%s: %s' % (type(e).__name__, e)


def _n_fields(db):
    return sum(sum(len(v) for v in ds.fields_lists.values()) for ds in db.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write the DB (default: dry run)')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--batch', type=int, default=100)
    ap.add_argument('--limit', type=int, default=0, help='only the first N parts')
    ap.add_argument('--state', default=DEFAULT_STATE)
    ap.add_argument('--restart', action='store_true', help='ignore the resume state')
    ap.add_argument('--no-tabula-watchdog', action='store_true',
                    help='do not supervise the Tabula GUI server during the sweep. On by '
                         'default because a sweep is exactly the sustained load that '
                         'wedges it (~2 h observed, twice in one sweep: 500s, then '
                         'unreachable while pgrep still shows it alive); each wedge '
                         'inflates s/part with backoff retries and climbs the failure '
                         'count until someone restarts the app.')
    args = ap.parse_args()

    # Supervise Tabula for the lifetime of THIS process. The watchdog only engages if the
    # server (or the app) was already up -- on a machine not using the GUI server it
    # refuses and exits, so this spawn is a no-op there rather than a surprise launch.
    #
    # Deliberately NO atexit.terminate: --watch-pid already makes the watchdog exit on
    # its own within one probe interval of this process ending, and an explicit terminate
    # RACED an in-flight restart on the first smoke test -- it killed the watchdog after
    # `open -a` but before the come-up check, leaving a relaunched-but-unverified Tabula
    # that never started serving. A <=30 s straggler is harmless; a half-finished restart
    # is not.
    if not args.no_tabula_watchdog:
        # Failure to SPAWN the supervisor must be loud but not fatal: stdout=sys.stderr
        # needs a real file descriptor, and pytest capture / notebook kernels / logging
        # wrappers replace sys.stderr with fd-less streams -- crashing the whole sweep
        # before its first parse over a missing watchdog inverts the priorities. The
        # sweep ran unguarded for years; it degrades, it does not die.
        try:
            subprocess.Popen(
                [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              'tabula_watchdog.py'),
                 '--watch-pid', str(os.getpid())],
                stdout=sys.stderr, stderr=subprocess.STDOUT)
        except Exception as e:
            print('WARNING: tabula watchdog did not start (%s: %s) -- sweeping '
                  'UNSUPERVISED; a wedged Tabula will need a manual restart'
                  % (type(e).__name__, e))

    db = datasheets_db.load()
    before_fields = _n_fields(db)
    # Symbol sets, not field counts: the property merge= guarantees. Snapshotted BEFORE any
    # write so the final check compares against what this run actually started from.
    before_syms = {k: set(ds.fields_lists) for k, ds in db.items()}
    print('corpus: %d records, %d fields' % (len(db), before_fields))

    done = set()
    if os.path.exists(args.state) and not args.restart:
        with open(args.state) as fh:
            done = {tuple(k) for k in json.load(fh).get('done', [])}
        print('resume: %d parts already done' % len(done))

    todo, no_pdf = [], 0
    for (mfr, mpn) in sorted(db):
        if (mfr, mpn) in done:
            continue
        p = _pdf_path(mfr, mpn)
        if p is None:
            no_pdf += 1
            continue
        todo.append((mfr, mpn, p))
    if args.limit:
        todo = todo[:args.limit]

    print('to re-parse: %d   (no pdf on disk: %d)' % (len(todo), no_pdf))
    if not todo:
        print('nothing to do')
        return 0
    if not args.apply:
        print('\nDRY RUN -- will parse but NOT write. Re-run with --apply.')

    if args.apply:
        backend = datasheets_db._backend_or_resolve()
        base = backend.path + '.bak-before-reparse-all'
        dest, n = base, 1
        while os.path.exists(dest):
            dest = '%s.%d' % (base, n)
            n += 1
        backend.snapshot(dest)
        print('backed up %s -> %s' % (backend.path, dest))

    from joblib import Parallel, delayed

    t0 = time.time()
    ok = failed = empty = 0
    errors = {}
    for i in range(0, len(todo), args.batch):
        chunk = todo[i:i + args.batch]
        results = Parallel(n_jobs=args.jobs, backend='multiprocessing', verbose=0)(
            delayed(parse_one)(mfr, mpn, p) for mfr, mpn, p in chunk)

        fresh = []
        for key, ds, err in results:
            if err == 'empty':
                empty += 1
            elif err:
                failed += 1
                errors[key] = err
            else:
                ok += 1
                fresh.append(ds)

        if args.apply and fresh:
            datasheets_db.add(fresh, merge=merge_keeping_absent_symbols)
            done.update(k for k, ds, e in results if e is None)
            with open(args.state, 'w') as fh:
                json.dump({'done': [list(k) for k in done]}, fh)

        el = time.time() - t0
        n_done = i + len(chunk)
        rate = el / max(1, n_done)
        print('[%5d/%5d] ok=%d empty=%d failed=%d  %.1fs/part  eta %.1f min'
              % (n_done, len(todo), ok, empty, failed, rate,
                 rate * (len(todo) - n_done) / 60.0), flush=True)

    print()
    print('parsed ok %d | empty %d | failed %d' % (ok, empty, failed))
    if failed:
        print('\nfirst failures:')
        for k, e in list(errors.items())[:10]:
            print('   %s  %s' % ('/'.join(k), e[:110]))

    if args.apply:
        after_db = datasheets_db.load(reload=True)
        after = _n_fields(after_db)
        # The field count DROPPING is EXPECTED and is not the alarm. A fresh parse replaces
        # every stored candidate for each symbol it produced, so a record that held 7
        # near-duplicate tabula candidates and re-parses to 1 loses 6 fields while losing
        # nothing meaningful. The first version of this check compared field counts and, on
        # a fully healthy sweep (-36103 fields, 0 symbols lost, 2511 records GAINING a
        # symbol), reported "another writer was active" -- a false alarm with a confident
        # wrong diagnosis baked into its message. Field count is a proxy; the property
        # merge= actually guarantees is at SYMBOL level, so that is what is checked.
        print('fields %d -> %d  (%+d; candidate churn, informational)'
              % (before_fields, after, after - before_fields))
        sym_lost = {}
        for k, syms in before_syms.items():
            c = after_db.get(k)
            if c is None:
                sym_lost[k] = 'RECORD GONE'
            else:
                miss = syms - set(c.fields_lists)
                if miss:
                    sym_lost[k] = sorted(miss)
        if sym_lost:
            print('\nWARNING: %d records lost a SYMBOL across the sweep -- merge= cannot '
                  'do that, so either another writer was active or the merge is broken. '
                  'Examples:' % len(sym_lost))
            for k, v in list(sym_lost.items())[:10]:
                print('   %s  %s' % ('/'.join(k), v))
            return 1
        print('symbol-level check: no record lost a symbol')
    return 0


if __name__ == '__main__':
    sys.exit(main())
