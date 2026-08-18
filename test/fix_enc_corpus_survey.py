"""Survey the REAL suspect-font corpus, ranked by how much like language the
repaired text reads.

WHY A PROXY, AND WHAT IT IS AND IS NOT
--------------------------------------
`test/fix_enc_eval.py` measures accuracy against a truth known by construction,
but it can only do that on SYNTHETIC pages: it has to write a correct
/ToUnicode before deleting it. The 2 368 real PDFs with a suspect font have no
truth available at any price -- if we knew what they said, there would be
nothing to repair.

What is available is a proxy. After repair the text either reads like datasheet
English or it does not, and the character n-gram model in `dslib/pdf/glyph_lm`
already scores exactly that. Mean log-probability per character ("perplexity",
lower magnitude = more language-like) is not accuracy, but it is strongly
ordered with it, and that is enough for the job this file is for: RANKING, so
that attention goes to the worst files rather than to whichever part someone
happened to open.

It is emphatically NOT a score to optimise. Three ways it lies, all of which
have to be read alongside the number:

 * A font that repairs to a uniformly SHIFTED alphabet scores terribly and is
   one substitution from perfect. A font that declines every glyph to a space
   scores well, because a page of spaces contains no improbable n-grams -- so
   `blank_frac` is reported next to it and a high one voids the score.
 * The model was trained on datasheet English. A page that is legitimately all
   numbers, or in Chinese, scores badly while being perfectly correct. Hence
   `alpha_frac`.
 * The language model is also, optionally, part of the matcher being measured
   (`--lm`). Scoring a stage with its own objective is circular, which is why
   the default here runs the matcher WITHOUT it. Pass `--lm` deliberately, and
   read the ranking as descriptive rather than comparative.

The baseline is the honest anchor: every file is also scored on the text
extractable BEFORE repair, and the delta is what the repair actually bought.

USAGE
-----
    python test/fix_enc_corpus_survey.py --limit 200
    python test/fix_enc_corpus_survey.py --mfr infineon --limit 100
    python test/fix_enc_corpus_survey.py --limit 400 -j 8 --csv out/survey.csv
    python test/fix_enc_corpus_survey.py --worst 40      # longer bad-list
"""

import argparse
import concurrent.futures
import csv
import os
import pathlib
import sys
import time
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# One file
# ---------------------------------------------------------------------------

class Survey:
    __slots__ = ('path', 'mfr', 'n_fonts', 'n_cids', 'chars', 'score',
                 'base_score', 'blank_frac', 'alpha_frac', 'exact_fonts',
                 'fontid_fonts', 'seconds', 'error')

    def __init__(self, path):
        self.path = path
        self.mfr = os.path.basename(os.path.dirname(path))
        self.n_fonts = self.n_cids = self.chars = 0
        self.score = self.base_score = float('nan')
        self.blank_frac = self.alpha_frac = 0.0
        self.exact_fonts = self.fontid_fonts = 0
        self.seconds = 0.0
        self.error = ''


def _mean_logp(lm, lines: List[str]) -> Tuple[float, int]:
    """Mean log-probability per character over the given lines."""
    total = 0.0
    n = 0
    for ln in lines:
        if len(ln) < 4:
            continue
        total += lm.logp(ln)
        n += len(ln)
    return (total / n if n else float('nan')), n


