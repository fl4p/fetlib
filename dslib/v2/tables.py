"""
Table detection & parameter extraction.

Operates on the rows produced by ``dslib.v2.chars``. The flow is:

  1. detect header rows via ``head_re`` (Symbol / Parameter / Min / Typ / Max /
     Unit / Conditions)
  2. derive column x-ranges from the header word positions
  3. for each row below a header, detect a parameter symbol with
     ``get_field_detect_regex(mfr)``
  4. for each detected symbol, pick the value words inside the min/typ/max
     columns and assemble a ``Field``

Only the header columns "min", "typ", "max", "unit", and "cond" are used to
build values. "values"/"rating" is treated as a "typ"-only column.
"""
from __future__ import annotations

import math
import re
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from dslib.field import Field
from dslib.pdf.expr import get_field_detect_regex
from dslib.pdf.parse import detect_fields
from dslib.v2.chars import BBox, Page, TextRow, Word

# inlined from dslib/pdf/sheet/__init__.py so v2 doesn't drag in PIL etc.
head_re = re.compile(
    r'((\s+|^\s*)('
    r'(?P<sym>Symbol)'
    r'|(?P<param>Parameters?|Characteristics?)'
    r'|(?P<min>Min(\.|imum)?)'
    r'|(?P<typ>Typ(\.|ycal)?)'
    r'|(?P<max>Max(\.|imum)?|LIMIT)'
    r'|(?P<cond>(Note *(/|or)? *)?(Test(ing)?\s+)?Conditions?)'
    r'|(?P<values>(Value|Rating)s?)'
    r'|(?P<unit>Units?)'
    r')(?=$|\s+))+', re.IGNORECASE)

head_re_groups = ('sym', 'param', 'min', 'typ', 'max', 'values', 'unit', 'cond')

head_stop = (
    'Avalanche', 'allowable', 'limited', 'Lead',
    'Static', 'Electrical', 'Dynamic', 'curves', 'above',
    'Continuous', 'Pulsed',
    'Thermal', 'Resistance',
    'Absolute',
    'Diagram', 'C, max',
)


# ---------- header detection ----------


def _row_is_header(row: TextRow, m: re.Match,
                   min_font_height: float = 2.5) -> bool:
    """Mirror the heuristics of ``dslib.pdf.sheet._header_filter``.

    The original used 7.5pt; we relax to ``min_font_height`` (default 2.5)
    so condensed Infineon-style sheets with tiny but legible headers still
    qualify. The font check is mainly there to reject decorative tiny
    asterisks/footnotes rather than to enforce a typographic minimum.
    """
    if any(sw in row.text for sw in head_stop):
        return False

    h_max = 0.0
    for g, v in m.groupdict().items():
        if not v:
            continue
        w = row.word_at_offset(m.start(g))
        if w is not None and w.bbox.height > h_max:
            h_max = w.bbox.height
    if h_max < min_font_height:
        return False
    return True


def _required_header_groups(m: re.Match) -> bool:
    """A row only qualifies as a value header when it has at least two of
    min/typ/max OR one of those plus the unit/cond columns.

    Prevents matching loose "Parameter" / "Symbol" labels that happen to
    appear in body copy.
    """
    g = m.groupdict()
    mtm = sum(bool(g.get(k)) for k in ("min", "typ", "max", "values"))
    other = sum(bool(g.get(k)) for k in ("sym", "param", "unit", "cond"))
    return (mtm >= 2) or (mtm >= 1 and other >= 1)


@dataclass
class HeaderRow:
    row: TextRow
    # x-range (x1, x2) of each detected header column, keyed by group name
    cols: Dict[str, Tuple[float, float]] = field(default_factory=dict)


_VALUE_COLS = ("min", "typ", "max", "values", "unit")


