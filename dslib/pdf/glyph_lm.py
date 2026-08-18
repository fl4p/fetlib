"""Document-level arbitration of glyph readings by a character language model.

WHY A SECOND OPINION AT ALL
---------------------------
`fix_encoding` decides each CID on its own, from its own bitmap. But the CIDs
are not independent -- they spell words. The two failures the tie-breakers were
written for are both trivial at the word level and near-impossible at the pixel
level:

    N-channeI, normaI IeveI      cosine separated 'l' from 'I' by 0.003
    OμtiMOS                      cosine separated 'p' from 'μ' by 0.008

No raster resolves 0.003 reliably; no model of English hesitates for a moment.
The document-level framing is also the one the literature uses for exactly this
problem -- Krutko, Stefanovitch & Postanogov, "Automatic Recovery of Corrupted
Font Encoding in PDF Documents Using CNN-based Symbol Recognition **with
Language Model**" (DAS/IAPR 2018) -- and the follow-up (Stefanovitch,
ACL ComputEL 2022) names the structure outright: recovering CID -> Unicode is a
monoalphabetic substitution cipher over the document. That work could not use a
language model because it targeted endangered languages with no corpus.
Datasheet English is the opposite case: stereotyped, abundant, and already
sitting in `datasheets/`.

WHAT THIS DOES
--------------
Coordinate ascent over the mapping, maximising

    w_vis * SUM_cid  count(cid) * emission(cid -> ch)
  + w_lm  * SUM_runs logP(decoded run)

where `emission` is the visual similarity `fix_encoding` already computed and
`logP` comes from an interpolated character 3-gram model trained on
`glyph_lm_corpus.txt.gz` (regenerate with apps/build_glyph_lm_corpus.py).
Runs are the actual on-page text-showing operands, in order, so the model sees
real words rather than the alphabet.

THE SAFETY PROPERTIES, which are the point
------------------------------------------
1. **It cannot invent a character.** Each CID's candidate set is exactly the
   shortlist vision already ranked (`_TIE_CANDIDATES` entries). The model
   reorders a shortlist; it never adds to one. A glyph that looks nothing like
   'e' cannot become 'e' because 'e' is common.
2. **It cannot overrule an exact match.** CIDs identified by outline in
   `glyph_exact` are passed as `pinned` and are never proposed against. An
   outline identity is stronger evidence than any amount of fluency.
3. **It abstains rather than guesses.** No corpus, too little text on the page,
   or a final score that does not beat the vision-only mapping by
   `_MIN_IMPROVEMENT` -- each returns the input mapping UNCHANGED. "Not enough
   evidence" is never allowed to become "here is my best guess".
4. **It is deterministic.** Coordinate ascent in sorted CID order with a fixed
   iteration cap; no sampling, no random restarts. Two runs on one file give
   one answer, which is what makes the accuracy harness meaningful.

WHAT IT CANNOT FIX
------------------
A uniformly shifted alphabet where the shift is itself plausible text, and any
font whose page carries too few words to constitute evidence (a chart axis with
four labels). Both abstain. It also cannot help a font whose visual shortlists
are all wrong -- it optimises within them.
"""

import collections
import gzip
import math
import os
import re
import warnings
from typing import Dict, List, Optional, Sequence, Set, Tuple

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_ORDER = 3  # character n-gram order

# Interpolation weights for 3-gram / 2-gram / 1-gram, highest order first. Fixed
# rather than fitted: with 290 KB of training text the trigram counts are dense
# for datasheet English and sparse everywhere else, and that is exactly the
# behaviour wanted -- unusual character sequences should cost something.
_LAMBDAS = (0.60, 0.30, 0.10)

# Add-k smoothing, so an unseen n-gram is expensive but not infinitely so. An
# infinite penalty would let one rare-but-correct character (a 'µ' in 'µC')
# veto an otherwise perfect reading.
_SMOOTH_K = 0.1

# Temperature converting a cosine similarity into a log-likelihood, so the two
# terms of the objective are in the same units and can be added at all.
#
# This is the single number that decides whether the model helps or hurts, and
# the first version got it wrong by omitting the conversion entirely. Raw cosine
# over non-negative ink is compressed into a narrow high band -- the whole
# candidate shortlist sits inside ~0.05, and the 'l' vs 'I' pair inside 0.003 --
# while a trigram log-probability moves by units. Added directly, vision
# contributed no dynamic range at all and the LM effectively decided every
# glyph on fluency alone. Measured on the synthetic harness that scored 76.9%
# against a 78.3% vision-only baseline: it was not a weak prior, it was no
# prior, and it invented errors ('[' -> '/', '9' -> '0') on text that was
# already right.
#
# Set to `_TIE_MARGIN` (0.03): one temperature unit IS the gap fix_encoding
# itself calls a tie. So a tied pair costs ~1 log unit per occurrence to swap --
# cheap, which is the point -- and a decisive 0.15 visual win costs 5 per
# occurrence, which no amount of fluency will pay.
_VIS_TEMP = 0.03

