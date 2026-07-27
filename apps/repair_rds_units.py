"""Repair Rds_on records whose unit cell was dropped during extraction.

WHY
    A resistance Field that reaches the DB with no unit lands on the reader's unitless
    default (`_RESISTANCE_UNITLESS_TO_MILLI['Rds_on'] = 1.0`, i.e. "already milliohm").
    For every sheet that quotes ohms -- overwhelmingly the high-voltage superjunction
    parts -- that is 1000x too LOW, and low is the dangerous direction: the part looks
    1000x better than it is and sorts straight to the top of a loss-ranked CSV. Measured
    on the shipped DB: 774 of 5667 Rds_on records are unitless and ~126 of them are wrong
    by exactly 1000x.

    The extractor bug itself is fixed in dslib/pdf/parse.py (the `iter_table` branch used
    the sticky table unit and ignored the row's own reconstructed unit cell), but that only
    helps parts that get re-parsed -- a full tabular re-parse is ~177 s/part. This repairs
    the records already in the DB.

HOW -- and why it is value-anchored
    The first version of this looked up "the unit near an RDS(on) row" and was wrong on 120
    of 121 checkable parts. Infineon front pages advertise

        'RDS(on),max'  '120'  'mΩ'

    while the characteristics table on a later page states the same parameter as

        'RDS(on)'  '-' '-' '0.103' '0.231' '0.120' '-'  'Ω'

    Both are RDS(on), both carry a real resistance unit, and they disagree by 1000x. Taking
    the unit from one block and the number from another is precisely how a parse failure
    turns into a believable wrong number, so the unit is only accepted from a block that
    CONTAINS THE STORED VALUE. No containing block -> unrecoverable -> the record keeps its
    missing unit rather than acquiring a guessed one.

GATE
    Infineon CoolMOS and Vishay MPNs encode the on-resistance (IPW60R120C7 -> 120 mΩ,
    SQD50N10-8M9L -> 8.9 mΩ). Every repair that can be checked against its own part number
    is checked, and --apply REFUSES to write if a single one disagrees. A repair pass that
    has never been seen to reproduce a known-good value is not a repair pass.

Usage:
    python3 apps/repair_rds_units.py            # dry run, prints what would change
    python3 apps/repair_rds_units.py --apply    # back up the pickle, then write
"""
import argparse
import math
import os
import re
import shutil
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from dslib.field import ohm_unit_to_milli_mul  # noqa: E402
from dslib.store import datasheets_db  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

SYM = re.compile(r'(R\s*DS\s*\(on\)|RDS\(on\)|drain[- ]source on[- ]?(state )?resistance'
                 r'|static drain[- ]to[- ]source on[- ]resistance|on[- ]state resistance)', re.I)
NUM = re.compile(r'^[\d.]+$')

# MPN-encoded on-resistance, in milliohm. Only used as a GATE, never as a data source, so a
# missed part costs one skipped check while a WRONG nominal invents a spurious alarm (or
# waves a real one through). Hence: keyed on manufacturer, and None whenever unsure.
#   Infineon CoolMOS  IPW60R024CFD7   -> R024 = 24 mΩ
#   Vishay            SQD50N10-8M9L   -> 8M9  = 8.9 mΩ
# Unkeyed, the Vishay pattern read Nexperia's BUK7Y3R1-80MX as 80 mΩ -- '-80M' is the 80 V
# rating and 'X' a package code, while the actual resistance is the '3R1' (3.1 mΩ) before
# the dash. It then reported the correct 3.1 mΩ record as a 26x scale error.
RE_VISHAY = re.compile(r'-(\d{1,3})M(\d)?')
RE_INFINEON = re.compile(r'^I[A-Z]{1,3}\d{2}[RT](\d{3})')

# Ω as rendered by the custom/broken font encodings in some Infineon sheets ('Â' in
# IPW65R048CFDA, where the symbol cell itself comes out as 'R‡»ñÓÒò'). Confined to reading
# RAW PDF TEXT here on purpose: dslib.field._OHM_BODY is consulted on every DB read, and
# teaching it one broken font's mojibake would eventually launder a mis-captured cell.
# Real omega codepoints are NOT listed: ohm_unit_to_milli_mul already accepts them, so
# they never reach _mojibake_ohm. This set is only the genuinely broken renderings.
PDF_OHM_MOJIBAKE = {'Â', 'Ã'}

BLOCK_SPAN = 14  # lines after the symbol row that still belong to its table entry


def mpn_nominal_milliohm(mpn, mfr=None):
    """Rds_on in mΩ as encoded in the part number, or None.

    `mfr` is REQUIRED to get an answer: these conventions are per-family and only collide
    when applied blindly. Nexperia's BUK7Y3R1-80MX is 3.1 mΩ / 80 V, and letting the Vishay
    pattern near it matched the '-80M' of the voltage rating, turning a correct 3.1 mΩ
    record into a reported 26x scale error. An unknown mfr therefore declines rather than
    trying every pattern -- for a gate, a skipped check costs far less than a false alarm
    (or a false pass).
    """
    if mfr == 'infineon':
        g = RE_INFINEON.match(mpn)
        if g:
            return float(g.group(1))
    elif mfr == 'vishay':
        g = RE_VISHAY.search(mpn)
        if g:
            return float(g.group(1) + ('.' + g.group(2) if g.group(2) else ''))
    return None