def _header_columns(row: TextRow, m: re.Match) -> Dict[str, Tuple[float, float]]:
    """Compute (x1, x2) for every recognized header group.

    The center of each header label anchors the column. For "wide" columns
    (Symbol / Parameter / Conditions) we extend to the midpoint of each
    neighbor. For narrow numeric columns (Min, Typ, Max, Unit) we use the
    smaller of (half-distance to neighbor) on each side, so a wide
    Conditions column doesn't bleed into Min.
    """
    items: List[Tuple[str, Word]] = []
    for g in head_re_groups:
        if not m.groupdict().get(g):
            continue
        w = row.word_at_offset(m.start(g))
        if w is None:
            continue
        items.append((g, w))

    items.sort(key=lambda kv: kv[1].bbox.cx)

    cols: Dict[str, Tuple[float, float]] = {}
    for i, (g, w) in enumerate(items):
        cx = w.bbox.cx
        prev_cx = items[i - 1][1].bbox.cx if i > 0 else None
        next_cx = items[i + 1][1].bbox.cx if i + 1 < len(items) else None

        if g in _VALUE_COLS:
            # narrow: half-distance to the closer neighbor
            d_left = (cx - prev_cx) if prev_cx is not None else float("inf")
            d_right = (next_cx - cx) if next_cx is not None else float("inf")
            # always prefer the closer neighbor as the *symmetric* bound, so
            # the column is centered on the label
            half = 0.5 * min(d_left, d_right, 60.0)
            # but never shrink below the header label width
            half = max(half, w.bbox.width * 0.6 + 1.5)
            x1 = cx - half
            x2 = cx + half
            # still clamp to the midpoint so we don't overrun a closer neighbor
            if prev_cx is not None:
                x1 = max(x1, 0.5 * (prev_cx + cx))
            if next_cx is not None:
                x2 = min(x2, 0.5 * (cx + next_cx))
        else:
            # wide: midpoint to each neighbor
            if prev_cx is None:
                x1 = w.bbox.x1 - max(w.bbox.width, 8.0)
            else:
                x1 = 0.5 * (prev_cx + cx)
            if next_cx is None:
                x2 = w.bbox.x2 + max(w.bbox.width, 8.0)
            else:
                x2 = 0.5 * (cx + next_cx)

        cols[g] = (x1, x2)

    if "values" in cols and "typ" not in cols:
        cols["typ"] = cols["values"]

    return cols


def _candidate_header(row: TextRow) -> Optional[Tuple[re.Match, Dict[str, Tuple[float, float]]]]:
    """Return (match, columns) if this row looks header-like at all (no
    minimum on min/typ/max — a row with just Sym/Param/Unit/Cond also
    counts so we can merge it with a neighbour)."""
    if not row.text:
        return None
    m = head_re.search(row.text)
    if not m:
        return None
    if not _row_is_header(row, m):
        return None
    cols = _header_columns(row, m)
    if not cols:
        return None
    return m, cols


def find_headers(page_rows: List[TextRow]) -> List[HeaderRow]:
    """Detect header rows on a page, merging adjacent header rows so a
    two-row header (Parameter|Symbol|Unit on top, Min|Typ|Max below)
    behaves like one effective table header.
    """
    # Pass 1: find candidate header rows with their detected columns
    cands: List[Tuple[int, TextRow, Dict[str, Tuple[float, float]]]] = []
    for i, row in enumerate(page_rows):
        c = _candidate_header(row)
        if c is None:
            continue
        _, cols = c
        cands.append((i, row, cols))

    if not cands:
        return []

    headers: List[HeaderRow] = []
    used: List[bool] = [False] * len(cands)

    median_h = max(2.0, sum(r.bbox.height for _, r, _ in cands) / len(cands))

    for ci, (i, row, cols) in enumerate(cands):
        if used[ci]:
            continue
        used[ci] = True

        merged = dict(cols)
        anchor_row = row

        # try to merge with the next candidate row(s) that are vertically
        # close — pdfminer often splits a single visual header into two
        # rows when font sizes differ between cells
        for cj in range(ci + 1, len(cands)):
            if used[cj]:
                continue
            j, r2, cols2 = cands[cj]
            dy = anchor_row.bbox.y1 - r2.bbox.y2
            # max one line-height gap between the two header rows
            if dy > median_h * 1.6:
                break
            # merge: take new column ranges where we don't already have them,
            # OR where the new ones are clearly the numeric (narrower) ones
            for k, v in cols2.items():
                if k not in merged:
                    merged[k] = v
                elif k in _VALUE_COLS:
                    # prefer the narrower/lower row for value columns since
                    # they more precisely overlay the data below
                    old = merged[k]
                    if (v[1] - v[0]) < (old[1] - old[0]):
                        merged[k] = v
            used[cj] = True
            # if r2 has min/typ/max it's likely the lower of the two header
            # rows — use it as the anchor for any subsequent merge
            if any(k in cols2 for k in ("min", "typ", "max")):
                anchor_row = r2

        # final filter: still need at least one numeric column
        if not any(k in merged for k in ("min", "typ", "max", "values")):
            continue
        headers.append(HeaderRow(row=anchor_row, cols=merged))

    return headers


# ---------- value parsing ----------


