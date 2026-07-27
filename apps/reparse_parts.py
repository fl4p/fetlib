"""Force a fresh parse of named parts and merge the result into datasheets_db.

WHY: a parse defect that has already been FIXED in code still leaves its wrong value in the
DB, because parse results are cached and the DB record was written from the old cache
generation. Fixing the extractor is only half the repair; the stored number stays wrong
until something re-parses. The v2 header guard (dslib/v2/tables.py
_header_match_is_incidental) is the case this was written for: four ST parts stored
Rds_on = 10000 mOhm read out of a condition cell, against a true 0.069 Ohm = 69 mOhm.

The write goes through `merge=merge_keeping_absent_symbols`, which means:

  * for a symbol the fresh parse DID produce, the fresh value REPLACES the stored one --
    that is the point here, the stored one is the corrupt value we are removing;
  * a symbol the fresh parse did not produce is kept from the stored record rather than
    deleted, so a re-parse narrower than the DB record cannot cost fields. That is the
    same rule main.py's live write uses.

Verification is not optional and not a formality: --expect takes 'MPN=milliohm' and the
script REPORTS PER PART whether the re-parse actually produced it. A re-parse that silently
produced nothing, or produced the same wrong number, must not look like a success.

    python3 apps/reparse_parts.py --mfr st STD20NF20 STF20NF20 STP20NF20 STP50NF25 \
        --expect STD20NF20=125 --expect STF20NF20=125 --expect STP20NF20=125 \
        --expect STP50NF25=69
    python3 apps/reparse_parts.py --mfr st STP50NF25 --apply
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.cache import disk_cache_disable  # noqa: E402
from dslib.field import merge_keeping_absent_symbols  # noqa: E402
from dslib.store import datasheets_db  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mpns', nargs='+')
    ap.add_argument('--mfr', required=True)
    ap.add_argument('--apply', action='store_true', help='write the DB (default: dry run)')
    ap.add_argument('--expect', action='append', default=[],
                    help='MPN=milliohm, the externally-known Rds_on to check against')
    args = ap.parse_args()

    expect = {}
    for e in args.expect:
        k, _, v = e.partition('=')
        expect[k.strip()] = float(v)

    # The whole point is to bypass the generation that produced the wrong value. Without
    # this the run is a no-op that LOOKS like a repair.
    disk_cache_disable(True)
    from dslib.pdf.parse import parse_datasheet

    db = datasheets_db.load()
    fresh_records, report = {}, []

    for mpn in args.mpns:
        key = (args.mfr, mpn)
        stored = db.get(key)
        path = 'datasheets/%s/%s.pdf' % (args.mfr, mpn)
        if not os.path.exists(path):
            report.append((mpn, 'NO PDF', None, None, False))
            continue

        ds = parse_datasheet(pdf_path=path, mfr=args.mfr, mpn=mpn)
        if ds is None or not len(ds.fields_filled):
            report.append((mpn, 'PARSE EMPTY', None, None, False))
            continue

        def rds(rec):
            """The RAW Rds_on field, deliberately NOT select_rds_on_milliohm().

            The selector prefers Rds_on_10v, which for these four parts was already
            correct -- so measuring it reported 125/125/125/69 for the DAMAGED records and
            would have called a re-parse that did nothing a success. The quantity being
            repaired is the Rds_on FIELD, so that is the quantity to check.
            """
            if rec is None:
                return None
            f = rec.fields_filled.get('Rds_on')
            if f is None:
                return None
            v = f.max if f.max == f.max else f.typ
            return None if v is None or not math.isfinite(v) else v

        before, after = rds(stored), rds(ds)
        want = expect.get(mpn)
        ok = want is None or (after is not None and abs(after - want) <= 0.02 * want)
        report.append((mpn, 'ok', before, after, ok))
        fresh_records[key] = ds

    print('%-14s %12s %12s %10s' % ('mpn', 'stored', 'reparsed', 'expected'))
    all_ok = True
    for mpn, status, before, after, ok in report:
        want = expect.get(mpn)
        print('%-14s %12s %12s %10s  %s' % (
            mpn,
            'n/a' if before is None else '%.4g' % before,
            status if status != 'ok' else ('n/a' if after is None else '%.4g' % after),
            'n/a' if want is None else '%.4g' % want,
            'OK' if ok else 'MISMATCH'))
        all_ok = all_ok and ok

    if not all_ok:
        print('\nAt least one part did not reach its expected value. NOT writing.')
        return 1
    if not args.apply:
        print('\nDRY RUN -- nothing written. Re-run with --apply.')
        return 0
    if not fresh_records:
        print('\nnothing to write')
        return 1

    backend = datasheets_db._backend_or_resolve()
    base = backend.path + '.bak-before-reparse'
    dest, n = base, 1
    while os.path.exists(dest):
        dest = '%s.%d' % (base, n)
        n += 1
    backend.snapshot(dest)
    print('\nbacked up %s -> %s' % (backend.path, dest))

    datasheets_db.add(list(fresh_records.values()), merge=merge_keeping_absent_symbols)
    print('wrote %d records' % len(fresh_records))

    reloaded = datasheets_db.load(reload=True)
    for (mfr, mpn) in fresh_records:
        rec = reloaded.get((mfr, mpn))
        print('  %-14s now Rds_on=%s mOhm' % (mpn, rec.select_rds_on_milliohm(stat='max')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
