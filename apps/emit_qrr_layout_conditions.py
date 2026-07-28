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
reads the Qrr and trr VALUES out of each recovery block and serves the conditions of the
block that PRINTS the DB's value -- so conditions are attributed to the same block as
the charge. On single-block sheets that is an independent agreement check; on
multi-di/dt sheets it is a selector (agreement with the chosen block holds by
construction), guarded by the trr co-match and by refusing a charge that matches blocks
with different conditions. The earlier first-block-only form of this check rejected
209-229 multi-block parts per run as 'wrong block'.

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
# The label separators vary per template: 'Reverse Recovery Charge' (space),
# 'Reverse-Recovery' / 'Reverse−Recovery' (ASCII / unicode hyphen, IR & onsemi),
# 'RecoveryCharge' printed with NO space (Vishay/IR column collision), and ST's older
# 'recovered charge' wording. All are the same anchor; front-page marketing bullets
# ('low reverse recovery charge (Qrr)') still anchor harmlessly -- their window has no
# IF/di-dt conditions, so iter_blocks drops them, as it always has.
# ST's F7 template wraps the label over three lines ('Reverse / Qrr recovery / charge'),
# so no line prints 'recovery charge' -- the value row is the one where the symbol Qrr
# PRECEDES 'recover'. Marketing bullets print it the other way round ('... low reverse
# recovery charge (Qrr)') and don't match the Qrr-first form.
RE_QRR_ROW = re.compile(
    r'[Rr]everse[\s−–—-]*[Rr]ecovery\s*[Cc]harge|recovered\s+charge'
    r'|\bQ\s*rr\b[^|]*?\brecover', re.I)
RE_TRR_ROW = re.compile(r'[Rr]everse[\s−–—-]*[Rr]ecovery\s*[Tt]ime|recovery\s+time', re.I)
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
    # 2026-07-28 batch, read off rendered pages when their layout classes were added:
    # N3G 'I F=I S' cross-reference (IS rating row prints 100 A), onsemi ta/tb-spaced
    # labels, ST F7 three-line wrapped label.
    ('infineon', 'IPP037N08N3GXKSA1'): (100.0, 100e6),
    ('onsemi', 'NVMFS6H818NLWFT1G'): (50.0, 100e6),
    ('st', 'STP150N10F7AG'): (110.0, 100e6),
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
    """Layout text -> dict(IF, didt, VR, Tj, qrr_seen, trr_seen), or None.

    FIRST block only. This is the right contract for --calibrate (the hand-read
    entries are anchored to it) and for single-block sheets; harvest() selects among
    ALL blocks by value instead — see extract_all_blocks."""
    r = extract_with_block(body)
    return r[0] if r else None


def extract_with_block(body):
    """First (conditions, block_lines) or None — the block being the exact text the
    conditions were read from.

    Verification tooling MUST go through this rather than re-deriving the block, or it
    shows a reader different evidence than the code used. The first cut of the sample
    sheet did re-derive it, took the first "reverse recovery charge" match, and quoted a
    front-page marketing bullet ("Very low reverse recovery charge (Qrr)") as the source
    for IAUTN12S5N018GATMA1 — whose real conditions came from the table further in.
    Evidence that does not match what ran is worse than no evidence.
    """
    for r in iter_blocks(body):
        return r
    return None


def extract_all_blocks(body):
    """Every recovery block on the sheet, in document order.

    extract()/extract_with_block() stop at the FIRST block, which on multi-di/dt
    sheets is often not the one the DB's Qrr was parsed from — the value cross-check
    in harvest() then refused the part: 229 'Qrr value mismatch (wrong block)'
    rejections in the run that shipped the 409-entry module. Selection among these
    blocks (by value match against the DB) happens in harvest(), not here."""
    return list(iter_blocks(body))


