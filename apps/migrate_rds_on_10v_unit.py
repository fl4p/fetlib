"""Stamp the ohm unit onto the DB's unitless `Rds_on_10v` fields.

`MosfetBasicSpecs.fields()` now builds them with `unit='Ω'`, so `Field.__init__`
converts to the canonical mΩ on the way in and `_RESISTANCE_UNITLESS_TO_MILLI`
no longer carries an entry for the symbol. Records written before that change
hold an ohm-magnitude number with no unit, which the reader would now refuse.
This brings them onto the new representation: value x1000, unit 'mΩ'.

WHY A GATE, WHEN THE MULTIPLIER IS KNOWN

Every one of these fields is supposed to have come from
`MosfetBasicSpecs.fields()`, whose attribute `ensure_ohm()` forces to ohms -- so
x1000 is right *if that provenance holds for the field in front of us*. Asserting
it for 10908 fields because it is true of the code path is exactly the proxy
argument that put ~4.5% of Rds_on values out by 1000x. So each field is checked
against evidence carried in its own record:

  A. `part.specs.Rds_on_10v_max` -- the very attribute `fields()` was handed,
     still on the record, still in ohms. Equality proves the stored number is on
     the ohm scale. This is direct, not circumstantial.
  B. where A is unavailable, the record's own `Rds_on`: after x1000 the two
     should agree to within a factor, since both describe the same device at
     comparable Vgs.

A field that satisfies neither is REPORTED AND LEFT ALONE, never migrated on
faith. `--apply` additionally refuses to write unless the gate has been shown to
reject a deliberately mis-scaled input, because a gate that has never been seen
to fail proves nothing about the ones it passed.

Idempotent: only fields whose unit is empty are touched, and the unit is set as
part of the same step that scales, so a second run is a no-op rather than a
second x1000.

    python3 apps/migrate_rds_on_10v_unit.py            # dry run
    python3 apps/migrate_rds_on_10v_unit.py --apply    # back up, then write
"""
import argparse
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dslib.store import datasheets_db  # noqa: E402

# Ω -> mΩ. Stated rather than derived from _RESISTANCE_UNITLESS_TO_MILLI, which no longer
# has an Rds_on_10v entry -- that removal is what this migration exists to make safe.
OHM_TO_MILLI = 1e3

SPECS_REL_TOL = 1e-6      # gate A is an equality check on the same float
RDS_ON_FACTOR = 5.0       # gate B: Rds_on_10v within this factor of Rds_on


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def unitless_r10v_fields(dsf):
    """Every Rds_on_10v Field on the record with no unit, aggregate and per-source.

    `fields_filled` holds a `copy()` of the field, so the aggregate and the list entries
    are distinct objects and both need migrating. Deduped by identity anyway, so a future
    change that starts sharing them cannot cause a double scale.
    """
    seen = set()
    out = []
    for f in ([dsf.fields_filled.get('Rds_on_10v')]
              + list(dsf.fields_lists.get('Rds_on_10v', []))):
        if f is None or id(f) in seen:
            continue
        seen.add(id(f))
        if not (f.unit or '').strip():
            out.append(f)
    return out


def specs_ohms(dsf):
    """The record's discovery value in ohms, or None."""
    v = getattr(getattr(dsf, 'part', None), 'specs', None)
    v = getattr(v, 'Rds_on_10v_max', None)
    return float(v) if _finite(v) else None


def rds_on_milliohm(dsf):
    """The record's other on-resistance reading in mΩ, or None.

    Read through `get_resistance_milliohm` so this witness uses the same unit resolution
    as production rather than a second, privately-reimplemented one.
    """
    try:
        v = dsf.get_resistance_milliohm('Rds_on', stat='max_or_typ')
    except Exception:
        return None
    return v if _finite(v) and v > 0 else None


def gate(field_value, specs_ohm, rds_on_mohm):
    """(verdict, witness) for migrating `field_value` by x1000.

    verdict is 'specs' / 'rds_on' when a witness confirms the value is ohm-scale,
    'contradicted' when a witness is present and disagrees, and 'unwitnessed' when
    there is nothing to check against. Only the first two are safe to migrate, and
    the caller must not treat 'unwitnessed' as a pass.
    """
    if not _finite(field_value) or field_value <= 0:
        return 'unwitnessed', None

    if specs_ohm is not None:
        if math.isclose(field_value, specs_ohm, rel_tol=SPECS_REL_TOL):
            return 'specs', specs_ohm
        return 'contradicted', specs_ohm

    if rds_on_mohm is not None:
        ratio = (field_value * OHM_TO_MILLI) / rds_on_mohm
        if 1 / RDS_ON_FACTOR <= ratio <= RDS_ON_FACTOR:
            return 'rds_on', rds_on_mohm
        return 'contradicted', rds_on_mohm

    return 'unwitnessed', None


