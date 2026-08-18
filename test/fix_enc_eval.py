"""Ground-truth accuracy harness for the glyph matcher in dslib/pdf/fix_encoding.py.

WHY THIS EXISTS
---------------
Until this file, nothing in the repo reported how often the matcher is RIGHT.
`test/unit/test_pdf_fix_enc*.py` assert behaviour (this keyword appears, that
PDF is detected) on nine hand-picked datasheets; they are regression tests, not
a measurement. Every constant the matcher arbitrates with -- `_TIE_MARGIN`,
`_CONFIDENT_MARGIN`, `min_similarity` -- was therefore set from anecdote, and a
change to the matcher could only be judged by whether those nine files still
passed. 2 368 PDFs in the corpus carry a suspect font; the nine tell you nothing
about the other 2 359.

WHAT IT MEASURES
----------------
Per-glyph mapping accuracy against a truth that is known BY CONSTRUCTION rather
than by inspection:

 1. Draw a text covering the matcher's own `_COMMON_GLYPHS` into a fresh PDF
    with a real font, via pymupdf. pymupdf embeds a subset as Type0/Identity-H
    and writes a CORRECT /ToUnicode -- that CMap is the ground truth, and it is
    the font's own statement about its own glyphs, not our reading of a bitmap.
 2. Record it, then delete it. The font is now exactly the failure mode the
    matcher exists for: Identity-H, ordering Identity, no /ToUnicode, codes that
    are bare glyph indices.
 3. Run the matcher and compare cid -> char against the recorded truth.

Every system font is an independent trial, so the reference-font monoculture
(DejaVu regular+bold) is measured rather than assumed: a face far from DejaVu
scores worse, and that shows up as per-font accuracy rather than as a mystery.

WHAT IT DOES *NOT* MEASURE, so nobody quotes it further than it goes
-------------------------------------------------------------------
 * Detection (`has_custom_font_encoding`) -- these PDFs are made suspect by
   construction, so 100% detection here is a tautology.
 * Type3 fonts. pymupdf embeds TrueType/CFF; the Type3 `/CharProcs` rendering
   path in `_render_type3_glyph` is not exercised.
 * Real-world subsetting damage: vendor PDFs are produced by distiller chains
   that mangle fonts in ways a clean pymupdf embed does not reproduce. A
   synthetic score is an UPPER BOUND on field accuracy.
 * Glyphs outside `_COMMON_GLYPHS`. The matcher cannot emit them, so scoring
   them would measure the alphabet, not the matcher. They are counted and
   reported separately as `unreachable`, never folded into accuracy.

USAGE
-----
    python test/fix_enc_eval.py                      # all modes, ~20 fonts
    python test/fix_enc_eval.py --fonts 60           # more trials
    python test/fix_enc_eval.py --mode vision        # single mode
    python test/fix_enc_eval.py --confusions 40      # longer error table
    python test/fix_enc_eval.py --keep out/enc-eval  # keep the synthetic PDFs

Not a pytest module: it is slow (seconds per font) and its output is a report,
not a pass/fail. `test/unit/test_fix_enc_eval.py` runs a 2-font smoke of it so
the harness itself cannot rot unnoticed.
"""

import argparse
import collections
import os
import pathlib
import re
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pymupdf

from dslib.pdf import fix_encoding as fe
from dslib.pdf import glyph_exact as gx

# ---------------------------------------------------------------------------
# The synthetic page
# ---------------------------------------------------------------------------