def iter_blocks(body):
    lines = body.split('\n')
    for i, line in enumerate(lines):
        if not RE_QRR_ROW.search(line):
            continue
        # Window = the trr..Qrr row span ONLY. See the module docstring for the
        # IAUCN08S7N013 miscapture this bound exists to prevent. Depth 6 (was 3):
        # onsemi spaces the labels with 'Charge Time ta' / 'Discharge Time tb' rows, so
        # trr sits 4-5 rows above Qrr there. The forward-voltage / other-charge-row
        # stops below still bound the scan -- depth alone never crosses a section.
        lo = i
        for j in range(i - 1, max(-1, i - 7), -1):
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
        for j in range(i + 1, hi):         # ... but never past a new section OR the
            if (RE_SECTION_BREAK.search(lines[j])   # next recovery block: its rows are
                    or RE_TRR_ROW.search(lines[j])  # not continuations of this cell,
                    or RE_QRR_ROW.search(lines[j])):  # and a 'TJ = 150 C' printed there
                hi = j                                # must not stamp THIS block's Tj
                break
        flat = re.sub(r'[ \t]+', ' ', '\n'.join(lines[lo:hi]))
        d, f_, v, t = (RE_DIDT.search(flat), RE_IF.search(flat),
                       RE_VR.search(flat), RE_TJ.search(flat))
        if_val = abs(_f(f_.group(1))) if f_ else _resolve_if_is(lines, lo, flat)
        if not (d and if_val is not None):
            continue
        qv = _values_in(re.sub(r'^[^|]*?charge\D*', '', line, flags=re.I))
        # The DB stores Qrr in nC; sheets printing uC (vishay '126 189 uC', ao '1.18
        # uC', st '0.9 uC') made the value cross-check compare across units and refuse
        # every such part. Normalise on the printed unit -- last charge-unit token on
        # the line, after the values ('/us' has no C, and the 'x C' of a temperature is
        # preceded by a degree sign, not a prefix). A bare/mangled 'C' (the IRFB38N20D
        # lost-micro class) matches no prefix and stays UNSCALED, so those sheets keep
        # refusing instead of guessing a magnitude.
        u = re.findall(r'([nuµμ])\s*C(?![a-zA-Z])', line)
        scale = 1e3 if u and u[-1] in 'uµμ' else 1.0
        qv = [x * scale for x in qv]
        if not qv:
            # IR/AUIR layout: the label line carries only symbol+name+unit, and the
            # value rows sit ABOVE and BELOW it, one per Tj, each self-tagged:
            #
            #         --- 180 ---   TJ = 25 C    VDD = 200V     <- trr @25
            #   trr   Reverse Recovery Time   ns
            #         --- 200 ---   TJ = 125 C   IF = 56A,      <- trr @125
            #         --- 1480 ---  TJ = 25 C    di/dt=100A/us  <- Qrr @25
            #   Qrr   Reverse Recovery Charge  nC
            #         --- 2260 ---  TJ = 125 C                  <- Qrr @125
            #
            # One test condition, spread vertically over the section (the VDD row sits
            # a line ABOVE the trr label, outside the normal window). Yield one
            # candidate per Tj-tagged Qrr row -- select_block() then picks the row that
            # prints the DB's value, the Tj attribution follows that row for free, and
            # the trr co-match compares against the SAME-Tj trr row only. ~150 parts
            # per harvest ('no block prints the DB value') are this layout.
            ir = _ir_rows(lines, i, lo, scale)
            if ir:
                for cand in ir:
                    yield cand
                continue
            # no IR rows either: fall through to the plain yield -- an empty
            # qrr_seen block still carries conditions, which is all the hand-read
            # calibration sheets (IAU*) have on this line, and select_block simply
            # never value-matches it.
        tv = []
        for j in range(lo, hi):
            if RE_TRR_ROW.search(lines[j]):
                tv = _values_in(re.sub(r'^[^|]*?time\D*', '', lines[j], flags=re.I))
                break
        yield (dict(IF=if_val, didt=abs(_f(d.group(1))) * 1e6,
                    VR=_f(v.group(1)) if v else None,
                    Tj=_f(t.group(1)) if t else 25.0,
                    qrr_seen=qv, trr_seen=tv),
               [re.sub(r'\s+', ' ', x).strip() for x in lines[lo:hi] if x.strip()])


