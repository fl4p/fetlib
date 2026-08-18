"""Exact glyph identification by outline fingerprint, for `fix_encoding`.

WHY BEFORE THE PIXELS
---------------------
The visual matcher in `fix_encoding.py` rasterizes a glyph and picks the
nearest reference bitmap. That is a statistical answer to a question that is
often not statistical at all: a large share of the broken PDFs in this corpus
embed a STANDARD FACE IN FULL -- Arial, Arial-BoldMT, TimesNewRomanPSMT,
Calibri -- and merely withhold the /ToUnicode. Their glyph programs are
byte-for-byte the designer's, so if the same face is installed here the
identification is an exact lookup, not a similarity score.

Measured on `datasheets/huayi/HY0910D.pdf`, whose four suspect fonts are
full-face embeds:

    Arial-BoldMT   ->  Arial Bold.ttf         60/60 glyphs
    TimesNewRomanPSMT -> Times New Roman.ttf  26/26 glyphs
    ArialMT        ->  Arial.ttf              82/82 glyphs
    Calibri        ->  (not installed)         0/26  -- abstains

and every WRONG candidate scores 0/N, not "a bit lower". That gap is the
method's own significance test: there is no threshold to tune between 0% and
100%, so a wrong font cannot be mistaken for a near miss. Where it fires it
also settles glyphs vision reliably gets wrong -- 'Ω' came out of the Times
font here, and 'l' vs 'I' cannot arise at all.

WHAT IT DOES NOT COVER, and why that is fine
--------------------------------------------
Subsetted fonts from a distiller that re-outlines or re-hints glyphs will not
hash-match, and neither will a face that is not installed on this machine.
Both abstain and fall through to the pixel matcher unchanged, which is the
correct division of labour: this module never guesses.

A DEAD END WORTH RECORDING, so it is not re-attempted
------------------------------------------------------
The obvious cheaper evidence -- the embedded font's own `post` glyph names and
`cmap` -- is NOT usable on the Infineon `Z_C000NN.tmp` fonts, which are the
largest suspect family in the corpus. They do carry both tables, and 84 of 87
glyphs are "named". But the names are `uniF020`, `uniF021`, `uniF022`, … i.e.
the Microsoft symbol-range spelling of the SCRAMBLED code, assigned by the
subsetter after the scramble. Decoding them yields `!"#$%&'()*` for a font
whose used codes are consecutive -- the identity map, dressed up as evidence.
Anything reading those names would have reported a confident, plausible, and
completely wrong answer for 5 of the 8 known-broken datasheets. Outline
geometry is the only internal evidence in these files that the subsetter did
not overwrite.
"""

import hashlib
import os
# pickle: this process is both the only writer and the only reader of the index
# file, which lives in the gitignored data/cache/ tree alongside every other
# `dslib.cache.disk_cache` artifact and is rebuilt from scratch when its
# signature does not match. No externally supplied blob is ever unpickled here.
import pickle
import warnings
from typing import Callable, Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Coordinates are quantized to 1/1000 em before hashing. Two independently
# built copies of the same face agree exactly at this precision; a genuinely
# different design does not come close, so this is a rounding tolerance, not a
# similarity threshold.
_UPEM = 1000

# A candidate face must explain at least this fraction of the font's used
# glyphs to be accepted. Deliberately high: the observed distribution is
# bimodal at 0.0 and 1.0, so any value in the middle of that gap behaves
# identically, and a high one fails safe if some future face lands in between.
_MIN_COVERAGE = 0.60

# ... and must beat the runner-up by this much, so two faces that are near
# revisions of each other cannot silently swap in for one another.
_MIN_MARGIN = 0.20

# Below this many usable glyphs the coverage fraction is not evidence -- 2 of 2
# is 100% and means nothing. Such fonts abstain to the pixel matcher.
_MIN_GLYPHS = 6

_CACHE_VERSION = 3  # bump on any change to the hashing scheme below