# Gate band. Calibrated to the ERROR CLASS this repair can introduce, which is a unit-scale
# mistake and therefore always a factor of 1000 (mΩ<->Ω) or 1e6 (mΩ<->kΩ) -- never 2x.
#
# It deliberately does NOT try to distinguish typ from max, or 25°C from 150°C. Those are
# real and large: IPL65R130C7AUMA1 states 0.115 (typ 25°C), 0.276 (typ 150°C) and 0.130 (max
# 25°C) in one row against a single 'Ω', and the MPN's "130" is the 25°C max, so a stored
# hot-temperature value legitimately reads 2.12x nominal. An earlier [0.5, 1.6] band called
# that a repair failure and blocked the whole run.
#
# [0.1, 10] keeps a 100x margin against the 1000x class while clearing every legitimate
# spread, so the two are cleanly separated rather than traded off.
GATE_LO, GATE_HI = 0.1, 10.0
SCALE_ERROR = 1000.0


def gate_agrees(got_milliohm, nominal_milliohm):
    return GATE_LO < got_milliohm / nominal_milliohm < GATE_HI


def gate_rejects_scale_error(got_milliohm, nominal_milliohm):
    """True if the gate would catch this value mis-scaled by 1000x in EITHER direction.
    Run against every passing repair so the band cannot silently widen past its purpose."""
    return (not gate_agrees(got_milliohm * SCALE_ERROR, nominal_milliohm)
            and not gate_agrees(got_milliohm / SCALE_ERROR, nominal_milliohm))


def _mojibake_ohm(cand):
    """'Â' -> 'Ω', 'mÂ' -> 'mΩ', else None.

    The SI prefix must survive. Mapping a mangled 'mΩ' cell onto a bare 'Ω' would be the
    same 1000x error this whole exercise is about, just pointing the other way (too HIGH),
    so the prefix is carried through rather than assumed absent.
    """
    if cand in PDF_OHM_MOJIBAKE:
        return 'Ω'
    if len(cand) > 1 and cand[0] in 'mkM' and cand[1:] in PDF_OHM_MOJIBAKE:
        return cand[0] + 'Ω'
    return None


def _blocks(doc):
    for page in doc:
        lines = [l.strip() for l in page.get_text().split('\n')]
        for i, line in enumerate(lines):
            if SYM.search(line):
                yield lines[i:i + BLOCK_SPAN]


def _read_blocks(pdf_path):
    """[(numbers, unit-strings)] for each Rds_on block in the PDF. One open per PDF."""
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return []
    out = []
    with doc:
        for blk in _blocks(doc):
            nums, units = [], []
            for cand in blk:
                if NUM.match(cand):
                    nums.append(float(cand))
                elif ohm_unit_to_milli_mul(cand) is not None:
                    units.append(cand)
                else:
                    moj = _mojibake_ohm(cand)
                    if moj:
                        units.append(moj)
            if units:
                out.append((nums, units))
    return out


def unit_for_value(blocks, value, rel=1e-9):
    """The unit of the block that actually contains `value`, or None.

    None on: no block containing the value, or containing blocks that disagree on scale.
    Both are 'I cannot tell', and must stay that way -- the caller then writes nothing.

    Resolved PER VALUE, never once per part: a single datasheet can hold several Rds_on
    rows (sibling MPNs, Tj=25/175 sub-rows) and they need not share a unit, so reusing one
    part-level multiplier for every field in the record would be the same
    unit-from-here/number-from-there mistake at a smaller scale.
    """
    hits = set()
    for nums, units in blocks:
        if not any(math.isclose(n, value, rel_tol=rel) for n in nums):
            continue
        if len({ohm_unit_to_milli_mul(u) for u in units}) == 1:
            hits.add(sorted(units)[0])
    if len(hits) == 1:
        return hits.pop()
    if len(hits) > 1 and len({ohm_unit_to_milli_mul(u) for u in hits}) == 1:
        return sorted(hits)[0]
    return None


def recover_unit(pdf_path, value, rel=1e-9):
    """Convenience single-value form of unit_for_value (used by the tests)."""
    return unit_for_value(_read_blocks(pdf_path), value, rel=rel)