# Infineon OptiMOS 3 (N3G) prints the recovery current as a CROSS-REFERENCE --
# 'V R=40 V, I F=I S, di F/dt=100 A/us' -- where IS is the diode continuous forward
# current, printed as its own labelled row a few lines up in the same reverse-diode
# table ('Diode continous forward current  IS  -  -  100  A'; the typo is Infineon's).
RE_IF_IS_XREF = re.compile(r'\bI\s*F\s*=\s*I\s*S\b(?!\s*,?\s*pulse)', re.I)
RE_IS_ROW = re.compile(r'diode\s+contin\w*\s+forward\s+current', re.I)


def _resolve_if_is(lines, lo, flat):
    """IF in amps for an 'I F=I S' condition cell, or None.

    Anchored to the LABELLED rating row, never a bare 'IS' anywhere: the nearest
    'diode continuous forward current' row above the window, its last 'NUM A' token.
    No row -> None, and the caller refuses the block -- a recovery point with a
    guessed current is worse than a missing one."""
    if not RE_IF_IS_XREF.search(flat):
        return None
    for j in range(lo - 1, max(-1, lo - 30), -1):
        if RE_IS_ROW.search(lines[j]):
            amps = re.findall(r'(' + _NUM + r')\s*A\b', lines[j])
            return abs(_f(amps[-1])) if amps else None
    return None


# An IR value row: optional dash placeholders (min), one or two numbers (typ [max]),
# dashes, then the row's own Tj tag. Anchored so label rows ('IRRM Reverse Recovery
# Current --- 16 --- A TJ = 25 C') cannot match: only whitespace/dashes may precede the
# first number.
RE_IR_VALROW = re.compile(
    r'^\s*[–—-]*\s*(?P<typ>\d+(?:[.,]\d+)?)(?:\s+(?P<max>\d+(?:[.,]\d+)?))?'
    r'\s*[–—-]*\s*TJ\s*=\s*(?P<tj>\d+(?:[.,]\d+)?)\s*°?\s*C', re.IGNORECASE)


def _ir_rows(lines, i, lo, scale):
    """Candidates for the IR values-above-the-label layout; [] when it does not hold.

    `i` is the Qrr label line, `lo` the window start (the trr label, when the upward
    scan found one). Qrr's value rows are the TJ-tagged rows at i-1/i+1; trr's are the
    ones adjacent to its label, excluding Qrr's. Conditions are searched across the
    whole section INCLUDING the row above the trr label (the VDD/VR row) -- but never
    Tj, which only ever comes off the matched row's own tag."""
    def valrow(k, taken=()):
        if k < 0 or k >= len(lines) or k in taken:
            return None
        m = RE_IR_VALROW.match(lines[k])
        if not m:
            return None
        vals = [_f(m['typ'])] + ([_f(m['max'])] if m['max'] else [])
        return k, _f(m['tj']), vals

    # the charge-unit scale applies to Qrr rows ONLY -- trr rows are ns regardless
    q_rows = [(k, tj, [x * scale for x in vals])
              for r in (valrow(i - 1), valrow(i + 1)) if r for k, tj, vals in [r]]
    if not q_rows:
        return []
    t_label = lo if lo != i and RE_TRR_ROW.search(lines[lo]) else None
    q_taken = {r[0] for r in q_rows}
    t_rows = ([r for r in (valrow(t_label - 1, q_taken), valrow(t_label + 1, q_taken))
               if r] if t_label is not None else [])
    sec_lo = max(0, (t_label - 1) if t_label is not None else i - 1)
    flat = re.sub(r'[ \t]+', ' ', '\n'.join(lines[sec_lo:i + 2]))
    d, f_, v = RE_DIDT.search(flat), RE_IF.search(flat), RE_VR.search(flat)
    if not (d and f_):
        return []
    block = [re.sub(r'\s+', ' ', x).strip() for x in lines[sec_lo:i + 2] if x.strip()]
    out = []
    for _k, tj, vals in q_rows:
        # trr values are only trusted from the row tagged with the SAME Tj; without
        # one the co-match is skipped, never satisfied by the other Tj's time.
        tv = [x for r in t_rows if r[1] == tj for x in r[2]]
        out.append((dict(IF=abs(_f(f_.group(1))), didt=abs(_f(d.group(1))) * 1e6,
                         VR=_f(v.group(1)) if v else None,
                         Tj=tj, qrr_seen=vals, trr_seen=tv), block))
    return out


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


