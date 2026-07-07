"""
Character extraction and word/row grouping from a PDF.

Self-contained — talks to pdfminer.six directly. Does not rely on dslib.pdf.tree
or dslib.pdf.ascii so the v2 pipeline can evolve independently.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTChar, LTPage, LTTextLine

from dslib.pdf.pdf2txt import normalize_text


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


# ---------- low-level char extraction ----------


def _iter_chars(layout: LTPage) -> Iterator[LTChar]:
    """Depth-first walk yielding every LTChar in a page layout."""
    stack: List[object] = [layout]
    while stack:
        obj = stack.pop()
        if isinstance(obj, LTChar):
            yield obj
        elif hasattr(obj, "__iter__"):
            # push children in reverse so we visit them in their natural order
            stack.extend(reversed(list(obj)))


def _normalize_char(c: str) -> str:
    """Normalize a single decoded char from pdfminer.

    pdfminer can emit ligatures ('ﬁ'), 2-char ligatures, or empty strings.
    normalize_text handles the common cases (NFKD + unidecode w/ Greek
    preserved). We feed each char individually so positional info is not
    disturbed.
    """
    if not c:
        return ""
    n = normalize_text(c)
    return n


# ---------- word / row grouping ----------


def _group_chars_into_words(chars: List[LTChar],
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
    cur_size = chars[0].size if hasattr(chars[0], "size") else (cur_y2 - cur_y1)

    def flush():
        if cur_text:
            words.append(Word(cur_text, BBox(cur_x1, cur_y1, cur_x2, cur_y2),
                              cur_size))

    prev_x2 = chars[0].bbox[2]
    prev_h = chars[0].bbox[3] - chars[0].bbox[1]

    for i, ch in enumerate(chars):
        c = _normalize_char(ch.get_text())
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
                cur_size = ch.size if hasattr(ch, "size") else ch_h
        else:
            if is_space:
                # whitespace inside a "word" -> still treat as a break
                flush()
                cur_text = ""
            else:
                if not cur_text:
                    cur_x1, cur_y1, cur_x2, cur_y2 = cx1, cy1, cx2, cy2
                    cur_size = ch.size if hasattr(ch, "size") else ch_h
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


def _cluster_lines(line_chars: List[LTChar],
                   min_overlap_ratio: float = 0.4) -> List[List[LTChar]]:
    """Cluster characters into horizontal lines.

    A new character joins an existing cluster when its vertical range
    overlaps the cluster's vertical range by ``min_overlap_ratio`` of the
    shorter of the two heights. This handles subscripts and superscripts:
    a small "gd" subscript sitting under a Q has only ~75% overlap with
    Q's full bbox but >40% relative to its own (smaller) height, so they
    still cluster together.

    The cluster's reference y-range is the *running min/max* of every
    char added, so subscript-heavy rows don't gradually drift away from
    the main baseline like a running-mean approach would.
    """
    if not line_chars:
        return []

    heights = [c.bbox[3] - c.bbox[1] for c in line_chars]
    heights = [h for h in heights if h > 0]
    if not heights:
        return [line_chars]

    line_chars = sorted(line_chars, key=lambda c: -c.bbox[3])

    clusters: List[List[LTChar]] = []
    cluster_y: List[Tuple[float, float, float]] = []  # (y1, y2, anchor_h)

    def overlap(a1: float, a2: float, b1: float, b2: float) -> float:
        return max(0.0, min(a2, b2) - max(a1, b1))

    for ch in line_chars:
        y1, y2 = ch.bbox[1], ch.bbox[3]
        h = max(y2 - y1, 0.1)
        assigned = False
        for i, (cy1, cy2, ch_anchor_h) in enumerate(cluster_y):
            ov = overlap(y1, y2, cy1, cy2)
            ref = min(h, ch_anchor_h)
            if ref > 0 and ov / ref >= min_overlap_ratio:
                clusters[i].append(ch)
                cluster_y[i] = (min(cy1, y1), max(cy2, y2), ch_anchor_h)
                assigned = True
                break
        if not assigned:
            clusters.append([ch])
            cluster_y.append((y1, y2, h))

    return clusters


def _build_rows(chars: List[LTChar]) -> List[TextRow]:
    """Build TextRows: cluster chars vertically, then group horizontally."""
    rows: List[TextRow] = []
    for cluster in _cluster_lines(chars):
        words = _group_chars_into_words(cluster)
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


# ---------- public API ----------


def extract_pages_with_rows(pdf_path: str,
                            max_pages: int = 0,
                            char_margin: float = 2.0,
                            line_overlap: float = 0.3) -> List[Page]:
    """Parse a PDF file and return a list of pages, each with TextRows.

    Pages with no extracted characters are returned with ``char_count=0`` so
    callers can detect scanned pages.
    """
    laparams = LAParams(line_overlap=line_overlap,
                        char_margin=char_margin,
                        line_margin=0.5,
                        all_texts=True)

    pages: List[Page] = []
    iter_pages = extract_pages(pdf_path,
                               maxpages=max_pages,
                               laparams=laparams)

    for page_num, layout in enumerate(iter_pages):
        chars = list(_iter_chars(layout))
        rows = _build_rows(chars)
        mb = BBox(*layout.mediabox) if hasattr(layout, "mediabox") else BBox(0, 0, 612, 792)
        pages.append(Page(page_num=page_num,
                          mediabox=mb,
                          rows=rows,
                          char_count=len(chars)))
    return pages


def page_likely_needs_ocr(pages: List[Page],
                          min_chars_per_page: int = 50) -> bool:
    """Heuristic: a PDF needs OCR when too few real chars are found.

    Returns True if every page has fewer than ``min_chars_per_page`` chars.
    """
    if not pages:
        return True
    return max(p.char_count for p in pages) < min_chars_per_page