_FONT_DIRS = (
    '/System/Library/Fonts/Supplemental',
    '/System/Library/Fonts',
    '/Library/Fonts',
    os.path.expanduser('~/Library/Fonts'),
    '/usr/share/fonts',
    '/usr/local/share/fonts',
    '/usr/share/fonts/truetype',
)


# ---------------------------------------------------------------------------
# Outline fingerprinting
# ---------------------------------------------------------------------------

def _outline_hash(glyph_set, name: str, upem: int) -> Optional[str]:
    """A content hash of one glyph's drawing program, in 1/1000-em units.

    Uses a DECOMPOSING pen so a composite glyph ('Ä' as 'A' + diaeresis, and in
    some faces plain letters as one-component composites) hashes as the outline
    it actually paints. Without that, the same visible glyph hashes differently
    depending on whether a given build chose to compose it, and the two copies
    of a face that this module exists to equate would not match.
    """
    try:
        from fontTools.pens.recordingPen import DecomposingRecordingPen
        pen = DecomposingRecordingPen(glyph_set)
        glyph_set[name].draw(pen)
    except Exception:
        return None
    if not pen.value:
        return None  # blank glyph (space): no shape, nothing to identify by

    parts: List[str] = []
    scale = _UPEM / float(upem or _UPEM)
    for op, args in pen.value:
        parts.append(op[0])
        for a in args:
            if isinstance(a, tuple) and len(a) == 2:
                parts.append('%d,%d' % (round(a[0] * scale), round(a[1] * scale)))
    return hashlib.sha1('|'.join(parts).encode()).hexdigest()[:16]


def _font_upem(tt) -> int:
    try:
        return int(tt['head'].unitsPerEm) or _UPEM
    except Exception:
        return _UPEM


def _hashes_for_gids(tt, gids) -> Dict[int, str]:
    """gid -> outline hash, for the requested gids of an open TTFont."""
    try:
        order = tt.getGlyphOrder()
        gs = tt.getGlyphSet()
    except Exception:
        return {}
    upem = _font_upem(tt)
    out: Dict[int, str] = {}
    for gid in gids:
        if not isinstance(gid, int) or gid < 0 or gid >= len(order):
            continue
        h = _outline_hash(gs, order[gid], upem)
        if h:
            out[gid] = h
    return out


# ---------------------------------------------------------------------------
# The reference index
# ---------------------------------------------------------------------------

def _index_one_font(path: str, alphabet: Set[str]) -> Optional[Dict[str, str]]:
    """{outline hash: character} for one installed font, over `alphabet` only.

    Restricting to the characters `fix_encoding` can emit keeps this to ~130
    outlines per face instead of the 3 000-30 000 a full face holds, which is
    what makes indexing the whole system affordable. It also means a glyph the
    matcher could never output cannot occupy a hash slot and collide a glyph it
    could.
    """
    try:
        from fontTools.ttLib import TTFont
        tt = TTFont(path, fontNumber=0, lazy=True)
    except Exception:
        return None

    try:
        cmap = tt.getBestCmap() or {}
    except Exception:
        cmap = {}
    if not cmap:
        tt.close()
        return None

    try:
        gs = tt.getGlyphSet()
    except Exception:
        tt.close()
        return None
    upem = _font_upem(tt)

    by_hash: Dict[str, str] = {}
    ambiguous: Set[str] = set()
    for cp, gname in cmap.items():
        ch = chr(cp)
        if ch not in alphabet:
            continue
        h = _outline_hash(gs, gname, upem)
        if not h:
            continue
        prev = by_hash.get(h)
        if prev is None:
            by_hash[h] = ch
        elif prev != ch:
            # One outline serving two characters -- 'A'/'Alpha', a hyphen and a
            # minus sign drawn identically. It cannot identify either, so it
            # identifies neither. Dropped rather than resolved by cmap order,
            # which would make the answer depend on dict iteration.
            ambiguous.add(h)
    tt.close()
    for h in ambiguous:
        by_hash.pop(h, None)
    return by_hash or None