def unitless_rds_fields(dsf):
    """Every Rds_on Field in a record that carries no unit -- the merged `fields_filled`
    view AND the per-source originals in `fields_lists`, because _get_by_cond serves from
    the latter."""
    out = []
    f = dsf.fields_filled.get('Rds_on')
    if f is not None and not (f.unit or '').strip():
        out.append(f)
    for f in dsf.fields_lists.get('Rds_on', []):
        if not (f.unit or '').strip():
            out.append(f)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write the DB (default: dry run)')
    args = ap.parse_args()

    db = datasheets_db.load()

    repaired = []      # (mfr, mpn, unit, mul, n_fields)
    unrecoverable = 0
    considered = 0
    gate_ok = gate_bad = 0
    mismatches = []    # rescaling repairs that disagree with the MPN -> BLOCK the write
    preexisting = []   # no-op repairs whose stored value already disagreed -> report only
    rescale_checked = 0
    calib_total = calib_blind = 0

    for (mfr, mpn), dsf in db.items():
        fields = unitless_rds_fields(dsf)
        if not fields:
            continue
        considered += len(fields)
        blocks = _read_blocks(os.path.join(REPO, 'datasheets', mfr, mpn + '.pdf'))
        nom = mpn_nominal_milliohm(mpn, mfr)

        for f in fields:
            anchor = f.max_or_typ
            if anchor is None or math.isnan(anchor):
                unrecoverable += 1
                continue

            unit = unit_for_value(blocks, anchor)
            if not unit:
                unrecoverable += 1
                continue

            mul = ohm_unit_to_milli_mul(unit)

            if nom is not None:
                got = mul * anchor
                agrees = gate_agrees(got, nom)
                if mul != 1.0:
                    rescale_checked += 1
                    # Calibration, every run: the SAME predicate must reject this repair's
                    # own value scaled by the error class we are guarding against. A gate
                    # never seen to fire is not a gate.
                    if agrees:
                        calib_total += 1
                        if not gate_rejects_scale_error(got, nom):
                            calib_blind += 1
                # Split by whether this repair CHANGES A NUMBER. mul==1.0 means the
                # recovered unit is milliohm, which is what the reader's unitless default
                # already assumed -- the repair only stamps the unit, so it cannot make any
                # value worse, and a disagreement there is a pre-existing bad value (e.g. a
                # multi-part datasheet whose row belongs to a sibling MPN). Reported, not
                # blocking. Only rescales can introduce a unit error, so only they gate.
                if agrees:
                    gate_ok += 1
                elif mul != 1.0:
                    gate_bad += 1
                    mismatches.append((mpn, unit, anchor, got, nom))
                else:
                    preexisting.append((mpn, unit, anchor, got, nom))

            repaired.append((mfr, mpn, unit, mul, 1))

            if args.apply:
                # Rescale in place to canonical mΩ and stamp the unit, matching what
                # Field.__init__ now does for a freshly parsed record. Reached only when
                # the unit was empty, and it is set here, so a second run is a no-op
                # rather than a second x1000.
                for stat in ('min', 'typ', 'max'):
                    v = getattr(f, stat)
                    if v is not None and not math.isnan(v):
                        setattr(f, stat, v * mul)
                f.unit = 'mΩ'

    scale_changed = sum(1 for r in repaired if r[3] != 1.0)

    print('unitless Rds_on FIELDS           : %d  (fields_filled + fields_lists)' % considered)
    print('  unit recovered (value-anchored): %d' % len(repaired))
    print('     of which rescale (were Ohm) : %d' % scale_changed)
    print('  unrecoverable, left untouched  : %d' % unrecoverable)
    print()
    print('MPN ground-truth gate')
    print('  checkable repairs              : %d' % (gate_ok + gate_bad + len(preexisting)))
    print('  agree                          : %d' % gate_ok)
    print('  rescales checkable             : %d' % rescale_checked)
    print('  DISAGREE (rescale) -> BLOCKING : %d' % gate_bad)
    for m in mismatches:
        print('     %-20s unit=%-4r stored=%-9g -> %-9.4g  MPN says %g' % m)
    print('  pre-existing bad value (no-op) : %d' % len(preexisting))
    for m in preexisting:
        print('     %-20s unit=%-4r stored=%-9g -> %-9.4g  MPN says %g' % m)
    print()
    print('gate calibration (would a 1000x error be caught?)')
    print('  passing rescales probed         : %d' % calib_total)
    print('  gate BLIND to a 1000x error     : %d' % calib_blind)

    if not args.apply:
        print('\nDRY RUN -- nothing written. Re-run with --apply.')
        return 0

    if gate_bad:
        print('\nREFUSING TO WRITE: %d rescaling repair(s) disagree with their own part '
              'number.' % gate_bad)
        return 1
    if not rescale_checked:
        print('\nREFUSING TO WRITE: not one rescaling repair could be checked against '
              'ground truth, so the x1000 correction is unvalidated.')
        return 1
    if calib_blind:
        print('\nREFUSING TO WRITE: the gate is blind to a 1000x error on %d of %d probed '
              'repairs, so passing it proves nothing.' % (calib_blind, calib_total))
        return 1

    backup = datasheets_db._lib_path + '.bak-rds-units'
    if os.path.exists(datasheets_db._lib_path):
        shutil.copy2(datasheets_db._lib_path, backup)
        print('\nbacked up -> %s' % backup)

    datasheets_db._lib_mem = db
    datasheets_db._write()
    print('wrote %d records (%d rescaled)' % (len(repaired), scale_changed))
    return 0


if __name__ == '__main__':
    sys.exit(main())