# Real datasheet prose, so that a language-model decode is scored on the kind of
# text it will actually see. Lorem ipsum would flatter it; a random permutation
# of the alphabet would starve it. The lines are drawn from the header and
# electrical-characteristics tables of the parts already in the unit corpus.
_DATASHEET_LINES = [
    "OptiMOS Power-Transistor",
    "N-channel, normal level, Enhancement mode",
    "Product Summary",
    "Drain source voltage V_DS 150 V",
    "Drain current I_D 100 A",
    "On-state resistance R_DS(on) = 118 mOhm",
    "Gate charge Q_g typ. 63 nC max. 82 nC",
    "Gate-drain charge Q_gd 11 nC",
    "Reverse recovery time t_rr 65 ns",
    "Reverse recovery charge Q_rr 120 nC",
    "Input capacitance C_iss 4200 pF",
    "Output capacitance C_oss 390 pF",
    "Reverse transfer capacitance C_rss 25 pF",
    "Gate threshold voltage V_GS(th) 2.1 3.0 V",
    "Continuous drain current T_C = 25 C",
    "Pulsed drain current, t_p limited by T_jmax",
    "Power dissipation P_tot 375 W",
    "Operating and storage temperature -55 ... 175 C",
    "Thermal resistance, junction - case 0.40 K/W",
    "Package TO-263-3 (D2PAK), Marking BSC190N15NS3",
    "Qualified according to AEC Q101 rev-D",
    "Typ. gate charge; Diagram 14: Typical output characteristics",
    "Body diode forward voltage V_SD 0.9 1.2 V",
    "Avalanche energy, single pulse E_AS 300 mJ",
    "dv/dt ruggedness 15 V/ns; di/dt = 500 A/us",
    "Ohm mu ohms per square, 25 mOhm at 10 V",
    "Note 1: measured with R_G = 1.8 Ohm, V_GS = 10 V",
    "Rev. 2.1, 2019-08-14  www.infineon.com  Page 3 of 14",
    "Absolute Maximum Ratings, T_j = 25 C unless otherwise specified",
    "Electrical Characteristics, at T_j = 25 C",
]


def _coverage_line() -> str:
    """Every glyph the matcher can emit, once, so the trial covers its whole
    output alphabet rather than only the letters datasheet prose happens to use.

    Without this, rare-but-important symbols (Ohm, mu, the degree sign, the
    comparison operators) would be absent from most trials and the headline
    accuracy would quietly describe the easy 60% of the alphabet.
    """
    return ' '.join(''.join(fe._COMMON_GLYPHS[i:i + 8])
                    for i in range(0, len(fe._COMMON_GLYPHS), 8))


def _sample_text() -> List[str]:
    return [_coverage_line()] + _DATASHEET_LINES


def _drawable(font_path: str, lines: Sequence[str]) -> List[str]:
    """Drop characters the trial font has no glyph for.

    A missing glyph is embedded as .notdef, and .notdef renders as an empty box
    or nothing at all. Scoring it would charge the MATCHER for the FONT's gap:
    there is no shape to recognise. Fonts vary a lot here -- many system faces
    have no U+2264 -- so this filter is what keeps per-font accuracy comparable
    across the fleet instead of tracking each face's symbol coverage.
    """
    from fontTools.ttLib import TTFont
    try:
        tt = TTFont(font_path, fontNumber=0, lazy=True)
        cmap = tt.getBestCmap() or {}
        tt.close()
    except Exception:
        return list(lines)
    have = set(cmap)
    out = []
    for ln in lines:
        kept = ''.join(c for c in ln if c == ' ' or ord(c) in have)
        if kept.strip():
            out.append(kept)
    return out


# ---------------------------------------------------------------------------
# Synthesis: a PDF whose correct answer we know because we deleted it
# ---------------------------------------------------------------------------