# A candidate may only be proposed if it is within this much visual similarity
# of that CID's best. Without it the model may move a glyph vision was CERTAIN
# about, which is not "reordering a shortlist" in any meaningful sense -- the
# shortlist is the top 6 by score regardless of how far behind #2 is.
#
# Measured, not assumed. Unrestricted, the model scored 75.6% against a 78.3%
# vision baseline and its error profile was pure frequency preference:
# '9'->'0' x8, 'q'->'o' x7, 'μ'->'u' x4, '®'->'C' x4 -- every one a rare glyph
# replaced by a common one it does not look like. Twice `_TIE_MARGIN`, so the
# band covers what fix_encoding calls a tie plus the near misses its own
# tie-breakers already arbitrate over.
_CAND_BAND = 0.06

# A run must contain at least this many alphabetic characters, under the
# INCOMING mapping, to be scored at all.
#
# A character n-gram model asked to judge '25', '(D2PAK)' or '±' has no
# linguistic evidence to offer and answers with letter frequency instead. On a
# datasheet that is most of the page -- axis labels, part numbers, table cells
# -- so unfiltered, frequency preference outvoted the words. Judged on the
# incoming decode rather than the trial one so the filter is a fixed property
# of each run and cannot be gamed by the search that follows.
_MIN_RUN_ALPHA = 3

# A CID must occur at least this many times in the scored text before the model
# is allowed to move it.
#
# One occurrence is one n-gram window. Deciding a character from that is not
# inference, it is noise-fitting, and it is where the unrestricted model did its
# damage: every one of its wrong moves on the Arial Narrow Italic trial --
# '%'->'N', '@'->'©', '['->'/', '\\'->'I', 'W'->'m' -- was a CID appearing once.
# Letters that carry real text occur dozens of times on a datasheet page, so
# this costs nothing where the model is actually useful.
_MIN_CID_OCCURRENCES = 4

# Penalty per surplus CID sharing one character, in log units per occurrence.
#
# The mapping being recovered is a substitution cipher, and a font does not
# carry five identical glyphs -- so two CIDs claiming the same character is
# positive evidence that at least one is wrong. Nothing before this expressed
# that. It is why the matcher could read 'OptiMOS Power-Transistor' as
# 'Op//MOS Power-7rans/s/or': 't', 'i' and 'l' had all collapsed onto '/',
# each locally plausible, jointly impossible. The n-gram model alone could not
# see it either, because it scores one run at a time and never compares CIDs.
#
# Space is exempt: every CID vision declined maps there legitimately, and
# charging for that would push the model to fill abstentions with guesses --
# turning a visible gap into an invisible error.
_COLLISION_PENALTY = 1.2

# Relative weight of the language model once both terms are log-likelihoods.
# 1.0 = read them as what they claim to be. Kept as a named knob rather than
# inlined so the harness can sweep it.
_LM_WEIGHT = 1.0

# The mapping must beat the vision-only mapping by this much total objective to
# be adopted. Guards against churn: a change that is within the model's own
# noise is not an improvement, it is a coin flip with extra steps.
_MIN_IMPROVEMENT = 1.0

# Below this many decoded characters on the page, word statistics are not
# evidence. Chart-axis fonts land here and abstain.
_MIN_TEXT_CHARS = 120

# Geometry constants for reassembling lines in `cid_runs`.
# A gap wider than this many ems between the estimated end of one glyph and the
# start of the next is read as a word space. 0.30 em sits between the residual
# slop of per-glyph positioning and a real space (~0.28 em of advance ON TOP of
# the preceding glyph's own width).
_SPACE_GAP_EM = 0.30
# Mean advance of a Latin glyph, used only to estimate where a run ends when the
# producer does not immediately re-position. Not a per-glyph width and not used
# as one.
_MEAN_ADVANCE_EM = 0.50
# TJ kerning more negative than this (thousandths of an em) is a drawn space.
_TJ_SPACE_KERN = 200.0

