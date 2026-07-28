"""Generate dslib/qrr_layout_conditions.py — reverse-recovery test points read from the
datasheet TABLE LAYOUT for parts the key-based parser leaves bare.

    python3 apps/emit_qrr_layout_conditions.py            # report only
    python3 apps/emit_qrr_layout_conditions.py --emit     # rewrite the generated module

WHY A SEPARATE PASS. dslib/conditions.py keys conditions off cond dict KEYS. That misses
sheets whose condition cell SPANS the trr and Qrr rows: flattened to text the span lands
on trr, and Qrr reads as bare "diF/dt = 100 A/us" with no current. `pdftotext -layout`
keeps the table geometry, so the whole cell comes back.

WHY IT IS NOT dslib/qrr_conditions.py. That file's precedence over parsed data rests on a
human having read the PDF. These are MACHINE-read, so they get their own module and their
own `source='layout'` tag, and they rank BELOW the hand-curated table:

    qrr_points (per-row) > qrr_conditions (hand-read) > THIS > parsed cond keys

THE PRIMARY SAFETY PROPERTY is a value cross-check, not regex confidence. The extractor
also reads the Qrr and trr VALUES out of the same block and requires them to match what
the DB parsed independently, so a condition taken from a different block than the charge
is dropped -- 229 were, in the run that produced the shipped module.

WHAT THAT CROSS-CHECK DOES NOT COVER, because getting this wrong shipped six bad entries:
it is only independent for cross-ROW and cross-BLOCK errors. When the DB value and the
layout value are two readings of the same UN-NORMALISED text, they agree while both being
wrong. IRFB38N20D prints "1.3 2.0 C" -- the micro glyph dropped -- the DB stores 1.3 with
unit 'PC', the layout regex reads 1.3, they match, and the shipped charge was 1000x too
small. Agreement between two readings of one corrupted source is not corroboration. Hence
the unit gate in harvest(): a Qrr whose unit survives as C/uC/PC proves normalisation did
NOT happen, so its scale is unknown and it is refused outright.

Survivors must also admit a Lauritzen-Ma fit with an IRRM between 0 and 5x IF, and a
Qrr/IF above a floor. That bound is TWO-SIDED on purpose -- it was one-sided at first
(reject IRRM > 5x IF), which is exactly why a 1000x-too-small charge, whose implied IRRM
is ~0, passed it without complaint.

CALIBRATED against the seven entries in dslib/qrr_conditions.py that were read off the
PDFs by hand. That calibration is not decoration: the first version of this extractor used
a symmetric window around the Qrr row, reached up into "Diode forward voltage V SD | I F=88
A", and returned 88 A for IAUCN08S7N013 whose true recovery current is 50 A -- the
cross-row attribution error, about to be applied to hundreds of parts at once. The window
below is anchored to the trr..Qrr span and stops at the forward-voltage row. Re-run
`--calibrate` after ANY change to the regexes or the window; it must stay 6/6.
"""
import json
import math
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_NUM = r'-?\d+(?:[.,]\d+)?'
RE_DIDT = re.compile(r'd\s*[iI]\s*[A-Z]{0,3}\s*/\s*d\s*t\s*=?\s*(' + _NUM + r')\s*A\s*/\s*[uµμm]\s*s', re.I)
RE_IF = re.compile(r'\bI\s*(?:F|S|SD|DR)\b\s*=?\s*(' + _NUM + r')\s*A(?![/\w])', re.I)
RE_VR = re.compile(r'\bV\s*(?:R|DD|DS)\b\s*=?\s*(' + _NUM + r')\s*V', re.I)
RE_TJ = re.compile(r'\bT\s*j\s*=?\s*(' + _NUM + r')\s*°?\s*C', re.I)
RE_QRR_ROW = re.compile(r'[Rr]everse\s+recovery\s+charge', re.I)
RE_TRR_ROW = re.compile(r'[Rr]everse\s+recovery\s+time', re.I)
RE_VSD_ROW = re.compile(r'forward\s+voltage|V\s*SD\b', re.I)
# A new table/section starting below the Qrr row ends the condition cell. Without this the
# downward window runs on into the next block: goford/8070.0 picked up "VGS=0V, VDS=0V"
# from a following "Dynamic Characteristics" header and stored VR=0 V. Only VR was wrong
# there (IF and di/dt sit on the recovery rows), and VR does not enter the fit -- but a
# registry that ships a value read from the wrong section is exactly what the value
# cross-check cannot catch, because VR has nothing to cross-check against.
RE_SECTION_BREAK = re.compile(
    r'characteristic|dynamic|thermal|switching|gate\s+charge|notes?\s*:|^\s*\d+\s*\)', re.I)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, 'dslib', 'qrr_layout_conditions.py')