def _read_to_unicode(doc: pymupdf.Document, xref: int) -> Dict[int, str]:
    """Parse a font's /ToUnicode CMap into {cid: char}.

    Only single-char targets are kept. A bfchar may legitimately map one code to
    a multi-char string (an 'ffi' ligature glyph), and the matcher's output
    alphabet is single characters, so a ligature is not something it could ever
    get right; those CIDs are dropped from the truth rather than counted as
    permanent failures.
    """
    obj = doc.xref_object(xref)
    m = re.search(r'/ToUnicode\s+(\d+)\s+0\s+R', obj)
    if not m:
        return {}
    try:
        cmap = doc.xref_stream(int(m.group(1))).decode('latin1', errors='replace')
    except Exception:
        return {}

    truth: Dict[int, str] = {}

    # bfchar: <src> <dst>
    for block in re.findall(r'beginbfchar(.*?)endbfchar', cmap, re.S):
        for s, t in re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', block):
            if len(t) != 4:
                continue  # surrogate pair or ligature -> not a single BMP char
            truth[int(s, 16)] = chr(int(t, 16))

    # bfrange: <lo> <hi> <dst-start>
    for block in re.findall(r'beginbfrange(.*?)endbfrange', cmap, re.S):
        for lo, hi, dst in re.findall(
                r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', block):
            if len(dst) != 4:
                continue
            lo_i, hi_i, d = int(lo, 16), int(hi, 16), int(dst, 16)
            if hi_i - lo_i > 0xFFFF:
                continue
            for k in range(lo_i, hi_i + 1):
                truth[k] = chr(d + (k - lo_i))
    return truth


class Trial:
    """One synthetic PDF plus the mapping the matcher is supposed to recover."""

    def __init__(self, path: str, font_name: str, xref: int,
                 truth: Dict[int, str], font_path: str = ''):
        self.path = path
        self.font_name = font_name
        self.xref = xref
        self.truth = truth
        # The source face, kept so the hold-out can exclude it -- see
        # `_holdout_names`.
        self.font_path = font_path


# A trial font must be able to draw at least this much of the Latin alphabet.
#
# Some installed faces are script-specific (SFGeorgian, CJK, symbol sets) and
# `_drawable` correctly strips every character they lack -- leaving a page of
# digits and punctuation. Such a trial still "passes", at a near-perfect score,
# while measuring almost nothing: the confusable pairs the matcher actually
# struggles with are letters. Excluded so they cannot inflate the headline.
_MIN_LATIN_COVERAGE = 40


def build_trial(font_path: str, out_dir: str) -> Optional[Trial]:
    """Draw the sample text with `font_path`, then strip the /ToUnicode.

    Returns None when the font cannot be embedded or the resulting file is not
    actually suspect. That second check is not ceremony: if `_scan_fonts` does
    not flag the file, the matcher would never see it in production either, and
    scoring it would report accuracy on a path that never runs.
    """
    lines = _drawable(font_path, _sample_text())
    if not lines:
        return None
    drawable_letters = {c for ln in lines for c in ln if c.isascii() and c.isalpha()}
    if len(drawable_letters) < _MIN_LATIN_COVERAGE:
        return None

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=1400)
    try:
        page.insert_font(fontname='EV', fontfile=font_path)
    except Exception:
        doc.close()
        return None

    y = 40.0
    for ln in lines:
        try:
            page.insert_text((30, y), ln, fontname='EV', fontsize=10)
        except Exception:
            pass
        y += 15.0

    try:
        raw = doc.tobytes(deflate=True)
    except Exception:
        doc.close()
        return None
    doc.close()

    doc = pymupdf.open('pdf', raw)
    target = None
    for pno in range(len(doc)):
        for xref, _ext, _typ, basefont, _name, _enc in doc.get_page_fonts(pno):
            if 'EV' in basefont or _read_to_unicode(doc, xref):
                target = xref
                break
        if target:
            break
    if target is None:
        doc.close()
        return None

    truth = _read_to_unicode(doc, target)
    if not truth:
        doc.close()
        return None

    # Break the font in exactly the way the corpus breaks it. `null` rather than
    # a key removal because pymupdf offers no delete; the detector looks for
    # `/ToUnicode <n> 0 R`, which `null` no longer matches -- verified below by
    # requiring _scan_fonts to actually flag the result.
    doc.xref_set_key(target, 'ToUnicode', 'null')

    name = pathlib.Path(font_path).stem
    out = os.path.join(out_dir, 'ev_%s.pdf' % re.sub(r'\W+', '_', name))
    doc.save(out, deflate=True)
    doc.close()

    check = pymupdf.open(out)
    suspect = [fi for fi in fe._scan_fonts(check) if fi.xref == target]
    check.close()
    if not suspect:
        return None

    # Score only the CIDs the page actually DRAWS, which is what the matcher is
    # asked to resolve in production (`_FontInfo.used_codes`). pymupdf embeds
    # the whole face rather than a subset, so the raw /ToUnicode also describes
    # ~47 000 glyphs that appear nowhere on the page. Those are neither correct
    # nor wrong -- they are not attempted -- and leaving them in made a font's
    # score a function of how large its cmap is.
    used = suspect[0].used_codes
    truth = {cid: ch for cid, ch in truth.items() if cid in used}
    if not truth:
        return None

    return Trial(out, name, target, truth, font_path=font_path)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class Result:
    def __init__(self, font_name: str):
        self.font_name = font_name
        self.correct = 0
        self.wrong = 0
        self.blank = 0          # matcher abstained (mapped to space)
        self.missing = 0        # CID in truth, absent from the mapping
        self.unreachable = 0    # truth char outside the matcher's alphabet
        self.confusions: List[Tuple[str, str]] = []
        self.seconds = 0.0

    @property
    def scored(self) -> int:
        return self.correct + self.wrong + self.blank + self.missing

    @property
    def accuracy(self) -> Optional[float]:
        return self.correct / self.scored if self.scored else None