def calibrate(samples):
    """Feed the gate values that are ALREADY milliohm and count how many it catches.

    This is the positive control. Migrating an already-migrated field would multiply a
    milliohm number by 1000 again; if the gate cannot see that, passing it says nothing
    about the fields it approved. Returns (probed, blind).
    """
    probed = blind = 0
    for value, specs_ohm, rds_on_mohm in samples:
        if specs_ohm is None and rds_on_mohm is None:
            continue
        probed += 1
        verdict, _ = gate(value * OHM_TO_MILLI, specs_ohm, rds_on_mohm)
        if verdict != 'contradicted':
            blind += 1
    return probed, blind


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true',
                    help='write the DB (default: dry run)')
    ap.add_argument('--limit-report', type=int, default=15)
    args = ap.parse_args()

    db = datasheets_db.load()

    counts = {'specs': 0, 'rds_on': 0, 'contradicted': 0, 'unwitnessed': 0}
    contradicted = []
    calib_samples = []
    already_united = 0
    records_touched = set()
    to_migrate = []

    for (mfr, mpn), dsf in db.items():
        s_ohm = specs_ohms(dsf)
        r_mohm = rds_on_milliohm(dsf)

        for f in ([dsf.fields_filled.get('Rds_on_10v')]
                  + list(dsf.fields_lists.get('Rds_on_10v', []))):
            if f is not None and (f.unit or '').strip():
                already_united += 1

        for f in unitless_r10v_fields(dsf):
            value = f.max if _finite(f.max) else f.typ
            verdict, witness = gate(value, s_ohm, r_mohm)
            counts[verdict] += 1
            if verdict in ('specs', 'rds_on'):
                to_migrate.append(f)
                records_touched.add((mfr, mpn))
                calib_samples.append((value, s_ohm, r_mohm))
            elif verdict == 'contradicted':
                contradicted.append((mfr, mpn, value, witness))

    probed, blind = calibrate(calib_samples)

    total = sum(counts.values())
    print('unitless Rds_on_10v FIELDS         : %d  (fields_filled + fields_lists)' % total)
    print('  witnessed by part.specs (exact)  : %d' % counts['specs'])
    print('  witnessed by record Rds_on       : %d' % counts['rds_on'])
    print('  CONTRADICTED, left untouched     : %d' % counts['contradicted'])
    print('  unwitnessed, left untouched      : %d' % counts['unwitnessed'])
    print('  already carrying a unit (no-op)  : %d' % already_united)
    print('records affected                   : %d of %d' % (len(records_touched), len(db)))
    print()
    if contradicted:
        print('contradicted (a witness disagrees that this is ohm-scale):')
        for mfr, mpn, value, witness in contradicted[:args.limit_report]:
            print('   %-10s %-22s stored=%-12.6g witness=%-12.6g ratio=%.4g'
                  % (mfr, mpn, value, witness,
                     (value / witness) if witness else float('nan')))
        if len(contradicted) > args.limit_report:
            print('   ... %d more' % (len(contradicted) - args.limit_report))
        print()
    print('gate calibration (would an already-migrated value be caught?)')
    print('  probed                           : %d' % probed)
    print('  gate BLIND to a double x1000     : %d' % blind)

    if not args.apply:
        print('\nDRY RUN -- nothing written. Re-run with --apply.')
        return 0

    if not to_migrate:
        print('\nnothing to migrate.')
        return 0
    if not probed:
        print('\nREFUSING TO WRITE: the gate was never exercised against a mis-scaled '
              'input, so its approvals are unvalidated.')
        return 1
    if blind:
        print('\nREFUSING TO WRITE: the gate is blind to a double x1000 on %d of %d probed '
              'values, so passing it proves nothing.' % (blind, probed))
        return 1

    # NEVER overwrite an existing backup. The name used to be fixed, which meant a second
    # --apply would copy the CURRENT (possibly already-damaged) pickle over the only
    # pre-migration snapshot -- destroying the very thing a backup exists for at exactly the
    # moment it is needed. This migration genuinely did have to be re-run after an unrelated
    # cache write reverted part of it, so this is the normal case, not an edge case.
    if os.path.exists(datasheets_db._lib_path):
        base = datasheets_db._lib_path + '.bak-r10v-unit'
        backup = base
        n = 1
        while os.path.exists(backup):
            backup = '%s.%d' % (base, n)
            n += 1
        shutil.copy2(datasheets_db._lib_path, backup)
        print('\nbacked up -> %s' % backup)
        if backup != base:
            print('  (kept the earlier snapshot at %s)' % base)

    for f in to_migrate:
        for stat in ('min', 'typ', 'max'):
            v = getattr(f, stat)
            if _finite(v):
                setattr(f, stat, v * OHM_TO_MILLI)
        # Scale and unit in one step: a second run sees 'mΩ' and skips the field.
        f.unit = 'mΩ'

    datasheets_db._lib_mem = db
    datasheets_db._write()
    print('wrote %d fields across %d records' % (len(to_migrate), len(records_touched)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