_MAX_PASSES = 6  # coordinate ascent converges in 2-3; the cap is a backstop

# Deliberately NOT under a directory called `data`: .gitignore carries a bare
# `data` pattern, which matches any such directory at any depth. Shipping the
# corpus there meant it was never committed, so a fresh clone would load no
# model and silently fall back to vision-only -- a documented stage quietly
# absent, with nothing failing to say so.
_CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'glyph_lm_corpus.txt.gz')


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

class CharLM:
    """Interpolated character n-gram model with add-k smoothing."""

    def __init__(self, text: str, order: int = _ORDER):
        self.order = order
        self.counts: List[collections.Counter] = [
            collections.Counter() for _ in range(order)]
        self.ctx: List[collections.Counter] = [
            collections.Counter() for _ in range(order)]
        vocab = set()
        pad = '\x02' * (order - 1)
        for line in text.splitlines():
            if not line:
                continue
            s = pad + line + '\x03'
            vocab.update(line)
            for i in range(order - 1, len(s)):
                for n in range(order):
                    gram = s[i - n:i + 1]
                    self.counts[n][gram] += 1
                    self.ctx[n][gram[:-1]] += 1
        self.vocab_size = max(1, len(vocab))

    def logp_char(self, context: str, ch: str) -> float:
        """log P(ch | context), interpolated over orders."""
        p = 0.0
        for n, lam in enumerate(_LAMBDAS[:self.order]):
            if not lam:
                continue
            c = context[len(context) - n:] if n else ''
            num = self.counts[n].get(c + ch, 0) + _SMOOTH_K
            den = self.ctx[n].get(c, 0) + _SMOOTH_K * self.vocab_size
            p += lam * (num / den)
        return math.log(p) if p > 0 else -30.0

    def logp(self, s: str) -> float:
        if not s:
            return 0.0
        pad = '\x02' * (self.order - 1)
        full = pad + s
        total = 0.0
        for i in range(self.order - 1, len(full)):
            total += self.logp_char(full[max(0, i - self.order + 1):i], full[i])
        return total


_LM: Optional[CharLM] = None
_LM_TRIED = False


def get_lm() -> Optional[CharLM]:
    """The shared model, or None if the corpus is missing or unreadable.

    None is a first-class answer here: a caller that cannot load a corpus must
    leave the mapping alone, not fall back to a uniform model. A uniform model
    would prefer whichever reading has the most common letters, which is a
    worse decision procedure than the vision it would be overruling.
    """
    global _LM, _LM_TRIED
    if _LM is not None or _LM_TRIED:
        return _LM
    _LM_TRIED = True
    try:
        with gzip.open(_CORPUS, 'rt', encoding='utf-8') as fh:
            text = fh.read()
    except Exception as e:
        # Warn rather than fail: vision-only is a correct, if weaker, matcher.
        # But say it out loud -- an absent corpus is indistinguishable from a
        # model that simply never found an improvement, and the two mean very
        # different things when a decode looks wrong.
        warnings.warn('glyph_lm: no corpus at %s (%s); language-model '
                      'arbitration disabled. Rebuild with '
                      'apps/build_glyph_lm_corpus.py' % (_CORPUS, e))
        return None
    if len(text) < 10_000:
        warnings.warn('glyph_lm: corpus at %s is only %d chars; too small to '
                      'arbitrate with, stage disabled' % (_CORPUS, len(text)))
        return None
    _LM = CharLM(text)
    return _LM


def corpus_salt() -> str:
    """Identity of the training corpus, for the parse-cache generation key."""
    import hashlib
    try:
        with open(_CORPUS, 'rb') as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:16]
    except Exception:
        return 'absent'


# ---------------------------------------------------------------------------
# Reading the CID sequences off the page
# ---------------------------------------------------------------------------

def _decode_hex_run(hex_bytes: bytes, two_byte: bool) -> List[int]:
    h = re.sub(rb'\s+', b'', hex_bytes)
    step = 4 if two_byte else 2
    if len(h) % step:
        h += b'0' * (step - len(h) % step)
    out = []
    for i in range(0, len(h), step):
        try:
            out.append(int(h[i:i + step], 16))
        except ValueError:
            pass
    return out


_ESCAPES = {b'n': 10, b'r': 13, b't': 9, b'b': 8, b'f': 12,
            b'(': 40, b')': 41, b'\\': 92}