def score(trial: Trial, mapping: Optional[Dict[int, str]]) -> Result:
    """Compare a recovered mapping against the trial's truth.

    A CID the matcher declined (space) is scored SEPARATELY from one it got
    wrong. They are different failures with different costs downstream: an
    abstention degrades the text, a wrong guess corrupts it into something that
    still looks like a value -- which is how four parts shipped an Rds_on 1000x
    low. Rolling both into one accuracy number would hide that distinction
    exactly where it matters.
    """
    r = Result(trial.font_name)
    alphabet = set(fe._COMMON_GLYPHS)
    mapping = mapping or {}
    for cid, true_ch in sorted(trial.truth.items()):
        if true_ch not in alphabet:
            r.unreachable += 1
            continue
        if cid not in mapping:
            r.missing += 1
            continue
        got = mapping[cid]
        if got == true_ch:
            r.correct += 1
        elif got == ' ' and true_ch != ' ':
            r.blank += 1
            r.confusions.append((true_ch, '_'))
        else:
            r.wrong += 1
            r.confusions.append((true_ch, got))
    return r


# ---------------------------------------------------------------------------
# Modes -- the A/B axis
# ---------------------------------------------------------------------------

MODES = ('vision', 'fontid', 'exact', 'lm', 'full')

_MODE_KWARGS = {
    'vision': dict(use_exact=False, use_lm=False, use_fontid=False),
    'fontid': dict(use_exact=False, use_lm=False, use_fontid=True),
    'exact': dict(use_exact=True, use_lm=False, use_fontid=False),
    'lm': dict(use_exact=False, use_lm=True, use_fontid=False),
    'full': dict(use_exact=True, use_lm=True, use_fontid=True),
}

HOLDOUTS = ('none', 'file', 'family')


def _holdout_names(trial: 'Trial', level: str) -> Optional[set]:
    """Font files the identification stages may not look at for this trial.

    WITHOUT THIS THE MEASUREMENT IS A TAUTOLOGY. Every trial is drawn with an
    INSTALLED face, so `glyph_exact` finds the very file it was drawn from and
    `glyph_fontid` identifies it perfectly. That is not a result -- it is the
    harness handing the answer to the thing it is testing. Real vendor PDFs
    embed faces that may not be installed at all, and are the output of a
    distiller that re-outlines and re-hints.

    Three levels, reported separately because they answer different questions:

      none    -- the optimistic bound: this exact file is installed.
      file    -- the same face is NOT installed, but relatives may be (Arial
                 Bold when the trial is Arial). Models a corpus where the
                 vendor's exact cut is missing but the family is present.
      family  -- nothing sharing the first word of the filename is available.
                 The pessimistic bound, and the closest analogue to the
                 Infineon subsets, whose true face is installed nowhere here.
    """
    if level == 'none':
        return None
    base = os.path.basename(trial.font_path)
    if level == 'file':
        return {base}
    stem = os.path.splitext(base)[0].split()[0].split('-')[0].lower()
    return {os.path.basename(p) for p in gx._installed_fonts()
            if os.path.basename(p).lower().startswith(stem)}