# (mfr, mpn) -> (IF, di/dt) read off the PDF by hand; see dslib/qrr_conditions.py
CALIBRATION = {
    ('infineon', 'IAUMN08S5N012G'): (50.0, 100e6),
    ('infineon', 'IAUTN08S5N012L'): (50.0, 100e6),
    ('infineon', 'IAUMN08S5N013G'): (50.0, 100e6),
    ('infineon', 'IAUCN08S7N013'): (50.0, 100e6),
    ('infineon', 'IPT015N10NF2S'): (100.0, 500e6),
    ('ao', 'AOGT68801'): (20.0, 500e6),
    # IPT014N10N5 is deliberately absent: it is a print-to-PDF with no text layer at all
    # (11 characters extract from 1.6 MB), so this pass MUST find nothing for it. It is
    # asserted as a no-extraction case instead.
}
CALIBRATION_MUST_MISS = [('infineon', 'IPT014N10N5')]


def _f(s):
    return float(s.replace(',', '.'))


def layout_text(pdf, timeout=90):
    try:
        r = subprocess.run(['pdftotext', '-q', '-layout', pdf, '-'],
                           capture_output=True, timeout=timeout)
        return r.stdout.decode('utf8', 'ignore')
    except Exception:
        return ''


def _values_in(line):
    return [_f(x) for x in re.findall(_NUM, line)]


def extract(body):
    """Layout text -> dict(IF, didt, VR, Tj, qrr_seen, trr_seen), or None."""
    r = extract_with_block(body)
    return r[0] if r else None


def extract_with_block(body):
    """(conditions, block_lines) or None — the block being the exact text the conditions
    were read from.

    Verification tooling MUST go through this rather than re-deriving the block, or it
    shows a reader different evidence than the code used. The first cut of the sample
    sheet did re-derive it, took the first "reverse recovery charge" match, and quoted a
    front-page marketing bullet ("Very low reverse recovery charge (Qrr)") as the source
    for IAUTN12S5N018GATMA1 — whose real conditions came from the table further in.
    Evidence that does not match what ran is worse than no evidence.
    """
    lines = body.split('\n')
    for i, line in enumerate(lines):
        if not RE_QRR_ROW.search(line):
            continue
        # Window = the trr..Qrr row span ONLY. See the module docstring for the
        # IAUCN08S7N013 miscapture this bound exists to prevent.
        lo = i
        for j in range(i - 1, max(-1, i - 4), -1):
            if RE_TRR_ROW.search(lines[j]):
                lo = j
                break
            if RE_VSD_ROW.search(lines[j]):
                break                      # forward-voltage row: stop, never cross it
            if RE_QRR_ROW.search(lines[j]):
                break                      # ANOTHER charge row: that block is not ours.
                # Review-hardening, not an observed failure: no live instance was found
                # across the 409-entry registry (every dual-block sheet anchored to its
                # own block). But the value cross-check cannot catch this one -- `qv` is
                # read off line `i`, which is always right for SOME block -- so the window
                # has to refuse it structurally rather than be caught downstream.
        hi = min(len(lines), i + 3)        # continuation lines below the Qrr row
        for j in range(i + 1, hi):         # ... but never past a new section
            if RE_SECTION_BREAK.search(lines[j]):
                hi = j
                break
        flat = re.sub(r'[ \t]+', ' ', '\n'.join(lines[lo:hi]))
        d, f_, v, t = (RE_DIDT.search(flat), RE_IF.search(flat),
                       RE_VR.search(flat), RE_TJ.search(flat))
        if not (d and f_):
            continue
        qv = _values_in(re.sub(r'^[^|]*?charge\D*', '', line, flags=re.I))
        tv = []
        for j in range(lo, hi):
            if RE_TRR_ROW.search(lines[j]):
                tv = _values_in(re.sub(r'^[^|]*?time\D*', '', lines[j], flags=re.I))
                break
        return (dict(IF=abs(_f(f_.group(1))), didt=abs(_f(d.group(1))) * 1e6,
                     VR=_f(v.group(1)) if v else None,
                     Tj=_f(t.group(1)) if t else 25.0,
                     qrr_seen=qv, trr_seen=tv),
                [re.sub(r'\s+', ' ', x).strip() for x in lines[lo:hi] if x.strip()])
    return None


