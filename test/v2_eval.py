"""
Evaluation harness for ``dslib.v2`` — accuracy *and* speed.

Sampling follows the "part series" idea: datasheets are grouped by
``(mfr, mpn[:3])`` on the assumption that one series shares a page layout.
Sampling whole groups (rather than individual parts) means a layout bug shows
up as a cluster of failures instead of a single lucky/unlucky part.

Two reference tiers, kept strictly apart because they differ in trust:

``truth``     ``dslib/manual_fields.py`` — hand-verified, treated as correct.
``db``        ``data/datasheets-lib.pkl`` — produced by the v1 pipeline and
              **never reviewed**. A disagreement here is a *lead*, not a bug.

Per (part, symbol, stat) each comparison lands in exactly one bucket::

    agree      both sides have a value and they match within rtol
    disagree   both sides have a value and they differ
    v2_miss    reference has a value, v2 does not
    v2_only    v2 has a value, reference does not

A part that could not be evaluated at all (missing PDF, parser exception,
scanned/needs-OCR) is reported as ``unevaluated`` and never silently counted
as a pass.

Usage::

    python3 test/v2_eval.py --groups 40 --per-group 2 --seed 0
    python3 test/v2_eval.py --groups 40 --seed 0 --out out/v2_eval/after.json
    python3 test/v2_eval.py --compare out/v2_eval/before.json out/v2_eval/after.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STATS = ('min', 'typ', 'max')


# ---------------------------------------------------------------- sampling


def group_key(mfr: str, mpn: str) -> Tuple[str, str]:
    """Series key. Datasheets in one series usually share a layout."""
    return (mfr, mpn[:3].upper())


def sample_groups(keys, n_groups: int, per_group: int, seed: int,
                  mfrs: Optional[List[str]] = None):
    """Pick ``n_groups`` random series, then ``per_group`` parts from each.

    Groups are drawn round-robin across manufacturers so a single huge mfr
    (infineon has 2104 DB entries) cannot swamp the sample.
    """
    by_group: Dict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
    for mfr, mpn in keys:
        if mfrs and mfr not in mfrs:
            continue
        by_group[group_key(mfr, mpn)].append((mfr, mpn))

    rnd = random.Random(seed)

    by_mfr: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for g in by_group:
        by_mfr[g[0]].append(g)
    for g_list in by_mfr.values():
        rnd.shuffle(g_list)

    mfr_names = sorted(by_mfr)
    rnd.shuffle(mfr_names)

    picked: List[Tuple[str, str]] = []
    i = 0
    while len(picked) < n_groups and any(by_mfr[m] for m in mfr_names):
        m = mfr_names[i % len(mfr_names)]
        i += 1
        if by_mfr[m]:
            picked.append(by_mfr[m].pop())

    out: List[Tuple[Tuple[str, str], List[Tuple[str, str]]]] = []
    for g in picked:
        parts = sorted(by_group[g])
        rnd.shuffle(parts)
        out.append((g, parts[:per_group]))
    return out


# ---------------------------------------------------------------- comparing


# Source tags that mean "this value came out of the PDF". Anything else in the
# DB (digikey, lcsc, onsemi.com, *_products, ...) was supplied by a vendor
# parametric table, never appears in the datasheet text, and must not be
# counted against v2 as a miss.
_PDF_SOURCE_MARKERS = ('read_sheet', 'tabular', 'v2', 'text', 'ref', 'manual',
                       'read_charts', '.pdf')


def _is_pdf_sourced(f, stat: str) -> bool:
    """True when the reference value plausibly came from the PDF.

    Unknown/absent provenance returns True: a value we cannot attribute stays
    in the comparison. Dropping it would silently shrink the denominator and
    flatter v2's recall.
    """
    src = getattr(f, '_sources', {}).get(stat)
    if not src:
        return True
    s = str(src).lower()
    return any(m in s for m in _PDF_SOURCE_MARKERS)


def _rel_eq(a: float, b: float, rtol: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return False
    if a == b:
        return True
    denom = max(abs(a), abs(b))
    if denom == 0:
        return True
    return abs(a - b) / denom <= rtol


def compare(v2_ds, ref_ds, rtol: float, symbols: Optional[set] = None,
            pdf_sourced_only: bool = False):
    """Bucket every (symbol, stat) pair of a v2 result against a reference.

    Returns (counts, details) where details lists the non-agreeing pairs.

    NOTE what this does NOT see: it reads ``fields_filled``, the single merged
    Field per symbol, so it is blind to whether the OTHER candidates for that
    symbol can be reached at all. See ``selection_audit``.
    """
    counts = defaultdict(int)
    details = []

    syms = set(ref_ds.keys()) | set(v2_ds.keys())
    if symbols:
        syms &= symbols

    for sym in sorted(syms):
        rf = ref_ds.fields_filled.get(sym)
        gf = v2_ds.fields_filled.get(sym)
        for stat in STATS:
            rv = getattr(rf, stat) if rf is not None else math.nan
            gv = getattr(gf, stat) if gf is not None else math.nan
            if (pdf_sourced_only and rf is not None
                    and not math.isnan(rv) and not _is_pdf_sourced(rf, stat)):
                counts['ref_not_in_pdf'] += 1
                continue
            r_has = not math.isnan(rv)
            g_has = not math.isnan(gv)
            if not r_has and not g_has:
                continue
            if r_has and g_has:
                if _rel_eq(rv, gv, rtol):
                    counts['agree'] += 1
                else:
                    counts['disagree'] += 1
                    details.append(dict(symbol=sym, stat=stat, ref=rv, v2=gv,
                                        kind='disagree'))
            elif r_has:
                counts['v2_miss'] += 1
                details.append(dict(symbol=sym, stat=stat, ref=rv, v2=None,
                                    kind='v2_miss'))
            else:
                counts['v2_only'] += 1
                details.append(dict(symbol=sym, stat=stat, ref=None, v2=gv,
                                    kind='v2_only'))
    return counts, details


# A curated value that differs from the printed one by one of these is a lost
# or added SI prefix, not a misread digit.
_PREFIX_RATIOS = (1e-9, 1e-6, 1e-3, 1e3, 1e6, 1e9)


def suspect_truth(v2_ds, ref_ds, truth_ds, rtol, symbols=None):
    """Keys where the hand-curated truth is the OUTLIER, not the extractor.

    Twice now a key that no method could reproduce turned out to be a bad
    reference rather than a bad parser: dslib/manual_fields.py records
    vishay/SUM70042E-GE3 Qrr as 126/189 nC while the sheet prints "126 189 uC",
    and a ti/TPS Vds.typ=3.0 went the same way. Scored blind, those punish the
    extractor for being right, and they do it permanently because a curated
    file is exactly what nobody re-checks.

    The obvious signal — "v2 and the shipped DB agree, only truth differs" —
    DOES NOT WORK, and finding out why is the useful part. dslib/manual_fields
    is priority 1 inside parse_datasheet, and the DB is built by that same
    pipeline, so an overridden value propagates INTO the DB. Checked on the
    case above: manual_fields says 126/189 nC and the DB says 126/189 nC,
    identically. The DB is therefore NOT an independent witness for any key
    manual_fields covers, and a corroboration rule can never fire for exactly
    the class it was written to catch. Anyone reading DB-vs-truth agreement as
    confirmation is reading a tautology.

    What remains usable without a second source is the SHAPE of the
    disagreement. A curated number that differs from the printed one by a round
    power of ten is a lost or added SI prefix, not a misread digit -- uC
    recorded as nC gives exactly 1000. So the queue flags truth-vs-v2
    disagreements at a prefix ratio and leaves a human to open the page. The DB
    value rides along as context, labelled, never as evidence.

    This only ever produces a REVIEW LIST. Nothing is reclassified, excluded or
    scored differently: a harness that quietly forgave its own disagreements
    could be made to agree with anything, and the curated file must be edited
    by a human who has looked at the page.
    """
    out = []
    syms = set(truth_ds.keys())
    if symbols:
        syms &= symbols
    for sym in sorted(syms):
        tf = truth_ds.fields_filled.get(sym)
        gf = v2_ds.fields_filled.get(sym)
        rf = ref_ds.fields_filled.get(sym) if ref_ds is not None else None
        if tf is None or gf is None:
            continue
        for stat in STATS:
            tv, gv = getattr(tf, stat), getattr(gf, stat)
            if math.isnan(tv) or math.isnan(gv) or tv == 0:
                continue
            if _rel_eq(tv, gv, rtol):
                continue          # truth and v2 agree — nothing to review
            ratio = gv / tv
            if not any(abs(ratio / r - 1.0) <= 0.02 for r in _PREFIX_RATIOS):
                continue          # not a prefix-shaped difference
            rv = getattr(rf, stat) if rf is not None else math.nan
            out.append(dict(
                symbol=sym, stat=stat, truth=tv, v2=gv,
                db=(None if math.isnan(rv) else rv),
                db_is_independent=not _rel_eq(rv, tv, rtol) if not math.isnan(rv) else None,
                ratio=ratio))
    return out


def _same_value(a, b) -> bool:
    """Two Fields carrying the same numbers (nan == nan for this purpose)."""
    for stat in STATS:
        x, y = getattr(a, stat), getattr(b, stat)
        if math.isnan(x) and math.isnan(y):
            continue
        if math.isnan(x) or math.isnan(y) or x != y:
            return False
    return True


def selection_audit(v2_ds, symbols=None):
    """Can a consumer address each candidate BY ITS OWN CONDITION?

    ``compare`` reads ``fields_filled`` — one merged Field per symbol — so it
    cannot see conditions at all. A change that makes the VGS=10V and the
    VGS=4.5V rows distinguishable moves nothing there, and a whole slice of
    condition work scored an exactly-zero delta on every bucket while
    demonstrably fixing a 2.2x wrong hot Rds_on. Zero delta meant NOT MEASURED.

    This measures the property the consumers actually rely on:
    ``dslib/field.py:_get_by_cond`` picks among candidates by scoring their
    cond dicts, so for every symbol with more than one candidate, asking for
    candidate C's own condition must return C. If it returns a sibling, that
    candidate is unreachable no matter how correct its value is — which is
    what identical conds on two rows does.

    Reference-free by construction: it needs no DB and no truth set, so it
    cannot reward reproducing their errors.

    Only symbols with >= 2 candidates count — with one candidate the selector
    has no choice to get wrong, and counting those would inflate the rate with
    trivial passes. A candidate carrying no cond is counted as ``no_cond``, its
    own bucket, never as a pass: it is precisely the unaddressable case.
    """
    counts = defaultdict(int)
    details = []
    for sym, lst in (v2_ds.fields_lists or {}).items():
        if symbols and sym not in symbols:
            continue
        if not lst or len(lst) < 2:
            continue
        for f in lst:
            cond = f.cond if isinstance(f.cond, dict) else None
            cond = {k: v for k, v in (cond or {}).items()
                    if isinstance(k, str) and isinstance(v, (int, float))}
            if not cond:
                counts['no_cond'] += 1
                details.append(dict(symbol=sym, kind='no_cond',
                                    value=f.typ_or_max_or_min))
                continue
            got = v2_ds._get_by_cond(sym, cond)
            # Success is "the consumer gets this candidate's VALUE", not "gets
            # this exact object". Two reasons, both measured rather than
            # assumed. Datasheets repeat their parameter table (nxp prints it
            # on p1 and again on p5), so the same row is extracted twice into
            # two equal Fields — 22 of an early 36 "failures" were that. And a
            # candidate can be beaten by a sibling holding the SAME number
            # under a richer condition (epc_space/EPC7018GSH: asking
            # {Id:40, Vgs:5} returns the row that also states Tc=25, value 5.2
            # either way). Nothing is lost for the caller in either case.
            #
            # This was relaxed AFTER a run flagged those two as a regression,
            # which deserves saying out loud. It is not a mute button: the
            # criterion is still whether a wrong NUMBER comes back, and the two
            # genuine failures in the same run (st/ST8L65N050DM9 trr, 315 asked
            # for vs 157 returned) are still counted. What was dropped is a
            # proxy — cond equality — that never spoke to value correctness.
            same = got is f or (got is not None and _same_value(got, f))
            if same:
                counts['selectable'] += 1
            else:
                counts['unselectable'] += 1
                details.append(dict(
                    symbol=sym, kind='unselectable', cond=cond,
                    want=f.typ_or_max_or_min,
                    got=(got.typ_or_max_or_min if got is not None else None),
                    got_cond=(got.cond if got is not None else None)))
    return counts, details


# ---------------------------------------------------------------- running


def build_truth() -> dict:
    """Hand-verified fields from dslib/manual_fields.py, as DatasheetFields."""
    from dslib.field import DatasheetFields
    import dslib.manual_fields

    out: Dict[Tuple[str, str], DatasheetFields] = {}
    for mfr, per_mpn in dslib.manual_fields.get_fields().items():
        if not isinstance(per_mpn, dict) or mfr.startswith('_'):
            continue
        for mpn, fields in per_mpn.items():
            if not isinstance(fields, list):
                continue
            ds = DatasheetFields(mfr=mfr, mpn=mpn)
            for f in fields:
                ds.add(f)
            if len(ds):
                out[(mfr, mpn)] = ds
    return out


def run(args) -> dict:
    from dslib.cache import disk_cache_disable
    if args.no_cache:
        disk_cache_disable(True)

    from dslib.store import datasheets_db
    from dslib.discovery import DiscoveredPart  # noqa: F401  (unpickle support)
    import dslib.v2

    db = datasheets_db.load()
    truth = build_truth()

    if args.truth_only:
        # every hand-verified part, no sampling — this is the set where a
        # disagreement is unambiguously v2's fault
        keys = sorted(truth)
        if args.mfr:
            keys = [k for k in keys if k[0] in args.mfr]
        groups = [(('truth', ''), keys)]
    else:
        groups = sample_groups(list(db.keys()), args.groups, args.per_group,
                               args.seed, args.mfr)

    symbols = set(args.symbols.split(',')) if args.symbols else None

    # Keep only the references for the sampled parts and drop the 124 MB
    # pickle. Holding it for the whole run pushed this machine to 94% memory
    # and the OOM killer took the process with no output written at all.
    wanted = {p for _, ps in groups for p in ps}
    db = {k: v for k, v in db.items() if k in wanted}
    datasheets_db.unload()

    parts_out = []
    t_total = 0.0
    n_eval = 0

    for g, parts in groups:
        for (mfr, mpn) in parts:
            pdf = os.path.join(ROOT, 'datasheets', mfr, mpn + '.pdf')
            rec: Dict[str, object] = dict(mfr=mfr, mpn=mpn, group='%s/%s' % g)

            if not os.path.exists(pdf):
                rec['unevaluated'] = 'no pdf'
                parts_out.append(rec)
                continue

            t0 = time.perf_counter()
            try:
                ds = dslib.v2.parse_datasheet(pdf, mfr=mfr, mpn=mpn)
            except Exception as e:  # noqa: BLE001 - harness must not die on one part
                rec['unevaluated'] = 'exception: %r' % (e,)
                rec['seconds'] = time.perf_counter() - t0
                parts_out.append(rec)
                continue
            dt = time.perf_counter() - t0

            rec['seconds'] = dt
            rec['n_fields'] = len(ds)
            rec['errors'] = list(ds.errors)
            t_total += dt
            n_eval += 1

            if ds.errors:
                # parsed nothing for a stated reason (needs OCR / pdfminer fail)
                rec['unevaluated'] = ';'.join(ds.errors)
                parts_out.append(rec)
                continue

            c, d = selection_audit(ds, symbols)
            if c:
                rec['sel'] = dict(c)
                rec['sel_details'] = d[:args.max_details]

            ref = db.get((mfr, mpn))
            if ref is not None:
                c, d = compare(ds, ref, args.rtol, symbols, pdf_sourced_only=True)
                rec['db'] = dict(c)
                rec['db_details'] = d[:args.max_details]

            tr = truth.get((mfr, mpn))
            if tr is not None:
                c, d = compare(ds, tr, args.rtol, symbols)
                rec['truth'] = dict(c)
                rec['truth_details'] = d[:args.max_details]
                s = suspect_truth(ds, ref, tr, args.rtol, symbols)
                if s:
                    rec['suspect_truth'] = s[:args.max_details]

            parts_out.append(rec)

    return dict(
        args=dict(groups=args.groups, per_group=args.per_group, seed=args.seed,
                  rtol=args.rtol, mfr=args.mfr, symbols=args.symbols,
                  no_cache=args.no_cache),
        n_parts=len(parts_out),
        n_evaluated=n_eval,
        seconds_total=t_total,
        seconds_per_part=(t_total / n_eval) if n_eval else None,
        parts=parts_out,
    )


# ---------------------------------------------------------------- reporting


def _sum(parts, key) -> Dict[str, int]:
    tot = defaultdict(int)
    for p in parts:
        for k, v in (p.get(key) or {}).items():
            tot[k] += v
    return dict(tot)


def _acc(c: Dict[str, int]) -> Optional[float]:
    """Accuracy over pairs where BOTH sides have a value.

    Returns None (not 1.0) when there is nothing to compare — an unevaluatable
    input must never read as a perfect score.
    """
    both = c.get('agree', 0) + c.get('disagree', 0)
    if both == 0:
        return None
    return c.get('agree', 0) / both


def _fmt_acc(a: Optional[float]) -> str:
    return 'n/a' if a is None else '%5.1f%%' % (100 * a)


def _sel_rate(c: Dict[str, int]) -> Optional[float]:
    """Of the candidates that STATE a condition, the share reachable by it.

    ``no_cond`` is deliberately NOT in this denominator, and that is a
    correction. Audited over 120 no_cond candidates by going back to the source
    row: 0 were conditions v2 failed to read, 58 (48%) were rows where the
    sheet states none at all — "VDS drain-source voltage - - 150 V" is an
    absolute-maximum rating with nothing to extract — and 62 had one on a
    neighbouring row, of which only some are legitimately inheritable (a shared
    gate-charge block header) while others belong to a different parameter
    entirely. Charging all 120 to the parser made the rate say more about how
    many abs-max rows a sheet prints than about extraction quality.

    Returns None when nothing stated a condition, so "nothing to disambiguate"
    cannot read as a perfect score.
    """
    n = c.get('selectable', 0) + c.get('unselectable', 0)
    if n == 0:
        return None
    return c.get('selectable', 0) / n


def _cond_coverage(c: Dict[str, int]) -> Optional[float]:
    """Share of multi-candidate rows that state a condition at all.

    Reported ALONGSIDE the rate rather than folded into it: moving a candidate
    out of no_cond and into unselectable would otherwise look like an
    improvement in one number while the other hid it.
    """
    n = (c.get('selectable', 0) + c.get('unselectable', 0)
         + c.get('no_cond', 0))
    if n == 0:
        return None
    return (c.get('selectable', 0) + c.get('unselectable', 0)) / n


def report(res: dict, verbose: bool = False) -> None:
    parts = res['parts']
    uneval = [p for p in parts if 'unevaluated' in p]

    print('=' * 78)
    print('v2 eval: %d parts, %d evaluated, %d unevaluated'
          % (res['n_parts'], res['n_evaluated'], len(uneval)))
    if res['seconds_per_part']:
        print('speed  : %.2f s/part total %.1f s'
              % (res['seconds_per_part'], res['seconds_total']))

    sel = _sum(parts, 'sel')
    if sel:
        print('-' * 78)
        print('select  selectable=%d unselectable=%d no_cond=%d'
              % (sel.get('selectable', 0), sel.get('unselectable', 0),
                 sel.get('no_cond', 0)))
        print('        rate=%s of those that state a cond; coverage=%s state one'
              % (_fmt_acc(_sel_rate(sel)), _fmt_acc(_cond_coverage(sel))))
        print('        (reference-free; ~48%% of no_cond is rows the sheet'
              ' gives no condition)')

    for tier in ('truth', 'db'):
        tot = _sum(parts, tier)
        if not tot:
            continue
        n = sum(tot.values())
        print('-' * 78)
        print('%-6s agree=%d disagree=%d v2_miss=%d v2_only=%d  (n=%d)  accuracy=%s'
              % (tier, tot.get('agree', 0), tot.get('disagree', 0),
                 tot.get('v2_miss', 0), tot.get('v2_only', 0), n,
                 _fmt_acc(_acc(tot))))
        # recall = how much of the reference v2 reproduced
        ref_have = tot.get('agree', 0) + tot.get('disagree', 0) + tot.get('v2_miss', 0)
        if ref_have:
            print('%-6s recall=%.1f%% (found %d of %d reference values)'
                  % ('', 100 * (tot.get('agree', 0) + tot.get('disagree', 0)) / ref_have,
                     tot.get('agree', 0) + tot.get('disagree', 0), ref_have))

        by_sym = defaultdict(lambda: defaultdict(int))
        for p in parts:
            for d in (p.get(tier + '_details') or []):
                by_sym[d['symbol']][d['kind']] += 1
            # agreements aren't in details; recompute per symbol only if verbose
        worst = sorted(by_sym.items(),
                       key=lambda kv: -(kv[1].get('disagree', 0) * 3
                                        + kv[1].get('v2_miss', 0)))
        print('  worst symbols (disagree/miss/only):')
        for sym, kinds in worst[:12]:
            print('    %-9s dis=%-4d miss=%-4d only=%-4d'
                  % (sym, kinds.get('disagree', 0), kinds.get('v2_miss', 0),
                     kinds.get('v2_only', 0)))

    susp = [(p['mfr'], p['mpn'], d)
            for p in parts for d in (p.get('suspect_truth') or [])]
    if susp:
        print('-' * 78)
        print('SUSPECT TRUTH: %d key(s) where manual_fields differs from the'
              ' printed value by an SI prefix' % len(susp))
        print('  (review queue for a human — nothing is rescored. db shown as'
              ' context only: it inherits manual_fields overrides, so it is'
              ' NOT an independent witness)')
        for mfr, mpn, d in susp[:12]:
            indep = d.get('db_is_independent')
            tag = '' if indep is None else ('  db-indep' if indep else '  db=echo-of-truth')
            print('   %s/%s %s.%s truth=%s v2=%s db=%s ratio=%.4g%s'
                  % (mfr, mpn, d['symbol'], d['stat'], d['truth'], d['v2'],
                     d['db'], d['ratio'], tag))

    if uneval:
        print('-' * 78)
        reasons = defaultdict(int)
        for p in uneval:
            reasons[p['unevaluated'].split(':')[0]] += 1
        print('unevaluated:', dict(reasons))
        if verbose:
            for p in uneval[:30]:
                print('   %s/%s: %s' % (p['mfr'], p['mpn'], p['unevaluated']))

    if verbose:
        print('-' * 78)
        print('slowest parts:')
        for p in sorted((p for p in parts if p.get('seconds')),
                        key=lambda p: -p['seconds'])[:10]:
            print('   %6.2fs %s/%s' % (p['seconds'], p['mfr'], p['mpn']))
        print('-' * 78)
        print('disagreements vs truth (hard ground truth):')
        for p in parts:
            for d in (p.get('truth_details') or []):
                if d['kind'] == 'disagree':
                    print('   %s/%s %s.%s ref=%s v2=%s'
                          % (p['mfr'], p['mpn'], d['symbol'], d['stat'],
                             d['ref'], d['v2']))


def compare_runs(a_path: str, b_path: str) -> None:
    with open(a_path) as f:
        a = json.load(f)
    with open(b_path) as f:
        b = json.load(f)

    print('=' * 78)
    print('A = %s' % a_path)
    print('B = %s' % b_path)

    def spp(r):
        return r.get('seconds_per_part') or float('nan')

    print('speed  : %.2f -> %.2f s/part  (%.2fx)'
          % (spp(a), spp(b), spp(a) / spp(b) if spp(b) else float('nan')))

    sa, sb = _sum(a['parts'], 'sel'), _sum(b['parts'], 'sel')
    if sa or sb:
        print('-' * 78)
        for k in ('selectable', 'unselectable', 'no_cond'):
            va, vb = sa.get(k, 0), sb.get(k, 0)
            flag = ''
            if k == 'selectable' and vb < va:
                flag = '  <-- REGRESSION'
            if k in ('unselectable', 'no_cond') and vb > va:
                flag = '  <-- REGRESSION'
            print('%-6s %-12s %5d -> %5d  (%+d)%s'
                  % ('select', k, va, vb, vb - va, flag))
        print('%-6s %-12s %s -> %s'
              % ('select', 'rate', _fmt_acc(_sel_rate(sa)), _fmt_acc(_sel_rate(sb))))
        print('%-6s %-12s %s -> %s'
              % ('select', 'coverage', _fmt_acc(_cond_coverage(sa)),
                 _fmt_acc(_cond_coverage(sb))))

    for tier in ('truth', 'db'):
        ta, tb = _sum(a['parts'], tier), _sum(b['parts'], tier)
        if not ta and not tb:
            continue
        print('-' * 78)
        for k in ('agree', 'disagree', 'v2_miss', 'v2_only'):
            va, vb = ta.get(k, 0), tb.get(k, 0)
            flag = ''
            if k in ('agree',) and vb < va:
                flag = '  <-- REGRESSION'
            if k in ('disagree', 'v2_miss') and vb > va:
                flag = '  <-- REGRESSION'
            print('%-6s %-9s %5d -> %5d  (%+d)%s' % (tier, k, va, vb, vb - va, flag))
        print('%-6s %-9s %s -> %s' % (tier, 'accuracy', _fmt_acc(_acc(ta)),
                                      _fmt_acc(_acc(tb))))

    # per-part regression list
    idx_a = {(p['mfr'], p['mpn']): p for p in a['parts']}
    regressed = []
    for pb in b['parts']:
        pa = idx_a.get((pb['mfr'], pb['mpn']))
        if pa is None:
            continue
        for tier in ('truth', 'db'):
            ca, cb = pa.get(tier), pb.get(tier)
            if not ca or not cb:
                continue
            if cb.get('agree', 0) < ca.get('agree', 0):
                regressed.append((pb['mfr'], pb['mpn'], tier,
                                  ca.get('agree', 0), cb.get('agree', 0)))
    if regressed:
        print('-' * 78)
        print('parts that lost agreements:')
        for r in regressed[:40]:
            print('   %s/%s [%s] %d -> %d' % r)
    else:
        print('-' * 78)
        print('no part lost agreements.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--groups', type=int, default=40,
                    help='number of (mfr, mpn[:3]) series to sample')
    ap.add_argument('--per-group', type=int, default=2,
                    help='parts to take from each series')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--rtol', type=float, default=0.02)
    ap.add_argument('--mfr', action='append',
                    help='restrict to these manufacturers (repeatable)')
    ap.add_argument('--symbols', help='comma separated symbol whitelist')
    ap.add_argument('--no-cache', action='store_true',
                    help='disable disk_cache (required for honest timing)')
    ap.add_argument('--truth-only', action='store_true',
                    help='evaluate every dslib/manual_fields.py part instead '
                         'of sampling (hand-verified ground truth)')
    ap.add_argument('--max-details', type=int, default=200)
    ap.add_argument('--out', help='write the raw result JSON here')
    ap.add_argument('-v', '--verbose', action='store_true')
    ap.add_argument('--compare', nargs=2, metavar=('A.json', 'B.json'),
                    help='compare two previous runs instead of running')
    args = ap.parse_args()

    if args.compare:
        compare_runs(*args.compare)
        return

    res = run(args)
    report(res, args.verbose)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, 'w') as f:
            json.dump(res, f, indent=1)
        print('\nwrote %s' % args.out)


if __name__ == '__main__':
    main()