def _index_path() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # dslib/
    return os.path.join(os.path.dirname(here), 'data', 'cache',
                        'glyph-outline-index-v%d.pkl' % _CACHE_VERSION)


def _installed_fonts() -> List[str]:
    """Every face this machine can offer as a reference, bundled ones first.

    The bundled set (dslib/pdf/fonts/) is listed FIRST and unconditionally, so
    that a checkout on a machine with no fonts installed still has metric
    stand-ins for Arial, Times and Courier. `seen` then keeps a system copy of
    the same filename from being indexed twice.
    """
    bundled: List[str] = []
    seen: Set[str] = set()
    try:
        from dslib.pdf.fix_encoding import bundled_fonts
        for p in bundled_fonts():
            seen.add(os.path.basename(p).lower())
            bundled.append(p)
    except Exception:
        pass
    out: List[str] = []
    for d in _FONT_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            walker = os.walk(d)
        except Exception:
            continue
        for root, _dirs, files in walker:
            for f in sorted(files):
                if not f.lower().endswith(('.ttf', '.otf', '.ttc')):
                    continue
                key = f.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(os.path.join(root, f))
    # Bundled first, then system paths -- both sorted, so the order is stable
    # and does not depend on which happens to sort earlier by absolute path.
    return sorted(bundled) + sorted(out)


_INDEX: Optional[Dict[str, Dict[str, str]]] = None


def reference_index(alphabet: Optional[Set[str]] = None,
                    rebuild: bool = False) -> Dict[str, Dict[str, str]]:
    """{font label: {outline hash: character}} over every installed font.

    Built once and cached to disk (~1 s to load, ~30 s to build). The cache is
    keyed by `_CACHE_VERSION` and by the alphabet, and it stores the FONT LIST
    it was built from: installing a font must not leave a stale index that
    silently cannot see it, which would look exactly like "that face is not
    installed" -- the one conclusion this module is allowed to draw.
    """
    global _INDEX
    if _INDEX is not None and not rebuild:
        return _INDEX

    if alphabet is None:
        from dslib.pdf.fix_encoding import _COMMON_GLYPHS
        alphabet = set(_COMMON_GLYPHS)

    paths = _installed_fonts()
    sig = hashlib.sha1(
        ('|'.join(paths) + '#' + ''.join(sorted(alphabet))).encode()
    ).hexdigest()[:16]

    cache = _index_path()
    if not rebuild and os.path.isfile(cache):
        try:
            with open(cache, 'rb') as fh:
                blob = pickle.load(fh)
            if blob.get('sig') == sig:
                _INDEX = blob['index'] or {}
                return _INDEX
        except Exception:
            pass  # unreadable cache is a rebuild, never an empty index

    index: Dict[str, Dict[str, str]] = {}
    for p in paths:
        try:
            m = _index_one_font(p, alphabet)
        except Exception:
            m = None
        if m:
            index[os.path.basename(p)] = m

    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, 'wb') as fh:
            pickle.dump({'sig': sig, 'index': index}, fh)
    except Exception as e:
        warnings.warn('glyph_exact: could not write index cache: %s' % e)

    _INDEX = index
    return index


def index_salt() -> str:
    """Identity of the reference index, for the parse-cache generation key.

    The set of installed fonts changes what this module can resolve, and
    therefore the text extracted from every affected PDF. A parse cached
    against one font set must not be served after that set changes.
    """
    try:
        return hashlib.sha1(
            ('|'.join(_installed_fonts())).encode()).hexdigest()[:16]
    except Exception:
        return 'unavailable'


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

class ExactMatch:
    """The outcome of an exact identification attempt. Never a bare dict, so a
    caller cannot mistake "no evidence" for "no glyphs matched"."""

    __slots__ = ('mapping', 'font_label', 'coverage', 'runner_up')

    def __init__(self, mapping: Dict[int, str], font_label: str,
                 coverage: float, runner_up: float):
        self.mapping = mapping
        self.font_label = font_label
        self.coverage = coverage
        self.runner_up = runner_up

    def __repr__(self):
        return ('ExactMatch(%s, %d glyphs, coverage=%.2f, runner_up=%.2f)'
                % (self.font_label, len(self.mapping), self.coverage,
                   self.runner_up))


