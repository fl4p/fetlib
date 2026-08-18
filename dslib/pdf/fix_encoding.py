"""Detect and fix custom font encoding in PDFs.

Some datasheet PDFs (e.g. older Infineon / certain Chinese vendors) embed
fonts with an arbitrary, scrambled glyph-to-code mapping. Their text streams
therefore contain bytes like ``"%&$!"#`` that visually render as ``OptiMOS``
on the page but extract as gibberish, defeating any text-based parser. The
font may even ship a ``/ToUnicode`` CMap whose entries are an identity
mapping — present, but useless.

The repair strategy is *visual glyph matching*:

1. Flag every font with a suspect encoding: empty/Differences encoding +
   no ``/ToUnicode``, or a ``/ToUnicode`` that is an identity mapping.
2. For each used character, render its glyph from the source font.
   - TrueType / CFF: extract the font binary, patch its cmap so PIL can
     render every glyph by GID through a PUA codepoint.
   - Type3: parse ``/CharProcs``, run each one's PDF drawing operators
     under a known CTM on a temporary one-page PDF, rasterize with pymupdf.
3. Render reference glyphs from a system reference font (DejaVu Sans
   regular + bold) for a curated set of common ASCII / power-electronics
   technical symbols.
4. Pick the closest reference glyph for each source glyph (cosine
   similarity over inked-pixel arrays, with baseline-anchored normalization
   so x-height letters aren't confused with cap-height letters), then break
   near-ties with two non-visual features -- see "Tie-breaking" below.
5. Synthesize a fresh ``/ToUnicode`` CMap and inject it into the font
   dictionary, replacing any existing one. The embedded glyph outlines are
   left alone so the page renders identically to before; downstream text
   extractors (pdfminer, pdftotext, pymupdf) now see proper unicode.

Tie-breaking
------------
Some character pairs are at or past the resolution limit of pixel matching,
and the failures are systematic rather than random -- every ``l`` in three
Infineon datasheets extracted as ``I`` ("N-channeI, normaI IeveI"), and every
``p`` in one display font as ``μ`` ("OμtiMOS"). Cosine similarity separated
those by 0.003 and 0.008 respectively, which is noise.

Two features that pixel matching does not see resolve them, and they are
complementary:

* **advance width** -- read from the embedded font's own ``hmtx``, calibrated
  per font against the reference metrics using only the confidently-matched
  glyphs. Separates same-shape/different-width pairs: ``l`` 222 vs ``I`` 278,
  ``C`` 722 vs ``0`` 556.
* **hole count** -- the number of enclosed background regions, a scale- and
  weight-invariant topological property. Separates closed-vs-open pairs that
  are the same width: ``p`` 1 vs ``μ`` 0, ``o`` 1 vs ``u`` 0, ``C`` 0 vs
  ``0`` 1.

Both are advisory and only run when the top two visual candidates are within
``_TIE_MARGIN``. When a feature cannot be computed -- Type3 fonts have no
``hmtx``, a hairline bowl can close or open under rasterization -- it returns
*no opinion* and the visual winner stands unchanged. Neither feature can
promote a candidate that visual matching did not already rank near the top.

Public API:
    has_custom_font_encoding(pdf_path) -> bool
    fix_pdf_font_encoding(pdf_path, out_path=None) -> str  # path to saved PDF
"""

import hashlib
import io
import logging
import os
import pathlib
import re
import warnings
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

# fontTools emits noisy "'created' timestamp seems very low" warnings when
# loading subset embedded fonts whose head timestamps are stripped — silence them.
logging.getLogger('fontTools.ttLib.tables._h_e_a_d').setLevel(logging.ERROR)

_GLYPH_SIZE = 64
_PUA_BASE = 0xE000  # render glyphs through PUA codes mapped to their GID
_PUA_SIZE = 0xF8FF - 0xE000 + 1  # 6400: the BMP Private Use Area, and the hard
                                 # ceiling on how many glyphs one patched
                                 # format-4 cmap can expose at once.

_REF_FONT_CANDIDATES: List[Tuple[str, str]] = [
    # (regular, bold) pairs; first one whose files both exist wins.
    # Linux
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
     '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
     '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
    ('/usr/share/fonts/dejavu/DejaVuSans.ttf',
     '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf'),
    # macOS (modern)
    ('/System/Library/Fonts/Supplemental/Arial.ttf',
     '/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
    ('/System/Library/Fonts/HelveticaNeue.ttc',
     '/System/Library/Fonts/HelveticaNeue.ttc'),
    ('/System/Library/Fonts/Helvetica.ttc',
     '/System/Library/Fonts/Helvetica.ttc'),
    # macOS (legacy)
    ('/Library/Fonts/Arial.ttf', '/Library/Fonts/Arial Bold.ttf'),
    # Windows
    (r'C:\Windows\Fonts\arial.ttf', r'C:\Windows\Fonts\arialbd.ttf'),
]

# Characters likely to appear in MOSFET / power-electronics datasheets.
# Greek is kept deliberately small — only letters that actually show up in
# spec tables (Ω, μ for resistance and micro-prefix); the lowercase σ/π/θ/λ
# of DejaVu look too similar to plain Latin letters at this raster size and
# cause systematic false matches if included.
_COMMON_GLYPHS: List[str] = (
        list("abcdefghijklmnopqrstuvwxyz")
        + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        + list("0123456789")
        + list(" .,;:!?'\"()[]{}/<>=+-*&%#@$~^_|\\`")
        + list("°±×÷")
        + list("•≤≥≠≈∞")
        + ['Ω', 'μ']
        + ['™', '®', '©', '€', '℃', '℉']
)

_REF_CACHE: Optional[Dict[str, List[np.ndarray]]] = None
_REF_ADV_CACHE: Optional[Dict[str, List[float]]] = None

# --- tie-breaking constants -------------------------------------------
# Measured on the three Infineon samples this was built for. The two known
# mis-resolutions sat at margins 0.0033 and 0.0082; the nearest CORRECT
# resolution that must not be disturbed sat at 0.047 (p over μ, vision right).
# 0.03 is between them with roughly a factor of 4 either way -- wide enough to
# catch the failures, far enough below 0.047 to leave correct calls alone.
_TIE_MARGIN = 0.03

# A glyph only calibrates the width scale if vision resolved it decisively.
# Deliberately well above _TIE_MARGIN: a glyph that needed arbitration must not
# then vote on the scale used to arbitrate it.
_CONFIDENT_MARGIN = 0.06

# Below this many confident samples the per-font scale is not estimated at all
# and width abstains. A scale fitted to one or two glyphs is a guess, and a
# guessed scale applied to a 3.6%-separated pair (p vs μ) decides by noise.
_MIN_WIDTH_SAMPLES = 4

# The rival's relative width error must be this many times SMALLER than the
# visual winner's before width overrides vision. l vs I clears it by ~9x.
_WIDTH_EDGE = 2.0

# How many runners-up to carry per CID. Only candidates inside _TIE_MARGIN can
# ever win, and more than a handful of distinct characters are never that close
# to one glyph; the cap just bounds the per-CID work.
_TIE_CANDIDATES = 6


# ----- glyph rendering --------------------------------------------------

def _fc_match(query: str) -> Optional[str]:
    """Resolve a fontconfig query (e.g. 'sans-serif:weight=bold') to a path,
    if fontconfig is installed. Returns None on any failure (no fc-match,
    no match, non-TTF/OTF result)."""
    import shutil
    import subprocess
    if not shutil.which('fc-match'):
        return None
    try:
        out = subprocess.run(['fc-match', '-f', '%{file}', query],
                             capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    path = out.stdout.strip()
    if not path or not os.path.isfile(path):
        return None
    if not path.lower().endswith(('.ttf', '.otf', '.ttc')):
        return None
    return path


BUNDLED_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'fonts')

# Characters missing from the primary reference are taken from here. DejaVu Sans
# is the only bundled face carrying all 113 of `_COMMON_GLYPHS`; Liberation and
# Arial both lack the degree-Celsius and degree-Fahrenheit ligatures, and a
# character absent from the reference can never be emitted at all.
_REF_FILL_FONTS = ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')


def bundled_fonts() -> List[str]:
    """The reference faces shipped with this repo, sorted.

    `dslib/pdf/fonts/` carries DejaVu (Sans/Serif/Mono) and Liberation
    (Sans/Serif/Mono, four weights each), with both licences alongside. They are
    here for two reasons, and the first is correctness rather than accuracy:

    * **Determinism.** The reference used to be whatever `fc-match sans-serif`
      returned, which is a property of the HOST, not of this code. On this Mac
      that resolves to Arial; on a Linux CI box it resolves to DejaVu. Same
      commit, same PDF, different extracted text -- and the only thing that made
      it detectable at all was `reference_font_salt()` forcing a cache miss.
      Note this repo's own documentation said "DejaVu regular+bold" while the
      code was in fact using Arial, for exactly that reason.
    * **Coverage where it is needed.** Liberation Sans/Serif/Mono are METRICALLY
      COMPATIBLE with Arial/Times New Roman/Courier New -- the three families
      vendor datasheets actually use -- so `glyph_fontid` has a usable stand-in
      for each even on a machine that licenses none of them. Measured: vision
      alone scores in the thirties on Courier-set text against a sans reference,
      and ~89% once a monospace reference is available.

    DejaVu Sans is the fallback REFERENCE (rather than Liberation Sans, which is
    the closer match to most datasheet text) purely on alphabet coverage: it is
    the only one of the three that carries all 113 of `_COMMON_GLYPHS`.
    Liberation and Arial both lack ℃ and ℉, and a character absent from the
    reference can never be emitted at all.
    """
    try:
        return sorted(
            os.path.join(BUNDLED_FONT_DIR, f)
            for f in os.listdir(BUNDLED_FONT_DIR)
            if f.lower().endswith(('.ttf', '.otf')))
    except Exception:
        return []


def _find_reference_fonts() -> Tuple[Union[str, bytes], Union[str, bytes]]:
    """Locate the regular + bold reference faces. Returns paths or in-memory
    font bytes — either form is accepted by PIL's `ImageFont.truetype`.

    Order of preference:

        0. The BUNDLED Liberation Sans (see `bundled_fonts` -- deterministic,
           and metric-compatible with Arial, which most datasheet text is).
           `_reference_glyphs` fills the two characters it lacks from the
           bundled DejaVu Sans, so coverage is not sacrificed for metrics.
        1. The hardcoded `_REF_FONT_CANDIDATES`.
        2. fontconfig (`fc-match`), if installed.
        3. Pillow's bundled DejaVu Sans (recent Pillow versions), as a last
           resort: regular is real, bold is the same regular font (some
           matching quality is lost but it works everywhere Pillow does).

    Steps 1-3 are kept as fallbacks for a checkout without the font directory,
    but they are host-dependent by nature -- see `bundled_fonts`.
    """
    reg = os.path.join(BUNDLED_FONT_DIR, 'LiberationSans-Regular.ttf')
    bold = os.path.join(BUNDLED_FONT_DIR, 'LiberationSans-Bold.ttf')
    if os.path.exists(reg) and os.path.exists(bold):
        return reg, bold

    for reg, bold in _REF_FONT_CANDIDATES:
        if os.path.exists(reg) and os.path.exists(bold):
            return reg, bold

    reg = _fc_match('sans-serif')
    bold = _fc_match('sans-serif:weight=bold')
    if reg and bold:
        return reg, bold

    # Pillow ≥ 10 ships a real TrueType DejaVu Sans accessible via
    # load_default(size). The font's `path` attribute is a BytesIO of the
    # raw TTF bytes; copy them out and hand them back so the caller can
    # rebuild via `ImageFont.truetype(BytesIO(...))`.
    try:
        default = ImageFont.load_default(size=_GLYPH_SIZE)
        src = getattr(default, 'path', None)
        if hasattr(src, 'getvalue'):
            data = src.getvalue()
            if data:
                return data, data  # same bytes used as regular & bold
        elif isinstance(src, (str, bytes)) and src and os.path.isfile(src):
            return src, src
    except Exception:
        pass

    raise RuntimeError(
        'No system reference font (regular+bold) found. Install DejaVu '
        '(`apt install fonts-dejavu`), Liberation, or any sans-serif via '
        'fontconfig. Tried: '
        + ', '.join(p for pair in _REF_FONT_CANDIDATES for p in pair))


def reference_font_salt() -> str:
    """Identity of the reference fonts the glyph matcher compares against.

    These bitmaps ARE the matcher's reference data: they decide which character each
    embedded glyph is judged to be, and therefore which characters the repaired text layer
    contains. Which file supplies them is resolved from the SYSTEM at runtime
    (`_REF_FONT_CANDIDATES`, then `fc-match`, then Pillow's bundled DejaVu), so a font
    install -- or simply a different machine -- changes the repaired text with no source
    change anywhere. Hashing the matcher's code but not its reference data is the
    signature-vs-proxy hole one level out from the code itself.

    Same treatment `field_repr_salt` gives unidecode: name the external input in the key.
    Unlike that one this does NOT raise when unresolvable, because "no usable reference
    font" is a legitimate state on a machine that never repairs a PDF, and failing every
    import over it would be worse than the gap. It is reported as its own distinct marker
    instead, so an unresolved run and a resolved one can never share a cache entry.
    """
    try:
        reg, bold = _find_reference_fonts()
    except Exception:
        return 'reffonts=UNRESOLVED'
    from dslib.cache import _file_content_sig
    parts = []
    for src in (reg, bold):
        if isinstance(src, bytes):
            # Pillow's bundled fallback: no path to stat, so hash the bytes themselves.
            parts.append('bytes:' + hashlib.sha256(src).hexdigest()[:16])
        else:
            try:
                parts.append(os.path.basename(src) + ':' + _file_content_sig(src))
            except Exception:
                parts.append('unreadable:' + os.path.basename(str(src)))
    return 'reffonts=' + hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]