def calibrate():
    """Must be 6/6 with 0 wrong. A miscapture here is a miscapture on every part."""
    ok = bad = miss = 0
    for (mfr, mpn), (IF, didt) in sorted(CALIBRATION.items()):
        c = extract(layout_text(os.path.join(REPO, 'datasheets', mfr, mpn + '.pdf')))
        if not c:
            miss += 1
            print('  %-22s NO EXTRACTION (expected %g A / %g A/us)' % (mpn, IF, didt / 1e6))
            continue
        good = abs(c['IF'] - IF) < 1e-6 and abs(c['didt'] - didt) < 1e-3 * didt
        ok += good
        bad += (not good)
        print('  %-22s %s IF=%g didt=%g  (hand-read: %g / %g)'
              % (mpn, 'OK   ' if good else 'WRONG', c['IF'], c['didt'] / 1e6, IF, didt / 1e6))
    for mfr, mpn in CALIBRATION_MUST_MISS:
        c = extract(layout_text(os.path.join(REPO, 'datasheets', mfr, mpn + '.pdf')))
        print('  %-22s %s (no text layer -- must extract nothing)'
              % (mpn, 'OK   ' if c is None else 'WRONG: extracted %s' % c))
        bad += (c is not None)
    print('\n  matched %d, wrong %d, missed %d' % (ok, bad, miss))
    return bad == 0 and miss == 0


def _near(v, lst, rel=0.02):
    return any(abs(v - x) <= max(rel * abs(v), 0.51) for x in (lst or []))


def harvest():
    """-> (candidates, rejection stats) over every part with a Qrr the parser left bare."""
    import warnings
    from collections import Counter
    warnings.filterwarnings('ignore')
    from dslib import qrr_model
    from dslib.store import datasheets_db

    stats, out = Counter(), []
    for key, ds in datasheets_db.load().items():
        # only parts the keyed parser could not serve; a curated or parsed point wins
        if ds.qrr_test_conditions() is not None:
            continue
        fq, ft = ds.fields_filled.get('Qrr'), ds.fields_filled.get('trr')
        try:
            qrr = fq.typ_or_max_or_min if fq else None
            trr = ft.typ_or_max_or_min if ft else None
        except ValueError:
            qrr = trr = None
        if not qrr or not trr or math.isnan(qrr) or math.isnan(trr):
            stats['no Qrr/trr in DB'] += 1
            continue
        # The Qrr SCALE must be trustworthy before its operating point is worth reading.
        #
        # The value cross-check below compares the layout reading against the DB reading,
        # and those are NOT independent when both come from the same un-normalised text:
        # IRFB38N20D's sheet prints "1.3 2.0 C" where the micro glyph was dropped, the DB
        # stores typ=1.3 with unit 'PC' (mangled uC), and the layout regex reads the same
        # 1.3. Both agree, on a number 1000x too small. Agreement between two readings of
        # one corrupted source is not corroboration.
        #
        # So gate on the unit itself: nC (the canonical storage) or nothing, never a
        # surviving 'C'/'uC'/'PC' that proves normalisation did NOT happen. Since
        # 2026-07-28 dslib/field.py converts the mangled micro spellings (PC/PSC/WC/mC,
        # UC, µC/μC with whitespace) at parse time and refuses ambiguous bare-'C'
        # values, and apps/repair_qrr_units.py repaired the records already in the DB —
        # so this gate is now DEFENCE IN DEPTH rather than the only line: it stays
        # because it is cheap and because it also catches any future mangle spelling
        # that field.py has not met yet.
        unit = str(getattr(fq, 'unit', '') or '').strip().lower()
        if unit and unit not in ('nc',):
            stats['Qrr unit not normalised (%s)' % unit] += 1
            continue
        pdf = os.path.join(REPO, 'datasheets', key[0], key[1] + '.pdf')
        if not os.path.exists(pdf):
            stats['no pdf'] += 1
            continue
        c = extract(layout_text(pdf))
        if not c:
            stats['no recovery block in layout text'] += 1
            continue
        if not _near(qrr, c['qrr_seen']):
            stats['Qrr value mismatch (wrong block)'] += 1
            continue
        if c['trr_seen'] and not _near(trr, c['trr_seen']):
            stats['trr value mismatch'] += 1
            continue
        if not (0.05 <= c['IF'] <= 3000) or not (1e6 <= c['didt'] <= 1e11):
            stats['out of band'] += 1
            continue
        try:
            f = qrr_model.fit_lm(qrr * 1e-9, trr * 1e-9, c['IF'], c['didt'], tj_fit=c['Tj'])
        except qrr_model.LMFitError:
            stats['LM fit fails'] += 1
            continue
        if f['irrm'] > 5.0 * c['IF']:
            stats['IRRM implausible (too high)'] += 1
            continue
        # TWO-SIDED, deliberately. The bound above was the only plausibility check and it
        # only rejected too MUCH charge, so a Qrr 1000x too small produced IRRM ~ 0 and
        # sailed through -- a guard that vanishes in one direction is not a guard.
        #
        # The floor is on Qrr/IF (nC per A, i.e. a recovery time scale) because that is
        # where the corrupt parts separate cleanly: the six lost-prefix entries sat at
        # 0.050-0.052 nC/A while the lowest LEGITIMATE entry in the corpus is 0.58
        # (nce/NCE8295A) and the hand-verified IAUCN08S7N013 is 0.68. 0.2 sits in an 11x
        # gap -- ~3x clear of the real parts and ~4x clear of the corrupt ones -- so it is
        # calibrated against both directions, not just the failure it was written for.
        if qrr / c['IF'] < 0.2:
            stats['Qrr/IF below any physical recovery (lost unit prefix?)'] += 1
            continue
        stats['ACCEPTED'] += 1
        out.append(dict(mfr=key[0], mpn=key[1], IF=c['IF'], didt=c['didt'],
                        VR=c['VR'], Tj=c['Tj'], qrr=qrr, trr=trr,
                        irrm_ratio=round(f['irrm'] / c['IF'], 3)))
    out.sort(key=lambda r: (r['mfr'], r['mpn']))
    return out, stats