_NUM_RE = re.compile(r"^[+\-]?\d+(?:\.\d+)?$")
_NUM_NAN_RE = re.compile(r"^(?:[+\-]?\d+(?:\.\d+)?|[-+]+|nan|\.\.\.|---?|~|N/A)$",
                         re.IGNORECASE)
_PM_NUM_RE = re.compile(r"^\+\-?\d+(?:\.\d+)?$")


def _is_numeric_token(s: str) -> bool:
    if not s:
        return False
    s = s.strip().strip(",;")
    if _NUM_RE.match(s):
        return True
    if _PM_NUM_RE.match(s):
        return True
    if s.startswith("(") and s.endswith(")"):
        s2 = s[1:-1]
        if _NUM_RE.match(s2):
            return True
    return False


def _is_nan_token(s: str) -> bool:
    s = s.strip().strip(",;")
    if not s:
        return True
    return bool(re.match(r"^[-+]+$", s)) or s.lower() in {"nan", "n/a", "--", "---", "—", "~"}


# units recognized by dslib.pdf.expr.any_unit, but we keep a small whitelist
# for predictability
_UNIT_TOKENS = {
    # time
    "ns", "us", "μs", "µs", "ms", "s",
    # capacitance
    "pF", "nF", "uF", "μF", "µF",
    # voltage
    "V", "mV", "kV",
    # current
    "A", "mA", "μA", "µA", "uA", "nA",
    # charge
    "nC", "uC", "μC", "µC", "pC",
    # resistance
    "Ω", "mΩ", "kΩ", "Ohm", "mOhm",
    # transconductance
    "S", "mS",
}


def _looks_like_unit(s: str) -> bool:
    s = s.strip(",;:")
    if not s:
        return False
    if s in _UNIT_TOKENS:
        return True
    # pdfminer may decode Ω as a CID glyph
    if s.startswith("(cid:") and s.endswith(")"):
        # might be a fancy Ω — usually next to a resistance value
        return False
    return False


def _join_value_words(words: List[Word]) -> str:
    """Join words inside one column cell into a single string."""
    return " ".join(w.text for w in words).strip()


@dataclass
class ExtractedRow:
    """A detected symbol row with its captured values."""
    symbol: str
    row: TextRow
    values: Dict[str, str]  # 'min'/'typ'/'max'
    unit: Optional[str]
    cond: Optional[str]
    page_num: int


def _value_str_from_column(row: TextRow,
                           x1: float, x2: float) -> Optional[str]:
    """Pick the best numeric/nan token from words inside the column."""
    cand: List[Word] = []
    for w in row.words:
        cx = w.bbox.cx
        if x1 <= cx <= x2:
            cand.append(w)

    if not cand:
        return None

    # collapse adjacent words (eg. "1 . 25") that should join
    cand.sort(key=lambda w: w.bbox.x1)

    # prefer a single numeric or nan-like token; otherwise join
    if len(cand) == 1:
        s = cand[0].text.strip(",;")
        return s

    joined = _join_value_words(cand)
    # squeeze whitespace inside decimal numbers — pdf occasionally splits
    sj = re.sub(r"(\d)\s+(\d)", r"\1\2", joined)
    sj = re.sub(r"(\d)\s+\.\s+(\d)", r"\1.\2", sj)
    return sj.strip()


def _unit_from_column(row: TextRow,
                      cols: Dict[str, Tuple[float, float]],
                      next_row: Optional[TextRow] = None) -> Optional[str]:
    """Look up the unit string in the unit column (if a header was defined)."""
    if "unit" not in cols:
        # try to infer from the right-most word of the row
        if row.words:
            tail = row.words[-1].text.strip(",;")
            if _looks_like_unit(tail) or tail in {"Ω", "nC", "pF", "ns"}:
                return tail
        return None

    x1, x2 = cols["unit"]
    cand = [w for w in row.words if x1 <= w.bbox.cx <= x2]
    if not cand:
        return None
    return _join_value_words(cand).strip()


def _cond_from_column(row: TextRow,
                      cols: Dict[str, Tuple[float, float]]) -> Optional[str]:
    """Read the text of the condition column for a row, if defined."""
    if "cond" not in cols:
        return None
    x1, x2 = cols["cond"]
    cand = [w for w in row.words if x1 <= w.bbox.cx <= x2]
    if not cand:
        return None
    return _join_value_words(cand).strip()


# ---------- bandying it all together ----------