def survey_one(path: str, use_lm: bool = False,
               max_lines: int = 400) -> Survey:
    import pymupdf
    from dslib.pdf import fix_encoding as fe
    from dslib.pdf import glyph_lm as gl

    r = Survey(path)
    t0 = time.time()
    lm = gl.get_lm()
    if lm is None:
        r.error = 'no language model corpus'
        return r
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        r.error = 'open: %s' % e
        return r

    try:
        fonts = fe._scan_fonts(doc)
        r.n_fonts = len(fonts)
        if not fonts:
            r.error = 'no suspect font'
            return r

        ref_items = list(fe._reference_glyphs().items())
        after: List[str] = []
        before: List[str] = []
        blanks = total = 0

        for fi in fonts:
            r.n_cids += len(fi.used_codes)
            try:
                mapping = fe._build_font_mapping(
                    doc, fi, ref_items, min_similarity=0.30, use_lm=use_lm)
            except Exception as e:
                r.error = 'map %s: %s' % (fi.short_name, e)
                continue
            if not mapping:
                continue
            blanks += sum(1 for v in mapping.values() if v == ' ')
            total += len(mapping)
            try:
                runs = gl.cid_runs(doc, fi.xref, fi.is_type0)
            except Exception:
                continue
            for run in runs[:max_lines]:
                after.append(gl._decode(run, mapping))
                # The pre-repair reading: CIDs interpreted as raw code points,
                # which is exactly what an unrepaired extractor produces.
                before.append(''.join(
                    chr(c) if 32 <= c < 0x3000 else ' ' for c in run))

        if total:
            r.blank_frac = blanks / total
        r.score, r.chars = _mean_logp(lm, after)
        r.base_score, _ = _mean_logp(lm, before)
        joined = ''.join(after)
        if joined:
            r.alpha_frac = sum(c.isalpha() for c in joined) / len(joined)
    except Exception as e:
        r.error = repr(e)
    finally:
        doc.close()
        r.seconds = time.time() - t0
    return r


def _worker(args):
    path, use_lm = args
    try:
        return survey_one(path, use_lm)
    except Exception as e:  # a crash on one PDF must not kill the sweep
        s = Survey(path)
        s.error = repr(e)
        return s


# ---------------------------------------------------------------------------
# Corpus selection
# ---------------------------------------------------------------------------