def run_trial(trial: Trial, mode: str, holdout: str = 'file') -> Result:
    kwargs = dict(_MODE_KWARGS[mode])
    exclude = _holdout_names(trial, holdout)
    kwargs['fontid_exclude'] = exclude
    doc = pymupdf.open(trial.path)
    t0 = time.time()
    try:
        fi = next(fi for fi in fe._scan_fonts(doc) if fi.xref == trial.xref)
        ref_items = list(fe._reference_glyphs().items())
        if kwargs.get('use_exact') and exclude:
            # glyph_exact has no exclude parameter of its own -- it is meant to
            # consult everything installed. Held out by filtering the shared
            # index in place for the duration of the trial, and restored after,
            # so the hold-out cannot leak into later modes.
            idx = gx.reference_index()
            saved = dict(idx)
            for name in list(idx):
                if name in exclude:
                    del idx[name]
            try:
                mapping = fe._build_font_mapping(doc, fi, ref_items,
                                                 min_similarity=0.30, **kwargs)
            finally:
                idx.clear()
                idx.update(saved)
        else:
            mapping = fe._build_font_mapping(doc, fi, ref_items,
                                             min_similarity=0.30, **kwargs)
    finally:
        doc.close()
    r = score(trial, mapping)
    r.seconds = time.time() - t0
    return r


# ---------------------------------------------------------------------------
# Font discovery
# ---------------------------------------------------------------------------

_FONT_DIRS = [
    '/System/Library/Fonts/Supplemental',
    '/System/Library/Fonts',
    '/Library/Fonts',
    os.path.expanduser('~/Library/Fonts'),
    '/usr/share/fonts',
    '/usr/local/share/fonts',
]

# Symbol and emoji faces carry no Latin text, so a trial on them measures
# nothing and their glyphs are not in the matcher's alphabet anyway.
_SKIP_RE = re.compile(
    r'emoji|symbol|dingbat|wingding|webding|icon|braille|'
    r'apple\s*color|notoserifhentaigana|zapf',
    re.I)


def find_fonts(limit: int, seed_names: Sequence[str] = ()) -> List[str]:
    """Trial fonts, deterministically ordered.

    Sorted, not sampled at random: a harness whose corpus changes between runs
    cannot tell a matcher regression from a different draw of fonts.
    """
    found: List[str] = []
    # The same face is routinely installed in two of these directories (and as
    # both .ttf and .otf). Trialling it twice does not add evidence, it just
    # double-weights that face in the pooled total.
    seen: set = set()
    for d in _FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for f in sorted(files):
                if not f.lower().endswith(('.ttf', '.otf')):
                    continue  # .ttc collections: pymupdf embeds face 0 only
                if _SKIP_RE.search(f):
                    continue
                key = os.path.splitext(f)[0].lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append(os.path.join(root, f))
    found.sort()

    if seed_names:
        want = [p for p in found
                if any(s.lower() in os.path.basename(p).lower()
                       for s in seed_names)]
        rest = [p for p in found if p not in want]
        found = want + rest
    return found[:limit] if limit > 0 else found


# The faces most like what vendor datasheets actually use, tried first so a
# small --fonts run is still representative rather than alphabetical.
_PREFERRED = ('Arial', 'Helvetica', 'Times', 'Verdana', 'Tahoma', 'Georgia',
              'Trebuchet', 'Courier', 'Futura', 'Optima', 'Gill', 'Avenir',
              'Palatino', 'Baskerville', 'Rockwell', 'Didot')


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _fmt_pct(x: Optional[float]) -> str:
    return '  n/a' if x is None else '%5.1f%%' % (100 * x)


