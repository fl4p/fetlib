"""
Rigorous sampled audit of extraction methods (phase 2 of the domination study).

Unlike `apps/ddb.py -D` (observational: reads the pickled DB, biased by the
pipeline's need_symbols short-circuit), this RE-RUNS each extraction strategy
INDEPENDENTLY and UNCONDITIONALLY on a sample of datasheets, so every method
gets a fair shot at every symbol. That removes the short-circuit bias and lets
us answer:

  (a) Tabula's TRUE redundancy -- of the values Tabula extracts, how many does
      the cheap text/regex pass (or read_sheet) also produce, when all run?
  (b) Text-first risk -- if we demoted the expensive stages behind the cheap
      text pass, how often would we (i) miss a value text can't get, or
      (ii) adopt a WRONG value that a pricier method got right?

Ground truth is the hand-curated manual fields (dslib/manual_fields.py). Where
no manual truth exists we fall back to method CONSENSUS, but consensus among
text+read_sheet is weak (both read the same extracted text -- shared failure
modes), so accuracy is reported on the manual subset only; elsewhere we report
disagreement rate (blame unknown).

Usage:
    python apps/method_audit.py                 # 30-part random sample, seed 0
    python apps/method_audit.py --sample 50 -m infineon
    python apps/method_audit.py --prefer-truth  # bias sample toward manual-truth parts
    python apps/method_audit.py --tab-methods nop,gs   # skip OCR preprocessing (faster)

Runs from the repo root (relative datasheets/ and tabula lock paths).
"""

import argparse
import math
import os
import random
import re
import sys
import time
import warnings
from collections import Counter, defaultdict
from typing import Dict, Optional, Tuple

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
os.chdir(_REPO)  # tabular.py / datasheets paths are relative to repo root

import dslib.store
from dslib import mfr_tag
from dslib.field import DatasheetFields, Field
from apps.ddb import _method_cost, _vals_equal  # reuse cost model + tolerance

Key = Tuple[str, str]  # (symbol, stat)


# --- method runners: each returns {(symbol, stat): value} ------------------

def _flatten(ds: DatasheetFields) -> Dict[Key, float]:
    out = {}
    for sym, f in ds.fields_filled.items():
        for stat in Field.StatKeys:
            v = getattr(f, stat)
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                out[(sym, stat)] = float(v)
    return out


def run_text(pdf_path: str, mfr: str) -> Dict[Key, float]:
    from dslib.pdf.parse import extract_text, extract_fields_from_text, normalize_text
    pdf_text, _ = extract_text(pdf_path, try_ocr=False, auto_decrypt=True)
    pdf_text = normalize_text(pdf_text)
    ds = extract_fields_from_text(pdf_text, mfr=mfr, pdf_path=pdf_path, verbose=False)
    return _flatten(ds)


def run_read_sheet(pdf_path: str, mfr: str) -> Dict[Key, float]:
    from dslib.pdf.sheet import read_sheet
    ds = DatasheetFields()
    ds.add_multiple(read_sheet(pdf_path).all_fields())
    return _flatten(ds)


def run_tabular(pdf_path: str, mfr: str, pre_methods) -> Dict[Key, float]:
    # Union over ALL preprocessing methods (nop, gs, OCR) so we capture Tabula's
    # full capability -- the pipeline stops at the first that satisfies
    # need_symbols, which understates what Tabula could extract.
    from dslib.pdf.parse import tabula_read
    ds = DatasheetFields()
    for m in pre_methods:
        try:
            r = tabula_read(pdf_path, pre_process_methods=(m,), need_symbols=None)
            if r:
                ds.add_multiple(r.all_fields())
        except Exception as e:
            print(f'    tabular[{m}] error: {type(e).__name__}: {e}', flush=True)
    return _flatten(ds)


def run_v2(pdf_path: str, mfr: str) -> Dict[Key, float]:
    # dslib/v2: the independent spatial reader (pdfminer char geometry only, no
    # Tabula/Java). Not wired into the pipeline -- audited here as a candidate
    # replacement for the hand-written read_sheet.
    import dslib.v2
    return _flatten(dslib.v2.parse_datasheet(pdf_path, mfr=mfr))


RUNNERS = {
    'text': run_text,
    'v2': run_v2,
    'read_sheet': run_read_sheet,
    'tabular': run_tabular,
}


