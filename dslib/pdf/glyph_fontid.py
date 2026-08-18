"""Identify WHICH FACE a scrambled font is, then match its glyphs against that
face instead of against a fixed reference.

THE PROBLEM THIS SOLVES
-----------------------
`fix_encoding`'s pixel matcher compares every embedded glyph against DejaVu Sans
regular + bold, because that is what is reliably installed. But the fonts it is
asked about are arbitrary vendor faces. Every shape difference between DejaVu
and, say, Arial Narrow Italic is noise added on top of the signal, and it lands
on exactly the comparisons that are already marginal -- the measured confusions
are 'Q'->'O', 'B'->'8', 'b'->'o', 'l'->'/', all pairs a same-face comparison
separates easily and a cross-face one does not.

Identifying the face first turns a cross-face comparison into a same-face one.
It is also a far easier question than identifying a glyph: one font supplies
50-150 glyphs of evidence for a single answer, so the face is massively
over-determined even where each individual glyph is ambiguous.

WHAT SURVIVES IN A SCRAMBLED FONT
---------------------------------
Nothing that names it. Infineon's `Z_C000NN.tmp` fonts have the `name` table
overwritten with the temp filename, PANOSE zeroed, and no usable `post`/`cmap`
(see glyph_exact's dead-end note). What DOES survive is METRICS -- the PDF
`/Widths` array and the font's own `hmtx`:

    Z_C00220.tmp  /Widths [278 333 333 277 333 277 277 556 556 ... 722 722 666
    Z_C00222.tmp  /Widths [278 889 333 333 277 333 277 277 556 556 ... 583 583

Those are Helvetica/Arial metrics exactly -- 278 space, 556 digits, 889 for '%',
584 for the comparison operators. The widths are in SCRAMBLED code order, so
they cannot identify individual glyphs, but as a MULTISET they fingerprint the
face. Measured over 184 installed faces with metrics:

    Z_C00220.tmp  ->  Arial Bold (20.61), Arial Bold Italic (20.73), ...
    Z_C00222.tmp  ->  Microsoft Sans Serif (15.74), Arial (15.89), Arial Italic (16.01)

Correct in both cases -- Z_C00220 is the bold heading font, Z_C00222 the body
text, and Microsoft Sans Serif is metrically identical to Arial by design.

WHY TWO STAGES
--------------
Read that second list again: regular, italic and a metric clone are separated by
0.3 out of 16. Widths CANNOT tell an upright from an oblique, because obliquing
a face does not change its advances -- and the italic's glyphs are the wrong
shape to match against. So widths only ever produce a SHORTLIST, and the choice
within it is made visually, on the glyphs themselves.

THE ACCEPTANCE TEST IS THE POINT
--------------------------------
A detected face is used only if it explains the embedded glyphs BETTER THAN
DEJAVU DOES, by `_MIN_GAIN`. That is not a formality -- it is the whole safety
argument. This module cannot make matching worse by picking a wrong face,
because "wrong" here is defined as "no better than what we already had", and
such a face is rejected in favour of the existing reference. A face that is not
the true one but genuinely resembles it more than DejaVu is a legitimate
improvement, not an error, which is why the bar is a gain over the incumbent
rather than a similarity threshold in the abstract.
"""

import collections
import os
import warnings
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Faces carried from the metric shortlist into the (much costlier) visual pass.
#
# Was 12, which was enough until `dslib/pdf/fonts/` added 19 bundled faces to
# the ranking and CROWDED THE RIGHT ANSWER OUT: on a Verdana trial, Tahoma (the
# closest installed relative, top1 0.974) fell past rank 12 and the stage
# settled for DejaVu Sans (top1 0.933), costing 5.5 points of end-to-end
# accuracy. The shortlist is a recall device -- it only has to CONTAIN the true
# face, the visual pass does the choosing -- so it should be generous. The cost
# is linear and the per-face renderings are cached across a corpus run.
_SHORTLIST = 28