def select_block(blocks, qrr, trr):
    """(conditions, None) from the recovery block that PRINTS the DB's (qrr, trr), or
    (None, rejection reason).

    This replaces the first-block-only cross-check, which insisted the DB matched
    whatever block came first on the sheet -- multi-di/dt sheets put the DB's charge in
    a later block, and that insistence cost 209-229 parts per run as 'wrong block'.

    Selecting by value changes what the cross-check IS: for the chosen block, agreement
    holds by construction, not as an independent verdict. What it certifies is
    ATTRIBUTION -- the conditions come from the recovery block that prints the DB's
    charge -- which is the property the check existed to protect. Residual risks and
    their guards: a coincidental numeric match in a different recovery block (trr must
    then also co-match where printed, and a charge matching blocks with DIFFERENT
    conditions is refused as ambiguous rather than resolved first-wins -- a wrong test
    point is worse than a missing one); a match against text that is not a recovery
    block cannot happen, because every candidate is anchored to a 'reverse recovery
    charge' row. The caller's IRRM band and Qrr/IF floor still gate the survivor."""
    if not blocks:
        return None, 'no recovery block in layout text'
    qrr_hits = [c for c, _blk in blocks if _near(qrr, c['qrr_seen'])]
    if not qrr_hits:
        return None, 'Qrr value mismatch (no block prints the DB value)'
    matches = [c for c in qrr_hits if not c['trr_seen'] or _near(trr, c['trr_seen'])]
    if not matches:
        return None, 'trr value mismatch'
    # _near's 2% band exists for parse rounding; ambiguity means EQUALLY close, not
    # merely both-within-band. FDH055N15A prints 342 nC @120 A and 348 nC @30 A -- the
    # DB stored 342 exactly, 348 is inside the band, and refusing both threw away a
    # part the value cross-check had always attributed correctly. Keep only the
    # closest-printing block(s); refuse only when equally close prints disagree on
    # conditions.
    def dist(c):
        return min(abs(qrr - x) for x in c['qrr_seen'])
    best = min(dist(c) for c in matches)
    closest = [c for c in matches if dist(c) <= best + max(1e-9 * abs(qrr), 1e-12)]
    if len({(c['IF'], c['didt'], c['VR'], c['Tj']) for c in closest}) > 1:
        return None, 'ambiguous: DB Qrr matches blocks with different conditions'
    return closest[0], None


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
        c, why = select_block(extract_all_blocks(layout_text(pdf)), qrr, trr)
        if c is None:
            stats[why] += 1
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

Every entry here satisfied all of: its conditions come from the recovery block that
prints the DB's Qrr (and, where printed there, trr) value -- an independent agreement
check on single-block sheets, a same-block attribution guarantee on multi-block ones,
with a charge matching blocks of differing conditions refused as ambiguous -- the value
lay in a physical band, a Lauritzen-Ma fit succeeded, and the implied IRRM stayed under
5x IF.
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
