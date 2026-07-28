"""Repair the two regressions the 2026-07-28 full re-parse sweep introduced.

REGRESSION 1 -- .part loss (5641 of 6356 records). merge_keeping_absent_symbols returns
copy(fresh), and the sweep's parse_datasheet builds records with a bare MpnMfr part, so
every merged record silently swapped its stored DiscoveredPart (catalog specs, package,
provenance) for the bare one. The audit's catalog-witnessed population collapsed 5562 ->
1442 comparable records. The sweep's own symbol-level integrity check was blind to this:
it validated fields_lists symbols only -- one more proxy-vs-property hole, found the same
day the previous one was fixed.

Repair: reattach the backup's DiscoveredPart wherever the current record carries a bare
part and the backup has the real one. Nothing else about the record is touched.

REGRESSION 2 -- garbled-font tabular captures. On sheets whose text layer is scrambled
(unit cell reads 'Â' for Ohm and lands in the cond dict), the tabular stage wrote
ohm-scale NUMBERS with NO unit, which the documented unitless convention then reads as
mOhm: IPW65R041CFD stored 0.041 "mOhm" against a true 41 mOhm, 1000x low, on ~20
witnessed Infineon CFD parts -- and the same sweep wrote absurd v2 values on the
historically-excluded broken BSC sheets (2.1e9 mOhm from a front page). Before the sweep
these records had HONEST ABSENCE; the sweep replaced nothing-with-a-reason by
garbage-with-confidence, which is the worst trade this pipeline can make.

Repair, deliberately narrow, per (record, Rds_on):
  * witnessed: if the MPN decodes (apps.audit_rds_witnesses.mpn_milliohm) or the backup's
    catalog carries Rds_on_10v_max, and the CURRENT aggregate disagrees with the witness
    by >= 5x while the BACKUP state either agreed or had no Rds_on at all -> restore the
    symbol (fields_lists + fields_filled) from the backup.
  * unwitnessed: only the unambiguous shape -- a unitless aggregate BELOW 1.0, i.e.
    sub-milliohm, physically absent from this corpus (its floor is ~0.5 mOhm WITH a unit)
    and exactly the ohm-scale-read-as-mOhm signature -> restore from backup.
  Everything else is left alone: a unitless mOhm-scale value is the documented legacy
  representation, not damage.

Every decision is printed. Dry run by default.

    python3 apps/repair_sweep_regressions.py
    python3 apps/repair_sweep_regressions.py --apply
"""
import argparse
import math
import os
import pickle
import sqlite3
import sys
import zlib
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.store import ENC_ZLIB, _decode_key, datasheets_db  # noqa: E402

BACKUP = 'data/datasheets-lib.sqlite3.bak-before-reparse-all'


def load_backup(path):
    """First-party file: this repo's own sqlite snapshot, written by backend.snapshot."""
    con = sqlite3.connect(path)
    out = {}
    for k, enc, blob in con.execute('select k, enc, blob from records'):
        out[_decode_key(k)] = pickle.loads(zlib.decompress(blob) if enc == ENC_ZLIB else blob)
    return out


def agg_max_or_typ(ds, sym):
    """Aggregate value in CANONICAL mOhm, via the record's own reader.

    NOT the raw magnitude. The first version compared f.max directly and called the
    backup's 0.11 'Q' a disagreement with a 110 mOhm witness -- but 'Q' is a recognized
    OCR-mangled Ohm (unit quality 2), so that field READS as 110 mOhm and was correct all
    along. Comparing magnitudes without normalising units is the exact 1000x confusion
    this whole workstream exists to remove, reproduced inside the repair tool.
    """
    if ds is None or sym not in ds.fields_filled:
        return None
    try:
        v = ds.get_resistance_milliohm(sym, stat='max_or_typ')
    except Exception:
        return None
    return v if v is not None and isinstance(v, float) and math.isfinite(v) else None


def witness_milliohm(mfr, mpn, old):
    from apps.audit_rds_witnesses import mpn_milliohm
    ref = mpn_milliohm(mfr, mpn)
    if ref is not None:
        return ref
    specs = getattr(getattr(old, 'part', None), 'specs', None)
    v = getattr(specs, 'Rds_on_10v_max', None)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v * 1000.0 if v and math.isfinite(v) and v > 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--backup', default=BACKUP)
    args = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bak_path = args.backup if os.path.isabs(args.backup) else os.path.join(repo, args.backup)
    if not os.path.exists(bak_path):
        print('no such backup: %s' % bak_path)
        return 1

    cur = datasheets_db.load()
    old = load_backup(bak_path)
    print('current %d records, backup %d' % (len(cur), len(old)))
    assert len(old) > 1000, 'backup unreadable -- refusing to run against nothing'

    # ---- regression 1: parts
    parts_fixed = 0
    for k, d in cur.items():
        o = old.get(k)
        if o is None:
            continue
        if type(d.part).__name__ == 'MpnMfr' and type(o.part).__name__ == 'DiscoveredPart':
            d.part = o.part
            parts_fixed += 1
    print('\n[1] parts reattached from backup: %d' % parts_fixed)

    # ---- regression 2: Rds_on restores
    restored = []
    for k, d in cur.items():
        o = old.get(k)
        f = d.fields_filled.get('Rds_on')
        if f is None:
            continue
        now_v = agg_max_or_typ(d, 'Rds_on')
        if now_v is None or now_v <= 0:
            continue
        old_v = agg_max_or_typ(o, 'Rds_on')
        ref = witness_milliohm(k[0], k[1], o)

        reason = None
        if ref is not None:
            ratio = now_v / ref
            if ratio >= 5 or ratio <= 0.2:
                if old_v is None or (0.5 <= old_v / ref <= 2.0):
                    reason = 'witness %.4g mOhm, now %.5g (x%.3g), backup %s' % (
                        ref, now_v, ratio, 'absent' if old_v is None else '%.4g' % old_v)
        elif not (f.unit or '').strip() and now_v < 1.0:
            reason = 'unwitnessed unitless sub-milliohm %.5g, backup %s' % (
                now_v, 'absent' if old_v is None else '%.4g' % old_v)

        if reason is None:
            continue
        # restore the SYMBOL from backup: candidates and aggregate, or clean removal
        if o is not None and 'Rds_on' in o.fields_lists:
            d.fields_lists['Rds_on'] = list(o.fields_lists['Rds_on'])
            if 'Rds_on' in o.fields_filled:
                d.fields_filled['Rds_on'] = o.fields_filled['Rds_on']
            else:
                d.fields_filled.pop('Rds_on', None)
        else:
            d.fields_lists.pop('Rds_on', None)
            d.fields_filled.pop('Rds_on', None)
        restored.append((k, reason))

    print('\n[2] Rds_on restored from backup: %d' % len(restored))
    for k, r in restored[:30]:
        print('   %-32s %s' % ('/'.join(k), r))
    if len(restored) > 30:
        print('   ... %d more' % (len(restored) - 30))

    if not args.apply:
        print('\nDRY RUN -- nothing written. Re-run with --apply.')
        return 0

    backend = datasheets_db._backend_or_resolve()
    base = backend.path + '.bak-before-regression-repair'
    dest, n = base, 1
    while os.path.exists(dest):
        dest = '%s.%d' % (base, n)
        n += 1
    backend.snapshot(dest)
    print('\nbacked up -> %s' % dest)

    datasheets_db._lib_mem = cur
    datasheets_db._write()
    print('wrote %d records' % len(cur))
    return 0


if __name__ == '__main__':
    sys.exit(main())