def _decode_literal_run(lit: bytes, two_byte: bool) -> List[int]:
    raw = bytearray()
    i = 0
    while i < len(lit):
        c = lit[i:i + 1]
        if c == b'\\' and i + 1 < len(lit):
            nxt = lit[i + 1:i + 2]
            if nxt in _ESCAPES:
                raw.append(_ESCAPES[nxt])
                i += 2
                continue
            if nxt.isdigit():
                oct_digits = lit[i + 1:i + 4]
                m = re.match(rb'[0-7]{1,3}', oct_digits)
                if m:
                    raw.append(int(m.group(), 8) & 0xFF)
                    i += 1 + len(m.group())
                    continue
            raw.append(nxt[0])
            i += 2
            continue
        raw.append(c[0])
        i += 1
    if two_byte:
        return [(raw[j] << 8) | raw[j + 1] for j in range(0, len(raw) - 1, 2)]
    return list(raw)


SPACE = -1  # sentinel inside a run: a gap wide enough to be a word space


_TOKEN_RE = re.compile(
    rb'/([^\s/<>\[\]()]+)\s+(-?[\d.]+)\s+Tf'
    rb'|((?:-?[\d.]+\s+){5}-?[\d.]+)\s+Tm'
    rb'|(-?[\d.]+)\s+(-?[\d.]+)\s+T[dD]'
    rb'|(T\*)'
    rb'|(BT)'
    rb'|<([0-9A-Fa-f\s]*)>\s*Tj'
    rb'|\(((?:\\.|[^\\()])*)\)\s*Tj'
    rb'|\[(.*?)\]\s*TJ',
    flags=re.DOTALL,
)


def cid_runs(doc, xref: int, two_byte: bool,
             max_runs: int = 4000) -> List[List[int]]:
    """The text shown with this font, assembled into LINES, in reading order.

    Returns a list of runs; each run is a list of CIDs with `SPACE` (-1) marking
    a gap wide enough to be a word break.

    WHY LINES, AND WHY FROM GEOMETRY
    --------------------------------
    The obvious implementation -- one run per text-showing operand -- is wrong
    for exactly the producers that matter here. Infineon's distiller emits ONE
    `Tm ... <XX> Tj` PAIR PER GLYPH, so operand grouping yields runs of length
    one and hands a character n-gram model no context whatsoever. Measured: with
    operand grouping the model could not repair `N-channeI, normaI IeveI` in
    BSC190N15NS3_G.pdf even with the visual tie-breakers disabled, because it
    was scoring 'N', '-', 'c', 'h' as independent one-character documents.

    So positions are tracked instead and glyphs are regrouped by baseline: the
    text matrix `Tm` (and `Td`/`TD`/`T*`) gives every glyph an x and a y,
    records are bucketed by y and sorted by x, and a gap wider than
    `_SPACE_GAP_EM` becomes a space. That reconstructs the line as a reader sees
    it, which is what the corpus was trained on.

    Falls back to operand order when a page carries no positioning operators at
    all -- rare, but a page laid out purely by TJ kerning would otherwise
    produce nothing.
    """
    runs: List[List[int]] = []

    for pno in range(len(doc)):
        try:
            page = doc[pno]
            names = {name: fx for fx, _e, _t, _b, name, _en
                     in doc.get_page_fonts(pno)}
            content = page.read_contents()
        except Exception:
            continue

        cur: Optional[int] = None
        size = 10.0
        x = y = 0.0
        # (y, x, size, cids) for every show operation using the target font
        recs: List[Tuple[float, float, float, List[int]]] = []
        positioned = False

        for m in _TOKEN_RE.finditer(content):
            if m.group(1) is not None:
                cur = names.get(m.group(1).decode('latin1'))
                try:
                    size = abs(float(m.group(2))) or 10.0
                except ValueError:
                    size = 10.0
                continue
            if m.group(3) is not None:
                nums = m.group(3).split()
                try:
                    x, y = float(nums[4]), float(nums[5])
                    # A Tm may carry the scale that a `1 Tf` leaves out; the
                    # vertical scale is the one that reflects glyph size.
                    sy = abs(float(nums[3]))
                    if sy > 0.01:
                        size = max(size, 1.0) if sy < 1.5 else sy
                except (ValueError, IndexError):
                    pass
                positioned = True
                continue
            if m.group(4) is not None:
                try:
                    x += float(m.group(4))
                    y += float(m.group(5))
                except ValueError:
                    pass
                positioned = True
                continue
            if m.group(6) is not None:      # T*
                y -= size * 1.2
                positioned = True
                continue
            if m.group(7) is not None:      # BT resets the text matrix
                x = y = 0.0
                continue
            if cur != xref:
                continue

            if m.group(8) is not None:
                seq = _decode_hex_run(m.group(8), two_byte)
            elif m.group(9) is not None:
                seq = _decode_literal_run(m.group(9), two_byte)
            else:
                seq = []
                for piece in re.finditer(
                        rb'<([0-9A-Fa-f\s]*)>|\((?:\\.|[^\\()])*\)|(-?[\d.]+)',
                        m.group(10), flags=re.DOTALL):
                    if piece.group(1) is not None:
                        seq.extend(_decode_hex_run(piece.group(1), two_byte))
                    elif piece.group(2) is not None:
                        try:
                            if float(piece.group(2)) <= -_TJ_SPACE_KERN:
                                seq.append(SPACE)
                        except ValueError:
                            pass
                    else:
                        seq.extend(_decode_literal_run(piece.group(0)[1:-1],
                                                       two_byte))
            if seq:
                recs.append((y, x, size, seq))
                # No width table here, so the pen advance is approximated at
                # half an em per glyph. It only has to be good enough to order
                # glyphs and size gaps; where the producer sets Tm per glyph
                # (the case this exists for) the next absolute x overwrites it.
                x += size * _MEAN_ADVANCE_EM * len(seq)

        if not recs:
            continue
        if not positioned:
            runs.extend(seq for _y, _x, _s, seq in recs)
            if len(runs) >= max_runs:
                return runs[:max_runs]
            continue

        lines: Dict[int, List[Tuple[float, float, List[int]]]] = {}
        for ry, rx, rs, seq in recs:
            lines.setdefault(int(round(ry * 2)), []).append((rx, rs, seq))

        for key in sorted(lines, reverse=True):
            items = sorted(lines[key])
            run: List[int] = []
            prev_end: Optional[float] = None
            for rx, rs, seq in items:
                if prev_end is not None and rx - prev_end > rs * _SPACE_GAP_EM:
                    run.append(SPACE)
                run.extend(seq)
                prev_end = rx + rs * _MEAN_ADVANCE_EM * len(seq)
            if run:
                runs.append(run)
                if len(runs) >= max_runs:
                    return runs
    return runs


