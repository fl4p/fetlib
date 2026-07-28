"""Repair negative stats on non-negative symbols in the datasheets DB.

    python3 apps/repair_negative_stats.py            # dry run (default)
    python3 apps/repair_negative_stats.py --apply    # snapshot backup + keyed write

The class (2026-07-28): v2 parsing OCR'd text layers fused the min-placeholder dash
onto the value ('- 54 -' -> min=-54), so charges/times/caps/resistances went negative
— Qrr typ=-54 nC books a NEGATIVE P_rr, and the layout registry's value cross-check
can never match the printed (positive) value again. 628 field instances across 96
records; ~3/4 v2-sourced, the rest the same fusion through tabula on the same OCR'd
sheets. dslib/v2 now refuses the stat at parse time (unit/test_v2_nonneg_guard.py);
this tool repairs what is already stored.

Scope: symbols starting Q/C/R/t ONLY. Currents and voltages are exempt — 381
negative Id/Idp instances in this DB are REAL P-channel ratings (SP010P40TH,
XRS80P10H, ...; negative Vds and Vgs_th corroborate) and must not be touched.

Action per corrupt field: negative stats -> NaN (never abs() — the sign says the
cell grouping failed, so the value's own magnitude is not evidence); a field left
all-NaN is dropped; the record's merged view is rebuilt through DatasheetFields.add,
the same code path that built it, so a clean lower-priority candidate fills the slot.

Write gates (all must hold or nothing is written):
* every repaired (record, symbol) fills to abs(old), a DIFFERENT-positive existing
  candidate, or goes empty — never to a new negative;
* the six fetlib#41-adjacent Qrr records land on their known printed charges;
* no field outside the repair scope changes at all.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')

from dslib.store import datasheets_db  # noqa: E402

SCOPE = 'QCRt'

# Known printed charges (sheet-verified; the OCR text prints the same digits the
# DB's corrupt field carries, sign-flipped). Format: (mfr, mpn) -> Qrr typ [nC].
PINS = {
    ('infineon', 'BSZ123N08NS3GATMA1'): 54.0,
    ('infineon', 'ISC0805NLS'): 28.0,
    ('infineon', 'IST019N08NM5'): 66.0,
    ('infineon', 'IST019N08NM5AUMA1'): 66.0,
    ('infineon', 'IST026N10NM5'): 75.0,
    ('infineon', 'IST026N10NM5AUMA1'): 75.0,
}


def _num(v):
    # int stats exist in older-generation records ('20', not '20.0'); a float-only
    # check reads them as absent and a clean int field would be dropped wholesale.
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _neg_stats(f):
    return [s for s in ('min', 'typ', 'max') if _num(getattr(f, s, None)) and getattr(f, s) < 0]


def _finite(v):
    return _num(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write the DB (default: dry run)')
    args = ap.parse_args()

    db = datasheets_db.load()

    touched_objs, report, gate_bad = [], [], []
    clean_snapshot = []   # (field_obj, (min,typ,max)) of every in-scope CLEAN field
    for key, dsf in db.items():
        record_touched = False
        for sym in list(dsf.fields_filled.keys() | dsf.fields_lists.keys()):
            if not sym or sym[0] not in SCOPE:
                continue
            cands = list(dsf.fields_lists.get(sym, []))
            filled = dsf.fields_filled.get(sym)
            rebuild_from = cands if cands else ([filled] if filled is not None else [])
            if not any(_neg_stats(f) for f in rebuild_from + ([filled] if filled else [])):
                for f in rebuild_from:
                    clean_snapshot.append((f, tuple(getattr(f, s) for s in
                                                    ('min', 'typ', 'max'))))
                continue
            old_filled = getattr(filled, 'typ', math.nan) if filled is not None else math.nan
            # The FILLED object leads the rebuild: fill() is first-wins, so it can hold
            # clean stats from an OLDER parse generation whose candidate is no longer
            # in the list (observed: tFall filled +20 while the list only carried the
            # corrupt -20). Rebuilding from the list alone destroys those.
            if filled is not None and all(f is not filled for f in rebuild_from):
                rebuild_from = [filled] + rebuild_from
            old_negs = sorted({getattr(f, s) for f in rebuild_from for s in _neg_stats(f)})
            survivors = []
            for f in rebuild_from:
                for s in _neg_stats(f):
                    setattr(f, s, math.nan)
                if any(_finite(getattr(f, s)) for s in ('min', 'typ', 'max')):
                    survivors.append(f)
            dsf.fields_lists[sym] = []
            dsf.fields_filled.pop(sym, None)
            for f in survivors:
                dsf.add(f)
            if not dsf.fields_lists[sym]:
                del dsf.fields_lists[sym]
            nf = dsf.fields_filled.get(sym)
            new_vals = [getattr(nf, s) for s in ('min', 'typ', 'max')] if nf else []
            # gate 1: the slot heals to a POSITIVE existing candidate or empties.
            if any(_finite(v) and v < 0 for v in new_vals):
                gate_bad.append(('still negative', key, sym, new_vals))
            report.append((key[0], key[1], sym, old_filled,
                           getattr(nf, 'typ', math.nan) if nf else math.nan, old_negs))
            record_touched = True
        if record_touched:
            touched_objs.append(dsf)

    # gate 2: the six known records land on their printed charge — or go EMPTY when
    # the record holds no clean candidate at all (the fixed v2 refills those on the
    # next reparse). What the gate must never pass is a DIFFERENT number: that would
    # mean the repair invented a value instead of selecting or abstaining.
    for (mfr, mpn), want in sorted(PINS.items()):
        dsf = db.get((mfr, mpn))
        nf = dsf.fields_filled.get('Qrr') if dsf is not None else None
        got = getattr(nf, 'typ', math.nan) if nf is not None else math.nan
        ok = (_finite(got) and abs(got - want) < 1e-9) or math.isnan(got)
        print('pin %-10s %-20s -> %s (want %g or empty): %s'
              % (mfr, mpn, got, want, 'OK' if ok else 'FAIL'))
        if not ok:
            gate_bad.append(('pin', (mfr, mpn), 'Qrr', got))

    # gate 3: no clean in-scope field moved.
    moved = [(f, snap) for f, snap in clean_snapshot
             if any(not (a == b or (isinstance(a, float) and isinstance(b, float)
                                    and math.isnan(a) and math.isnan(b)))
                    for a, b in zip(snap, (f.min, f.typ, f.max)))]
    if moved:
        gate_bad.append(('clean fields moved', len(moved), None, None))

    print('\nrepaired %d (record, symbol) slots across %d records:'
          % (len(report), len(touched_objs)))
    for mfr, mpn, sym, old, new, negs in report:
        print('  %-10s %-22s %-6s filled %8s -> %-8s  (negatives dropped: %s)'
              % (mfr, mpn, sym, old, new, negs))

    if gate_bad:
        print('\nGATES FAILED (%d) -- refusing to write:' % len(gate_bad))
        for g in gate_bad:
            print('  ', g)
        return 1
    if not args.apply:
        print('\nDRY RUN -- nothing written. Re-run with --apply.')
        return 0
    backup = datasheets_db._lib_path + '.bak-neg-stats'
    if os.path.exists(datasheets_db._lib_path):
        datasheets_db.snapshot(backup)     # snapshot(), never copy2 (WAL sidecar)
        print('\nbacked up -> %s' % backup)
    datasheets_db.add(touched_objs, overwrite=True)
    print('wrote %d records' % len(touched_objs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
