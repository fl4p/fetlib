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
import sys
import time
import traceback
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
    args = ap.parse_args()

    db = datasheets_db.load()
    before_fields = _n_fields(db)
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

    after = _n_fields(datasheets_db.load(reload=True)) if args.apply else before_fields
    print()
    print('parsed ok %d | empty %d | failed %d' % (ok, empty, failed))
    print('fields %d -> %d  (%+d)' % (before_fields, after, after - before_fields))
    if failed:
        print('\nfirst failures:')
        for k, e in list(errors.items())[:10]:
            print('   %s  %s' % ('/'.join(k), e[:110]))
    # merge= makes a net loss structurally impossible; if it happens, something else wrote.
    if args.apply and after < before_fields:
        print('\nWARNING: field count DROPPED despite merge=. Another writer was active.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
