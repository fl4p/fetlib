"""Repair Qrr records whose micro-coulomb unit survived un-normalised into the DB.

WHY
    dslib/field.py's old Qrr fix demanded the unit be absent or exactly 'c' AND every
    stat sit in 0.1-0.9, so a whole class of mangled micro spellings fell through both
    tests: 'UC', micro-sign 'µC' (U+00B5), 'μC' with stray whitespace, and Infineon
    IRF*N20D/N15D text layers that mangle µC to 'PC'. Those fields store 1.3 for a
    1.3 µC charge — 1000x low — and the same scalar feeds the flat P_rr path in
    dcdc_buck_ls, so the parts have been under-charged for reverse recovery in every
    run ever made (docs/qrr-open-fixes-brief.md §2; same class as the Rds_on 1000x
    corruption). Field.__init__ now converts these at parse time, but a pickled Field
    bypasses __init__, so the records already in the DB need this pass.

HOW — and why the unit string is the anchor
    Field.__init__ scales and RENAMES in one step: values are multiplied exactly when
    the unit is rewritten to 'nC'. A surviving 'PC'/'UC'/'µC' therefore PROVES the
    conversion never ran on that field — no magnitude guessing needed, and a second
    run of this script is a no-op because the unit it writes ('nC') is not in the
    repair set. Each fields_lists candidate is a single-parse product with one
    consistent unit; fields_filled is NOT patched in place (fill() can merge stats
    from several candidates under one unit) but REBUILT by replaying
    DatasheetFields.add() over the repaired candidates — the same code path that
    built it, in the same insertion order.

    Bare 'C' fields are dropped, not scaled: at parse time the old band logic
    converted in-band values but left unit='C', so a stored ('C', 350) may be a
    correct conversion while a stored ('C', 1.3) is an unconverted µC mangle — the
    two cannot be told apart from the DB alone, and a lost 'n' vs a lost 'µ' differ
    by 1000x. A missing Qrr is recoverable (the field.py edit rotated
    field_repr_salt, so the next parse re-reads the PDF under the new refusal
    logic); a plausible wrong one is not.

GATES (all BLOCK --apply; a repair never seen to reproduce a known value is not one)
    * The six brief-documented parts (IRFB38N20D et al., true charge ~1.3 µC) must
      come out at 800-3000 nC with unit 'nC'.
    * Not one field whose unit was already trustworthy ('nC'/'nc'/None) may change —
      measured by value snapshot, not claimed by construction.
    * Every conversion must land in a physically plausible band (20-50000 nC).
    * The classifier is calibrated each run against a known-good and a known-bad
      input before touching the DB.

Usage:
    python3 apps/repair_qrr_units.py            # dry run, prints the full diff
    python3 apps/repair_qrr_units.py --apply    # snapshot the DB, then write
"""
import argparse
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from dslib.store import datasheets_db  # noqa: E402

# The six parts §2 of the brief verified against their PDFs ('1.3 2.0 C' printed with
# the µ glyph dropped; DB stores unit 'PC'). Ground-truth band, not exact values: the
# 41N15D family sits near the 38N20D's 1.3 µC but is not pinned to it.
PINNED_MICRO_PARTS = {
    ('infineon', 'IRFB38N20D'), ('infineon', 'IRFB41N15D'),
    ('infineon', 'IRFIB41N15D'), ('infineon', 'IRFS38N20D'),
    ('infineon', 'IRFS41N15D'), ('infineon', 'IRFSL38N20D'),
}
PIN_LO_NC, PIN_HI_NC = 800.0, 3000.0

# Any conversion landing outside this band is evidence the mangled-unit theory is
# wrong for that field -> the whole write is blocked, not just that field skipped.
PLAUSIBLE_LO_NC, PLAUSIBLE_HI_NC = 20.0, 50000.0

MICRO = 'convert'     # provably µC -> x1000, unit 'nC'
GOOD = 'good'         # nC/nc/None -> untouched, and MUST stay untouched
BARE_C = 'bare-c'     # bare 'C' -> decided per VALUE (see _bare_c_action)
UNKNOWN = 'unknown'   # anything else -> report, never guess

# _bare_c_action outcomes
C_CONVERT = 'c-convert'   # all stats in the 0.1-0.9 µ band -> x1000
C_KEEP = 'c-keep'         # all stats >= 100: identical under both readings -> keep
C_DROP = 'c-drop'         # the readings diverge 1000x -> remove the field