# --- per-part checkpointing (survive OOM kills; resume across restarts) -----
# Cold-cache parsing of some datasheets spikes memory hard enough that the OS
# kills the process mid-run. Since the report is emitted only at the end, a
# kill would otherwise lose everything. We persist each part's result the
# moment it's computed; on restart, completed parts load from disk (fresh
# process => memory can't accumulate across the kill boundary), so a few
# restarts always drive the sample to completion.
import hashlib
import json

# Source files whose content determines each method's output. The checkpoint
# stores a hash of these, so editing a parser AUTO-invalidates its checkpointed
# results -- a checkpoint keyed on (mfr,mpn) alone would serve pre-edit values
# forever and make a real improvement look like a no-op.
_METHOD_SRC = {
    'text': ['dslib/pdf/parse.py', 'dslib/pdf/expr.py', 'dslib/pdf/pdf2txt/__init__.py'],
    'v2': ['dslib/v2/__init__.py', 'dslib/v2/chars.py', 'dslib/v2/tables.py'],
    'read_sheet': ['dslib/pdf/sheet/__init__.py', 'dslib/pdf/sheet/spatial.py',
                   'dslib/pdf/sheet/tables.py'],
    'tabular': ['dslib/pdf/parse.py', 'dslib/pdf/tabular.py'],
}
_UNKNOWN_SIG = 0  # counter making every unresolvable signature unique => never matches


def _code_sig(method: str) -> str:
    """Content hash of the code that derives `method`'s values.

    If any source file is missing/unreadable we must NOT return a stable value --
    that would let an unverifiable signature masquerade as "unchanged". Return a
    never-matching sentinel instead, forcing a live re-parse.
    """
    global _UNKNOWN_SIG
    files = _METHOD_SRC.get(method)
    if not files:
        _UNKNOWN_SIG += 1
        return f'unknown-method-{method}-{_UNKNOWN_SIG}'
    h = hashlib.sha256()
    for rel in sorted(files):
        try:
            with open(os.path.join(_REPO, rel), 'rb') as fh:
                h.update(rel.encode())
                h.update(fh.read())
        except OSError:
            _UNKNOWN_SIG += 1
            return f'unreadable-{method}-{rel}-{_UNKNOWN_SIG}'
    return h.hexdigest()[:16]


def _ckpt_path(ckpt_dir: str, mfr: str, mpn: str) -> str:
    safe = f'{mfr}__{mpn}'.replace('/', '_').replace(os.sep, '_')
    return os.path.join(ckpt_dir, safe + '.json')


def _save_ckpt(ckpt_dir: str, mfr: str, mpn: str, per: Dict[str, Dict[Key, float]],
               sigs: Optional[Dict[str, str]] = None):
    os.makedirs(ckpt_dir, exist_ok=True)
    sigs = sigs or {}
    payload = {m: {'sig': sigs.get(m) or _code_sig(m),
                   'vals': [[sym, stat, val] for (sym, stat), val in kv.items()]}
               for m, kv in per.items()}
    tmp = _ckpt_path(ckpt_dir, mfr, mpn) + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(payload, fh)
    os.replace(tmp, _ckpt_path(ckpt_dir, mfr, mpn))  # atomic; no half-written ckpt


def _load_ckpt(ckpt_dir: str, mfr: str, mpn: str, adopt_legacy_sig: bool = False):
    """Load a checkpoint, dropping any method whose parser code has changed.

    Returns (per_method_values, stale_methods). Entries in the pre-signature
    format are only kept when `adopt_legacy_sig` is set (an explicit, one-time
    migration by a caller asserting the code is unchanged since they were
    written); otherwise they are reported stale and re-parsed.
    """
    p = _ckpt_path(ckpt_dir, mfr, mpn)
    if not os.path.isfile(p):
        return {}, []
    try:
        with open(p) as fh:
            payload = json.load(fh)
    except Exception:
        return {}, []  # unreadable => re-parse, never "assume fine"
    out, stale = {}, []
    for m, entry in payload.items():
        if isinstance(entry, list):  # legacy: no signature recorded
            if not adopt_legacy_sig:
                stale.append(f'{m}(legacy-unsigned)')
                continue
            triples = entry
        elif isinstance(entry, dict):
            if entry.get('sig') != _code_sig(m):
                stale.append(f'{m}(code-changed)')
                continue
            triples = entry.get('vals') or []
        else:
            stale.append(f'{m}(corrupt)')
            continue
        out[m] = {(sym, stat): float(val) for sym, stat, val in triples}
    return out, stale