# A replacement face must improve BOTH statistics over the incumbent -- top-1
# similarity by `_MIN_TOP1_GAIN` and margin by `_MIN_MARGIN_GAIN` -- and is then
# ranked on their sum.
#
# Requiring both is not belt-and-braces, it is the fix for a measured
# regression. An earlier version accepted on margin alone, subject to top-1 not
# falling more than 0.02. On a Verdana trial with Verdana itself held out, that
# picked VERDANA ITALIC and dropped accuracy from 88.0% to 80.6%:
#
#     candidate              widthEMD     top1   margin
#     DejaVu (incumbent)            -   0.8014   0.1063
#     Verdana Italic.ttf         2.75   0.7834   0.1603   <- won on margin
#     Tahoma Bold.ttf           15.80   0.8077   0.1222
#
# Obliquing a face does not change its advances, so the italic is metrically
# perfect (EMD 2.75) and passes the width shortlist at rank 1. And its slanted
# glyphs are MORE mutually distinguishable than upright ones, so it wins on
# margin too. What it is not is a match for the upright shapes on the page --
# which only top-1 sees, and which it lost by 0.018, just inside the old
# tolerance. Margin says "this reference makes confident decisions"; top-1 says
# "those decisions are about the right shapes". A reference needs to be both.
_MIN_TOP1_GAIN = 0.005
_MIN_MARGIN_GAIN = 0.005

# A candidate's width consistency must also be no worse than the incumbent's by
# more than this factor. See `_width_consistency` -- it is the one signal here
# that is independent of the pixels, and it exists because top1 and margin agree
# with each other by construction and can therefore be jointly wrong.
_MAX_WIDTH_CV_RATIO = 1.15

# Below this many rendered glyphs, "mean best similarity" is not a measurement
# of anything and the shortlist is not evidence. Abstain to the fixed reference.
_MIN_GLYPHS = 12

# Glyphs sampled for the visual rerank. Scoring all of them is pointless -- the
# face is over-determined -- and this is the inner loop.
_VISUAL_SAMPLE = 40


# ---------------------------------------------------------------------------
# Per-face reference data, built lazily and cached
# ---------------------------------------------------------------------------

class FaceRefs:
    """Everything the matcher needs to compare against one identified face."""

    __slots__ = ('label', 'ref_items', 'advances', 'score', 'baseline_score')

    def __init__(self, label: str,
                 ref_items: List[Tuple[str, List[np.ndarray]]],
                 advances: Dict[str, List[float]],
                 score: float = 0.0, baseline_score: float = 0.0):
        self.label = label
        self.ref_items = ref_items
        self.advances = advances
        self.score = score
        self.baseline_score = baseline_score

    def __repr__(self):
        return ('FaceRefs(%s, %d chars, score=%.4f vs baseline %.4f)'
                % (self.label, len(self.ref_items), self.score,
                   self.baseline_score))


_FACE_CACHE: "collections.OrderedDict[str, Optional[FaceRefs]]" = \
    collections.OrderedDict()
_FACE_CACHE_MAX = 48  # a corpus run revisits the same handful of faces

_WIDTH_CACHE: Optional[Dict[str, Dict[str, float]]] = None


def _alphabet() -> Set[str]:
    from dslib.pdf.fix_encoding import _COMMON_GLYPHS
    return set(_COMMON_GLYPHS)


def _face_widths_all() -> Dict[str, Dict[str, float]]:
    """{font file: {char: advance in 1/1000 em}} for every installed face.

    Cheap enough to build eagerly (metrics only, no rasterising) and reused for
    every font in every PDF of a run.
    """
    global _WIDTH_CACHE
    if _WIDTH_CACHE is not None:
        return _WIDTH_CACHE
    from dslib.pdf.glyph_exact import _installed_fonts
    alpha = _alphabet()
    out: Dict[str, Dict[str, float]] = {}
    for path in _installed_fonts():
        try:
            from fontTools.ttLib import TTFont
            tt = TTFont(path, fontNumber=0, lazy=True)
        except Exception:
            continue
        try:
            upem = int(tt['head'].unitsPerEm) or 1000
            cmap = tt.getBestCmap() or {}
            hmtx = tt['hmtx']
            w = {}
            for cp, gname in cmap.items():
                ch = chr(cp)
                if ch in alpha:
                    try:
                        w[ch] = hmtx[gname][0] * 1000.0 / upem
                    except Exception:
                        pass
            # A face with only a handful of the alphabet cannot be compared on
            # distribution shape; excluded rather than scored on noise.
            if len(w) > 60:
                out[path] = w
        except Exception:
            pass
        finally:
            try:
                tt.close()
            except Exception:
                pass
    _WIDTH_CACHE = out
    return out