def report(results_by_mode: Dict[str, List[Result]], n_confusions: int,
           holdout: Optional[str] = None) -> None:
    modes = [m for m in MODES if m in results_by_mode]

    print()
    print('=' * 78)
    print('GLYPH MATCHER ACCURACY -- synthetic ground truth')
    if holdout is not None:
        print('holdout=%s  (what the identification stages were NOT allowed '
              'to see)' % holdout)
    print('=' * 78)

    fonts = [r.font_name for r in results_by_mode[modes[0]]]
    w = max([len(f) for f in fonts] + [12])

    print()
    print('%-*s  %s' % (w, 'font', '  '.join('%8s' % m for m in modes)))
    print('-' * (w + 2 + 10 * len(modes)))
    for i, name in enumerate(fonts):
        cells = []
        for m in modes:
            rs = results_by_mode[m]
            cells.append('%8s' % _fmt_pct(rs[i].accuracy) if i < len(rs) else '     n/a')
        print('%-*s  %s' % (w, name[:w], '  '.join(cells)))

    print()
    print('%-*s  %s' % (w, 'TOTAL', '  '.join(
        '%8s' % _fmt_pct(
            sum(r.correct for r in results_by_mode[m])
            / max(1, sum(r.scored for r in results_by_mode[m])))
        for m in modes)))

    print()
    print('breakdown (all fonts pooled)')
    print('-' * 78)
    hdr = '%-10s %8s %8s %8s %8s %8s %9s' % (
        'mode', 'correct', 'wrong', 'blank', 'missing', 'unreach', 'sec/font')
    print(hdr)
    for m in modes:
        rs = results_by_mode[m]
        n = max(1, len(rs))
        print('%-10s %8d %8d %8d %8d %8d %9.2f' % (
            m,
            sum(r.correct for r in rs), sum(r.wrong for r in rs),
            sum(r.blank for r in rs), sum(r.missing for r in rs),
            sum(r.unreachable for r in rs),
            sum(r.seconds for r in rs) / n))

    for m in modes:
        rs = results_by_mode[m]
        conf = collections.Counter()
        for r in rs:
            conf.update(r.confusions)
        if not conf:
            continue
        print()
        print("top confusions -- %s   ('_' = declined, mapped to space)" % m)
        print('-' * 78)
        row = []
        for (true_ch, got), cnt in conf.most_common(n_confusions):
            row.append('%r->%r x%d' % (true_ch, got, cnt))
            if len(row) == 4:
                print('  ' + '   '.join('%-16s' % c for c in row))
                row = []
        if row:
            print('  ' + '   '.join('%-16s' % c for c in row))
    print()