def classify(symbol, unit):
    """Mirror of Field.__init__'s repair-relevant unit decision (keep in lock-step)."""
    if not unit:
        return GOOD
    u = re.sub(r'\s+', '', unit)
    if u.lower() in {'uc', 'µc', 'μc', '∝c'} or \
            (symbol == 'Qrr' and u in {'PC', 'PSC', 'WC', 'mC'}):
        return MICRO
    if u.lower() == 'nc':
        return GOOD
    if u.lower() == 'c':
        return BARE_C
    return UNKNOWN


def _bare_c_action(f):
    """Bare 'C' is decided on the values, mirroring Field.__init__: the parse-time band
    logic converted in-band values but left unit='C', so a stored ('C', 600) is a
    correct conversion (or an equally-correct lost-'n' nC value — the two readings
    agree numerically at >= 100) while a stored ('C', 1.3) diverges 1000x between
    readings. Dropping the >= 100 class would PROMOTE a worse sibling candidate —
    observed on IXFN150N10, where the 'C' field held the correct 600 and an
    unconverted 'PSC' 0.6 would have replaced it."""
    nn = [getattr(f, s) for s in ('min', 'typ', 'max')
          if getattr(f, s) is not None and not math.isnan(getattr(f, s))]
    if nn and all(0.1 < v < 0.9 for v in nn):
        return C_CONVERT
    if nn and min(nn) >= 100:
        return C_KEEP
    return C_DROP


class _F:  # minimal stand-in for calibration
    def __init__(self, min=math.nan, typ=math.nan, max=math.nan):
        self.min, self.typ, self.max = min, typ, max


def _calibrate_classifier():
    """Known-good must pass through, known-bad must convert — refuse to run otherwise."""
    bad = [('PC', MICRO), ('UC', MICRO), ('µC', MICRO), ('μ C', MICRO), ('uc', MICRO),
           ('PSC', MICRO), ('WC', MICRO), ('mC', MICRO),
           ('C', BARE_C), ('c', BARE_C), (' C', BARE_C), ('C ', BARE_C)]
    good = [('nC', GOOD), ('nc', GOOD), (None, GOOD), ('', GOOD), ('  nC', GOOD)]
    for unit, want in bad + good:
        got = classify('Qrr', unit)
        if got != want:
            raise SystemExit('classifier calibration FAILED: unit %r -> %s, want %s'
                             % (unit, got, want))
    # the Qrr-only claim must stay narrow: 'PC' on another charge symbol is untouched
    if classify('Qg', 'PC') != UNKNOWN:
        raise SystemExit("classifier calibration FAILED: 'PC' must convert for Qrr only")
    for st, want in ((dict(typ=0.6), C_CONVERT), (dict(max=600.0), C_KEEP),
                     (dict(typ=1.3, max=2.0), C_DROP), (dict(typ=0.52, max=1.2), C_DROP),
                     (dict(typ=35.0), C_DROP)):
        got = _bare_c_action(_F(**st))
        if got != want:
            raise SystemExit('bare-C calibration FAILED: %s -> %s, want %s'
                             % (st, got, want))


def _stats(f):
    return {s: getattr(f, s) for s in ('min', 'typ', 'max')}


def _fmt(v):
    return 'nan' if (v is None or (isinstance(v, float) and math.isnan(v))) else '%g' % v