def _row_chunks_below_header(headers: List[HeaderRow],
                             rows: List[TextRow],
                             header_idx: int) -> List[TextRow]:
    """Rows between this header and the next header (exclusive)."""
    h_row = headers[header_idx].row
    end_y = -math.inf
    if header_idx + 1 < len(headers):
        end_y = headers[header_idx + 1].row.bbox.y2

    out: List[TextRow] = []
    seen_header = False
    for r in rows:
        if not seen_header:
            if r is h_row:
                seen_header = True
            continue
        if end_y > -math.inf and r.bbox.cy <= end_y:
            break
        if r is h_row:
            continue
        out.append(r)
    return out


def _extract_value(s: Optional[str]) -> Optional[str]:
    """Filter raw column-cell text down to a meaningful value token."""
    if s is None:
        return None
    s = s.strip().strip(",;")
    if not s:
        return None
    return s


def _values_for_row(row: TextRow,
                    cols: Dict[str, Tuple[float, float]]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for k in ("min", "typ", "max"):
        if k not in cols:
            continue
        x1, x2 = cols[k]
        v = _value_str_from_column(row, x1, x2)
        v = _extract_value(v)
        if v is not None:
            values[k] = v
    return values


def _strip_symbol_words(row: TextRow,
                        m: re.Match,
                        cols: Dict[str, Tuple[float, float]]) -> List[Word]:
    """Words *outside* the symbol/param/cond columns (left side of table).

    Helpful for spotting a unit/condition that's been written together with
    the parameter description.
    """
    excluded = []
    for k in ("sym", "param", "cond"):
        if k in cols:
            excluded.append(cols[k])

    out: List[Word] = []
    for w in row.words:
        cx = w.bbox.cx
        if any(x1 <= cx <= x2 for (x1, x2) in excluded):
            continue
        out.append(w)
    return out


def _detect_symbol_on_row(mfr: str,
                          row: TextRow,
                          cols: Dict[str, Tuple[float, float]]):
    """Detect at most one parameter symbol on a row.

    Strategy, in priority order:
      1. phrase that falls within the explicit ``sym`` column (the strongest
         signal — beats the description column)
      2. phrase within the ``param`` column
      3. detection on the whole-row text
      4. any other phrase

    Phrase-by-phrase detection is needed because the full-row text can
    contain stop-words that block a per-phrase match (e.g. "Turn-On Rise
    Time").
    """
    phrases = row.phrases()
    sym_x = cols.get("sym")
    param_x = cols.get("param")

    def phrase_text(ph):
        return " ".join(w.text for w in ph).strip()

    def in_xspan(ph, span):
        if not span or not ph:
            return False
        cx = sum(w.bbox.cx for w in ph) / len(ph)
        return span[0] <= cx <= span[1]

    # 1. symbol column
    if sym_x:
        for ph in phrases:
            if not in_xspan(ph, sym_x):
                continue
            txt = phrase_text(ph)
            if not txt:
                continue
            s = detect_fields(mfr, [txt])
            if s:
                return s

    # 2. parameter-description column
    if param_x:
        for ph in phrases:
            if not in_xspan(ph, param_x):
                continue
            txt = phrase_text(ph)
            if not txt:
                continue
            s = detect_fields(mfr, [txt])
            if s:
                return s

    # 3. whole-row text
    if row.text:
        s = detect_fields(mfr, [row.text])
        if s:
            return s

    # 4. any remaining phrase
    for ph in phrases:
        txt = phrase_text(ph)
        if not txt:
            continue
        s = detect_fields(mfr, [txt])
        if s:
            return s
    return None


def parse_rows_for_page(mfr: str,
                        page: Page,
                        headers: List[HeaderRow]) -> List[ExtractedRow]:
    """Yield ExtractedRow for every detected parameter row on the page."""
    out: List[ExtractedRow] = []
    if not headers:
        return out

    rows = page.rows

    for hi, header in enumerate(headers):
        body = _row_chunks_below_header(headers, rows, hi)
        for body_row in body:
            text = body_row.text
            if not text:
                continue
            sym = _detect_symbol_on_row(mfr, body_row, header.cols)
            if not sym:
                continue
            values = _values_for_row(body_row, header.cols)
            unit = _unit_from_column(body_row, header.cols)
            cond = _cond_from_column(body_row, header.cols)
            if not any(_is_numeric_token(v) for v in values.values()):
                continue
            out.append(ExtractedRow(symbol=sym.symbol,
                                    row=body_row,
                                    values=values,
                                    unit=unit,
                                    cond=cond,
                                    page_num=page.page_num))
    return out