def _ink_bbox(img: Image.Image, threshold: int = 220) -> Optional[Tuple[int, int, int, int]]:
    """Bounding box of inked (dark) pixels in a grayscale image. `getbbox()`
    treats white-on-white the wrong way around for our purposes — it returns
    the whole image when the background is white (255 != 0)."""
    arr = np.asarray(img, dtype=np.uint8)
    ink = arr < threshold
    if not ink.any():
        return None
    ys, xs = np.where(ink)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _normalize_glyph_bitmap(img: Image.Image, baseline_y: int,
                            size: int = _GLYPH_SIZE) -> Optional[np.ndarray]:
    """Normalize a rendered glyph (with known baseline pixel-y) to a
    size×size float array, preserving baseline-relative vertical placement.
    """
    bbox = _ink_bbox(img)
    if bbox is None:
        return None
    x0, _, x1, _ = bbox
    # Fixed-height window around the baseline: 110% above, 35% below.
    top = max(0, baseline_y - int(size * 1.1))
    bot = min(img.height, baseline_y + int(size * 0.35))
    glyph = img.crop((x0, top, x1, bot))
    gw, gh = glyph.size
    if gw == 0 or gh == 0:
        return None
    scale = min(size / gw, size / gh)
    new_w = max(1, int(round(gw * scale)))
    new_h = max(1, int(round(gh * scale)))
    glyph = glyph.resize((new_w, new_h), Image.LANCZOS)
    out = Image.new('L', (size, size), 255)
    baseline_in_window = baseline_y - top
    target_baseline = int(round(baseline_in_window * scale))
    desired_baseline = int(size * 0.7)
    paste_x = (size - new_w) // 2
    paste_y = max(0, min(size - new_h, desired_baseline - target_baseline))
    out.paste(glyph, (paste_x, paste_y))
    arr = 1.0 - np.asarray(out, dtype=np.float32) / 255.0
    return arr if arr.sum() >= 1.0 else None