def calibrate(trials: List['Trial'], n_report: int = 12) -> None:
    """Report the score distributions the matcher's thresholds are set from.

    Every absolute constant in the matcher -- `min_similarity`, `_TIE_MARGIN`,
    `_CONFIDENT_MARGIN`, and the language model's `_VIS_TEMP` / `_CAND_BAND`
    derived from them -- is a number ON THE SIMILARITY SCALE. Change the
    similarity function and they all mean something different, so carrying them
    across a metric change is not conservative, it is meaningless. This prints
    what they should be for whichever metric is active.

    Two distributions matter, split by whether the top choice was RIGHT:

      top1        how similar the winner was. Sets `min_similarity`: the floor
                  must sit below almost every CORRECT top1, or the matcher
                  declines glyphs it had right.
      gap         top1 minus top2. Sets the tie margins: errors concentrate at
                  small gaps -- that is what "the pixels could not decide"
                  looks like -- so the tie band wants to cover most WRONG
                  decisions while excluding most correct ones, since everything
                  inside it is handed to the tie-breakers and the language
                  model to re-decide.
    """
    import numpy as np

    top1_ok, top1_bad, gap_ok, gap_bad = [], [], [], []
    for t in trials:
        doc = pymupdf.open(t.path)
        try:
            fi = next(f for f in fe._scan_fonts(doc) if f.xref == t.xref)
            ref = fe._prepare_items(list(fe._reference_glyphs().items()))
            fb = doc.extract_font(fi.xref)[3]
            c2g = fe._cid_to_gid_lookup(fb, fi.is_type0)
            wanted = {g for g in (c2g(c) for c in fi.used_codes) if g}
            built = fe._build_pil_font_for_gid_render(fb, wanted)
            if built is None:
                continue
            pil, code_by_gid = built
            for cid, true_ch in sorted(t.truth.items()):
                g = c2g(cid)
                code = code_by_gid.get(g) if g else None
                if code is None:
                    continue
                arr = fe._render_glyph(pil, code)
                if arr is None:
                    continue
                pa = fe._prepare(arr)
                scores = sorted(
                    ((max(fe._similarity_prepared(pa, v) for v in var), ch)
                     for ch, var in ref), reverse=True)
                if len(scores) < 2:
                    continue
                gap = scores[0][0] - scores[1][0]
                if scores[0][1] == true_ch:
                    top1_ok.append(scores[0][0]); gap_ok.append(gap)
                else:
                    top1_bad.append(scores[0][0]); gap_bad.append(gap)
        finally:
            doc.close()

    def pct(xs, q):
        return float(np.percentile(xs, q)) if xs else float('nan')

    print()
    print('=' * 78)
    print('THRESHOLD CALIBRATION -- metric=%s' % fe._METRIC)
    print('=' * 78)
    print('  correct top1: n=%d  p01=%.4f p05=%.4f p50=%.4f'
          % (len(top1_ok), pct(top1_ok, 1), pct(top1_ok, 5), pct(top1_ok, 50)))
    print('  wrong   top1: n=%d  p50=%.4f p95=%.4f'
          % (len(top1_bad), pct(top1_bad, 50), pct(top1_bad, 95)))
    print('  correct gap : p05=%.4f p25=%.4f p50=%.4f'
          % (pct(gap_ok, 5), pct(gap_ok, 25), pct(gap_ok, 50)))
    print('  wrong   gap : p50=%.4f p75=%.4f p90=%.4f p95=%.4f'
          % (pct(gap_bad, 50), pct(gap_bad, 75), pct(gap_bad, 90),
             pct(gap_bad, 95)))
    print()
    print('  SUGGESTED for this metric:')
    print('    min_sim   = %.3f   (just under the 1st percentile of correct '
          'top1, so it declines almost nothing it had right)'
          % (pct(top1_ok, 1) * 0.9 if top1_ok else 0.0))
    print('    tie       = %.3f   (90th percentile of WRONG gaps: the band that '
          'catches the errors worth re-deciding)' % pct(gap_bad, 90))
    print('    confident = %.3f   (2x tie, as before -- a glyph that needed '
          'arbitration must not vote on the width calibration)'
          % (2 * pct(gap_bad, 90)))
    print()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description='Measure glyph-matcher accuracy against synthetic ground truth.')
    ap.add_argument('--fonts', type=int, default=20,
                    help='number of trial fonts (0 = all found; default 20)')
    ap.add_argument('--mode', action='append', choices=MODES,
                    help='repeatable; default: all modes')
    ap.add_argument('--confusions', type=int, default=20,
                    help='how many confusion pairs to print per mode')
    ap.add_argument('--holdout', choices=HOLDOUTS, default='file',
                    help="how much of the trial font's own family the "
                         "identification stages may see. 'none' is the "
                         "optimistic bound and a near-tautology; 'file' "
                         "(default) hides the exact face; 'family' hides "
                         "everything sharing its name stem (default: file)")
    ap.add_argument('--calibrate', action='store_true',
                    help='report the score distributions the thresholds are '
                         'set from, for the active metric, and exit')
    ap.add_argument('--keep', metavar='DIR',
                    help='keep the synthetic PDFs in DIR instead of a temp dir')
    args = ap.parse_args(argv)

    modes = args.mode or list(MODES)

    import tempfile
    tmp = args.keep or tempfile.mkdtemp(prefix='fix-enc-eval-')
    os.makedirs(tmp, exist_ok=True)

    paths = find_fonts(args.fonts * 3 if args.fonts else 0, _PREFERRED)
    trials: List[Trial] = []
    for p in paths:
        if args.fonts and len(trials) >= args.fonts:
            break
        try:
            t = build_trial(p, tmp)
        except Exception as e:
            print('  skip %s: %s' % (os.path.basename(p), e), file=sys.stderr)
            continue
        if t is not None:
            trials.append(t)

    if not trials:
        print('no usable trial fonts found', file=sys.stderr)
        return 2

    print('%d trial fonts, %d modes, holdout=%s, metric=%s, PDFs in %s'
          % (len(trials), len(modes), args.holdout, fe._METRIC, tmp))

    if args.calibrate:
        calibrate(trials)
        return 0

    results_by_mode: Dict[str, List[Result]] = {}
    for m in modes:
        rs = []
        for t in trials:
            try:
                rs.append(run_trial(t, m, args.holdout))
            except Exception as e:
                print('  %s/%s failed: %s' % (m, t.font_name, e), file=sys.stderr)
                rs.append(Result(t.font_name))
        results_by_mode[m] = rs
        print('  %-7s done' % m)

    report(results_by_mode, args.confusions, args.holdout)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