def find_suspect_pdfs(root: str, limit: int, mfr: Optional[str],
                      stride: int = 1) -> List[str]:
    """PDFs under `root` that `has_custom_font_encoding` flags, in sorted order.

    Sorted and strided rather than sampled at random, so two runs over the same
    tree survey the same files and their numbers can be compared. Detection is
    the expensive part of selection, so the scan stops as soon as `limit` files
    have been found rather than classifying the whole 24 519-file tree.
    """
    from dslib.pdf.fix_encoding import has_custom_font_encoding

    base = os.path.join(root, mfr) if mfr else root
    all_pdfs = []
    for dirpath, _dirs, files in os.walk(base):
        for f in sorted(files):
            if f.lower().endswith('.pdf'):
                all_pdfs.append(os.path.join(dirpath, f))
    all_pdfs.sort()
    all_pdfs = all_pdfs[::stride]

    out = []
    for p in all_pdfs:
        if len(out) >= limit:
            break
        try:
            if has_custom_font_encoding(p):
                out.append(p)
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def report(results: List[Survey], n_worst: int, use_lm: bool) -> None:
    ok = [r for r in results if not r.error and r.chars > 50]
    thin = [r for r in results if not r.error and r.chars <= 50]
    print()
    print('=' * 78)
    print('REAL-CORPUS SURVEY -- %d files, %d scored%s'
          % (len(results), len(ok), ', matcher LM ON' if use_lm else ''))
    print('=' * 78)

    # Accounting for everything, because a report that lists only the files it
    # could score reads as a statement about the corpus when it is a statement
    # about the sample that survived. This is the single most misleading thing
    # a survey like this can do.
    if thin:
        no_glyphs = sum(1 for r in thin if r.blank_frac > 0.9)
        print()
        print('%d files produced too little text to score (<=50 chars).'
              % len(thin))
        print('  Of those, %d had >90%% of their CIDs DECLINED -- the matcher'
              % no_glyphs)
        print('  rendered or resolved almost nothing, which is a real failure')
        print('  and not a property of the page. The rest are genuinely small')
        print('  suspect fonts: a logo or a few symbols, with the body text in')
        print('  an unaffected font. Only the scored files appear below.')
    if not ok:
        print('nothing scored; errors:')
        for r in results[:20]:
            print('   %-58s %s' % (os.path.basename(r.path)[:58], r.error))
        return

    ok.sort(key=lambda r: r.score)
    scores = [r.score for r in ok]
    n = len(scores)

    def pct(q):
        return scores[min(n - 1, int(q * n / 100))]

    print()
    print('mean log-prob per character (higher = more language-like)')
    print('  after repair : p10=%.2f p25=%.2f p50=%.2f p75=%.2f p90=%.2f'
          % (pct(10), pct(25), pct(50), pct(75), pct(90)))
    base = sorted(r.base_score for r in ok if r.base_score == r.base_score)
    if base:
        bm = base[len(base) // 2]
        print('  before       : p50=%.2f          (delta at the median: %+.2f)'
              % (bm, pct(50) - bm))
    print('  a fluent English line scores about -2.5; uniform noise about -4.5')

    print()
    print('by manufacturer (median after repair, worst first)')
    print('-' * 78)
    by_mfr: Dict[str, List[float]] = {}
    for r in ok:
        by_mfr.setdefault(r.mfr, []).append(r.score)
    rows = sorted(((sorted(v)[len(v) // 2], k, len(v))
                   for k, v in by_mfr.items()))
    for med, mfr, cnt in rows:
        bar = '#' * max(0, min(40, int((med + 5.0) * 12)))
        print('  %-16s n=%-4d %6.2f  %s' % (mfr[:16], cnt, med, bar))

    print()
    print('worst %d files -- where the repair is least convincing' % n_worst)
    print('-' * 78)
    print('  %-42s %7s %7s %6s %6s' % ('file', 'after', 'before', 'blank', 'alpha'))
    for r in ok[:n_worst]:
        print('  %-42s %7.2f %7.2f %5.0f%% %5.0f%%'
              % (('%s/%s' % (r.mfr, os.path.basename(r.path)))[:42],
                 r.score, r.base_score, 100 * r.blank_frac,
                 100 * r.alpha_frac))
    print()
    print('  Read `blank` and `alpha` before believing `after`: a font that')
    print('  declined every glyph scores WELL (spaces contain no improbable')
    print('  n-grams) and a page of pure numbers scores BADLY while being right.')

    errs = [r for r in results if r.error]
    if errs:
        print()
        print('%d files not scored:' % len(errs))
        seen: Dict[str, int] = {}
        for r in errs:
            seen[r.error.split(':')[0][:40]] = seen.get(
                r.error.split(':')[0][:40], 0) + 1
        for k, v in sorted(seen.items(), key=lambda kv: -kv[1]):
            print('   %-50s x%d' % (k, v))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description='Rank the real suspect-font corpus by how language-like '
                    'the repaired text reads.')
    ap.add_argument('--datasheets', default=str(REPO_ROOT / 'datasheets'))
    ap.add_argument('--limit', type=int, default=150,
                    help='how many suspect PDFs to survey (default 150)')
    ap.add_argument('--stride', type=int, default=1,
                    help='sample every Nth PDF when scanning for suspects, to '
                         'spread the sample across manufacturers')
    ap.add_argument('--mfr', help='restrict to one manufacturer directory')
    ap.add_argument('-j', '--jobs', type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument('--lm', action='store_true',
                    help='run the matcher WITH its language-model stage. Off by '
                         'default: scoring that stage with its own objective is '
                         'circular')
    ap.add_argument('--worst', type=int, default=25)
    ap.add_argument('--csv', help='also write per-file rows here')
    args = ap.parse_args(argv)

    print('scanning %s for suspect fonts ...' % args.datasheets)
    pdfs = find_suspect_pdfs(args.datasheets, args.limit, args.mfr, args.stride)
    if not pdfs:
        print('no suspect PDFs found', file=sys.stderr)
        return 2
    print('%d suspect PDFs, surveying with %d jobs' % (len(pdfs), args.jobs))

    results: List[Survey] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as ex:
        for i, r in enumerate(ex.map(_worker, [(p, args.lm) for p in pdfs]), 1):
            results.append(r)
            if i % 25 == 0:
                print('  %d/%d' % (i, len(pdfs)))

    report(results, args.worst, args.lm)

    if args.csv:
        os.makedirs(os.path.dirname(args.csv) or '.', exist_ok=True)
        with open(args.csv, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['path', 'mfr', 'n_fonts', 'n_cids', 'chars',
                        'score_after', 'score_before', 'blank_frac',
                        'alpha_frac', 'seconds', 'error'])
            for r in results:
                w.writerow([r.path, r.mfr, r.n_fonts, r.n_cids, r.chars,
                            '%.4f' % r.score, '%.4f' % r.base_score,
                            '%.4f' % r.blank_frac, '%.4f' % r.alpha_frac,
                            '%.2f' % r.seconds, r.error])
        print('wrote %s' % args.csv)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