def exact_mapping(font_bytes: bytes,
                  cid_to_gid: Callable[[int], Optional[int]],
                  used_cids: Set[int],
                  alphabet: Optional[Set[str]] = None) -> Optional[ExactMatch]:
    """Identify `used_cids` exactly by matching outlines against installed fonts.

    Returns None -- meaning "no opinion", never "no characters" -- when the font
    will not parse, too few glyphs carry an outline, or no installed face
    explains enough of them by a clear margin. The caller must fall through to
    visual matching in that case rather than treating the absence as a result.
    """
    if not font_bytes or not used_cids:
        return None
    try:
        from fontTools.ttLib import TTFont
        import io
        tt = TTFont(io.BytesIO(font_bytes), fontNumber=0, lazy=True)
    except Exception:
        return None

    cid_by_gid: Dict[int, List[int]] = {}
    for cid in used_cids:
        try:
            gid = cid_to_gid(cid)
        except Exception:
            gid = None
        if gid is None or gid == 0:
            continue
        cid_by_gid.setdefault(gid, []).append(cid)

    try:
        gid_hash = _hashes_for_gids(tt, sorted(cid_by_gid))
    finally:
        try:
            tt.close()
        except Exception:
            pass

    if len(gid_hash) < _MIN_GLYPHS:
        return None

    index = reference_index(alphabet)
    if not index:
        return None

    # Score every installed face by how much of THIS font it explains.
    best_label, best_hits = '', 0
    second_hits = 0
    for label, by_hash in index.items():
        hits = sum(1 for h in gid_hash.values() if h in by_hash)
        if hits > best_hits:
            best_label, best_hits, second_hits = label, hits, best_hits
        elif hits > second_hits:
            second_hits = hits

    n = len(gid_hash)
    coverage = best_hits / n
    runner_up = second_hits / n
    if coverage < _MIN_COVERAGE or coverage - runner_up < _MIN_MARGIN:
        return None

    by_hash = index[best_label]
    mapping: Dict[int, str] = {}
    for gid, h in gid_hash.items():
        ch = by_hash.get(h)
        if ch is None:
            continue
        for cid in cid_by_gid.get(gid, ()):
            mapping[cid] = ch
    if not mapping:
        return None
    return ExactMatch(mapping, best_label, coverage, runner_up)


def _cli(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog='glyph_exact',
        description='Report which installed face (if any) exactly explains the '
                    'embedded fonts of a PDF, by outline fingerprint.')
    ap.add_argument('pdf', nargs='*')
    ap.add_argument('--rebuild-index', action='store_true')
    args = ap.parse_args(argv)

    if args.rebuild_index:
        idx = reference_index(rebuild=True)
        print('indexed %d fonts, %d outlines'
              % (len(idx), sum(len(v) for v in idx.values())))
        if not args.pdf:
            return 0

    import pymupdf
    from dslib.pdf.fix_encoding import _scan_fonts, _cid_to_gid_lookup

    for path in args.pdf:
        print('##', path)
        doc = pymupdf.open(path)
        for fi in _scan_fonts(doc):
            try:
                fb = doc.extract_font(fi.xref)[3]
            except Exception:
                fb = None
            if not isinstance(fb, bytes) or not fb:
                print('   %-22s (no embedded binary)' % fi.short_name[:22])
                continue
            m = exact_mapping(fb, _cid_to_gid_lookup(fb, fi.is_type0),
                              fi.used_codes)
            if m is None:
                print('   %-22s no exact match' % fi.short_name[:22])
            else:
                text = ''.join(m.mapping.get(c, '?') for c in sorted(fi.used_codes))
                print('   %-22s %-28s cov=%.2f  %s'
                      % (fi.short_name[:22], m.font_label, m.coverage, text[:60]))
        doc.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(_cli())