HEADER = '''"""GENERATED -- do not edit. Rebuild with:

    python3 apps/emit_qrr_layout_conditions.py --emit

Reverse-recovery test points read from the datasheet TABLE LAYOUT (pdftotext -layout) for
parts whose condition cell spans the trr/Qrr rows, which the key-based parser in
dslib/conditions.py cannot see. See apps/emit_qrr_layout_conditions.py for the extraction
rules, the value cross-check that gates every entry, and the calibration against the
hand-read entries in dslib/qrr_conditions.py.

These are MACHINE-read, not human-verified. They carry source='layout' and rank below the
hand-curated dslib/qrr_conditions.py:

    qrr_points (per-row) > qrr_conditions (hand-read) > THIS > parsed cond keys

Every entry here satisfied all of: the Qrr (and where present trr) value in the block
matched what the DB independently parsed, the value lay in a physical band, a
Lauritzen-Ma fit succeeded, and the implied IRRM stayed under 5x IF.
"""

QRR_LAYOUT_CONDITIONS = {
'''

FOOTER = '''}


def qrr_layout_conditions_for(mfr, mpn):
    """(mfr, mpn) -> dict(IF, didt, VR, Tj, source='layout') or None.

    Same orderable-suffix fallback as dslib/qrr_conditions.py, so a family variant
    resolves to its base die without a separate entry."""
    from dslib.mpn_match import lookup_base_variant
    hit = lookup_base_variant(QRR_LAYOUT_CONDITIONS, mfr, mpn)
    return dict(hit, source='layout') if hit else None
'''


def emit(cands):
    with open(OUT, 'w') as fh:
        fh.write(HEADER)
        for r in cands:
            vr = 'None' if r['VR'] is None else '%g' % r['VR']
            fh.write('    ("%s", "%s"): dict(IF=%g, didt=%g, VR=%s, Tj=%g),'
                     '  # Qrr=%g nC trr=%g ns, IRRM/IF=%.2f\n'
                     % (r['mfr'], r['mpn'], r['IF'], r['didt'], vr, r['Tj'],
                        r['qrr'], r['trr'], r['irrm_ratio']))
        fh.write(FOOTER)
    print('wrote %s (%d entries)' % (OUT, len(cands)))


if __name__ == '__main__':
    if '--calibrate' in sys.argv:
        sys.exit(0 if calibrate() else 1)
    print('calibrating against the hand-read entries first:')
    if not calibrate():
        sys.exit('CALIBRATION FAILED -- refusing to harvest with a miscapturing extractor')
    print('\nharvesting...')
    cands, stats = harvest()
    for k, n in stats.most_common():
        print('  %5d  %s' % (n, k))
    json.dump(cands, open(os.path.join(REPO, 'out', 'qrr_layout_candidates.json'), 'w'),
              indent=1) if os.path.isdir(os.path.join(REPO, 'out')) else None
    if '--emit' in sys.argv:
        emit(cands)
    else:
        print('\n(dry run -- pass --emit to rewrite %s)' % os.path.relpath(OUT, REPO))