def _typ_or_max(f):
    for s in ('typ', 'max', 'min'):
        v = getattr(f, s)
        if v is not None and not math.isnan(v):
            return v
    return math.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write the DB (default: dry run)')
    args = ap.parse_args()

    _calibrate_classifier()

    db = datasheets_db.load()

    converted = []      # (mfr, mpn, unit, stats_before, stats_after)
    dropped = []        # (mfr, mpn, unit, stats)
    unknown = []        # (mfr, mpn, unit, stats)
    implausible = []    # conversions landing outside the plausibility band -> BLOCK
    pins_seen = {}      # pinned part -> resulting typ_or_max [nC] (from the FILLED view)
    touched_objs = []   # the records this run modified — the ONLY ones written on --apply
    good_before = []    # (field_obj, stats) for every trustworthy-unit Qrr field. The
                        # object reference is held ON PURPOSE: an id()-keyed dict would
                        # go stale when the rebuild replaces filled copies, and a freed
                        # object's id can be reused by a new Field.
    record_diff = []    # (mfr, mpn, filled_before_nC, filled_after_nC) for touched records
    touched_records = 0

    # Snapshot every trustworthy field's values FIRST, so gate 2 measures instead of
    # trusting that the repair loop cannot reach them.
    for key, dsf in db.items():
        for f in ([dsf.fields_filled['Qrr']] if 'Qrr' in dsf.fields_filled else []) + \
                list(dsf.fields_lists.get('Qrr', [])):
            if classify('Qrr', f.unit) == GOOD:
                good_before.append((f, _stats(f)))

    for (mfr, mpn), dsf in db.items():
        cands = list(dsf.fields_lists.get('Qrr', []))
        filled = dsf.fields_filled.get('Qrr')
        # Old-generation records may hold a filled field with no backing list; treat
        # the filled object as the single candidate then.
        rebuild_from = cands if cands else ([filled] if filled is not None else [])
        classes = [classify('Qrr', f.unit) for f in rebuild_from]
        f_cls = classify('Qrr', filled.unit) if filled is not None else GOOD
        if all(c == GOOD for c in classes) and f_cls == GOOD:
            continue
        touched_records += 1
        filled_before = _typ_or_max(filled) if filled is not None else math.nan

        survivors = []
        for f, cls in zip(rebuild_from, classes):
            if cls == BARE_C:
                cls = _bare_c_action(f)
            if cls in (MICRO, C_CONVERT):
                before = _stats(f)
                for s in ('min', 'typ', 'max'):
                    v = getattr(f, s)
                    if v is not None and not math.isnan(v):
                        setattr(f, s, v * 1e3)
                old_unit = f.unit
                if cls == MICRO:
                    f.unit = 'nC'  # C_CONVERT keeps 'C': band-decided, not unit-proven
                converted.append((mfr, mpn, old_unit, before, _stats(f)))
                tv = _typ_or_max(f)
                if not (PLAUSIBLE_LO_NC <= tv <= PLAUSIBLE_HI_NC):
                    implausible.append((mfr, mpn, old_unit, tv))
                survivors.append(f)
            elif cls == C_DROP:
                dropped.append((mfr, mpn, f.unit, _stats(f)))
            else:
                if cls == UNKNOWN:
                    unknown.append((mfr, mpn, f.unit, _stats(f)))
                survivors.append(f)

        # Rebuild the merged view through the SAME code path that built it. Clearing
        # fields_lists first because add() re-appends each candidate.
        dsf.fields_lists['Qrr'] = []
        dsf.fields_filled.pop('Qrr', None)
        for f in survivors:
            dsf.add(f)
        if not dsf.fields_lists['Qrr']:
            del dsf.fields_lists['Qrr']

        nf = dsf.fields_filled.get('Qrr')
        record_diff.append((mfr, mpn, filled_before,
                            _typ_or_max(nf) if nf is not None else math.nan))
        touched_objs.append(dsf)

    # The pin gate judges the FINAL state of all six, touched or not: a concurrent
    # pipeline run (same repo, other agent) re-parses records under the fixed
    # Field.__init__ and can heal a pinned part before this script reaches it —
    # observed live on IRFB38N20D/IRFB41N15D. "Already correct" must count as OK,
    # while "missing or still 1.3" must still block.
    for part in PINNED_MICRO_PARTS:
        dsf = db.get(part)
        nf = dsf.fields_filled.get('Qrr') if dsf is not None else None
        pins_seen[part] = (_typ_or_max(nf), nf.unit) if nf is not None else None

    # ---- gates ------------------------------------------------------------------
    pin_bad = []
    for part in sorted(PINNED_MICRO_PARTS):
        got = pins_seen.get(part)
        if got is None or got[1] != 'nC' or not (PIN_LO_NC <= got[0] <= PIN_HI_NC):
            pin_bad.append((part, got))

    def _same(a, b):
        return a == b or (isinstance(a, float) and isinstance(b, float)
                          and math.isnan(a) and math.isnan(b))

    good_changed = [(f, snap, _stats(f)) for f, snap in good_before
                    if any(not _same(snap[s], getattr(f, s))
                           for s in ('min', 'typ', 'max'))]

    # ---- report -----------------------------------------------------------------
    print('records with a non-good Qrr unit  : %d' % touched_records)
    print('fields converted x1000 -> nC      : %d' % len(converted))
    for mfr, mpn, u, b, a in converted:
        print('   %-10s %-18s %-4r  (%s,%s,%s) -> (%s,%s,%s)' % (
            mfr, mpn, u, _fmt(b['min']), _fmt(b['typ']), _fmt(b['max']),
            _fmt(a['min']), _fmt(a['typ']), _fmt(a['max'])))
    print('fields dropped (bare C, ambiguous): %d' % len(dropped))
    for mfr, mpn, u, s in dropped:
        print('   %-10s %-18s %-4r  (%s,%s,%s)' % (
            mfr, mpn, u, _fmt(s['min']), _fmt(s['typ']), _fmt(s['max'])))
    print('fields with unhandled unit (kept) : %d' % len(unknown))
    for mfr, mpn, u, s in unknown:
        print('   %-10s %-18s %-4r  (%s,%s,%s)' % (
            mfr, mpn, u, _fmt(s['min']), _fmt(s['typ']), _fmt(s['max'])))
    print()
    print('CONSUMED (filled) value per touched record — the whole-DB Qrr diff:')
    n_1000x = n_drop = n_same = n_other = 0
    for mfr, mpn, fb, fa in sorted(record_diff):
        if math.isnan(fb) and math.isnan(fa):
            tag = 'was-empty'
        elif math.isnan(fa):
            tag = 'DROPPED'
            n_drop += 1
        elif math.isnan(fb):
            tag = 'appeared'
            n_other += 1
        elif abs(fa / fb - 1000.0) < 1:
            tag = 'x1000'
            n_1000x += 1
        elif fa == fb:
            tag = 'unchanged'
            n_same += 1
        else:
            tag = 'x%.3g' % (fa / fb)
            n_other += 1
        print('   %-10s %-18s %10s -> %-10s %s' % (mfr, mpn, _fmt(fb), _fmt(fa), tag))
    print('   summary: %d x1000, %d dropped, %d unchanged, %d other'
          % (n_1000x, n_drop, n_same, n_other))
    print()
    print('pinned ground-truth parts (%d): %s' % (len(PINNED_MICRO_PARTS),
                                                  'ALL OK' if not pin_bad else 'FAILURES'))
    for part, got in sorted(pins_seen.items()):
        print('   %-10s %-18s -> %s' % (part[0], part[1],
                                        '%g nC [%s]' % got if got else 'MISSING'))
    print('trustworthy-unit fields changed   : %d  (must be 0)' % len(good_changed))
    for f, b, a in good_changed[:20]:
        print('   %r: %s -> %s' % (f, b, a))
    print('conversions outside %g-%g nC      : %d  (must be 0)'
          % (PLAUSIBLE_LO_NC, PLAUSIBLE_HI_NC, len(implausible)))
    for mfr, mpn, u, tv in implausible:
        print('   %-10s %-18s %-4r -> %g nC' % (mfr, mpn, u, tv))

    if not args.apply:
        print('\nDRY RUN -- nothing written. Re-run with --apply.')
        return 0

    if pin_bad:
        print('\nREFUSING TO WRITE: %d pinned part(s) did not land at their known '
              'charge.' % len(pin_bad))
        return 1
    if good_changed:
        print('\nREFUSING TO WRITE: %d trustworthy-unit field(s) were modified.'
              % len(good_changed))
        return 1
    if implausible:
        print('\nREFUSING TO WRITE: %d conversion(s) landed outside the plausible '
              'charge band.' % len(implausible))
        return 1
    if not converted and not dropped:
        print('\nnothing to write.')
        return 0

    backup = datasheets_db._lib_path + '.bak-qrr-units'
    if os.path.exists(datasheets_db._lib_path):
        # snapshot(), not shutil.copy2: a plain copy of a WAL-mode sqlite store misses
        # the -wal sidecar and yields a backup with no tables in it.
        datasheets_db.snapshot(backup)
        print('\nbacked up -> %s' % backup)

    # Keyed add() of ONLY the touched records, NOT save_all(db): another agent's
    # pipeline run writes this store concurrently (observed live), and rewriting the
    # whole point-in-time mapping would clobber every record it re-parsed since our
    # load — the exact read-modify-write race the SQLite migration exists to kill.
    datasheets_db.add(touched_objs, overwrite=True)
    print('wrote: %d converted, %d dropped across %d records'
          % (len(converted), len(dropped), len(touched_objs)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
