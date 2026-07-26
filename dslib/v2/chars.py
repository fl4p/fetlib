"""
Character extraction and word/row grouping from a PDF.

Self-contained — talks to pdfminer.six directly. Does not rely on dslib.pdf.tree
or dslib.pdf.ascii so the v2 pipeline can evolve independently.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterator, List, NamedTuple, Optional, Sequence, Tuple

from pdfminer.layout import LTChar, LTPage

from dslib.pdf.pdf2txt import normalize_text

# Which library reads glyphs out of the PDF. "fitz" (PyMuPDF, C-backed) is
# 3-100x faster than pdfminer and produces the same rows; pdfminer stays as the
# fallback for files fitz reads badly. "auto" runs fitz and falls back.
# Override with DSLIB_V2_BACKEND=pdfminer.
DEFAULT_BACKEND = os.environ.get("DSLIB_V2_BACKEND", "auto")

# Below this many characters on the best page, a PDF is treated as unreadable
# (scanned, or a font encoding the backend could not decode).
MIN_CHARS_READABLE = 50

# Baseline tolerances, as a fraction of the font size. Two regimes, because
# glyphs of the row's own size and sub/superscripts behave differently:
# same-size glyphs on one line share a baseline exactly, so they get only
# enough slack for rounding, while a sub/superscript is deliberately offset.
# 0.20 sits between two measured bounds: same-line glyphs of mixed fonts need
# more than ~0.11 em of slack (a diodes sheet loses tRise/tDoff below that),
# while an infineon multi-line condition cell sits 0.317 em off its neighbour's
# baseline and must stay out. Anything in 0.15-0.30 passes the known cases.
_SAME_LINE_TOL = 0.20
_SCRIPT_TOL = 0.45

# A glyph smaller than this fraction of the row's size counts as a
# sub/superscript and is the only kind allowed the larger tolerance.
_SCRIPT_MAX_SIZE_RATIO = 0.9

# A cluster of at most this many glyphs is a stray cell rather than a line, and
# may be folded into a nearby row from up to _STRAY_MERGE_TOL em away.
_STRAY_MAX_GLYPHS = 2
_STRAY_MERGE_TOL = 0.6
# If the two nearest rows are this close to equidistant, the stray's owner is
# ambiguous and it is discarded instead of guessed.
_STRAY_TIE_MARGIN = 0.25

# How close, in ems, two identical glyphs must sit before the second is read as
# an overstrike (fake bold) rather than as real repeated text. Overstrikes land
# at 0 to ~0.05 em; the narrowest real advance between two identical glyphs is
# about 0.22 em ('l', 'i', '.').
_OVERSTRIKE_MAX_D = 0.10

# Fallback descender when a backend does not report one, as a fraction of the
# font size — used to recover the baseline from a glyph box bottom.
_DEFAULT_DESCENT = -0.2


@dataclass
class BBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def cx(self) -> float:
        return 0.5 * (self.x1 + self.x2)

    @property
    def cy(self) -> float:
        return 0.5 * (self.y1 + self.y2)

    def union(self, o: "BBox") -> "BBox":
        return BBox(min(self.x1, o.x1), min(self.y1, o.y1),
                    max(self.x2, o.x2), max(self.y2, o.y2))

    def h_overlap(self, o: "BBox") -> float:
        return max(0.0, min(self.x2, o.x2) - max(self.x1, o.x1))

    def v_overlap(self, o: "BBox") -> float:
        return max(0.0, min(self.y2, o.y2) - max(self.y1, o.y1))


@dataclass
class Word:
    text: str
    bbox: BBox
    font_size: float

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"Word({self.text!r}, x={self.bbox.x1:.1f},y={self.bbox.y1:.1f})"


@dataclass
class TextRow:
    """A horizontal row of words extracted from one page."""
    words: List[Word]
    bbox: BBox

    # text + per-character offset into text for each word (so regex matches
    # can be mapped back to their source words)
    text: str = ""
    word_offsets: List[int] = field(default_factory=list)

    def build_text(self) -> None:
        parts: List[str] = []
        offsets: List[int] = []
        pos = 0
        for i, w in enumerate(self.words):
            if i > 0:
                parts.append(" ")
                pos += 1
            offsets.append(pos)
            parts.append(w.text)
            pos += len(w.text)
        self.text = "".join(parts)
        self.word_offsets = offsets

    def word_at_offset(self, off: int) -> Optional[Word]:
        for w, start in zip(self.words, self.word_offsets):
            if start <= off < start + len(w.text):
                return w
        return None

    def words_in_xspan(self, x1: float, x2: float,
                       min_overlap_ratio: float = 0.5) -> List[Word]:
        """Words whose horizontal extent overlaps a given x-span."""
        out: List[Word] = []
        for w in self.words:
            ov = min(w.bbox.x2, x2) - max(w.bbox.x1, x1)
            if ov <= 0:
                continue
            if ov / max(w.bbox.width, 1e-6) >= min_overlap_ratio:
                out.append(w)
        return out

    def phrases(self, gap_ratio: float = 1.5) -> List[List[Word]]:
        """Group spatially-close words into "phrases".

        A new phrase starts when the gap between two words exceeds
        ``gap_ratio * height``. The phrase boundaries roughly correspond
        to table cell boundaries.
        """
        if not self.words:
            return []
        words = sorted(self.words, key=lambda w: w.bbox.x1)
        groups: List[List[Word]] = [[words[0]]]
        for w in words[1:]:
            prev = groups[-1][-1]
            gap = w.bbox.x1 - prev.bbox.x2
            h = max(prev.bbox.height, w.bbox.height, 1.0)
            if gap > gap_ratio * h:
                groups.append([w])
            else:
                groups[-1].append(w)
        return groups

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        y = round(self.bbox.y1, 1)
        return f"Row(y={y}, {self.text!r})"


@dataclass
class Page:
    page_num: int
    mediabox: BBox
    rows: List[TextRow]
    char_count: int  # used to decide "needs OCR"
    # cells lost to glyphs the backend could not name. Non-zero means a whole
    # table cell is missing from ``rows``, not that the page is merely odd.
    n_undecoded: int = 0


# ---------- low-level char extraction ----------


class RawChar(NamedTuple):
    """One glyph, backend-agnostic.

    ``bbox`` is (x1, y1, x2, y2) in PDF user space (y grows *upwards*), which
    is pdfminer's convention; the fitz backend flips into it.

    ``baseline`` is the y the glyph sits on. It is what rows are clustered by:
    every glyph typeset on one line shares it exactly, while box overlap only
    correlates with it.
    """
    text: str
    bbox: Tuple[float, float, float, float]
    size: float
    baseline: float


def _iter_chars(layout: LTPage) -> Iterator[LTChar]:
    """Depth-first walk yielding every LTChar in a page layout."""
    stack: List[object] = [layout]
    while stack:
        obj = stack.pop()
        if isinstance(obj, LTChar):
            yield obj
        elif hasattr(obj, "__iter__"):
            # push children in reverse so we visit them in their natural order
            stack.extend(reversed(list(obj)))  # type: ignore[arg-type]


_norm_char_memo: dict = {}

# ASCII letters/digits and the punctuation normalize_text leaves alone. Skipping
# the memo dict for these avoids a hash lookup on the ~90% common case.
_ASCII_PASSTHROUGH = frozenset(
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    " ()[]{}/\\|.,:;+*=<>#$%&?!'\"@^_`~"
    # U+FFFD must survive normalisation (which would strip it) so that a
    # glyph the backend could not decode stays countable — see _scrub_undecodable.
    "�"
)


def _normalize_char(c: str) -> str:
    """Normalize a single decoded char from pdfminer.

    pdfminer can emit ligatures ('ﬁ'), 2-char ligatures, or empty strings.
    normalize_text handles the common cases (NFKD + unidecode w/ Greek
    preserved). We feed each char individually so positional info is not
    disturbed.

    ``normalize_text`` costs ~20 Python-level operations (custom_subs, NFKD,
    unidecode, a regex sub) and is called once per glyph — tens of thousands
    of times per datasheet. It is a pure function of the single character, so
    memoizing on the character is exact, not an approximation.
    """
    if not c:
        return ""
    if c in _ASCII_PASSTHROUGH:
        return c
    n = _norm_char_memo.get(c)
    if n is None:
        n = normalize_text(c)
        _norm_char_memo[c] = n
    return n


# ---------- word / row grouping ----------


def _group_chars_into_words(chars: List[RawChar],
                            word_gap_ratio: float = 0.25) -> List[Word]:
    """Group horizontally adjacent characters into words.

    Rule: start a new word when the gap to the previous char exceeds
    ``word_gap_ratio * max(prev_height, this_height)``.
    """
    if not chars:
        return []

    # sort by x within the row
    chars = sorted(chars, key=lambda c: c.bbox[0])

    words: List[Word] = []
    cur_text = ""
    cur_x1 = chars[0].bbox[0]
    cur_y1 = chars[0].bbox[1]
    cur_x2 = chars[0].bbox[2]
    cur_y2 = chars[0].bbox[3]
    cur_size = chars[0].size

    def flush():
        if cur_text:
            words.append(Word(cur_text, BBox(cur_x1, cur_y1, cur_x2, cur_y2),
                              cur_size))

    prev_x2 = chars[0].bbox[2]
    prev_h = chars[0].bbox[3] - chars[0].bbox[1]

    for i, ch in enumerate(chars):
        c = _normalize_char(ch.text)
        cx1, cy1, cx2, cy2 = ch.bbox
        ch_h = cy2 - cy1
        gap = cx1 - prev_x2 if i > 0 else 0.0
        h_ref = max(ch_h, prev_h, 1.0)

        is_space = c == " " or c == "\t" or c == "\xa0"
        new_word = (i > 0 and (gap > word_gap_ratio * h_ref or is_space))

        if new_word:
            flush()
            cur_text = ""
            if not is_space:
                cur_text = c
                cur_x1, cur_y1, cur_x2, cur_y2 = cx1, cy1, cx2, cy2
                cur_size = ch.size
        else:
            if is_space:
                # whitespace inside a "word" -> still treat as a break
                flush()
                cur_text = ""
            else:
                if not cur_text:
                    cur_x1, cur_y1, cur_x2, cur_y2 = cx1, cy1, cx2, cy2
                    cur_size = ch.size
                else:
                    cur_x2 = max(cur_x2, cx2)
                    cur_y1 = min(cur_y1, cy1)
                    cur_y2 = max(cur_y2, cy2)
                cur_text += c

        if not is_space:
            prev_x2 = cx2
            prev_h = ch_h

    flush()
    return [w for w in words if w.text.strip()]


def _cluster_lines(line_chars: List[RawChar]) -> List[List[RawChar]]:
    """Cluster characters into horizontal lines, by baseline.

    Every glyph typeset on one line shares a baseline exactly, so a tolerance
    of a fraction of the font size separates rows cleanly while still pulling
    in sub/superscripts, whose baseline is offset by only ~0.2-0.33 em.

    Clustering by *bounding-box overlap* — the obvious alternative — cannot
    do this, because a glyph box is over a point tall and table cells are not
    aligned to a common top. Two failures made that concrete:

    * A unit cell "A" sitting vertically centred between the "Continuous
      Drain Current" and "Pulsed Drain Current" rows overlapped both. It
      joined the first, dragged that row's band down, and the band then
      swallowed the second row whole: the two came out interleaved character
      by character — "ID"+"IDM" as "IIDDM", 90 and 360 as "39600" — losing
      both rows. By baseline the "A" is 5.5 pt off either row and joins
      neither.
    * An nxp condition cell "Tj = 25 C" belonging to the row above overlapped
      the "Q_GS(th) pre-threshold" row by 51% of a glyph height, enough to
      merge them, which then left that row's own subscript out of reach.
      Their baselines differ by 4.4 pt on a 9 pt font, so they separate,
      while the subscript is 1.7 pt away and stays.

    The cluster's reference is the baseline of the *largest* glyph seen, so a
    superscript that happens to be visited first cannot pin the row to itself.

    A glyph joins the *nearest* candidate row, not the first one that happens to
    be within tolerance. Taking the first is not a harmless tie-break, because
    the scan runs top-down and the script tolerance is wide: on
    onsemi/NTMFWS1D5N08XT1G the "DS(on)"/"GS"/"D" subscripts sit 1.63 pt below
    their own row but 3.49 pt below a lone stray glyph above it — inside the
    3.60 pt script tolerance — so they were captured by the stray. The merged
    cluster then held 9 visible glyphs, which is too many for stray absorption
    to undo, and the row lost every subscript it needed: "RDS(on)" read as "R"
    and the conditions as "V = 10 V, I = 50" instead of VGS and ID.
    """
    if not line_chars:
        return []

    # Descending baseline: rows are then produced roughly top to bottom, and a
    # glyph only ever has to look at rows at or above it.
    line_chars = sorted(line_chars, key=lambda c: -c.baseline)

    clusters: List[List[RawChar]] = []
    refs: List[Tuple[float, float]] = []  # (baseline, size of the largest glyph)
    spans: List[Tuple[float, float]] = []  # (x1, x2) covered by each cluster

    # Widest tolerance any pairing on this page can produce. Since refs are
    # built in descending-baseline order, scanning them backwards visits the
    # closest rows first, and once a ref is farther than this bound no earlier
    # ref can come back into range — so the scan stops there instead of
    # walking every row on the page for every glyph.
    #
    # The doubling is not slack for its own sake. A ref moves *down* when a
    # larger glyph joins its cluster, by at most one tolerance, so refs can end
    # up locally out of descending order by that much and a nearer row can hide
    # behind a farther one. Stopping at a single tolerance would then drop the
    # glyph into a row of its own — a silently split line, which is the failure
    # this function exists to prevent — so the bound is set where no reordering
    # can reach.
    max_size = max((c.size for c in line_chars), default=0.0)

    for ch in line_chars:
        size = ch.size if ch.size > 0 else max(ch.bbox[3] - ch.bbox[1], 0.1)
        cutoff = 2 * _SCRIPT_TOL * max(size, max_size)
        best_d = None
        best_i = -1
        for i in range(len(refs) - 1, -1, -1):
            cb, csize = refs[i]
            d = abs(ch.baseline - cb)
            if d > cutoff:
                break
            # Deliberately one-directional: only an *incoming* glyph smaller
            # than the row earns the wide tolerance. Making it symmetric — so a
            # large glyph arriving at a row seeded by a small one also got it —
            # fixes no observed case and breaks a real one: on
            # infineon/BSZ070N08LS5ATMA1 the Ohm of the Rg unit cell is a lone
            # Symbol-font "W" sitting 0.72 pt from its row, and symmetry let
            # the 2.15 pt footnote marker "1)" 0.75 pt above capture it first.
            # The pair is then a 3-glyph cluster, one over the stray-absorption
            # limit, so the Ohm never reaches the row and Rg reads 1.3 instead
            # of 1300 mOhm.
            is_script = size < csize * _SCRIPT_MAX_SIZE_RATIO
            tol = (_SCRIPT_TOL if is_script else _SAME_LINE_TOL) * max(size, csize)
            if d > tol:
                continue
            # A sub/superscript belongs to the text it is attached to, so it
            # must fall inside that row's horizontal span. Distance alone gets
            # this wrong whenever a row wraps: on onsemi/NVMFWS2D1N08XT1G the
            # "d(OFF)" of t_d(OFF) sits 1.63 below its own row but only 0.21
            # from the condition line "ID = 43 A, RG = 2.5" printed beside it,
            # so the nearest row is the wrong one — and the right one is
            # obvious horizontally, since the condition column starts well to
            # its right. Only applied when the *incoming* glyph is the small
            # one; a row seeded by a superscript and joined later by its own
            # body text is the same merge seen from the other side, and that
            # cluster is still a lone glyph with no meaningful span yet.
            if is_script and size < csize:
                sx1, sx2 = spans[i]
                pad = size
                if not (sx1 - pad <= ch.bbox[0] <= sx2 + pad):
                    continue
            if best_d is None or d < best_d:
                best_d = d
                best_i = i
        if best_d is None:
            clusters.append([ch])
            refs.append((ch.baseline, size))
            spans.append((ch.bbox[0], ch.bbox[2]))
        else:
            clusters[best_i].append(ch)
            # Whitespace never defines a row's typographic size. A space is
            # frequently emitted at a nominal size unrelated to the text around
            # it: diodes/DMT15H017LPS-13 has a lone 12 pt space beside an 8 pt
            # table row, and letting it set the reference made the row's own
            # body text register as a *subscript* of it (8.04 < 12 * 0.9),
            # which then failed the span test below and split the typ value
            # "0.8" off its row entirely.
            if ch.text.strip() and size > refs[best_i][1]:
                refs[best_i] = (ch.baseline, size)
            sx1, sx2 = spans[best_i]
            spans[best_i] = (min(sx1, ch.bbox[0]), max(sx2, ch.bbox[2]))

    return _absorb_stray_glyphs(clusters, refs)


def _absorb_stray_glyphs(clusters: List[List[RawChar]],
                         refs: List[Tuple[float, float]]) -> List[List[RawChar]]:
    """Fold one- or two-glyph clusters into the nearest real row.

    Some glyphs sit off their row's baseline by more than typographic jitter
    but less than a line: an Omega from a Symbol font in an onsemi unit cell
    is raised 0.275 em, and a unit "A" shared between two rows is centred
    between them. Widening the same-line tolerance to reach them is not an
    option — an infineon condition cell sits 0.317 em from its neighbour and
    must stay separate — so the discriminator is mass rather than distance: a
    lone glyph is a stray cell, whereas a genuine line brings a crowd.

    Dropping the stray instead is not neutral. The Omega *is* the unit cell,
    and losing it leaves 0.0067 where the datasheet says 6.7 mOhm.

    A near-tie is refused outright. A unit cell shared by two rows is centred
    between them, i.e. equidistant *by construction*, so "nearest" would be
    decided by rounding noise and glyph order — attaching a unit to one of two
    rows nondeterministically. That is the same shape as the 1000x error this
    rule exists to prevent, and a miss is recoverable where a wrong unit is
    not.
    """
    # Whitespace does not make a cluster substantial — the Omega above arrives
    # as "  (cid:2)", and counting its two padding spaces hid it from this
    # rule entirely.
    weight = [sum(1 for ch in c if ch.text.strip()) for c in clusters]

    tiny = [i for i, w in enumerate(weight) if w <= _STRAY_MAX_GLYPHS]
    if not tiny:
        return clusters

    absorbed = set()
    for i in tiny:
        reach = _STRAY_MERGE_TOL * refs[i][1]
        near = sorted(
            (abs(refs[i][0] - refs[j][0]), j)
            for j in range(len(clusters))
            if j != i and weight[j] > _STRAY_MAX_GLYPHS and j not in absorbed
            and abs(refs[i][0] - refs[j][0]) <= _STRAY_MERGE_TOL * max(refs[i][1], refs[j][1])
        )
        if not near:
            continue
        if len(near) > 1 and near[1][0] - near[0][0] < _STRAY_TIE_MARGIN * reach:
            continue  # ambiguous owner — leave it out rather than guess
        clusters[near[0][1]].extend(clusters[i])
        absorbed.add(i)

    return [c for i, c in enumerate(clusters) if i not in absorbed]


def _drop_overstrikes(cluster: List[RawChar]) -> List[RawChar]:
    """Remove glyphs that are redrawn on top of an identical glyph.

    Some PDFs emit the same text run twice at the same coordinates to fake a
    bolder face. ti/TPS1100 does it for every bold run: the header span
    "PARAMETER TEST CONDITIONS UNIT" appears twice with bit-identical origins,
    and since rows are rebuilt from glyph positions the two copies interleave
    into "PPAARRAAMMEETTEERR TTEESSTT CCOONNDDIITTIIOONNSS UUNNIITT".

    That is not merely ugly. It silently changes numbers: the abs-max cell
    "V = -2.7 V" reads as "VV == -22.77 VV", i.e. -22.77, and "V = -12 V"
    becomes -1122. A wrong value with no marker of being wrong is the worst
    outcome this module can produce, and it also costs the whole table, since
    the doubled header no longer matches ``head_re`` and the Conditions/Unit
    columns are never derived.

    The discriminator is horizontal distance, in ems so it holds at any font
    size. Two *legitimately* adjacent identical glyphs are separated by an
    advance width -- the narrowest in common use is about 0.22 em ('l', 'i',
    '.') -- while an overstrike sits at 0 to 0.05 em. ``_OVERSTRIKE_MAX_D``
    sits between the two, nearer the overstrike side.

    A glyph whose size cannot be established is *kept*: with no em to measure
    against, "is this a duplicate" is unanswerable, and answering "yes" would
    delete real text. Only a duplicate that can be positively identified is
    dropped.
    """
    if len(cluster) < 2:
        return cluster

    order = sorted(range(len(cluster)), key=lambda i: cluster[i].bbox[0])
    drop = set()
    kept: List[int] = []          # indices into `order`, ascending x, not dropped
    for oi in order:
        ch = cluster[oi]
        size = ch.size if ch.size > 0 else (ch.bbox[3] - ch.bbox[1])
        if size <= 0:
            kept.append(oi)
            continue              # cannot measure -> cannot judge -> keep
        eps = _OVERSTRIKE_MAX_D * size
        is_dup = False
        for kj in range(len(kept) - 1, -1, -1):
            other = cluster[kept[kj]]
            if ch.bbox[0] - other.bbox[0] > eps:
                break             # sorted by x: everything earlier is farther
            if (other.text == ch.text
                    and abs(ch.baseline - other.baseline) <= eps):
                is_dup = True
                break
        if is_dup:
            drop.add(oi)
        else:
            kept.append(oi)

    if not drop:
        return cluster
    return [ch for i, ch in enumerate(cluster) if i not in drop]


def _build_rows(chars: List[RawChar]) -> List[TextRow]:
    """Build TextRows: cluster chars vertically, then group horizontally."""
    rows: List[TextRow] = []
    for cluster in _cluster_lines(chars):
        words = _group_chars_into_words(_drop_overstrikes(cluster))
        if not words:
            continue
        bbox = words[0].bbox
        for w in words[1:]:
            bbox = bbox.union(w.bbox)
        r = TextRow(words=words, bbox=bbox)
        r.build_text()
        rows.append(r)

    rows.sort(key=lambda r: -r.bbox.cy)
    return rows


# ---------- backends ----------


def _pdfminer_baseline(c: LTChar) -> float:
    """Recover a glyph's baseline from pdfminer's box.

    pdfminer puts the box bottom at ``baseline + descent * size``, so the
    baseline is that offset removed. ``LTChar`` does not expose the font
    object — only ``fontname`` as a string — so the real descent is not
    reachable here and a typical value is used instead. Real descents run
    about -0.21 to -0.25, and the residual error is a few hundredths of an em:
    far inside ``_SAME_LINE_TOL``, so it shifts a glyph within its own row and
    never into another one.

    Note this makes pdfminer baselines *approximate* where fitz baselines are
    exact (fitz reports the glyph origin directly). The two backends therefore
    agree within tolerance rather than identically.
    """
    size = getattr(c, "size", c.bbox[3] - c.bbox[1])
    return c.bbox[1] - _DEFAULT_DESCENT * size


def _pages_pdfminer(pdf_path: str, max_pages: int
                    ) -> Iterator[Tuple[List[RawChar], BBox, int]]:
    """Reference backend. Slow but battle-tested on odd embedded fonts.

    ``laparams=None`` skips pdfminer's layout analysis entirely. v2 rebuilds
    words and rows from raw glyph boxes itself and never looks at the
    LTTextLine/LTTextBox tree, so that analysis was pure waste — dropping it
    is up to 3x faster and yields byte-identical glyphs.
    """
    from pdfminer.high_level import extract_pages

    for layout in extract_pages(pdf_path, maxpages=max_pages, laparams=None):
        chars = [RawChar(c.get_text(),
                         (c.bbox[0], c.bbox[1], c.bbox[2], c.bbox[3]),
                         getattr(c, "size", c.bbox[3] - c.bbox[1]),
                         _pdfminer_baseline(c))
                 for c in _iter_chars(layout)]
        # LTPage exposes the page box as .bbox (there is no .mediabox); the
        # mediabox is only carried for callers that want page dimensions.
        # pdfminer never drops a glyph — it emits "(cid:N)" — so 0 undecodable.
        yield chars, BBox(*layout.bbox), 0


# What fitz returns for a glyph whose font gives no usable Unicode mapping.
# pdfminer instead emits a "(cid:N)" token for the same glyph, and the unit
# handling downstream (``(cid:2)`` -> Omega) is keyed on pdfminer's numbering.
# fitz's glyph *index* is not that number — on an onsemi sheet fitz's gid 2 is
# pdfminer's cid 3 — and the offset is font-dependent, so the two cannot be
# translated in general. A page with any of these is therefore handed to
# pdfminer rather than guessed at: dropping the glyph silently cost the Omega
# in an rDS(ON) unit cell, leaving the value unscaled and wrong by 1000x
# (0.0067 instead of 6.7 mOhm) — worse than a miss, because nothing looks
# broken.
_UNDECODABLE = "�"


def _pages_fitz(pdf_path: str, max_pages: int
                ) -> Iterator[Tuple[List[RawChar], BBox, int]]:
    """PyMuPDF backend — 3-100x faster than pdfminer.

    Two things matter for speed here:

    * ``flags`` deliberately omits ``TEXT_PRESERVE_IMAGES``. Datasheets are
      full of raster plots; decoding them cost 2.3 s of 2.4 s on a toshiba
      sheet and yields nothing a text parser can use.
    * fitz never walks the vector-graphics operators. pdfminer spent 17 s on a
      single onsemi sheet parsing 640k PostScript tokens for 43k chart paths.

    fitz uses a y-down coordinate system with the origin at the page's top
    left; PDF user space (what pdfminer and the rest of v2 expect) is y-up
    from the bottom left, so y is flipped here.

    The vertical extent is *rebuilt* rather than taken from ``ch["bbox"]``.
    fitz reports the full line box (ascender-to-descender, measured at
    1.374 x font size on a TI sheet) whereas pdfminer reports a box exactly
    1.000 x font size. The remaining box-relative thresholds — the 0.25 word
    gap, the 1.5 phrase gap, the 2.5 pt minimum header font — were tuned
    against pdfminer's proportions, so taller boxes would silently shift all
    of them. Rebuilding with height == font size keeps one set of constants
    valid for both backends.
    """
    import fitz

    flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES

    doc = fitz.open(pdf_path)
    try:
        for page_num, page in enumerate(doc):
            if max_pages and page_num >= max_pages:
                break
            height = page.rect.height
            chars: List[RawChar] = []
            n_bad = 0
            for block in page.get_text("rawdict", flags=flags).get("blocks", ()):
                for line in block.get("lines", ()):
                    for span in line.get("spans", ()):
                        size = span.get("size", 0.0) or 0.0
                        desc = span.get("descender", _DEFAULT_DESCENT)
                        for ch in span.get("chars", ()):
                            text = ch["c"]
                            if text == _UNDECODABLE:
                                n_bad += 1
                            x1, _, x2, _ = ch["bbox"]
                            baseline = height - ch["origin"][1]
                            y1 = baseline + desc * size
                            chars.append(RawChar(text, (x1, y1, x2, y1 + size),
                                                 size, baseline))
            yield chars, BBox(0.0, 0.0, page.rect.width, height), n_bad
    finally:
        doc.close()


def _scrub_undecodable(rows: List[TextRow]) -> int:
    """Remove undecodable glyphs from rows; return how many *cells* were lost.

    A glyph fitz could not name is only a problem when it was the whole cell.
    Inside a word it is cosmetic — "1.5�" still parses as a value — but a
    cell consisting of nothing else disappears completely, and a vanished
    unit cell turns into a wrongly-scaled number rather than a visible gap.

    Counting lost *cells* rather than lost glyphs is what makes the pdfminer
    fallback affordable: an onsemi sheet with 34 undecodable glyphs, all of
    them inside words, needs no fallback at all, while the one whose Omega
    formed its own unit cell does.
    """
    lost = 0
    for row in rows:
        if _UNDECODABLE not in row.text:
            continue
        kept: List[Word] = []
        for w in row.words:
            cleaned = w.text.replace(_UNDECODABLE, "")
            if not cleaned:
                lost += 1
                continue
            w.text = cleaned
            kept.append(w)
        if len(kept) != len(row.words):
            row.words = kept
        row.build_text()
    return lost


# ---------- public API ----------


def extract_pages_with_rows(pdf_path: str,
                            max_pages: int = 0,
                            backend: Optional[str] = None) -> List[Page]:
    """Parse a PDF file and return a list of pages, each with TextRows.

    Pages with no extracted characters are returned with ``char_count=0`` so
    callers can detect scanned pages.

    ``backend`` is "auto" (default), "fitz", or "pdfminer". "auto" uses fitz
    and hands the file to pdfminer when fitz raised, found almost no text, or
    could not decode some glyph. That last case is the important one: fitz
    drops an undecodable glyph entirely, and a dropped unit is not a visible
    failure, it is a wrong number. ~20% of the corpus trips it, so the
    fallback is not free — but it keeps "auto" no worse than pdfminer
    anywhere, which a speedup that loses values would not be.
    """
    backend = backend or DEFAULT_BACKEND

    if backend == "auto":
        try:
            pages = extract_pages_with_rows(pdf_path, max_pages, backend="fitz")
        except Exception:  # noqa: BLE001 - fall back rather than fail the parse
            return extract_pages_with_rows(pdf_path, max_pages, backend="pdfminer")

        readable = max((p.char_count for p in pages), default=0) >= MIN_CHARS_READABLE
        if readable and not any(p.n_undecoded for p in pages):
            return pages

        # Either fitz read nothing usable (possibly a genuine scan, which
        # pdfminer will also fail) or it hit glyphs it cannot name. Prefer
        # pdfminer, but only if it actually did better — so a scanned PDF
        # still comes back empty and reports as needing OCR.
        try:
            alt = extract_pages_with_rows(pdf_path, max_pages, backend="pdfminer")
        except Exception:  # noqa: BLE001
            return pages
        if not readable:
            return alt if sum(p.char_count for p in alt) > sum(p.char_count for p in pages) else pages
        return alt if sum(p.char_count for p in alt) else pages

    reader = _pages_fitz if backend == "fitz" else _pages_pdfminer

    pages: List[Page] = []
    for page_num, (chars, mb, n_bad) in enumerate(reader(pdf_path, max_pages)):
        rows = _build_rows(chars)
        lost = _scrub_undecodable(rows) if n_bad else 0
        pages.append(Page(page_num=page_num,
                          mediabox=mb,
                          rows=rows,
                          char_count=len(chars),
                          n_undecoded=lost))
    return pages


def page_likely_needs_ocr(pages: List[Page],
                          min_chars_per_page: int = MIN_CHARS_READABLE) -> bool:
    """Heuristic: a PDF needs OCR when too few real chars are found.

    Returns True if every page has fewer than ``min_chars_per_page`` chars.
    """
    if not pages:
        return True
    return max(p.char_count for p in pages) < min_chars_per_page