# --- ground truth ----------------------------------------------------------

# manual_fields.py is NOT uniformly extraction ground truth. Some entries exist
# because a parser failed ("# tabula failure", "# need OCR") -- those ARE truth.
# Others DELIBERATELY CONTRADICT the printed datasheet ("# error in Datasheet
# (mistake)", "# the datasheet has a different definition of Qg_th?"). A correct
# extractor MUST disagree with those, so scoring them makes accuracy
# anti-monotone: improving extraction lowers the score. We tier them and score
# only the uncontested keys.
_CONTESTED_MARKERS = (
    'error in datasheet', 'mistake', 'different definition', 'very low?',
)
_TRUTH_MARKERS = ('tabula failure', 'need ocr')  # kept for documentation of the legit tier


def _contested_keys() -> Dict[Tuple[str, str], Dict[str, str]]:
    """(mfr_tag, mpn) -> {symbol: marker} for entries that contradict the PDF.

    Parsed from the SOURCE of manual_fields.py because the markers are comments
    and so absent from the imported objects. Three comment placements all count:
    on the `'MPN': [` line (applies to the whole block), on the `Field(...)` line
    (that symbol only), and on a standalone line (applies to the Field(s) that
    follow it within the block).
    """
    import dslib.manual_fields as mf
    out: Dict[Tuple[str, str], Dict[str, str]] = {}
    try:
        with open(mf.__file__, encoding='utf-8') as fh:
            lines = fh.readlines()
    except OSError:
        return out  # cannot tier -> caller keeps full truth and says so
    cur_mfr = cur_mpn = None
    block_marker = pending_marker = None
    for ln in lines:
        m_mfr = re.match(r"^(\w+)\s*=\s*(?:dict\(|\{)", ln)
        if m_mfr:
            cur_mfr, cur_mpn = m_mfr.group(1), None
            block_marker = pending_marker = None
            continue
        m_mpn = re.match(r"\s*['\"]([^'\"]+)['\"]\s*:\s*\[", ln)
        if m_mpn:
            cur_mpn = m_mpn.group(1)
            cmt = ln.split('#', 1)[1].lower() if '#' in ln else ''
            block_marker = next((k for k in _CONTESTED_MARKERS if k in cmt), None)
            pending_marker = None
            continue
        stripped = ln.strip()
        if stripped.startswith('#'):  # standalone comment -> applies to Fields below
            cmt = stripped[1:].lower()
            pending_marker = next((k for k in _CONTESTED_MARKERS if k in cmt),
                                 pending_marker)
            continue
        if 'Field(' in ln and cur_mfr and cur_mpn:
            m_sym = re.search(r"Field\(\s*['\"]([^'\"]+)['\"]", ln)
            if not m_sym:
                continue
            cmt = ln.split('#', 1)[1].lower() if '#' in ln else ''
            marker = (next((k for k in _CONTESTED_MARKERS if k in cmt), None)
                      or pending_marker or block_marker)
            if marker:
                out.setdefault((mfr_tag(cur_mfr), cur_mpn), {})[m_sym.group(1)] = marker
            continue
        if stripped in ('],', ']'):  # end of an MPN block
            pending_marker = None
    return out


def build_truth(drop_contested: bool = True):
    """(mfr_tag, mpn) -> {(sym, stat): value} from manual_fields.

    Returns (truth, contested_count). Entries whose comment marks them as a
    deliberate contradiction of the datasheet are excluded from `truth` when
    `drop_contested` -- scoring an extractor against them punishes correctness.
    """
    import dslib.manual_fields as mf
    mod = mf.get_fields()  # stamps 'manual' source; returns module __dict__
    contested = _contested_keys() if drop_contested else {}
    truth: Dict[Tuple[str, str], Dict[Key, float]] = {}
    n_contested = 0
    for name, d in list(mod.items()):
        if name.startswith('_') or not isinstance(d, dict):
            continue
        for mpn, flist in d.items():
            if not isinstance(flist, list) or not flist:
                continue
            if not all(isinstance(f, Field) for f in flist):
                continue
            key = (mfr_tag(name), str(mpn))
            bad_syms = contested.get(key, {})
            slot = truth.setdefault(key, {})
            for f in flist:
                if f.symbol in bad_syms:
                    n_contested += 1
                    continue
                for stat in Field.StatKeys:
                    v = getattr(f, stat)
                    if v is not None and not (isinstance(v, float) and math.isnan(v)):
                        slot[(f.symbol, stat)] = float(v)
    return {k: v for k, v in truth.items() if v}, n_contested