def _face_refs(path: str) -> Optional[FaceRefs]:
    """Render one installed face's alphabet into comparable bitmaps."""
    if path in _FACE_CACHE:
        _FACE_CACHE.move_to_end(path)
        return _FACE_CACHE[path]

    from dslib.pdf.fix_encoding import (_COMMON_GLYPHS, _GLYPH_SIZE,
                                        _render_glyph)
    from PIL import ImageFont
    built: Optional[FaceRefs] = None
    try:
        pil = ImageFont.truetype(path, _GLYPH_SIZE)
        widths = _face_widths_all().get(path, {})
        items: List[Tuple[str, List[np.ndarray]]] = []
        advs: Dict[str, List[float]] = {}
        for ch in _COMMON_GLYPHS:
            arr = _render_glyph(pil, ord(ch))
            if arr is None:
                continue
            items.append((ch, [arr]))
            if ch in widths:
                advs[ch] = [widths[ch]]
        if len(items) > 40:
            built = FaceRefs(os.path.basename(path), items, advs)
    except Exception:
        built = None

    _FACE_CACHE[path] = built
    if len(_FACE_CACHE) > _FACE_CACHE_MAX:
        _FACE_CACHE.popitem(last=False)
    return built


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _width_distance(embedded: Sequence[float],
                    face: Sequence[float]) -> float:
    """1-D earth-mover distance between two advance-width MULTISETS.

    A multiset, because the embedded widths are indexed by scrambled code and
    carry no character identity -- only the distribution is comparable. Both
    samples are resampled to a common number of quantiles first, since the font
    supplies 50-150 used glyphs and the face 60-130 alphabet entries, and an
    unequal-length comparison would measure the size difference.
    """
    a, b = sorted(embedded), sorted(face)
    if not a or not b:
        return float('inf')
    n = min(len(a), len(b))
    if n == 1:
        return abs(a[0] - b[0])
    qa = [a[round(i * (len(a) - 1) / (n - 1))] for i in range(n)]
    qb = [b[round(i * (len(b) - 1) / (n - 1))] for i in range(n)]
    return sum(abs(x - y) for x, y in zip(qa, qb)) / n


def _face_score(glyphs: Sequence[np.ndarray],
                ref_items: Sequence[Tuple[str, List[np.ndarray]]]
                ) -> Tuple[float, float]:
    """(mean top-1 similarity, mean top-1 minus top-2) over the sampled glyphs.

    MARGIN is the acceptance criterion, not top-1, and the reason is measured.
    Scored against `Z_C00222.tmp` -- an Arial subset -- the two references come
    out as:

        DejaVu (incumbent)   top1 0.9637   margin 0.1841
        Arial.ttf            top1 0.9634   margin 0.1978
        Arial Bold.ttf       top1 0.8709   margin 0.1287
        Times New Roman.ttf  top1 0.7077   margin 0.0641
        Courier New.ttf      top1 0.5669   margin 0.0542

    Top-1 cannot tell the TRUE face from the incumbent at all (0.9634 vs
    0.9637): it takes a max over ~130 reference characters, so some character
    always resembles the glyph and the statistic saturates. It separates a
    grossly wrong face fine and a nearly-right one not at all, which is the
    opposite of what is needed.

    Margin is also the quantity that actually decides accuracy downstream. What
    makes the matcher wrong is not a low score, it is a NARROW GAP between the
    right answer and the wrong one -- that is what `_TIE_MARGIN`, the width
    tie-break and the language model all exist to arbitrate. A reference that
    widens the gap removes the ambiguity at its source.

    Top-1 is still returned, and used as a guard: a face with a SPARSE
    repertoire gets a wide margin for free, simply by having nothing to be
    confused with. Requiring top-1 not to regress rejects that.
    """
    from dslib.pdf.fix_encoding import (_prepare, _prepare_items,
                                        _similarity_prepared)
    if not glyphs or len(ref_items) < 2:
        return 0.0, 0.0
    # Prepared once per call rather than per (glyph, reference) pair. This runs
    # over a 12-face shortlist, so it is the hottest loop in the pipeline.
    pref = _prepare_items(ref_items)
    pglyphs = [_prepare(g) for g in glyphs]
    top1 = top_gap = 0.0
    for g in pglyphs:
        best = second = -1.0
        for _ch, variants in pref:
            s = max(_similarity_prepared(g, v) for v in variants)
            if s > best:
                best, second = s, best
            elif s > second:
                second = s
        top1 += best
        top_gap += best - max(second, 0.0)
    n = len(glyphs)
    return top1 / n, top_gap / n


