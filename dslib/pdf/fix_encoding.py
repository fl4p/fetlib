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
   so x-height letters aren't confused with cap-height letters).
5. Synthesize a fresh ``/ToUnicode`` CMap and inject it into the font
   dictionary, replacing any existing one. The embedded glyph outlines are
   left alone so the page renders identically to before; downstream text
   extractors (pdfminer, pdftotext, pymupdf) now see proper unicode.

Public API:
    has_custom_font_encoding(pdf_path) -> bool
    fix_pdf_font_encoding(pdf_path, out_path=None) -> str  # path to saved PDF
"""

import io
import logging
import os
import pathlib
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple, Union

import numpy as np
import pymupdf
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from PIL import Image, ImageDraw, ImageFont

# fontTools emits noisy "'created' timestamp seems very low" warnings when
# loading subset embedded fonts whose head timestamps are stripped — silence them.
logging.getLogger('fontTools.ttLib.tables._h_e_a_d').setLevel(logging.ERROR)

_GLYPH_SIZE = 64
_PUA_BASE = 0xE000  # render glyphs through PUA codes mapped to their GID

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


def _find_reference_fonts() -> Tuple[Union[str, bytes], Union[str, bytes]]:
    """Locate a regular + bold sans-serif font on this system. Returns paths
    or in-memory font bytes — either form is accepted by PIL's
    `ImageFont.truetype`. Order of preference:

        1. The hardcoded `_REF_FONT_CANDIDATES` for fast, deterministic lookup.
        2. fontconfig (`fc-match`), if installed.
        3. Pillow's bundled DejaVu Sans (recent Pillow versions), as a last
           resort: regular is real, bold is the same regular font (some
           matching quality is lost but it works everywhere Pillow does).
    """
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
    """
    global _REF_CACHE
    if _REF_CACHE is not None:
        return _REF_CACHE
    reg_src, bold_src = _find_reference_fonts()
    def _load(src):
        return ImageFont.truetype(io.BytesIO(src) if isinstance(src, bytes) else src,
                                  _GLYPH_SIZE)
    fonts = [_load(reg_src), _load(bold_src)]
    # Skip duplicate when fallback returned the same source for both weights.
    if reg_src == bold_src:
        fonts = fonts[:1]
    refs: Dict[str, List[np.ndarray]] = {}
    for ch in _COMMON_GLYPHS:
        variants = []
        for f in fonts:
            arr = _render_glyph(f, ord(ch))
            if arr is not None:
                variants.append(arr)
        if variants:
            refs[ch] = variants
    _REF_CACHE = refs
    return refs


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two inked-pixel arrays. Range ~0..1."""
    denom = float(np.sqrt((a * a).sum() * (b * b).sum())) + 1e-6
    return float((a * b).sum() / denom)


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


def _font_has_suspect_encoding(doc: pymupdf.Document, xref: int, enc: str) -> bool:
    """A font is suspect (likely scrambled custom encoding) when either:
        - its Encoding entry is absent / a Differences dict (pymupdf reports `enc=''`)
          AND it has no /ToUnicode, OR
        - it has a /ToUnicode that's an identity mapping.
    """
    if not enc:
        obj = doc.xref_object(xref)
        if not re.search(r'/ToUnicode\s+\d+\s+0\s+R', obj):
            return True
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


def _build_pil_font_for_gid_render(font_bytes: bytes) -> Optional[ImageFont.FreeTypeFont]:
    """Patch the font's cmap to expose every GID at code `_PUA_BASE + gid`,
    then load it via PIL so `chr(_PUA_BASE + gid)` renders that glyph.
    """
    try:
        tt = TTFont(io.BytesIO(font_bytes))
    except Exception:
        return None
    glyph_order = tt.getGlyphOrder()
    new_map: Dict[int, str] = {
        _PUA_BASE + gid: gname for gid, gname in enumerate(glyph_order)
        if gname != '.notdef'
    }
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
        return ImageFont.truetype(io.BytesIO(buf.getvalue()), _GLYPH_SIZE)
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
        if re.search(r'/W\s*\[', desc_obj):
            new_desc = re.sub(r'/W\s*\[[^\]]*\]', f'/W {w_str}', desc_obj)
        else:
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
    new_obj = re.sub(r'/Widths\s*\[[^\]]*\]', f'/Widths {new_w_str}', obj)
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


# ----- content-stream rewrite (replace suspect font with Helvetica) -----

# WinAnsi reverse map: unicode codepoint → WinAnsi byte, for chars outside
# ASCII but inside WinAnsiEncoding's coverage.
_WINANSI_MAP: Dict[int, int] = {
    0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84, 0x2026: 0x85,
    0x2020: 0x86, 0x2021: 0x87, 0x02C6: 0x88, 0x2030: 0x89, 0x0160: 0x8A,
    0x2039: 0x8B, 0x0152: 0x8C, 0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92,
    0x201C: 0x93, 0x201D: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97,
    0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B, 0x0153: 0x9C,
    0x017E: 0x9E, 0x0178: 0x9F,
}

# Plain-text fallback for chars not representable in WinAnsi at all.
_WINANSI_FALLBACK: Dict[str, str] = {
    'Ω': 'Ohm', '≤': '<=', '≥': '>=', '≠': '!=', '≈': '~',
    '∞': 'inf', '℃': 'degC', '℉': 'degF',
}


def _encode_winansi(text: str) -> bytes:
    out = bytearray()
    for c in text:
        cp = ord(c)
        if cp < 0x80 or 0xA0 <= cp <= 0xFF:
            out.append(cp)
        elif cp in _WINANSI_MAP:
            out.append(_WINANSI_MAP[cp])
        elif c in _WINANSI_FALLBACK:
            out.extend(_WINANSI_FALLBACK[c].encode('ascii'))
        else:
            out.append(ord('?'))
    return bytes(out)


def _escape_pdf_literal(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b in (0x28, 0x29, 0x5C):  # ( ) backslash
            out.append(0x5C)
            out.append(b)
        elif b < 0x20 or b == 0x7F:
            out.extend(f'\\{b:03o}'.encode('ascii'))
        else:
            out.append(b)
    return bytes(out)


# Tokens we need to recognize in a content stream. The order matters: we want
# `Tf` to match before generic operators, hex-string + Tj before bare hex, etc.
# Groups: (Tf-name, Tf-size, hex-string Tj, literal-string Tj, array-string TJ).
_REWRITE_RE = re.compile(
    rb'/(\w+)\s+(\S+)\s+Tf'                  # /Name size Tf
    rb'|<([0-9A-Fa-f\s]*)>\s*Tj'              # <hex> Tj
    rb'|\(((?:\\.|[^\\)])*)\)\s*Tj'           # (literal) Tj
    rb'|\[(.*?)\]\s*TJ',                      # [array] TJ
    re.DOTALL,
)

# Inside a [...] TJ array, strings are either <hex> or (literal); ignore
# numeric kerning offsets since they're meaningless after our rewrite.
_ARRAY_STR_RE = re.compile(
    rb'<([0-9A-Fa-f\s]*)>|\(((?:\\.|[^\\)])*)\)', re.DOTALL)


def _decode_hex_cids(hex_bytes: bytes, two_byte: bool) -> List[int]:
    clean = bytes(c for c in hex_bytes if c not in b' \r\n\t').decode('ascii', 'ignore')
    step = 4 if two_byte else 2
    return [int(clean[i:i + step], 16)
            for i in range(0, len(clean) - step + 1, step)]


def _decode_literal_cids(lit: bytes) -> List[int]:
    out: List[int] = []
    i = 0
    while i < len(lit):
        b = lit[i]
        if b == 0x5C and i + 1 < len(lit):  # backslash escape
            nxt = lit[i + 1]
            if nxt in b'nrtbf()\\':
                out.append({b'n': 10, b'r': 13, b't': 9, b'b': 8, b'f': 12,
                            b'(': 40, b')': 41, b'\\': 92}[bytes([nxt])])
                i += 2
                continue
            if 0x30 <= nxt <= 0x37:
                j = i + 1
                while j < len(lit) and j < i + 4 and 0x30 <= lit[j] <= 0x37:
                    j += 1
                out.append(int(lit[i + 1:j], 8) & 0xFF)
                i = j
                continue
            i += 2
            continue
        out.append(b)
        i += 1
    return out


def _cids_to_text(cids: List[int], mapping: Dict[int, str]) -> str:
    return ''.join(mapping.get(c, ' ') for c in cids)


def _emit_text_show(text: str) -> bytes:
    """Re-emit decoded text as a PDF literal-string `Tj` operation."""
    return b'(' + _escape_pdf_literal(_encode_winansi(text)) + b') Tj'


_TJ_LIT_RE = re.compile(rb'\(((?:\\.|[^\\)])*)\)\s*Tj')
_TD_RE = re.compile(rb'(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+T[Dd]\b')
_BASELINE_BREAK_RE = re.compile(rb'\b(BT|ET|T\*|Tm)\b')


def _gap_breaks_baseline(gap: bytes) -> bool:
    """True if `gap` (the bytes between two consecutive `(text) Tj` operations)
    contains an operator that moves the text baseline. Conservative: any `Tm`
    or `BT`/`ET`/`T*` breaks the run; `Td`/`TD` breaks only if its dy is
    non-zero. State operators (Tc, Tw, Tz, Tr, Ts, TL, Tf, q, Q, …) are fine."""
    if _BASELINE_BREAK_RE.search(gap):
        return True
    for m in _TD_RE.finditer(gap):
        try:
            if abs(float(m.group(2))) > 1e-6:
                return True
        except ValueError:
            return True
    return False


def _collapse_text_runs(contents: bytes) -> bytes:
    """Merge consecutive `(literal) Tj` shows whose intervening operators don't
    move the text baseline. Drops the intermediate positioning operators —
    visual layout shifts, but the merged text extracts as one string per run."""
    matches = list(_TJ_LIT_RE.finditer(contents))
    if not matches:
        return contents

    out = bytearray()
    last_end = 0
    i = 0
    while i < len(matches):
        out.extend(contents[last_end:matches[i].start()])

        parts = [matches[i].group(1)]
        run_end = matches[i].end()
        j = i + 1
        while j < len(matches):
            if _gap_breaks_baseline(contents[run_end:matches[j].start()]):
                break
            parts.append(matches[j].group(1))
            run_end = matches[j].end()
            j += 1

        out.extend(b'(' + b''.join(parts) + b') Tj')
        last_end = run_end
        i = j

    out.extend(contents[last_end:])
    return bytes(out)


def _rewrite_content_stream(
    contents: bytes,
    suspect_by_name: Dict[str, Dict],
    helv_name: str,
) -> bytes:
    """Walk the stream. Replace each suspect-font `Tf` with a Helvetica one,
    and rewrite each subsequent text-show operator (`<hex> Tj`, `(literal) Tj`,
    `[…] TJ`) to a single `(decoded) Tj` carrying the visually-matched unicode.

    Positioning operators (`Tm`, `TD`, `Td`, …) are passed through untouched.
    Visual layout shifts (Helvetica metrics differ) but text extraction is
    perfect: copy-paste yields the right characters."""
    out = bytearray()
    pos = 0
    active: Optional[Dict] = None  # the {mapping, is_type0} dict of the active suspect font
    for m in _REWRITE_RE.finditer(contents):
        # Copy everything between our last emit and this match unchanged.
        out.extend(contents[pos:m.start()])
        pos = m.end()

        tf_name, tf_size, hex_s, lit_s, arr_s = m.groups()

        if tf_name is not None:
            name = tf_name.decode('ascii', 'ignore')
            size = tf_size.decode('ascii', 'ignore')
            if name in suspect_by_name:
                active = suspect_by_name[name]
                out.extend(f'/{helv_name} {size} Tf'.encode('ascii'))
            else:
                active = None
                out.extend(m.group(0))
            continue

        if active is None:
            out.extend(m.group(0))
            continue

        is_t0 = active['is_type0']
        mapping = active['mapping']
        cids: List[int] = []

        if hex_s is not None:
            cids = _decode_hex_cids(hex_s, is_t0)
        elif lit_s is not None:
            # Literal strings in a simple font are 1-byte codes; in a Type0
            # font they're (rare here) 2-byte big-endian sequences.
            raw = _decode_literal_cids(lit_s)
            if is_t0:
                cids = [(raw[i] << 8) | raw[i + 1]
                        for i in range(0, len(raw) - 1, 2)]
            else:
                cids = raw
        elif arr_s is not None:
            for am in _ARRAY_STR_RE.finditer(arr_s):
                h, l = am.groups()
                if h is not None:
                    cids.extend(_decode_hex_cids(h, is_t0))
                elif l is not None:
                    raw = _decode_literal_cids(l)
                    if is_t0:
                        cids.extend((raw[i] << 8) | raw[i + 1]
                                    for i in range(0, len(raw) - 1, 2))
                    else:
                        cids.extend(raw)

        out.extend(_emit_text_show(_cids_to_text(cids, mapping)))

    out.extend(contents[pos:])
    return bytes(out)


def _rewrite_pdf_streams(
    doc: pymupdf.Document,
    suspect_xref_info: Dict[int, Dict],
) -> bool:
    """For every page, swap suspect-font text for Helvetica + decoded unicode.

    Returns True if at least one page was modified.
    """
    changed = False
    for pno in range(len(doc)):
        page = doc[pno]
        page_suspects: Dict[str, Dict] = {}
        for xref, _ext, _typ, _bf, fname, _enc in doc.get_page_fonts(pno):
            if xref in suspect_xref_info:
                page_suspects[fname] = suspect_xref_info[xref]
        if not page_suspects:
            continue

        helv_xref = page.insert_font(fontname='helv')
        helv_name = None
        for xref, _e, _t, _b, name, _en in doc.get_page_fonts(pno):
            if xref == helv_xref:
                helv_name = name
                break
        if helv_name is None:
            continue

        contents = page.read_contents()
        new_contents = _rewrite_content_stream(contents, page_suspects, helv_name)
        new_contents = _collapse_text_runs(new_contents)
        if new_contents == contents:
            continue

        # Collapse the page's /Contents (which may be an array of streams)
        # into a single new stream. Pymupdf's update_stream replaces an
        # existing stream xref; for an array we create a fresh one and
        # repoint the page object.
        xrefs = page.get_contents()
        if len(xrefs) == 1:
            doc.update_stream(xrefs[0], new_contents)
        else:
            new_xref = doc.get_new_xref()
            doc.update_object(new_xref, '<<>>')
            doc.update_stream(new_xref, new_contents, new=True)
            page_obj = doc.xref_object(page.xref)
            if '/Contents' in page_obj:
                page_obj = re.sub(
                    r'/Contents\s+\d+\s+0\s+R',
                    f'/Contents {new_xref} 0 R', page_obj)
                page_obj = re.sub(
                    r'/Contents\s*\[[^\]]*\]',
                    f'/Contents {new_xref} 0 R', page_obj)
                doc.update_object(page.xref, page_obj)
        changed = True
    return changed


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
) -> Optional[Dict[int, str]]:
    """For a single suspect font, render each used CID and pick the best
    matching reference char. Returns {cid: unicode_str} or None on failure.
    Unrenderable / sub-threshold CIDs map to space.
    """
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
        pil_font = _build_pil_font_for_gid_render(font_bytes)
        if pil_font is None:
            return None
        cid_to_gid = _cid_to_gid_lookup(font_bytes, fi.is_type0)
        def render(cid: int) -> Optional[np.ndarray]:
            gid = cid_to_gid(cid)
            if gid is None or gid == 0:
                return None
            return _render_glyph(pil_font, _PUA_BASE + gid)

    mapping: Dict[int, str] = {}
    for cid in sorted(fi.used_codes):
        glyph_arr = render(cid)
        if glyph_arr is None:
            mapping[cid] = ' '
            continue
        best_ch, best_score = None, -1.0
        for ref_ch, variants in ref_items:
            for v in variants:
                s = _similarity(glyph_arr, v)
                if s > best_score:
                    best_score, best_ch = s, ref_ch
        mapping[cid] = best_ch if (best_ch is not None
                                   and best_score >= min_similarity) else ' '
    return mapping or None


def fix_pdf_font_encoding(
    pdf_path: str,
    out_path: Optional[str] = None,
    min_similarity: float = 0.30,
    rewrite_streams: bool = False,
) -> str:
    """Detect custom font encodings in `pdf_path` and repair them.

    Two strategies:

    - Default (`rewrite_streams=False`): inject a fresh `/ToUnicode` CMap for
      each suspect font. The page renders pixel-identically; only text
      extraction tools see different unicode. Punctuation rendering is
      preserved.
    - `rewrite_streams=True`: replace every suspect-font `Tf` in each page's
      content stream with a Helvetica reference and collapse the per-char
      `Tm`/`Tj` pattern into one `Tj` per visible line, encoded as WinAnsi
      text. **Visual layout shifts** because Helvetica's metrics differ;
      text extraction is cleaner because chars on a line are no longer
      separated by inserted spaces.

    Returns the path to the saved PDF. If no problematic font is found, the
    original `pdf_path` is returned unchanged and no new file is written.
    """
    doc = pymupdf.open(pdf_path)
    bad_fonts = _scan_fonts(doc)
    if not bad_fonts:
        doc.close()
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

    if rewrite_streams:
        suspect_info = {
            xref: {'is_type0': fi.is_type0, 'mapping': m}
            for xref, (fi, m) in mappings.items()
        }
        fixed_any = _rewrite_pdf_streams(doc, suspect_info)
    else:
        fixed_any = False
        # Measure each CID's actual on-page advance. Overriding the font's
        # widths to match these prevents PDF viewers (Preview / Adobe /
        # Chrome) from inserting a space at every per-char Tm gap when you
        # copy text out.
        widths = _actual_advances(doc, set(mappings))
        for xref, (fi, m) in mappings.items():
            _set_font_to_unicode(
                doc, xref, _build_to_unicode_cmap(m, two_byte=fi.is_type0))
            if xref in widths:
                _override_widths(doc, xref, widths[xref], fi.is_type0)
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
    parser.add_argument('-r', '--rewrite', action='store_true',
                        help='rewrite content streams: swap suspect fonts for '
                             'Helvetica and collapse per-char Tj into one Tj '
                             'per line. Breaks visual layout; cleans up text '
                             'extraction')
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
                min_similarity=args.threshold,
                rewrite_streams=args.rewrite)
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