# --- sampling --------------------------------------------------------------

def select_sample(n: int, seed: int, mfr_sub: Optional[str], prefer_truth: bool,
                  truth: Dict[Tuple[str, str], Dict[Key, float]]):
    db = dslib.store.datasheets_db.load()
    cands = []
    for (mfr, mpn), ds in db.items():
        if mfr_sub and mfr_sub.lower() not in (mfr or '').lower():
            continue
        try:
            path = ds.ds_path
        except Exception:
            continue
        if path and os.path.isfile(path):
            cands.append((mfr, mpn, path))
    rng = random.Random(seed)
    rng.shuffle(cands)
    if prefer_truth:
        has = [c for c in cands if (mfr_tag(c[0]), c[1]) in truth]
        no = [c for c in cands if (mfr_tag(c[0]), c[1]) not in truth]
        cands = has + no
    sample = cands[:n]
    # free the 112 MB DB (cached in the ObjectDatabase singleton) so parsing
    # has memory headroom -- the resident DB is what OOM-killed the OCR run.
    dslib.store.datasheets_db.unload()
    del db, cands
    import gc
    gc.collect()
    return sample


# --- analysis --------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sample', type=int, default=30, help='number of datasheets (default 30)')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('-m', '--mfr', help='restrict sample to a manufacturer substring')
    ap.add_argument('--rtol', type=float, default=0.02, help='value-agreement tolerance')
    ap.add_argument('--methods', default='text,read_sheet,tabular',
                    help='comma list of methods to run')
    ap.add_argument('--tab-methods', default='nop,gs,r600_ocrmypdf',
                    help='tabula preprocessing methods to union (default incl. OCR)')
    ap.add_argument('--prefer-truth', action='store_true',
                    help='bias the sample toward parts with manual ground truth')
    ap.add_argument('--resume-dir', default='out/method_audit',
                    help='per-part checkpoint dir; completed parts are reused so '
                         'an OOM-killed run resumes on restart (default out/method_audit)')
    ap.add_argument('--adopt-legacy-checkpoints', action='store_true',
                    help='one-time migration: trust pre-signature checkpoints and stamp '
                         'them with the CURRENT code signature. Only correct if the '
                         'parsers have not changed since those checkpoints were written.')
    ap.add_argument('--dump-defects', default='',
                    help='comma list of methods (or "all") whose per-key truth defects '
                         'to print: every MISS and WRONG with the truth value and which '
                         'other methods got it right. Use this instead of scripting a '
                         'dump off the checkpoints.')
    ap.add_argument('--refresh', default='',
                    help='comma list of methods to re-run even if checkpointed (or '
                         '"all"). REQUIRED after editing a parser: checkpoints are '
                         'keyed on (mfr,mpn) only, NOT on parser code, so a stale '
                         'checkpoint would silently serve pre-edit results.')
    args = ap.parse_args(argv)

    methods = [m.strip() for m in args.methods.split(',') if m.strip()]
    refresh = {m.strip() for m in args.refresh.split(',') if m.strip()}
    if 'all' in refresh:
        refresh = set(RUNNERS)
    unknown = refresh - set(RUNNERS)
    if unknown:  # fail loudly: a typo'd --refresh must not silently serve stale results
        ap.error(f'--refresh: unknown method(s) {sorted(unknown)}; '
                 f'known: {sorted(RUNNERS)} (or "all")')
    if refresh:
        print(f'# --refresh: ignoring checkpoints for {sorted(refresh)} '
              f'(re-parsing them live)')
    pre_methods = tuple(m.strip() for m in args.tab_methods.split(',') if m.strip())
    rtol = args.rtol

    truth, n_contested = build_truth()
    sample = select_sample(args.sample, args.seed, args.mfr, args.prefer_truth, truth)
    if not sample:
        print('no sampled parts have a PDF on disk', file=sys.stderr)
        return 1

    n_truth = sum((mfr_tag(m), p) in truth for m, p, _ in sample)
    print(f'# rigorous method audit: {len(sample)} datasheets '
          f'({n_truth} with manual truth), methods={methods}, '
          f'tab_pre={pre_methods}, rtol={rtol:.0%}')
    print('# running each method independently & unconditionally per PDF ...\n')

    # per-method timing
    m_time: Dict[str, float] = defaultdict(float)
    # parts parsed live this run, PER METHOD (m_time only covers these; resumed
    # parts contribute no wall-clock, so cost/part must divide by this)
    n_fresh: Dict[str, int] = defaultdict(int)
    # per (part) -> method -> {key: value}
    results = []
    for i, (mfr, mpn, path) in enumerate(sample):
        cached, stale = _load_ckpt(args.resume_dir, mfr, mpn,
                                   adopt_legacy_sig=args.adopt_legacy_checkpoints)
        cached = {m: v for m, v in cached.items() if m not in refresh}
        todo = [m for m in methods if m not in cached]
        stale_note = f' [stale: {",".join(stale)}]' if stale else ''
        if not todo:
            print(f'[{i+1}/{len(sample)}] {mfr}/{mpn} (resumed from checkpoint)'
                  f'{stale_note}', flush=True)
            if args.adopt_legacy_checkpoints:
                # persist the adopted signatures, else the migration never sticks
                _save_ckpt(args.resume_dir, mfr, mpn, cached)
            results.append((mfr, mpn, {m: cached[m] for m in methods}))
            continue
        note = '' if len(todo) == len(methods) else \
            f' (resumed {sorted(set(methods) - set(todo))}, running {todo})'
        print(f'[{i+1}/{len(sample)}] {mfr}/{mpn}{note}{stale_note}', flush=True)
        # keep already-computed methods; only run what's missing (adding a new
        # method must not force a full cold re-parse of the others)
        per = {m: cached[m] for m in methods if m in cached}
        for m in todo:
            t0 = time.time()
            try:
                if m == 'tabular':
                    per[m] = run_tabular(path, mfr, pre_methods)
                else:
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore')
                        per[m] = RUNNERS[m](path, mfr)
            except Exception as e:
                print(f'    {m} FAILED: {type(e).__name__}: {e}')
                per[m] = {}
            m_time[m] += time.time() - t0
            n_fresh[m] += 1
        # merge over the whole checkpoint so methods outside --methods survive
        _save_ckpt(args.resume_dir, mfr, mpn, {**cached, **per})  # persist before next part can OOM us
        results.append((mfr, mpn, per))

    # aggregate
    produced = Counter()             # values each method produced
    repro_any = Counter()            # ... also produced (equal) by some other method
    repro_cheaper = Counter()        # ... also produced (equal) by a cheaper method
    sole_producer = Counter()        # ... no other method produced any value for that key
    cheaper_by = defaultdict(Counter)

    # truth-based accuracy (manual subset)
    t_produced = Counter()
    t_correct = Counter()
    t_wrong = Counter()
    t_sole_correct = Counter()       # only this method got the truth value
    t_missed = Counter()             # truth key existed, method produced NOTHING
    t_available = [0]                # truth keys examined (shared denominator)
    defects = defaultdict(list)      # method -> [(mfr,mpn,key,got,truth,who_got_it)]

    # text-first decision counters (over keys where a truth value exists,
    # manual OR strong-consensus incl. tabular)
    tf_covered = 0                   # keys with a truth value
    tf_text_ok = 0                   # text produced the truth value
    tf_text_miss = 0                 # text absent, a pricier method has truth
    tf_text_wrong = 0                # text present but wrong, a pricier method has truth
    # unbiased conflict surface (no truth needed)
    conflicts = Counter()            # per method: produced a value conflicting w/ another

    def strong_truth(vals: Dict[str, float]) -> Optional[float]:
        """Consensus truth requiring an independent (tabular) corroboration:
        tabular agrees with at least one text-based method."""
        if 'tabular' not in vals:
            return None
        tv = vals['tabular']
        for m in ('text', 'read_sheet'):
            if m in vals and _vals_equal(vals[m], tv, rtol):
                return tv
        return None

    for mfr, mpn, per in results:
        tkey = (mfr_tag(mfr), mpn)
        manual = truth.get(tkey, {})
        keys = set()
        for d in per.values():
            keys.update(d.keys())
        for key in keys:
            vals = {m: per[m][key] for m in methods if key in per[m]}
            if not vals:
                continue
            # --- redundancy (no truth) ---
            for m, v in vals.items():
                produced[m] += 1
                others = {mm: vv for mm, vv in vals.items() if mm != m}
                eq = {mm for mm, vv in others.items() if _vals_equal(vv, v, rtol)}
                if not others:
                    sole_producer[m] += 1
                if eq:
                    repro_any[m] += 1
                    cheap = {mm for mm in eq if _method_cost(mm) < _method_cost(m)}
                    if cheap:
                        repro_cheaper[m] += 1
                        for mm in cheap:
                            cheaper_by[m][mm] += 1
                # conflict surface: another method has a DIFFERENT value
                if any(not _vals_equal(vv, v, rtol) for vv in others.values()):
                    conflicts[m] += 1

            # --- truth value for this key ---
            tv = manual.get(key)
            tsource = 'manual'
            if tv is None:
                tv = strong_truth(vals)
                tsource = 'consensus'
            if tv is None:
                continue

            if tsource == 'manual':
                t_available[0] += 1  # truth keys in play (same denominator for all)
                for m, v in vals.items():
                    t_produced[m] += 1
                    if _vals_equal(v, tv, rtol):
                        t_correct[m] += 1
                    else:
                        t_wrong[m] += 1
                for m in methods:  # a method that produced NOTHING is a MISS, not a pass
                    if m not in vals:
                        t_missed[m] += 1
                # record per-key defects for --dump-defects. Emitted by the SAME
                # run that computes the report, so the list can never disagree
                # with the numbers (a separately-scripted dump reading stale
                # checkpoints once overstated v2's misses ~7x).
                for m in methods:
                    v = vals.get(m)
                    if v is None:
                        defects[m].append((mfr, mpn, key, None, tv,
                                           sorted(mm for mm, vv in vals.items()
                                                  if _vals_equal(vv, tv, rtol))))
                    elif not _vals_equal(v, tv, rtol):
                        defects[m].append((mfr, mpn, key, v, tv,
                                           sorted(mm for mm, vv in vals.items()
                                                  if _vals_equal(vv, tv, rtol))))
                correct_ms = {m for m, v in vals.items() if _vals_equal(v, tv, rtol)}
                if len(correct_ms) == 1:
                    t_sole_correct[next(iter(correct_ms))] += 1

            # text-first decision (manual OR strong consensus)
            tf_covered += 1
            pricier_ok = any(_vals_equal(v, tv, rtol) for m, v in vals.items()
                             if m != 'text' and _method_cost(m) > _method_cost('text'))
            if 'text' in vals and _vals_equal(vals['text'], tv, rtol):
                tf_text_ok += 1
            elif 'text' not in vals:
                if pricier_ok:
                    tf_text_miss += 1
            else:  # text present but wrong
                if pricier_ok:
                    tf_text_wrong += 1

    def pct(a, b):
        return (100.0 * a / b) if b else 0.0

    all_m = sorted(set(produced), key=lambda m: (_method_cost(m), m))

    print('\n' + '=' * 78)
    print(f'## empirical cost (wall-clock; per method, only freshly-parsed parts '
          f'count -- checkpoint-resumed parts contribute no time):')
    for m in sorted(m_time, key=lambda m: -m_time[m]):
        nf = n_fresh[m]
        print(f'  {m:<14} {m_time[m]:8.1f}s total   {m_time[m]/max(nf,1):8.2f}s/part'
              f'   (fresh {nf}/{len(sample)}, {len(sample)-nf} resumed)')
    if not any(n_fresh.values()):
        print('  (everything resumed from checkpoints -- no timing measured this run)')

    print('\n## (a) UNBIASED redundancy -- all methods run on every symbol:')
    print(f'{"method":<14}{"cost":>5}{"values":>8}{"sole-src":>10}'
          f'{"repro-any":>11}{"repro-cheap":>13}  cheaper-coverer')
    for m in all_m:
        p = produced[m]
        tc = cheaper_by[m].most_common(1)
        tc_s = f'{tc[0][0]} {pct(tc[0][1], p):.0f}%' if tc else '-'
        print(f'{m:<14}{_method_cost(m):>5.1f}{p:>8}{pct(sole_producer[m], p):>9.0f}%'
              f'{pct(repro_any[m], p):>10.0f}%{pct(repro_cheaper[m], p):>12.0f}%  {tc_s}')

    print('\n## (b1) accuracy on MANUAL-truth subset (hard ground truth):')
    print(f'  ({n_contested} manual entries EXCLUDED as contested -- comments mark them as '
          f'deliberate\n   contradictions of the printed datasheet, so a correct extractor '
          f'must disagree.)')
    if sum(t_produced.values()) == 0:
        print('  (no manual-truth keys in this sample -- use --prefer-truth or -m infineon)')
    else:
        # PRECISION (of values produced, how many right) is NOT the whole story:
        # a method that produces nothing for a truth key is silently perfect on
        # precision. RECALL (of the truth keys in play, how many it got right)
        # is what catches a method that simply fails to find things.
        print(f'  {t_available[0]} manual-truth keys in play (shared recall denominator)')
        print(f'{"method":<14}{"scored":>8}{"correct":>9}{"wrong":>7}'
              f'{"precis":>8}{"missed":>8}{"RECALL":>8}{"sole-ok":>9}')
        for m in all_m:
            tp = t_produced[m]
            if not tp and not t_missed[m]:
                continue
            print(f'{m:<14}{tp:>8}{t_correct[m]:>9}{t_wrong[m]:>7}'
                  f'{pct(t_correct[m], tp):>7.0f}%{t_missed[m]:>8}'
                  f'{pct(t_correct[m], t_available[0]):>7.0f}%{t_sole_correct[m]:>9}')

    print('\n## (b2) text-first decision (truth = manual or tabular-corroborated consensus):')
    print(f'  truth-valued keys examined:        {tf_covered}')
    print(f'  text already gets the truth value: {tf_text_ok} ({pct(tf_text_ok, tf_covered):.0f}%)')
    print(f'  text MISSES (pricier method has it):{tf_text_miss} ({pct(tf_text_miss, tf_covered):.0f}%)'
          '  -> still need the pricier stage for these')
    print(f'  text WRONG but pricier is right:    {tf_text_wrong} ({pct(tf_text_wrong, tf_covered):.0f}%)'
          '  -> regressions if we blindly trust text first')

    print('\n## conflict surface (blame unknown -- another method disagrees):')
    for m in all_m:
        print(f'  {m:<14} {conflicts[m]:>5} / {produced[m]} values '
              f'({pct(conflicts[m], produced[m]):.0f}%) conflict with another method')

    print('\n## verdict:')
    tab_sole = sole_producer.get('tabular', 0)
    tab_p = produced.get('tabular', 0)
    if tab_p:
        print(f'  tabular: {pct(repro_cheaper["tabular"], tab_p):.0f}% of its {tab_p} values are '
              f'reproduced by a cheaper method; {pct(tab_sole, tab_p):.0f}% '
              f'({tab_sole}) are sole-source (lost if removed).')
    print(f'  text-first regression risk: {pct(tf_text_wrong, tf_covered):.0f}% of truth-valued keys '
          f'({tf_text_wrong}); coverage gap: {pct(tf_text_miss, tf_covered):.0f}% ({tf_text_miss}).')
    print('\n  NOTE: consensus truth leans on tabular corroboration (text & read_sheet '
          'share the\n  extracted-text failure mode, so their agreement is not independent). '
          'Widen the\n  manual subset (--prefer-truth) for a firmer accuracy read.')

    dump = {m.strip() for m in args.dump_defects.split(',') if m.strip()}
    if 'all' in dump:
        dump = set(methods)
    for m in sorted(dump & set(methods), key=lambda x: (_method_cost(x), x)):
        rows = defects[m]
        print(f'\n## per-key truth defects for {m} ({len(rows)}): '
              f'MISS = produced nothing, WRONG = produced a different value')
        for mfr, mpn, key, got, tv, who in rows:
            kind = 'MISS ' if got is None else 'WRONG'
            gs = 'none' if got is None else f'{got:g}'
            print(f'  {kind} {mfr}/{mpn:<24} {key[0]}.{key[1]:<5} got={gs:<9} '
                  f'truth={tv:<9g} got-it-right: {who or "NOBODY"}')
        if not rows:
            print('  (none)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