def _width_consistency(sample_cids: Sequence[int],
                       glyph_arrays: Dict[int, np.ndarray],
                       emb_widths: Dict[int, float],
                       ref_items: Sequence[Tuple[str, List[np.ndarray]]],
                       advances: Dict[str, List[float]]) -> Optional[float]:
    """Robust spread of emb_width / ref_width over the face's OWN best guesses.

    The idea: take whatever character this face thinks each glyph is, then ask
    the METRICS whether that story holds together. For the true face every ratio
    is the same number (the em scale), so the spread is ~0. For a wrong face the
    pixel assignment is scattered across characters whose widths have nothing to
    do with the observed ones, and the ratios scatter with it.

    This matters because top1 and margin are not independent evidence -- both
    are computed from the same cosine scores, so a face that matches shapes well
    but to the WRONG characters scores well on both. That is exactly what
    happened when DejaVu Sans beat the incumbent on top1 AND margin for a
    Verdana font and still lost 5.5 points of accuracy. Measured on that trial
    (lower is better):

        Verdana (the true face)  0.000
        Tahoma                   0.026
        Liberation Sans          0.063
        Times New Roman          0.138
        Courier New              0.164

    Median absolute deviation over the median, not the standard deviation over
    the mean: a handful of genuinely mismatched glyphs is expected even for the
    right face, and a squared statistic would let them dominate.

    Returns None -- no opinion -- when too few glyphs carry usable metrics.
    """
    from dslib.pdf.fix_encoding import (_prepare, _prepare_items,
                                        _similarity_prepared)
    if not advances:
        return None
    pref = _prepare_items(ref_items)
    ratios: List[float] = []
    for cid in sample_cids:
        w = emb_widths.get(cid)
        arr = glyph_arrays.get(cid)
        if not w or w <= 0 or arr is None:
            continue
        pg = _prepare(arr)
        best_ch, best_s = None, -2.0
        for ch, variants in pref:
            s = max(_similarity_prepared(pg, v) for v in variants)
            if s > best_s:
                best_ch, best_s = ch, s
        refs = advances.get(best_ch) if best_ch else None
        if not refs:
            continue
        # Nearest weight variant, as elsewhere: bold and regular differ enough
        # to bias the fit if the wrong one is assumed.
        ratios.append(w / min(refs, key=lambda r: abs(r - w)))
    if len(ratios) < 8:
        return None
    ratios.sort()
    med = ratios[len(ratios) // 2]
    if med <= 0:
        return None
    devs = sorted(abs(r - med) for r in ratios)
    return devs[len(devs) // 2] / med


def detect_face(glyph_arrays: Dict[int, np.ndarray],
                emb_widths: Optional[Dict[int, float]],
                baseline_items: Sequence[Tuple[str, List[np.ndarray]]],
                exclude: Optional[Set[str]] = None) -> Optional[FaceRefs]:
    """Identify the face and return its reference data, or None to keep the
    incumbent.

    `glyph_arrays` are the already-normalised bitmaps `fix_encoding` rendered --
    detection re-uses them rather than rasterising a second time.
    `baseline_items` is the incumbent reference (DejaVu), which the winner must
    beat; passing it in rather than importing it keeps the comparison honest
    when a caller has substituted a different incumbent.

    `exclude` drops font files by basename. It exists for the accuracy harness:
    the synthetic trials are drawn WITH installed faces, so without a hold-out
    this stage would find the exact file and report a tautology.
    """
    glyphs = list(glyph_arrays.values())
    if len(glyphs) < _MIN_GLYPHS:
        return None

    widths_by_face = _face_widths_all()
    if not widths_by_face:
        return None
    exclude = {e.lower() for e in (exclude or set())}

    candidates: List[str]
    ew = [w for w in (emb_widths or {}).values() if w and w > 0]
    if len(ew) >= _MIN_GLYPHS:
        scored = sorted(
            (_width_distance(ew, list(fw.values())), path)
            for path, fw in widths_by_face.items()
            if os.path.basename(path).lower() not in exclude)
        candidates = [p for _d, p in scored[:_SHORTLIST]]
    else:
        # No usable metrics (Type3 has no hmtx, and a font whose binary will not
        # parse gives none either). Rather than skip detection entirely, fall
        # back to a visual sweep over a bounded, deterministic slice of the
        # installed faces -- worse odds of finding the true face, but the
        # acceptance test still guarantees it cannot make things worse.
        candidates = [p for p in sorted(widths_by_face)
                      if os.path.basename(p).lower() not in exclude][:_SHORTLIST]

    if not candidates:
        return None

    # Deterministic sample: sorted CID order, evenly spaced. Not random, so two
    # runs on one file give one answer.
    keys = sorted(glyph_arrays)
    if len(keys) > _VISUAL_SAMPLE:
        step = len(keys) / _VISUAL_SAMPLE
        keys = [keys[int(i * step)] for i in range(_VISUAL_SAMPLE)]
    sample = [glyph_arrays[k] for k in keys]

    base_top1, base_margin = _face_score(sample, baseline_items)
    from dslib.pdf.fix_encoding import _reference_advances
    base_cv = _width_consistency(keys, glyph_arrays, emb_widths or {},
                                 baseline_items, _reference_advances())

    best: Optional[FaceRefs] = None
    best_combined = base_top1 + base_margin
    best_margin = base_margin
    for path in candidates:
        refs = _face_refs(path)
        if refs is None:
            continue
        top1, margin = _face_score(sample, refs.ref_items)
        if (top1 < base_top1 + _MIN_TOP1_GAIN
                or margin < base_margin + _MIN_MARGIN_GAIN):
            continue
        if base_cv is not None:
            cv = _width_consistency(keys, glyph_arrays, emb_widths or {},
                                    refs.ref_items, refs.advances)
            # No metrics for this face is no opinion, not a pass: the check is
            # skipped, not deemed satisfied. A face that HAS metrics and
            # disagrees with them is rejected.
            if cv is not None and cv > base_cv * _MAX_WIDTH_CV_RATIO:
                continue
        if top1 + margin > best_combined:
            best, best_combined, best_margin = refs, top1 + margin, margin

    if best is None:
        return None
    best.score = best_margin
    best.baseline_score = base_margin
    return best


def _cli(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog='glyph_fontid',
        description='Report which installed face each suspect font in a PDF '
                    'most resembles, and whether it beats the fixed reference.')
    ap.add_argument('pdf', nargs='+')
    args = ap.parse_args(argv)

    import pymupdf
    from dslib.pdf.fix_encoding import (_scan_fonts, _cid_to_gid_lookup,
                                        _build_pil_font_for_gid_render,
                                        _render_glyph, _reference_glyphs,
                                        _embedded_advances)

    base_items = list(_reference_glyphs().items())
    for path in args.pdf:
        print('##', path)
        doc = pymupdf.open(path)
        for fi in _scan_fonts(doc):
            try:
                fb = doc.extract_font(fi.xref)[3]
            except Exception:
                fb = None
            if not isinstance(fb, bytes) or not fb:
                continue
            c2g = _cid_to_gid_lookup(fb, fi.is_type0)
            wanted = {g for g in (c2g(c) for c in fi.used_codes) if g}
            built = _build_pil_font_for_gid_render(fb, wanted)
            if built is None:
                continue
            pil, code_by_gid = built
            arrs = {}
            for cid in sorted(fi.used_codes):
                g = c2g(cid)
                code = code_by_gid.get(g) if g else None
                if code is None:
                    continue
                a = _render_glyph(pil, code)
                if a is not None:
                    arrs[cid] = a
            adv = _embedded_advances(fb, c2g, set(arrs))
            m = detect_face(arrs, adv, base_items)
            print('   %-22s %s' % (
                fi.short_name[:22],
                'no better than the fixed reference' if m is None else
                '%-28s %.4f vs %.4f' % (m.label, m.score, m.baseline_score)))
        doc.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(_cli())