# ---------------------------------------------------------------------------
# Coordinate ascent
# ---------------------------------------------------------------------------

def _decode(run: Sequence[int], mapping: Dict[int, str]) -> str:
    return ''.join(' ' if c == SPACE else mapping.get(c, ' ') for c in run)


# Scoring a trial by rebuilding the whole objective is O(all text) per candidate,
# which at 60 CIDs x 6 candidates x 6 passes rescores a page some 2 000 times.
# Changing one CID can only change the runs that CONTAIN it, so the ascent below
# keeps per-run scores and updates the affected ones. Identical arithmetic,
# ~50x less of it -- the difference between the LM stage costing 0.1 s and 5 s
# per font, on a matcher that runs over thousands of PDFs.


def lm_refine(doc, fi, mapping: Dict[int, str],
              ranked: Dict[int, List[Tuple[float, str]]],
              pinned: Optional[Set[int]] = None) -> Dict[int, str]:
    """Refine `mapping` using the text it produces. Returns it unchanged when
    the evidence does not support a change -- never a partial or a guess."""
    lm = get_lm()
    if lm is None or not ranked:
        return mapping

    all_runs = cid_runs(doc, fi.xref, two_byte=fi.is_type0)
    # Keep only the runs that are words under the incoming decode; see
    # `_MIN_RUN_ALPHA`. Everything else on the page stays exactly as vision
    # left it, which is the right outcome for a part number or an axis tick.
    runs = [r for r in all_runs
            if sum(mapping.get(c, ' ').isalpha() for c in r) >= _MIN_RUN_ALPHA]
    if not runs:
        return mapping

    counts: Dict[int, int] = collections.Counter()
    for r in runs:
        counts.update(r)
    n_chars = sum(counts.values())
    if n_chars < _MIN_TEXT_CHARS:
        return mapping

    pinned = pinned or set()
    # Emission as a log-likelihood relative to that CID's own best candidate:
    # the top choice costs 0 and every rival costs what its visual deficit is
    # worth in `_VIS_TEMP` units. Per-CID rather than global because the
    # absolute cosine level says more about how ordinary the glyph's shape is
    # than about how certain the match is -- only the SPREAD within one CID's
    # shortlist carries confidence.
    emission: Dict[int, Dict[str, float]] = {}
    candidates: Dict[int, List[str]] = {}
    for cid, scores in ranked.items():
        top = scores[0][0]
        emission[cid] = {ch: (s - top) / _VIS_TEMP for s, ch in scores}
        candidates[cid] = [ch for s, ch in scores if top - s <= _CAND_BAND]

    # Only CIDs that (a) vision left genuinely undecided, (b) are not pinned by
    # an exact outline match, and (c) actually appear in the scored text are
    # movable. A CID absent from the page cannot be judged by the text it does
    # not occur in, and one vision decided by a wide margin is not this stage's
    # business.
    movable = [cid for cid in sorted(ranked)
               if cid not in pinned
               and counts.get(cid, 0) >= _MIN_CID_OCCURRENCES
               and len(candidates.get(cid, ())) > 1]
    if not movable:
        return mapping

    runs_by_cid: Dict[int, List[int]] = {}
    for i, r in enumerate(runs):
        for cid in set(r):
            runs_by_cid.setdefault(cid, []).append(i)

    cur = dict(mapping)
    run_score = [lm.logp(_decode(r, cur)) for r in runs]
    text_score = sum(run_score)
    vis_score = sum(counts.get(cid, 0) * emission.get(cid, {}).get(ch, 0.0)
                    for cid, ch in cur.items())

    # How many CIDs currently claim each character, across the WHOLE font --
    # including the ones this stage may not move, since a pinned or confident
    # CID still occupies its character and a movable one must not duplicate it.
    users: Dict[str, int] = collections.Counter(cur.values())

    def _collision_cost(ch: str, users_map: Dict[str, int]) -> float:
        if ch == ' ':
            return 0.0
        return _COLLISION_PENALTY * max(0, users_map.get(ch, 0) - 1)

    collision = sum(_collision_cost(c, users) for c in set(cur.values()))
    base_total = vis_score + _LM_WEIGHT * text_score - collision

    for _ in range(_MAX_PASSES):
        improved = False
        for cid in movable:
            old = cur.get(cid, ' ')
            idxs = runs_by_cid.get(cid, ())
            em = emission.get(cid, {})
            # A CID vision DECLINED (below `min_similarity`, mapped to space) has
            # no emission entry. Scoring the absent entry as 0.0 would rank it
            # equal to a confident top match and make the abstention the hardest
            # thing on the page to move -- the exact opposite of what a declined
            # glyph deserves. It is priced at the worst candidate on its own
            # shortlist instead: cheap to replace, but still bounded by that
            # CID's own evidence rather than free.
            em_old = em.get(old, min(em.values(), default=0.0)) if em else 0.0
            n = counts.get(cid, 0)
            best_ch, best_gain, best_scores = old, 0.0, None
            for ch in candidates[cid]:
                if ch == old:
                    continue
                cur[cid] = ch
                new_scores = [lm.logp(_decode(runs[i], cur)) for i in idxs]
                cur[cid] = old
                d_text = sum(new_scores) - sum(run_score[i] for i in idxs)
                d_vis = n * (em.get(ch, 0.0) - em_old)
                # Freeing `old` and claiming `ch` each shift one occupancy
                # count, so the collision term is evaluated on the trial
                # occupancy rather than the current one.
                trial_users = dict(users)
                trial_users[old] = trial_users.get(old, 1) - 1
                trial_users[ch] = trial_users.get(ch, 0) + 1
                d_coll = ((_collision_cost(old, trial_users)
                           + _collision_cost(ch, trial_users))
                          - (_collision_cost(old, users)
                             + _collision_cost(ch, users)))
                gain = d_vis + _LM_WEIGHT * d_text - d_coll
                if gain > best_gain + 1e-9:
                    best_ch, best_gain, best_scores = ch, gain, new_scores
            if best_scores is not None:
                cur[cid] = best_ch
                for i, s in zip(idxs, best_scores):
                    run_score[i] = s
                text_score = sum(run_score)
                vis_score += n * (em.get(best_ch, 0.0) - em_old)
                users[old] = users.get(old, 1) - 1
                users[best_ch] = users.get(best_ch, 0) + 1
                collision = sum(_collision_cost(c, users) for c in users)
                improved = True
        if not improved:
            break

    total = vis_score + _LM_WEIGHT * text_score - collision
    if total - base_total < _MIN_IMPROVEMENT:
        return mapping
    return cur