def _render_glyph(pil_font: ImageFont.FreeTypeFont, code: int, size: int = _GLYPH_SIZE
                  ) -> Optional[np.ndarray]:
    """Render `chr(code)` from `pil_font` into a size×size float array of inked
    intensity (0=blank, 1=ink). The glyph is placed with a fixed baseline so
    lowercase x-height letters and full-cap letters keep their relative
    vertical proportions — critical for telling 'a' apart from 'P'.
    """
    canvas_w = int(size * 2.5)
    canvas_h = int(size * 2.5)
    img = Image.new('L', (canvas_w, canvas_h), 255)
    draw = ImageDraw.Draw(img)
    baseline_y = int(canvas_h * 0.7)
    try:
        draw.text((size // 4, baseline_y), chr(code), font=pil_font,
                  fill=0, anchor='ls')
    except Exception:
        return None
    return _normalize_glyph_bitmap(img, baseline_y, size)


def _reference_glyphs() -> Dict[str, List[np.ndarray]]:
    """For each char in `_COMMON_GLYPHS`, the rendering from each available
    reference font (regular + bold). Returns char → list of inked arrays.

    Built from Liberation Sans, then GAP-FILLED from DejaVu Sans. The split is
    deliberate and the reason is the width tie-break, not the pixels:

        advance (1/1000 em)      'l'     'I'    apart
        Arial / Liberation Sans  222     278      25%
        DejaVu Sans              278     295       6%

    `_break_tie` separates 'l' from 'I' on advance width because vision cannot
    -- the cosine gap is 0.003. That only works if the REFERENCE metrics
    actually distinguish them, and DejaVu's barely do: switching the reference
    to DejaVu broke four tie-break tests outright. Liberation is metrically
    identical to Arial, which is what these datasheets are set in, so the width
    evidence stays as sharp as it was on a host that happened to have Arial
    installed -- but now by construction rather than by luck.

    DejaVu is still the fill, because it is the only bundled face with the full
    alphabet, and a missing reference character is unrecoverable.
    """
    global _REF_CACHE, _REF_ADV_CACHE
    if _REF_CACHE is not None:
        return _REF_CACHE
    reg_src, bold_src = _find_reference_fonts()

    def _load(src):
        return ImageFont.truetype(io.BytesIO(src) if isinstance(src, bytes) else src,
                                  _GLYPH_SIZE)

    srcs = [reg_src, bold_src]
    # Skip duplicate when fallback returned the same source for both weights.
    if reg_src == bold_src:
        srcs = srcs[:1]
    fonts = [_load(s) for s in srcs]
    # Advances are built here rather than in a separate function so the metric
    # list stays index-aligned with the bitmap list by construction. Two
    # independent builders, each re-deriving the regular/bold dedup, is exactly
    # the kind of parallel table that drifts.
    adv_per_font = [_font_advances(s) for s in srcs]

    # Gap-fill sources, appended so the primary face always wins a character it
    # has. Only consulted for characters the primary lacks -- mixing metrics
    # from two faces for the SAME character would corrupt the width
    # calibration, which fits a single scale factor across all of them.
    fill_fonts, fill_advs = [], []
    for name in _REF_FILL_FONTS:
        fp = os.path.join(BUNDLED_FONT_DIR, name)
        if os.path.isfile(fp):
            try:
                fill_fonts.append(_load(fp))
                fill_advs.append(_font_advances(fp))
            except Exception:
                pass

    refs: Dict[str, List[np.ndarray]] = {}
    advs: Dict[str, List[float]] = {}
    for ch in _COMMON_GLYPHS:
        variants = []
        widths = []
        for f, adv in zip(fonts, adv_per_font):
            arr = _render_glyph(f, ord(ch))
            if arr is not None:
                variants.append(arr)
                if ch in adv:
                    widths.append(adv[ch])
        if not variants:
            for f, adv in zip(fill_fonts, fill_advs):
                arr = _render_glyph(f, ord(ch))
                if arr is not None:
                    variants.append(arr)
                    if ch in adv:
                        widths.append(adv[ch])
        if variants:
            refs[ch] = variants
            if widths:
                advs[ch] = widths
    _REF_CACHE = refs
    _REF_ADV_CACHE = advs
    return refs


def _reference_advances() -> Dict[str, List[float]]:
    """char -> advance widths (one per reference weight), 1000ths of an em.

    A char may be absent: it renders but its metrics could not be read. Callers
    must treat that as "no width evidence", never as a width of zero.
    """
    if _REF_ADV_CACHE is None:
        _reference_glyphs()
    return _REF_ADV_CACHE or {}


def _box_blur(arr: np.ndarray, passes: int = 2, k: int = 3) -> np.ndarray:
    """Separable box blur, repeated -- a cheap Gaussian approximation.

    Why blur at all: raw pixel overlap is unforgiving about POSITION. Two
    renderings of the same letter at slightly different weight or hinting share
    most of their ink but not the same pixels, and a hard overlap charges full
    price for a one-pixel offset. Blurring makes a near miss score nearly as
    well as a hit, which is the whole idea behind chamfer / distance-transform
    matching -- without needing a distance transform, and so without scipy,
    which is not in requirements.txt.
    """
    out = arr
    for _ in range(passes):
        pad = k // 2
        p = np.pad(out, pad, mode='constant')
        acc = np.zeros_like(out)
        for dy in range(k):
            for dx in range(k):
                acc += p[dy:dy + out.shape[0], dx:dx + out.shape[1]]
        out = acc / (k * k)
    return out


# Which comparison the pixel matcher uses. CHOSEN BY MEASUREMENT, on 24 fonts
# of test/fix_enc_eval.py at holdout=family:
#
#     metric        vision   +fontid
#     cosine         69.9%     75.9%     <- the original
#     zncc           69.1%     75.2%
#     cosine_blur    71.7%     80.0%     <- chosen
#     zncc_blur      71.5%     79.9%
#
# Two ideas were tried and only one paid. BLURRING is worth ~1.8 points on its
# own and ~4 once face detection can act on the cleaner ranking, because it
# stops charging full price for a one-pixel offset between two renderings of
# the same letter. MEAN-CENTRING (the 'z') was expected to help by decompressing
# cosine's narrow high band and did not -- it is a wash at best and slightly
# negative without blur. The compression is real, but it turns out to be
# harmless: the median correct top1-vs-top2 gap is ~0.13, not the ~0.003 seen on
# the few genuinely hard pairs, so there was little range to recover.
#
# Override with FETLIB_GLYPH_METRIC to re-run that comparison without editing
# code; `test/fix_enc_eval.py --calibrate` prints the distributions each
# metric's thresholds would need.
_METRIC = os.environ.get('FETLIB_GLYPH_METRIC', 'cosine_blur')

_METRICS = ('cosine', 'zncc', 'cosine_blur', 'zncc_blur')


def _prepare(arr: np.ndarray) -> np.ndarray:
    """Put one inked-pixel array into the form `_similarity_prepared` compares.

    Both improvements over the original raw cosine are applied here rather than
    in the comparison, so each array is transformed ONCE and every comparison is
    then a plain dot product -- with ~130 reference characters per glyph, that
    is also faster than the original, which recomputed both norms every time.

    MEAN-CENTRING (the 'z' in zncc). Cosine over non-negative ink is compressed
    into a narrow high band: every candidate scores 0.9+, and the pairs that
    actually matter are separated by thousandths -- 'l' vs 'I' by 0.003, 'p' vs
    'mu' by 0.008. That compression is not a property of the glyphs, it is an
    artefact of comparing two vectors that are both entirely non-negative and
    therefore always point into the same orthant. Subtracting the mean lets a
    pixel that is ink in one image and blank in the other push the score DOWN
    instead of merely failing to push it up, which is what restores the dynamic
    range. It is also why `glyph_lm._VIS_TEMP` had to exist: the emission term
    had no range to contribute.

    BLURRING trades positional precision for tolerance to weight and hinting
    differences -- see `_box_blur`.
    """
    if _METRIC in ('cosine_blur', 'zncc_blur'):
        arr = _box_blur(arr)
    if _METRIC in ('zncc', 'zncc_blur'):
        arr = arr - arr.mean()
    n = float(np.sqrt((arr * arr).sum()))
    return arr / n if n > 1e-9 else arr


def _prepare_items(items: Sequence[Tuple[str, List[np.ndarray]]]
                   ) -> List[Tuple[str, List[np.ndarray]]]:
    """`_prepare` every variant of a reference set, keeping its shape."""
    return [(ch, [_prepare(v) for v in variants]) for ch, variants in items]


def _similarity_prepared(a: np.ndarray, b: np.ndarray) -> float:
    """Similarity between two arrays already through `_prepare`.

    Both are unit-norm, so this is the cosine (or the Pearson correlation, for
    the mean-centred metrics) and the dot product is the whole computation.
    """
    return float((a * b).sum())


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Similarity between two RAW inked-pixel arrays.

    Convenience wrapper that prepares both. Correct but wasteful in a loop --
    the hot paths prepare once and call `_similarity_prepared`.

    Range depends on the metric: ~0..1 for the cosine variants, ~-1..1 for the
    mean-centred ones. Callers that compare against an absolute threshold must
    take their constant from `_METRIC_CONSTANTS`, never hard-code one.
    """
    return _similarity_prepared(_prepare(a), _prepare(b))


# ----- non-visual glyph features ---------------------------------------

def _hole_count(arr: np.ndarray, threshold: float = 0.35) -> int:
    """Number of background regions fully enclosed by ink ('p'->1, 'μ'->0,
    'B'->2). Topological, so it survives the weight and width differences that
    make cosine similarity ambiguous.

    Implemented as a border flood-fill in numpy rather than via scipy.ndimage:
    scipy is not in requirements.txt and a 64x64 raster does not justify adding
    it. Iterating binary dilation against the ink mask reaches a fixed point in
    O(image diameter) passes.

    The background is flooded 8-CONNECTED while regions are counted 4-connected.
    That pairing is not arbitrary -- mixing connectivities is the standard way
    out of the digital-topology paradox, and using 4 for both gets this wrong in
    the direction that matters here. A stroke that closes only DIAGONALLY, which
    is what antialiasing plus a hard threshold produces at a near-miss junction,
    blocks a 4-connected background and so invents an enclosed region:
    demonstrated on a 12x12 ring whose cavity is reachable from outside purely
    corner-to-corner, which counted as 1 hole. An invented hole is the dangerous
    direction, because `_break_tie` uses the count to ELIMINATE candidates -- a
    phantom bowl on a real 'μ' would eliminate 'μ' and promote 'p', reproducing
    the bug this feature exists to fix with the sign flipped.
    """
    ink = arr > threshold
    bg = ~ink
    if not bg.any():
        return 0

    # Flood the background inward from the border until it stops growing.
    outside = np.zeros_like(bg)
    outside[0, :] = bg[0, :]
    outside[-1, :] = bg[-1, :]
    outside[:, 0] = bg[:, 0]
    outside[:, -1] = bg[:, -1]
    while True:
        grown = outside.copy()
        grown[1:, :] |= outside[:-1, :]
        grown[:-1, :] |= outside[1:, :]
        grown[:, 1:] |= outside[:, :-1]
        grown[:, :-1] |= outside[:, 1:]
        # diagonals -- see the connectivity note above
        grown[1:, 1:] |= outside[:-1, :-1]
        grown[1:, :-1] |= outside[:-1, 1:]
        grown[:-1, 1:] |= outside[1:, :-1]
        grown[:-1, :-1] |= outside[1:, 1:]
        grown &= bg
        if grown.sum() == outside.sum():
            break
        outside = grown

    enclosed = bg & ~outside
    if not enclosed.any():
        return 0

    # Count connected components among the enclosed pixels the same way.
    remaining = enclosed.copy()
    n = 0
    while remaining.any():
        ys, xs = np.where(remaining)
        seed = np.zeros_like(remaining)
        seed[ys[0], xs[0]] = True
        while True:
            grown = seed.copy()
            grown[1:, :] |= seed[:-1, :]
            grown[:-1, :] |= seed[1:, :]
            grown[:, 1:] |= seed[:, :-1]
            grown[:, :-1] |= seed[:, 1:]
            grown &= remaining
            if grown.sum() == seed.sum():
                break
            seed = grown
        remaining &= ~seed
        # A speck of anti-aliasing noise should not read as a counting bowl.
        # Components below a few pixels are dropped rather than counted.
        if seed.sum() >= 4:
            n += 1
    return n


def _font_advances(src: Union[str, bytes]) -> Dict[str, float]:
    """char -> advance width in 1000ths of an em, for a reference font file."""
    try:
        tt = TTFont(io.BytesIO(src) if isinstance(src, bytes) else src,
                    fontNumber=0, lazy=True)
        upm = tt['head'].unitsPerEm or 1000
        cmap = tt.getBestCmap()
        hmtx = tt['hmtx']
    except Exception:
        return {}
    out: Dict[str, float] = {}
    for ch in _COMMON_GLYPHS:
        gname = cmap.get(ord(ch))
        if not gname:
            continue
        try:
            out[ch] = hmtx[gname][0] * 1000.0 / upm
        except Exception:
            continue
    return out


# ----- font analysis ---------------------------------------------------

@dataclass
class _FontInfo:
    xref: int
    is_type0: bool
    is_type3: bool
    short_name: str
    used_codes: Set[int] = field(default_factory=set)


def _name_aliases(basefont: str) -> List[str]:
    """Names by which a font appears in `Page.get_text('rawdict')` spans."""
    out = [basefont]
    if '+' in basefont:
        out.append(basefont.split('+', 1)[1])
    return out


def _is_identity_to_unicode(doc: pymupdf.Document, font_xref: int) -> bool:
    """True if the font's /ToUnicode CMap is an identity (cid → cid) mapping.

    PDFs occasionally ship such a CMap to *look* compliant while still defeating
    text extraction — every code maps to itself, so the gibberish stays gibberish.
    """
    obj = doc.xref_object(font_xref)
    m = re.search(r'/ToUnicode\s+(\d+)\s+0\s+R', obj)
    if not m:
        return False
    try:
        cmap = doc.xref_stream(int(m.group(1))).decode('latin1', errors='replace')
    except Exception:
        return False
    pairs = re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', cmap)
    # First pair is the codespacerange (range bounds, not a mapping) — drop it.
    bfchars = pairs[1:]
    if not bfchars:
        return False
    same = sum(1 for s, t in bfchars if len(s) <= 4 and int(s, 16) == int(t, 16))
    return same / len(bfchars) >= 0.9


def _cid_ordering(doc: pymupdf.Document, xref: int) -> Optional[str]:
    """The descendant CIDFont's /CIDSystemInfo /Ordering, or None if unreadable.

    'Identity' means the CIDs are raw glyph indices of a subset font and carry
    no character meaning whatsoever. A registered collection ('Japan1', 'GB1',
    …) is the opposite: a conforming reader maps those to unicode through a
    standard CMap, so a missing /ToUnicode is not by itself a defect there.
    """
    try:
        obj = doc.xref_object(xref)
        m = re.search(r'/DescendantFonts\s*\[\s*(\d+)\s+0\s+R', obj)
        desc = doc.xref_object(int(m.group(1))) if m else obj
        mo = re.search(r'/Ordering\s*\(([^)]*)\)', desc)
        return mo.group(1) if mo else None
    except Exception:
        return None


def _font_has_suspect_encoding(doc: pymupdf.Document, xref: int, enc: str) -> bool:
    """A font is suspect (likely scrambled custom encoding) when either:
        - it has no /ToUnicode and its encoding cannot supply unicode itself, OR
        - it has a /ToUnicode that's an identity mapping.

    The no-/ToUnicode case covers two encodings:
      * absent / a Differences dict — pymupdf reports `enc=''`;
      * Identity-H / Identity-V — codes ARE glyph indices, so there is nothing
        to decode them with.

    The Identity arm used to be missing, and `enc` being the truthy string
    'Identity-H' meant the `not enc` test skipped straight past it. Five fonts
    in MCAC100N08Y-TP.pdf are exactly that shape, which is why its part number
    extracted as '0&$&\\x14\\x13\\x131\\x13\\x1b<' — every byte a uniform 0x1D
    below the real text — while the file was being reported as clean.
    """
    obj = doc.xref_object(xref)
    if not re.search(r'/ToUnicode\s+\d+\s+0\s+R', obj):
        if not enc:
            return True
        if enc.startswith('Identity'):
            # A registered collection is decodable without /ToUnicode; only
            # Adobe-Identity-0 (or an ordering we cannot read, which we must
            # not assume is a standard collection) is not.
            ordering = _cid_ordering(doc, xref)
            return ordering in (None, 'Identity')
        return False
    return _is_identity_to_unicode(doc, xref)


_CONTENT_TOKEN_RE = re.compile(
    rb'/(\w+)\s+\S+\s+Tf|<([0-9A-Fa-f\s]+)>\s*Tj|\(((?:\\.|[^\\)])*)\)\s*Tj|\[(.*?)\]\s*TJ',
    flags=re.DOTALL,
)
_ARRAY_TOKEN_RE = re.compile(
    rb'<([0-9A-Fa-f\s]+)>|\(((?:\\.|[^\\)])*)\)', flags=re.DOTALL)


def _hex_to_cids(hex_bytes: bytes, two_byte: bool, out: Set[int]) -> None:
    clean = bytes(c for c in hex_bytes if c not in b' \r\n\t').decode('ascii', 'ignore')
    step = 4 if two_byte else 2
    for i in range(0, len(clean) - step + 1, step):
        try:
            out.add(int(clean[i:i + step], 16))
        except ValueError:
            pass


def _literal_to_cids(lit: bytes, out: Set[int]) -> None:
    # Handles the common PDF \( \) \\ \n \r \t \b \f \ddd escapes — enough for
    # our text-extraction needs.
    i = 0
    while i < len(lit):
        b = lit[i]
        if b == 0x5C and i + 1 < len(lit):  # '\\'
            nxt = lit[i + 1]
            if nxt in b'nrtbf()\\':
                out.add({b'n': 10, b'r': 13, b't': 9, b'b': 8, b'f': 12,
                         b'(': 40, b')': 41, b'\\': 92}[bytes([nxt])])
                i += 2
                continue
            if 0x30 <= nxt <= 0x37:
                # Octal escape: up to 3 digits
                j = i + 1
                while j < len(lit) and j < i + 4 and 0x30 <= lit[j] <= 0x37:
                    j += 1
                out.add(int(lit[i + 1:j], 8) & 0xFF)
                i = j
                continue
            i += 2
            continue
        out.add(b)
        i += 1


def _used_cids_per_font(doc: pymupdf.Document) -> Dict[int, Set[int]]:
    """For each font xref, collect every CID actually used by any Tj/TJ in any
    page's content stream. More reliable than scanning rawdict spans, which
    silently drops CIDs that the original /ToUnicode mapped to control codes."""
    out: Dict[int, Set[int]] = {}
    for pno in range(len(doc)):
        name_info: Dict[str, Tuple[int, bool]] = {}
        for xref, _ext, typ, _bf, fname, _enc in doc.get_page_fonts(pno):
            name_info[fname] = (xref, typ == 'Type0')
        contents = doc[pno].read_contents()
        cur_xref: Optional[int] = None
        cur_type0 = False
        for m in _CONTENT_TOKEN_RE.finditer(contents):
            tf, hex_s, lit_s, arr_s = m.groups()
            if tf is not None:
                name = tf.decode('latin1', 'ignore')
                if name in name_info:
                    cur_xref, cur_type0 = name_info[name]
                else:
                    cur_xref = None
            elif cur_xref is None:
                continue
            elif hex_s is not None:
                _hex_to_cids(hex_s, cur_type0, out.setdefault(cur_xref, set()))
            elif lit_s is not None and not cur_type0:
                _literal_to_cids(lit_s, out.setdefault(cur_xref, set()))
            elif arr_s is not None:
                for am in _ARRAY_TOKEN_RE.finditer(arr_s):
                    h, lit = am.groups()
                    if h is not None:
                        _hex_to_cids(h, cur_type0, out.setdefault(cur_xref, set()))
                    elif lit is not None and not cur_type0:
                        _literal_to_cids(lit, out.setdefault(cur_xref, set()))
    return out


def _scan_fonts(doc: pymupdf.Document, only_fixable: bool = True) -> List[_FontInfo]:
    """Return one `_FontInfo` per suspect font: empty/custom encoding without
    /ToUnicode, or identity /ToUnicode.

    With `only_fixable=True` (default), fonts that aren't extractable
    (Type3, built-ins) are filtered out — they need a different fix.
    """
    info_by_xref: Dict[int, _FontInfo] = {}
    name_to_xref: Dict[str, int] = {}
    ext_by_xref: Dict[int, str] = {}
    suspect: Set[int] = set()

    for pno in range(len(doc)):
        for xref, ext, typ, basefont, _name, enc in doc.get_page_fonts(pno):
            if xref not in info_by_xref:
                short = basefont.split('+', 1)[1] if '+' in basefont else basefont
                info_by_xref[xref] = _FontInfo(
                    xref=xref, is_type0=(typ == 'Type0'),
                    is_type3=(typ == 'Type3'), short_name=short)
                ext_by_xref[xref] = ext
                for n in _name_aliases(basefont):
                    name_to_xref.setdefault(n, xref)
                if _font_has_suspect_encoding(doc, xref, enc):
                    suspect.add(xref)

    if not suspect:
        return []

    # Parse content streams directly. pymupdf.rawdict silently drops CIDs that
    # the original /ToUnicode mapped to control codes (e.g. NUL in an identity
    # CMap), so the rawdict-based scan was missing real CIDs that the source
    # uses for things like hyphens and commas.
    used_per_font = _used_cids_per_font(doc)
    for xref in suspect:
        if xref in used_per_font:
            info_by_xref[xref].used_codes.update(used_per_font[xref])

    out = []
    for x in suspect:
        if not info_by_xref[x].used_codes:
            continue
        # Type3 fonts are extractable via /CharProcs even though pymupdf reports
        # ext='n/a' (there's no TrueType/CFF binary to dump). Keep those.
        if (only_fixable
                and ext_by_xref.get(x, 'n/a') == 'n/a'
                and not info_by_xref[x].is_type3):
            continue
        out.append(info_by_xref[x])
    return out


def _build_pil_font_for_gid_render(
        font_bytes: bytes,
        needed_gids: Optional[Set[int]] = None,
) -> Optional[Tuple[ImageFont.FreeTypeFont, Dict[int, int]]]:
    """Expose the wanted GIDs at Private-Use codepoints so PIL can render them.

    Returns `(pil_font, {gid: codepoint})`, or None if the font will not build.
    Render a glyph with `chr(code_by_gid[gid])`.

    `needed_gids` restricts the patch to the glyphs actually asked for, and is
    not an optimisation -- it is what makes large fonts work at all. The BMP
    Private Use Area is U+E000..U+F8FF, 6 400 codes, and a format-4 cmap
    subtable is 16-bit by definition. Mapping EVERY gid to `_PUA_BASE + gid`
    therefore overflows on any font with more than ~6 400 glyphs: fontTools
    refuses to compile the subtable, this function returned None, and
    `_build_font_mapping` then produced NO MAPPING AT ALL for that font --
    silently, since a missing repair is indistinguishable from a font that
    needed none.

    That is not a hypothetical size. Arial Unicode has 50 377 glyphs (codes to
    U+1A4C9); `datasheets/mcc/MCAC100N08Y-TP.pdf` embeds MicrosoftYaHei at
    30 133 and SegoeUISymbol at 9 209, and both were being skipped entirely.
    A page's used-CID set is a few hundred at most, so packing only those into
    the PUA keeps every font in range regardless of how large it is.
    """
    try:
        tt = TTFont(io.BytesIO(font_bytes))
    except Exception:
        return None
    glyph_order = tt.getGlyphOrder()

    wanted = [gid for gid in
              (sorted(needed_gids) if needed_gids is not None
               else range(len(glyph_order)))
              if 0 <= gid < len(glyph_order) and glyph_order[gid] != '.notdef']
    if not wanted:
        return None
    if len(wanted) > _PUA_SIZE:
        # More glyphs wanted than the PUA can hold. Truncating would render the
        # tail as whatever the leftover codes happen to hit, which is worse than
        # rendering nothing: the caller can tell None from a wrong bitmap.
        warnings.warn('fix_encoding: %d glyphs exceed the %d-codepoint PUA; '
                      'font skipped' % (len(wanted), _PUA_SIZE))
        return None

    code_by_gid: Dict[int, int] = {
        gid: _PUA_BASE + i for i, gid in enumerate(wanted)}
    new_map: Dict[int, str] = {
        code: glyph_order[gid] for gid, code in code_by_gid.items()}
    if 'cmap' in tt:
        cmap_t = tt['cmap']
    else:
        from fontTools.ttLib import newTable
        cmap_t = newTable('cmap')
        cmap_t.tableVersion = 0
        cmap_t.tables = []
        tt['cmap'] = cmap_t
    NewSub = CmapSubtable.getSubtableClass(4)
    new = NewSub(4)
    new.platformID = 3
    new.platEncID = 1
    new.format = 4
    new.length = 0
    new.language = 0
    new.cmap = new_map
    cmap_t.tables = [t for t in cmap_t.tables if t.format != 4]
    cmap_t.tables.append(new)
    buf = io.BytesIO()
    try:
        tt.save(buf)
    except Exception:
        return None
    try:
        return ImageFont.truetype(io.BytesIO(buf.getvalue()), _GLYPH_SIZE), code_by_gid
    except Exception:
        return None


# ----- Type3 rendering -------------------------------------------------

_BRACKET_NUM = r'-?\d+(?:\.\d+)?'


def _parse_array(obj_str: str, key: str) -> Optional[List[float]]:
    """Pull the array following `/key` out of a PDF dict-string. Returns a list
    of floats, or None if not found."""
    m = re.search(re.escape(key) + r'\s*\[\s*((?:' + _BRACKET_NUM + r'\s*){2,})\]', obj_str)
    if not m:
        return None
    return [float(x) for x in re.findall(_BRACKET_NUM, m.group(1))]


@dataclass
class _Type3Resources:
    """Everything we need to render any glyph of a single Type3 font."""
    font_bbox: Tuple[float, float, float, float]
    font_matrix: Tuple[float, float, float, float, float, float]
    # Maps a code-point used in the content stream to the charproc stream xref
    # holding that glyph's PDF drawing operators.
    code_to_charproc_xref: Dict[int, int]


def _gather_type3_resources(doc: pymupdf.Document, font_xref: int) -> Optional[_Type3Resources]:
    """Parse a Type3 font dict to find its FontBBox, FontMatrix, and the
    code→charproc-xref mapping (via /Encoding /Differences).
    """
    obj = doc.xref_object(font_xref)
    bbox = _parse_array(obj, '/FontBBox')
    matrix = _parse_array(obj, '/FontMatrix')
    if not bbox or len(bbox) != 4 or not matrix or len(matrix) != 6:
        return None

    m_cp = re.search(r'/CharProcs\s+(\d+)\s+0\s+R', obj)
    if not m_cp:
        return None
    cp_obj = doc.xref_object(int(m_cp.group(1)))
    name_to_xref = {n: int(x) for n, x in re.findall(r'/(\S+?)\s+(\d+)\s+0\s+R', cp_obj)}

    # Build code -> glyph name from /Encoding. May be a /Differences dict or
    # a name like /WinAnsiEncoding (rare for Type3).
    m_enc = re.search(r'/Encoding\s+(\d+)\s+0\s+R', obj)
    code_to_name: Dict[int, str] = {}
    if m_enc:
        enc_obj = doc.xref_object(int(m_enc.group(1)))
        m_diff = re.search(r'/Differences\s*\[(.*?)\]', enc_obj, re.DOTALL)
        if m_diff:
            tokens = re.findall(r'(\d+)|/(\S+)', m_diff.group(1))
            cur_code: Optional[int] = None
            for n, name in tokens:
                if n:
                    cur_code = int(n)
                elif cur_code is not None and name:
                    code_to_name[cur_code] = name
                    cur_code += 1

    code_to_xref: Dict[int, int] = {
        code: name_to_xref[gname]
        for code, gname in code_to_name.items()
        if gname in name_to_xref
    }
    if not code_to_xref:
        return None

    return _Type3Resources(
        font_bbox=tuple(bbox),
        font_matrix=tuple(matrix),
        code_to_charproc_xref=code_to_xref,
    )


def _render_type3_glyph(
        src_doc: pymupdf.Document,
        charproc_xref: int,
        res: _Type3Resources,
        size: int = _GLYPH_SIZE,
) -> Optional[np.ndarray]:
    """Render one Type3 glyph to a baseline-anchored normalized inked array.

    Builds a one-page temporary PDF whose content stream is the charproc's body
    under a CTM that maps glyph space into a known pixel rectangle, then
    rasterizes via pymupdf.
    """
    charproc = src_doc.xref_stream(charproc_xref)
    if not charproc:
        return None
    # Strip the leading d0/d1 operator — only legal inside a Type3 char context.
    nl = charproc.find(b'\n')
    body = charproc[nl + 1:] if nl > 0 else charproc

    a, _b, _c, d, _e, _f = res.font_matrix
    # We render at a 2× supersample (Matrix(2,2)). We want one em of glyph
    # height to come out to roughly `size` pixmap pixels, so that the
    # baseline-window logic in `_normalize_glyph_bitmap` (which is sized in
    # multiples of `size`) lines up with real ascenders and descenders.
    # em = 1 / abs(d) glyph units (FontMatrix maps glyph units → text units,
    # 1 text unit = 1 em). So px_per_glyph_unit = size * abs(d) / 2.
    matrix_scale = 2
    px_per_glyph_unit = max(abs(d) * size / matrix_scale, 0.5)

    llx, lly, urx, ury = res.font_bbox
    # Page large enough to contain the FontBBox, plus a small margin.
    pad = 4
    page_w = max(8, int(round((urx - llx) * px_per_glyph_unit)) + pad * 2)
    page_h = max(8, int(round((ury - lly) * px_per_glyph_unit)) + pad * 2)

    s = px_per_glyph_unit
    tx = -llx * s + pad
    ty = -lly * s + pad
    setup = f'q {s} 0 0 {s} {tx} {ty} cm\n'.encode('ascii')
    contents = setup + body + b'\nQ\n'

    tmp = pymupdf.open()
    try:
        page = tmp.new_page(width=page_w, height=page_h)
        new_xref = tmp.get_new_xref()
        tmp.update_object(new_xref, '<<>>')
        tmp.update_stream(new_xref, contents, new=True)
        page_obj = tmp.xref_object(page.xref)
        if '/Contents' in page_obj:
            page_obj = re.sub(r'/Contents\s+\d+\s+0\s+R',
                              f'/Contents {new_xref} 0 R', page_obj)
            page_obj = re.sub(r'/Contents\s*\[[^\]]*\]',
                              f'/Contents {new_xref} 0 R', page_obj)
        else:
            page_obj = page_obj.rstrip()
            if page_obj.endswith('>>'):
                page_obj = page_obj[:-2].rstrip() + f' /Contents {new_xref} 0 R\n>>'
        tmp.update_object(page.xref, page_obj)

        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(matrix_scale, matrix_scale),
            colorspace=pymupdf.csGRAY,
        )
        img = Image.frombytes('L', (pix.width, pix.height), pix.samples)
    finally:
        tmp.close()

    # PDF coords have origin at bottom-left; the pixmap is top-down. Glyph y=0
    # in glyph space maps to PDF y=ty; that's pixmap_y = h - ty * matrix_scale.
    baseline_y = img.height - int(round(ty * matrix_scale))
    return _normalize_glyph_bitmap(img, baseline_y, size)


# ----- TrueType/CFF font handling --------------------------------------

def _cid_to_gid_lookup(font_bytes: bytes, is_type0: bool) -> Callable[[int], Optional[int]]:
    """Given a CID/byte used in the PDF content stream, return the GID inside the font.

    - Type0 with Identity-H + identity CIDToGIDMap: CID == GID.
    - Simple TrueType: CID → font's internal cmap → glyph name → GID.
    """
    if is_type0:
        return lambda cid: cid
    try:
        tt = TTFont(io.BytesIO(font_bytes))
    except Exception:
        return lambda _: None
    glyph_order = tt.getGlyphOrder()
    name_to_gid = {n: i for i, n in enumerate(glyph_order)}
    sub = next((t for t in tt['cmap'].tables if t.format == 0), None)
    if sub is None and tt['cmap'].tables:
        sub = tt['cmap'].tables[0]
    if sub is None:
        return lambda _: None
    cmap = dict(sub.cmap)

    def lookup(cid: int) -> Optional[int]:
        gname = cmap.get(cid)
        return name_to_gid.get(gname) if gname else None

    return lookup


def _embedded_advances(font_bytes: bytes, cid_to_gid: Callable[[int], Optional[int]],
                       cids: Set[int]) -> Dict[int, float]:
    """cid -> advance width in 1000ths of an em, from the embedded font's hmtx.

    Read from the font binary rather than measured off the page: the on-page
    spacing in `_actual_advances` is a per-occurrence Tm delta that includes
    tracking and kerning, and it is absent for any CID the regex did not catch
    (it came back NaN for every glyph of the display font that produced the
    "OμtiMOS" mis-resolution). hmtx is the designed metric, present for every
    glyph, and independent of how the text happens to be laid out.

    CIDs whose advance cannot be read are OMITTED, never defaulted -- a
    missing key means "no width evidence" and callers abstain on it.
    """
    try:
        tt = TTFont(io.BytesIO(font_bytes), fontNumber=0, lazy=True)
        upm = tt['head'].unitsPerEm or 1000
        hmtx = tt['hmtx']
        order = tt.getGlyphOrder()
    except Exception:
        return {}
    out: Dict[int, float] = {}
    for cid in cids:
        gid = cid_to_gid(cid)
        if gid is None or gid <= 0 or gid >= len(order):
            continue
        try:
            out[cid] = hmtx[order[gid]][0] * 1000.0 / upm
        except Exception:
            continue
    return out


# ----- ToUnicode CMap ---------------------------------------------------

def _build_to_unicode_cmap(mapping: Dict[int, str], two_byte: bool) -> bytes:
    width = 4 if two_byte else 2
    lo = '0' * width
    hi = 'F' * width
    lines: List[str] = [
        '/CIDInit /ProcSet findresource begin',
        '12 dict begin',
        'begincmap',
        '/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def',
        '/CMapName /Adobe-Identity-UCS def',
        '/CMapType 2 def',
        '1 begincodespacerange',
        f'<{lo}> <{hi}>',
        'endcodespacerange',
    ]
    items = sorted(mapping.items())
    for i in range(0, len(items), 100):
        batch = items[i:i + 100]
        lines.append(f'{len(batch)} beginbfchar')
        for code, target in batch:
            tgt = ''.join(f'{ord(c):04X}' for c in target)
            lines.append(f'<{code:0{width}X}> <{tgt}>')
        lines.append('endbfchar')
    lines += [
        'endcmap',
        'CMapName currentdict /CMap defineresource pop',
        'end',
        'end',
    ]
    return '\n'.join(lines).encode('ascii')


# Capture `/Fname size Tf` plus the very next `Tm <hex> Tj` triple. Used to
# learn, per CID, the actual on-page horizontal advance to the next character.
_TM_TJ_CID_RE = re.compile(
    rb'/(\w+)\s+(\S+)\s+Tf'
    rb'|(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+'
    rb'(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+Tm'
    rb'\s*<([0-9A-Fa-f\s]+)>\s*Tj',
    re.DOTALL,
)


def _actual_advances(doc: pymupdf.Document, font_xrefs: Set[int]
                     ) -> Dict[int, Dict[int, float]]:
    """For each font xref in `font_xrefs`, return {cid → max-observed advance
    in glyph units (1/1000 em)} based on `Tm <hex> Tj` triples in any page's
    content stream. Only consecutive triples on the same baseline with the
    same font size contribute. CIDs not seen as the first char of a triple
    don't appear in the output."""
    advances: Dict[int, Dict[int, List[float]]] = {}

    for pno in range(len(doc)):
        # Build name → (xref, is_type0) for this page's resource scope.
        names: Dict[str, Tuple[int, bool]] = {}
        for xref, _e, typ, _b, fname, _en in doc.get_page_fonts(pno):
            if xref in font_xrefs:
                names[fname] = (xref, typ == 'Type0')
        if not names:
            continue

        contents = doc[pno].read_contents()
        cur_xref: Optional[int] = None
        cur_size = 1.0
        is_t0 = False
        records: List[Tuple[int, float, float, float, int]] = []
        # records: (font_xref, font_size, tm_x, tm_y, first_cid)

        for m in _TM_TJ_CID_RE.finditer(contents):
            if m.group(1):
                name = m.group(1).decode('ascii', errors='ignore')
                if name in names:
                    cur_xref, is_t0 = names[name]
                    try:
                        cur_size = float(m.group(2))
                    except (ValueError, TypeError):
                        cur_size = 1.0
                else:
                    cur_xref = None
                continue
            if cur_xref is None:
                continue
            try:
                tm_x = float(m.group(7))
                tm_y = float(m.group(8))
            except ValueError:
                continue
            hex_str = bytes(c for c in m.group(9)
                            if c not in b' \r\n\t').decode('ascii', 'ignore')
            step = 4 if is_t0 else 2
            if len(hex_str) < step:
                continue
            try:
                cid = int(hex_str[:step], 16)
            except ValueError:
                continue
            records.append((cur_xref, cur_size, tm_x, tm_y, cid))

        # Sort per (font, descending y, ascending x) and pair consecutive
        # records on the same line + same font + same size.
        records.sort(key=lambda r: (r[0], -r[3], r[2]))
        for i in range(len(records) - 1):
            cur, nxt = records[i], records[i + 1]
            if cur[0] != nxt[0] or cur[1] != nxt[1]:
                continue
            if abs(cur[3] - nxt[3]) > 0.5:
                continue  # different baseline
            dx = nxt[2] - cur[2]
            if dx <= 0:
                continue  # reverse positioning — ignore
            units = dx * 1000.0 / cur[1]
            advances.setdefault(cur[0], {}).setdefault(cur[4], []).append(units)

    # Use the MEDIAN advance per CID, not max. Max picks up cross-paragraph
    # and end-of-line jumps (20000+ glyph units), and using those as the
    # declared width causes extractors to overlap adjacent chars and wrap
    # mid-word. The median is the typical intra-word advance to the next
    # character — exactly what `/Widths` is meant to declare.
    def _median(xs: List[float]) -> float:
        s = sorted(xs)
        return s[len(s) // 2]

    return {xref: {cid: _median(advs) for cid, advs in cid_advs.items()}
            for xref, cid_advs in advances.items()}


# A measured advance may legitimately differ from the designed one through
# tracking and kerning -- a few percent, tens of percent for loose display
# setting. A factor of two is not a glyph advance any more.
_MAX_MEASURED_WIDTH_RATIO = 2.0


def _plausible_measured_widths(doc: pymupdf.Document, fi: _FontInfo,
                               measured: Dict[int, float]) -> Dict[int, float]:
    """Keep only measured advances the font's own `hmtx` corroborates.

    `_actual_advances` reads the gap between consecutive `Tm` operators, which
    equals the advance only when the glyphs are set as a run. Where a producer
    positions each glyph independently, that gap is a jump to the next column
    or line instead: in HY0910D.pdf the median measured advance is 54x the
    glyph's designed width and the worst is 832x, and declaring those as `/W`
    made every extractor split words apart ("H Y0 9 1", "P o w e r") -- text
    that came out correct before the override touched it. On a normally-set
    file (BSC190N15NS3_G.pdf) the same measurement lands at 1.01x, so the
    measurement is not wrong in general, only unguarded.

    `hmtx` is the authority here and the measurement is a proxy for it, so
    where they disagree the proxy loses. A CID the font has no metric for is
    dropped rather than trusted unchecked -- including every CID of a font
    whose binary will not parse at all, which is why this returns {} in that
    case instead of the measurements it could not check.
    """
    if not measured or fi.is_type3:
        return {}
    try:
        _basefont, _ext, _typ, font_bytes = doc.extract_font(fi.xref)
    except Exception:
        return {}
    if not font_bytes:
        return {}
    designed = _embedded_advances(font_bytes,
                                  _cid_to_gid_lookup(font_bytes, fi.is_type0),
                                  set(measured))
    out = {}
    for cid, w in measured.items():
        d = designed.get(cid)
        if not d or d <= 0 or w <= 0:
            continue
        if 1 / _MAX_MEASURED_WIDTH_RATIO <= w / d <= _MAX_MEASURED_WIDTH_RATIO:
            out[cid] = w
    return out


def _has_pdf_array(obj: str, key: str) -> bool:
    """Whether `/key` in this dict-string is followed by an array at all.

    Exists so a caller can tell `_replace_pdf_array`'s two None outcomes apart. They mean
    opposite things: 'the key is absent, add it' versus 'the key is there but malformed,
    do not touch it'. Conflating them made the Type0 branch append a SECOND /W next to the
    broken one, and the PDF spec does not define which of two duplicate keys wins -- mupdf
    takes the last, so the intended widths happened to survive here, but a first-wins
    consumer would keep the broken table with nothing reported.
    """
    return bool(re.search(r'/' + re.escape(key) + r'\s*\[', obj))


def _replace_pdf_array(obj: str, key: str, new_array: str) -> Optional[str]:
    """Replace the array following `/key` in a PDF dict-string, or None if
    `/key` is not followed by an array.

    Scans with a bracket counter instead of matching `\\[[^\\]]*\\]`: a CIDFont
    `/W` array nests, e.g. `/W [ 9 [ 722 ] 11 12 333 16 [ 333 278 ] ]`, and the
    lazy form terminates at the first INNER `]`. That left the tail
    (`11 12 333 …`) stranded at dict level, and mupdf rejected the object with
    'invalid key in dict' -- aborting the entire repair, /ToUnicode included,
    for every Type0 font whose widths happen to be written in ranged form.
    """
    m = re.search(r'/' + re.escape(key) + r'\s*\[', obj)
    if not m:
        return None
    depth = 0
    for i in range(m.end() - 1, len(obj)):
        c = obj[i]
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                return obj[:m.start()] + '/' + key + ' ' + new_array + obj[i + 1:]
    return None  # unbalanced — leave the object alone rather than corrupt it


def _override_widths(doc: pymupdf.Document, font_xref: int,
                     cid_to_width: Dict[int, float], is_type0: bool) -> None:
    """Replace the font's declared widths with the measured advances.

    Type0: rewrite the descendant CIDFont's `/W` array.
    Simple: rewrite the font dict's `/Widths` array, keeping `/FirstChar` and
    `/LastChar` intact.
    """
    if not cid_to_width:
        return

    if is_type0:
        obj = doc.xref_object(font_xref)
        m = re.search(r'/DescendantFonts\s*\[\s*(\d+)\s+0\s+R', obj)
        if not m:
            return
        desc_xref = int(m.group(1))
        items = sorted(cid_to_width.items())
        # Sparse [cid [w]] form, one entry per CID. Simple and exact.
        w_str = '[ ' + ' '.join(f'{cid} [{int(round(w))}]'
                                for cid, w in items) + ' ]'
        desc_obj = doc.xref_object(desc_xref)
        new_desc = _replace_pdf_array(desc_obj, 'W', w_str)
        if new_desc is None:
            if _has_pdf_array(desc_obj, 'W'):
                # Present but unbalanced. Appending here would leave the broken array in
                # place AND add a second /W, so leave the object exactly as it is; the
                # /ToUnicode repair is already applied and is the part that matters.
                warnings.warn('fix_encoding: malformed /W array on xref %d; '
                              'leaving widths unchanged' % desc_xref)
                return
            new_desc = desc_obj.rstrip()
            if new_desc.endswith('>>'):
                new_desc = new_desc[:-2].rstrip() + f' /W {w_str}\n>>'
            else:
                return
        doc.update_object(desc_xref, new_desc)
        return

    # Simple font: /Widths array indexed from /FirstChar.
    obj = doc.xref_object(font_xref)
    m_fc = re.search(r'/FirstChar\s+(\d+)', obj)
    m_w = re.search(r'/Widths\s*\[([^\]]*)\]', obj)
    if not m_fc or not m_w:
        return
    first = int(m_fc.group(1))
    try:
        widths = [int(round(float(n))) for n in m_w.group(1).split()]
    except ValueError:
        return
    for cid, w in cid_to_width.items():
        idx = cid - first
        if 0 <= idx < len(widths):
            widths[idx] = int(round(w))
    new_w_str = '[ ' + ' '.join(str(w) for w in widths) + ' ]'
    new_obj = _replace_pdf_array(obj, 'Widths', new_w_str)
    if new_obj is not None:
        doc.update_object(font_xref, new_obj)


def _set_font_to_unicode(doc: pymupdf.Document, font_xref: int, cmap_bytes: bytes) -> None:
    """Attach `cmap_bytes` as the font's /ToUnicode stream, replacing any prior one."""
    new_xref = doc.get_new_xref()
    doc.update_object(new_xref, '<<>>')
    doc.update_stream(new_xref, cmap_bytes, new=True)
    obj = doc.xref_object(font_xref).rstrip()
    obj = re.sub(r'/ToUnicode\s+\d+\s+0\s+R', '', obj)
    if obj.endswith('>>'):
        obj = obj[:-2].rstrip() + f'\n  /ToUnicode {new_xref} 0 R\n>>'
    doc.update_object(font_xref, obj)



# ----- public API -------------------------------------------------------

def has_custom_font_encoding(pdf_path: str) -> bool:
    """True if the PDF contains any font with a custom / scrambled encoding,
    whether or not it is fixable by this module (Type3 fonts are detected but
    can't currently be repaired)."""
    doc = pymupdf.open(pdf_path)
    try:
        return bool(_scan_fonts(doc, only_fixable=False))
    finally:
        doc.close()


def _build_font_mapping(
        doc: pymupdf.Document,
        fi: _FontInfo,
        ref_items: List[Tuple[str, List[np.ndarray]]],
        min_similarity: float,
        use_exact: bool = True,
        use_lm: bool = True,
        use_fontid: bool = True,
        fontid_exclude: Optional[Set[str]] = None,
) -> Optional[Dict[int, str]]:
    """For a single suspect font, render each used CID and pick the best
    matching reference char. Returns {cid: unicode_str} or None on failure.
    Unrenderable / sub-threshold CIDs map to space.
    """
    font_bytes: Optional[bytes] = None
    cid_to_gid: Optional[Callable[[int], Optional[int]]] = None

    if fi.is_type3:
        res = _gather_type3_resources(doc, fi.xref)
        if res is None:
            return None

        def render(cid: int) -> Optional[np.ndarray]:
            xr = res.code_to_charproc_xref.get(cid)
            return _render_type3_glyph(doc, xr, res) if xr else None
    else:
        try:
            _basefont, _ext, _typ, font_bytes = doc.extract_font(fi.xref)
        except Exception:
            return None
        if not font_bytes:
            return None
        cid_to_gid = _cid_to_gid_lookup(font_bytes, fi.is_type0)
        # Only the glyphs this page uses are patched into the PUA; see
        # _build_pil_font_for_gid_render on why mapping all of them silently
        # dropped every font over 6 400 glyphs.
        wanted = set()
        for c in fi.used_codes:
            g = cid_to_gid(c)
            if g:
                wanted.add(g)
        built = _build_pil_font_for_gid_render(font_bytes, wanted)
        if built is None:
            return None
        pil_font, code_by_gid = built

        def render(cid: int) -> Optional[np.ndarray]:
            gid = cid_to_gid(cid)
            if gid is None or gid == 0:
                return None
            code = code_by_gid.get(gid)
            if code is None:
                return None
            return _render_glyph(pil_font, code)

    # Exact identification first, where the font permits it. A full-face embed
    # of an installed face is a lookup, not a similarity judgement, and pixels
    # can only make it worse: see dslib/pdf/glyph_exact.py. Returns None -- no
    # opinion -- for subsetted or unknown faces, which then go through vision
    # exactly as before.
    exact: Dict[int, str] = {}
    if use_exact and font_bytes and cid_to_gid is not None:
        try:
            from dslib.pdf.glyph_exact import exact_mapping
            em = exact_mapping(font_bytes, cid_to_gid, set(fi.used_codes))
        except Exception as e:
            warnings.warn('fix_encoding: exact match failed for font %s: %s'
                          % (fi.short_name, e))
            em = None
        if em is not None:
            exact = em.mapping

    # Render once, up front. The bitmaps are needed twice -- to identify the
    # face and then to match against it -- and rasterising is the expensive part.
    arrays: Dict[int, np.ndarray] = {}
    for cid in sorted(set(fi.used_codes) - set(exact)):
        a = render(cid)
        if a is not None:
            arrays[cid] = a

    # Type3 glyphs are drawing procedures with no hmtx, so width abstains for
    # them and topology alone does the arbitration.
    emb_adv = (_embedded_advances(font_bytes, cid_to_gid, set(arrays))
               if font_bytes and cid_to_gid else {})

    # Identify the face and, if it explains these shapes more decisively than
    # the fixed reference does, compare against it instead. Abstains to
    # `ref_items` otherwise -- it can only ever swap in a reference that scored
    # BETTER on this font's own glyphs, so a wrong guess cannot degrade the
    # match. See dslib/pdf/glyph_fontid.py.
    ref_advs: Optional[Dict[str, List[float]]] = None
    if use_fontid and arrays:
        try:
            from dslib.pdf.glyph_fontid import detect_face
            face = detect_face(arrays, emb_adv, ref_items,
                               exclude=fontid_exclude)
        except Exception as e:
            warnings.warn('fix_encoding: face detection failed for %s: %s'
                          % (fi.short_name, e))
            face = None
        if face is not None:
            ref_items = face.ref_items
            # The identified face's OWN metrics also replace the reference
            # advances. That matters more than the bitmaps for the width
            # tie-break: against the true face the widths agree exactly rather
            # than up to a fitted scale factor.
            ref_advs = face.advances

    # Rank every candidate per CID, keeping the runners-up: a near-tie is not
    # visible from the winner alone, and the tie-break needs the rivals.
    #
    # References are prepared ONCE for the whole font rather than per glyph:
    # `_prepare` is the expensive half of the comparison (a blur and a
    # normalisation) and the reference set does not change between glyphs.
    prepared_refs = _prepare_items(ref_items)
    ranked: Dict[int, List[Tuple[float, str]]] = {}
    holes: Dict[int, int] = {}
    for cid, glyph_arr in arrays.items():
        pg = _prepare(glyph_arr)
        scores = sorted(
            ((max(_similarity_prepared(pg, v) for v in variants), ref_ch)
             for ref_ch, variants in prepared_refs),
            reverse=True)
        if not scores:
            continue
        ranked[cid] = scores[:_TIE_CANDIDATES]
        try:
            holes[cid] = _hole_count(glyph_arr)
        except Exception:
            pass  # no topology evidence for this CID; width/vision still apply

    scale = _calibrate_width_scale(ranked, emb_adv, ref_advs)

    mapping: Dict[int, str] = {}
    for cid in sorted(fi.used_codes):
        if cid in exact:
            mapping[cid] = exact[cid]
            continue
        scores = ranked.get(cid)
        if not scores:
            mapping[cid] = ' '
            continue
        best_score, best_ch = scores[0]
        if best_score < min_similarity:
            mapping[cid] = ' '
            continue
        mapping[cid] = _break_tie(scores, holes.get(cid),
                                  emb_adv.get(cid), scale,
                                  ref_items, ref_advs)

    if use_lm and mapping:
        # Document-level arbitration, last: it needs the per-CID shortlists AND
        # the mapping vision settled on, and it may only reorder candidates
        # vision already ranked. `exact` CIDs are passed as pinned -- an outline
        # identity is not something a language model gets to overrule.
        try:
            from dslib.pdf.glyph_lm import lm_refine
            mapping = lm_refine(doc, fi, mapping, ranked, pinned=set(exact))
        except Exception as e:
            warnings.warn('fix_encoding: lm refine failed for font %s: %s'
                          % (fi.short_name, e))
    return mapping or None


def _calibrate_width_scale(ranked: Dict[int, List[Tuple[float, str]]],
                           emb_adv: Dict[int, float],
                           ref_adv: Optional[Dict[str, List[float]]] = None
                           ) -> Optional[float]:
    """Ratio between this font's advance widths and the reference font's.

    Subset display faces are routinely 5-15% wider or narrower than the
    reference, which is more than the gap between some confusable pairs, so
    raw widths cannot be compared directly. The scale is fitted only on glyphs
    vision resolved decisively (margin >= `_CONFIDENT_MARGIN`) -- an ambiguous
    glyph must not vote on the scale that will then arbitrate it.

    Returns None when fewer than `_MIN_WIDTH_SAMPLES` glyphs qualify. That is
    deliberately not a fallback of 1.0: assuming reference metrics for an
    unmeasured font would decide 3%-separated pairs on an assumption, and the
    caller abstains instead.
    """
    # `ref_adv` is the IDENTIFIED face's metrics when face detection accepted
    # one, and the fixed reference's otherwise. Against the true face the fitted
    # ratio comes out at ~1.0 and the width tie-break stops depending on a
    # calibration at all.
    ref_adv = ref_adv if ref_adv is not None else _reference_advances()
    ratios: List[float] = []
    for cid, scores in ranked.items():
        if len(scores) < 2 or scores[0][0] - scores[1][0] < _CONFIDENT_MARGIN:
            continue
        w = emb_adv.get(cid)
        refs = ref_adv.get(scores[0][1])
        if not w or w <= 0 or not refs:
            continue
        # Nearest weight variant: bold and regular differ enough (Arial 'I' is
        # 278 vs 333) to bias the fit if the wrong one is assumed.
        ratios.append(min(refs, key=lambda r: abs(r - w)) / w)
    if len(ratios) < _MIN_WIDTH_SAMPLES:
        return None
    return float(np.median(ratios))


def _break_tie(scores: List[Tuple[float, str]], hole_count: Optional[int],
               emb_width: Optional[float], scale: Optional[float],
               ref_items: Optional[Sequence[Tuple[str, List[np.ndarray]]]] = None,
               ref_adv: Optional[Dict[str, List[float]]] = None) -> str:
    """Choose among visual candidates that are within `_TIE_MARGIN` of the top.

    Returns the visual winner unchanged whenever the extra features are absent
    or do not clearly disagree with it. Only candidates vision already placed
    in the tie band can win, so a feature can reorder the shortlist but never
    introduce a character that did not look like the glyph.
    """
    best_score, best_ch = scores[0]
    tied = [(s, c) for s, c in scores if best_score - s <= _TIE_MARGIN]
    if len(tied) < 2:
        return best_ch

    # --- topology first: discrete, and invariant to weight and width.
    if hole_count is not None:
        ref_glyphs = (dict(ref_items) if ref_items is not None
                      else _reference_glyphs())
        agreeing = []
        for s, c in tied:
            variants = ref_glyphs.get(c) or []
            counts = {_hole_count(v) for v in variants}
            # ANY weight matching is enough. Arial's '6' encloses two regions
            # regular and one bold, so requiring every variant to agree would
            # discard the feature on exactly the glyphs it is meant to judge.
            if hole_count in counts:
                agreeing.append((s, c))
        if agreeing and len(agreeing) < len(tied):
            tied = agreeing
            if tied[0][1] != best_ch:
                best_score, best_ch = tied[0]

    if len(tied) < 2:
        return best_ch

    # --- then width, for same-topology pairs such as l/I and O/Q.
    if scale is None or not emb_width or emb_width <= 0:
        return best_ch
    ref_adv = ref_adv if ref_adv is not None else _reference_advances()
    scaled = emb_width * scale

    def rel_err(ch: str) -> Optional[float]:
        refs = ref_adv.get(ch)
        if not refs:
            return None
        return min(abs(r - scaled) / r for r in refs)

    incumbent = rel_err(best_ch)
    if incumbent is None:
        return best_ch
    challengers = [(e, c) for _s, c in tied
                   if c != best_ch and (e := rel_err(c)) is not None]
    if not challengers:
        return best_ch
    err, ch = min(challengers)
    # Require a clear margin, not merely a smaller number: two candidates a
    # few percent apart are within the calibration's own uncertainty, and
    # flipping on that would trade one coin-toss for another.
    return ch if err * _WIDTH_EDGE < incumbent else best_ch


def fix_pdf_font_encoding(
        pdf_path: str,
        out_path: Optional[str] = None,
        min_similarity: float = 0.30,
        raise_if_no_bad_fonts=False,
) -> str:
    """Detect custom font encodings in `pdf_path` and repair them.

    - Inject a fresh `/ToUnicode` CMap for
      each suspect font. The page renders pixel-identically; only text
      extraction tools see different unicode. Punctuation rendering is
      preserved.

    Returns the path to the saved PDF. If no problematic font is found, the
    original `pdf_path` is returned unchanged and no new file is written.
    """
    doc = pymupdf.open(pdf_path)
    bad_fonts = _scan_fonts(doc)
    if not bad_fonts:
        doc.close()
        if raise_if_no_bad_fonts:
            raise ValueError('no bad fonts nothing to fix')
        return pdf_path

    refs = _reference_glyphs()
    ref_items = list(refs.items())

    mappings: Dict[int, Tuple[_FontInfo, Dict[int, str]]] = {}
    for fi in bad_fonts:
        m = _build_font_mapping(doc, fi, ref_items, min_similarity)
        if m:
            mappings[fi.xref] = (fi, m)

    if not mappings:
        doc.close()
        return pdf_path

    fixed_any = False
    # Measure each CID's actual on-page advance. Overriding the font's
    # widths to match these prevents PDF viewers (Preview / Adobe /
    # Chrome) from inserting a space at every per-char Tm gap when you
    # copy text out.
    widths = _actual_advances(doc, set(mappings))
    for xref, (fi, m) in mappings.items():
        _set_font_to_unicode(
            doc, xref, _build_to_unicode_cmap(m, two_byte=fi.is_type0))
        trusted = _plausible_measured_widths(doc, fi, widths.get(xref, {}))
        if trusted:
            # Width override is a copy-and-paste nicety; the /ToUnicode above is
            # the actual repair and is already applied. Letting a malformed
            # width object abort the run threw away a working text fix for
            # every font in the file, so contain it -- but say so, because a
            # silently skipped override is a real (if cosmetic) degradation.
            try:
                _override_widths(doc, xref, trusted, fi.is_type0)
            except Exception as e:
                warnings.warn('fix_encoding: width override failed for font '
                              'xref %d (%s): %s' % (xref, fi.short_name, e))
        fixed_any = True

    if not fixed_any:
        doc.close()
        return pdf_path

    if out_path is None:
        p = pathlib.Path(pdf_path)
        out_path = str(p.with_name(p.stem + '.unicoded' + p.suffix))
    doc.save(out_path, deflate=True)
    doc.close()
    return out_path


# ----- CLI --------------------------------------------------------------

def _cli(argv: Optional[List[str]] = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog='fix_encoding',
        description='Repair PDFs with custom / scrambled font encoding by '
                    'visually matching each embedded glyph against a standard '
                    'reference font and injecting a /ToUnicode CMap.',
    )
    parser.add_argument('pdf', nargs='+', help='input PDF file(s)')
    parser.add_argument('-o', '--output',
                        help='output path (only valid with a single input PDF; '
                             'default: <input>.unicoded.pdf)')
    parser.add_argument('-c', '--check', action='store_true',
                        help='only report whether each PDF has custom encoding; '
                             'do not write anything. Exit code 0 if none of the '
                             'inputs have custom encoding, 1 if any do.')
    parser.add_argument('-t', '--threshold', type=float, default=0.30,
                        metavar='X',
                        help='minimum visual-similarity score required to '
                             'commit a glyph→unicode mapping (default: 0.30)')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='suppress per-file progress; only print output paths')
    args = parser.parse_args(argv)

    if args.output and len(args.pdf) != 1:
        parser.error('--output is only valid with exactly one input PDF')

    any_custom = False
    rc = 0
    for path in args.pdf:
        if not os.path.isfile(path):
            print(f'{path}: not found', file=sys.stderr)
            rc = 2
            continue
        try:
            has = has_custom_font_encoding(path)
        except Exception as e:
            print(f'{path}: detection error: {e}', file=sys.stderr)
            rc = 2
            continue

        if args.check:
            print(f'{path}\t{"custom" if has else "clean"}')
            if has:
                any_custom = True
            continue

        if not has:
            if not args.quiet:
                print(f'{path}: clean, nothing to do', file=sys.stderr)
            print(path)
            continue

        try:
            out = fix_pdf_font_encoding(
                path, out_path=args.output,
                min_similarity=args.threshold)
        except Exception as e:
            print(f'{path}: fix error: {e}', file=sys.stderr)
            rc = 2
            continue
        if not args.quiet:
            kind = 'fixed' if out != path else 'no fixable fonts'
            print(f'{path} -> {out}  ({kind})', file=sys.stderr)
        print(out)

    if args.check and any_custom:
        return 1
    return rc


if __name__ == '__main__':
    import sys

    sys.exit(_cli())
