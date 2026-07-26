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
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from dslib.pdf.parse import detect_fields
from dslib.v2.chars import Page, TextRow, Word

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


@dataclass
class HeaderRow:
    row: TextRow
    # x-range (x1, x2) of each detected header column, keyed by group name
    cols: Dict[str, Tuple[float, float]] = field(default_factory=dict)


_VALUE_COLS = ("min", "typ", "max", "values", "unit")

# How far apart (in multiples of the symbol row's height) a symbol row and its
# value row may sit and still be treated as one table row.
_PAIR_MAX_ROW_GAP = 2.5


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
            _, r2, cols2 = cands[cj]
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
    # A cell may carry its own unit instead of relying on a unit column
    # ("150 V", "3700 pF"). Rejecting those dropped every row of a diotec
    # sheet, which then extracted nothing at all.
    return _num_with_unit(s)[0] is not None


def _num_with_unit(s: str):
    """Split "150 V" into (150.0, "V"); (None, None) when it is not that.

    Delegates to ``dslib.field.get_value_with_unit`` so v2 accepts exactly the
    units the rest of the project does, rather than a second private list that
    could drift out of step.
    """
    from dslib.field import get_value_with_unit
    v, u = get_value_with_unit(s)
    if isinstance(v, (int, float)) and not math.isnan(v):
        return float(v), u
    return None, None


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


_UNIT_ONLY_RE = None

_CID_GLYPHS = ((r"\(cid:2\)", "Ω"), (r"\(cid:4\)", "μ"))

_SI_PREFIXES = frozenset("mkM")
# Base unit per dimension, for rebuilding a cell that kept only its prefix.
# Resistance only: it is the dimension where the lost glyph (Omega, from a
# Symbol font) is common and where the reconstruction is safe — "m" rebuilds
# to the mOhm dslib already assumes, so the number cannot move, only become
# emittable. Charge and time have no such guarantee ("m" on a Qg row would
# read as milli-coulomb, a unit no datasheet uses), so they are left alone
# until there is evidence for them.
_DIMENSION_BASE_UNIT = {"R": "Ω"}


def _map_cid_glyphs(s: str) -> str:
    """Resolve the ``(cid:N)`` tokens pdfminer emits for undecodable glyphs.

    Must happen *before* a unit is validated, not after: the Omega in an
    onsemi rDS(ON) unit cell arrives only as ``(cid:2)``, so validating first
    would discard it as unreadable and leave the value unscaled.
    """
    for pat, repl in _CID_GLYPHS:
        s = re.sub(pat, repl, s)
    return s


def _clean_unit(s: Optional[str], symbol: Optional[str] = None) -> Optional[str]:
    """Reduce a unit cell to a bare unit token, or None.

    The unit column's x-range is derived from a header label's centre, so it
    routinely catches neighbouring cells: real captures include
    ``"2.7 2.7 3.1 m V =10V,I"`` for an Rds_on row and ``"1.0 1.5 W -"`` for
    Rg. Passing those through is not a cosmetic wart — ``dslib.field.Field``
    converts resistance to the canonical mOhm only when it *recognises* the
    unit, so an unrecognised one silently skips conversion and leaves 0.00685
    where the datasheet says 6.85 mOhm. On an independent 120-part sample that
    accounted for 48 of 92 disagreements, all of them factor-1000, and it is
    invisible to any metric that normalises units before comparing.

    Returning None for an unreadable cell is the safe answer: ``Field`` then
    has no unit to trust rather than a bogus one to ignore.
    """
    global _UNIT_ONLY_RE
    if _UNIT_ONLY_RE is None:
        from dslib.pdf.expr import any_unit
        _UNIT_ONLY_RE = re.compile(r"^(%s)$" % any_unit)

    if not s:
        return None
    mapped = _map_cid_glyphs(s).strip()
    # Note the order: cid tokens are removed from the *unstripped* text,
    # because stripping ",;:()" first eats the closing paren and leaves
    # "m(cid:3" for the pattern below to miss.
    no_cid = re.sub(r"\(cid:\d+\)", "", mapped).strip()
    s = mapped.strip(",;:()")
    if not s:
        return None
    dim = _symbol_dimension(symbol) if symbol else None

    # A unit cell holding nothing but an SI prefix means the base glyph was
    # lost in decoding: a renesas rDS(on) row reads "- 6.9 8.9 m", i.e. "mΩ"
    # minus its Omega. A bare prefix is not a unit in any dimension, and the
    # symbol pins down the base, so this reads the cell rather than guessing
    # at it. (For resistance it does not even change the number — mOhm is what
    # dslib assumes anyway — it just lets the value be emitted at all instead
    # of being dropped as unitless.)
    if dim is not None and dim in _DIMENSION_BASE_UNIT:
        # The base glyph may be missing outright ("m") or still present as a
        # cid token this font's map does not resolve ("m(cid:3)" on
        # onsemi/NTMFWS1D5N08XT1G). Both are the same cell with the same
        # reading; requiring the WHOLE remainder to be one prefix plus cid
        # tokens keeps this from touching a cell that merely contains an
        # unreadable glyph among real content.
        if s in _SI_PREFIXES:
            return s + _DIMENSION_BASE_UNIT[dim]
        if no_cid != mapped and no_cid in _SI_PREFIXES:
            return no_cid + _DIMENSION_BASE_UNIT[dim]

    unit = None
    if _UNIT_ONLY_RE.match(s):
        unit = s
    else:
        # a cell like "nC 1)" — keep it only if exactly one token is a unit
        hits = [t for t in re.split(r"[\s/]+", s) if _UNIT_ONLY_RE.match(t)]
        if len(hits) == 1:
            unit = hits[0]

    if unit is None or symbol is None:
        return unit

    # The unit must belong to the symbol's dimension. Salvaging a lone token
    # out of a mis-captured cell otherwise yields nonsense like unit="V" on an
    # Rds_on row (from "2.7 2.7 3.1 m V =10V,I"), which reads as a real unit
    # downstream and is worse than admitting we could not read it.
    dim = _symbol_dimension(symbol)
    if dim is not None and not _dimension_unit_re(dim).match(unit):
        return None
    return unit


# Symbol -> key in dslib.pdf.expr.DIMENSIONS. A unit from another dimension is
# always a mis-capture, and accepting one rescales the value silently.
_SYMBOL_DIMENSION = {
    "Rds_on": "R", "Rg": "R", "Rds_on_10v": "R",
    "Qg": "Q", "Qgs": "Q", "Qgd": "Q", "Qg_th": "Q", "Qgs2": "Q", "Qsw": "Q",
    "Qoss": "Q", "Qrr": "Q", "Qg_sync": "Q", "Qsync": "Q",
    "tRise": "t", "tFall": "t", "tDon": "t", "tDoff": "t", "trr": "t",
    "Coss": "C", "Ciss": "C", "Crss": "C", "Coss_TR": "C", "Coss_ER": "C",
    "Vds": "V", "Vgs_th": "V", "Vpl": "V", "Vsd": "V",
    "Id": "I", "Idp": "I", "ID_25": "I",
    "gfs": "g",
}


def _symbol_dimension(symbol: str) -> Optional[str]:
    return _SYMBOL_DIMENSION.get(symbol)


@lru_cache(maxsize=None)
def _dimension_unit_re(dim: str):
    from dslib.pdf.expr import DIMENSIONS
    return re.compile(r"^(%s)$" % DIMENSIONS[dim].unit_regex)


def _unit_from_column(row: TextRow,
                      cols: Dict[str, Tuple[float, float]],
                      symbol: Optional[str] = None) -> Optional[str]:
    """Look up the unit string in the unit column (if a header was defined)."""
    if "unit" not in cols:
        # try to infer from the right-most word of the row
        if row.words:
            tail = row.words[-1].text.strip(",;")
            if _looks_like_unit(tail) or tail in {"Ω", "nC", "pF", "ns"}:
                return _clean_unit(tail, symbol)
        return None

    x1, x2 = cols["unit"]
    cand = [w for w in row.words if x1 <= w.bbox.cx <= x2]
    unit = _clean_unit(_join_value_words(cand).strip(), symbol) if cand else None
    if unit is not None:
        return unit

    # The column is derived from a header label's centre, so it misses the
    # cell on plenty of rows. Before giving up — and an absent unit is not
    # neutral, it makes Field treat a resistance as already-canonical mOhm —
    # look for a unit of the right dimension among the row's trailing words.
    for w in reversed(row.words):
        got = _clean_unit(w.text, symbol)
        if got is not None:
            return got
    return None


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


def _headers_that_explain_numbers(headers: List[HeaderRow],
                                  rows: List[TextRow]) -> List[HeaderRow]:
    """Drop headers whose numeric columns sit above no numbers at all.

    ``head_re`` matches on words, so a section title reads as a header: TI's
    "absolute maximum ratings over operating free-air temperature" yields
    max="maximum" and values="ratings", and the columns derived from it are
    nonsense (typ="VDS", max="voltage"). ``head_stop`` exists to catch exactly
    this, but it matches case-sensitively and that sheet is lowercase — a
    guard that is right in intent and silently never fires.

    Validating the *derived columns* instead of blacklisting words is monotone
    and indifferent to case, language and vendor: a real header explains
    numbers, so at least one row beneath it must parse as numeric in one of
    its numeric columns. A bogus header is not merely useless — it truncates
    the row range of the real header above it.
    """
    keep: List[HeaderRow] = []
    for hi in range(len(headers)):
        for body_row in _row_chunks_below_header(headers, rows, hi):
            values = _values_for_row(body_row, headers[hi].cols)
            if any(_is_numeric_token(v) for v in values.values()):
                keep.append(headers[hi])
                break
    return keep


def _pair_split_rows(scan: List[dict], i: int) -> List[TextRow]:
    """Value rows belonging to a symbol row that carries no numbers.

    Where one parameter is measured under several conditions, the label and
    symbol are often set once, vertically centred against the block of
    condition rows::

        Static Drain-Source On-Resistance  RDS(ON)  -  3.1  4.0  mOhm  VGS = 10V
                                                    -  4.4  5.7  mOhm  VGS = 6V

    The label lands on its own row with no numbers while the numbers land on
    rows with no symbol, and taking either alone yields nothing.

    Both neighbours are returned, above first, because which side holds the
    *primary* condition varies by vendor — a diodes sheet centres the label
    below its first condition row, an mcc sheet puts it above. Returning both
    in page order lets the normal merge pick the topmost, which is the
    condition datasheets lead with; guessing a side got Rds_on wrong on 15
    parts by silently reading the secondary condition.

    Only rows that name no symbol of their own are eligible — a neighbour with
    its own symbol owns its values, and stealing them would attach real
    numbers to the wrong parameter, which is worse than the miss this repairs.
    Adjacency in the row list is not enough either: rows are dropped along the
    way, so neighbours in the list can be far apart on the page.
    """
    row = scan[i]["row"]
    reach = max(row.bbox.height, 1.0) * _PAIR_MAX_ROW_GAP

    out: List[TextRow] = []
    for j in (i - 1, i + 1):
        if not (0 <= j < len(scan)):
            continue
        other = scan[j]
        if not other["has_num"] or other["sym"]:
            continue
        if abs(other["row"].bbox.cy - row.bbox.cy) <= reach:
            out.append(other["row"])
    return out


def parse_rows_for_page(mfr: str,
                        page: Page,
                        headers: List[HeaderRow]) -> List[ExtractedRow]:
    """Yield ExtractedRow for every detected parameter row on the page."""
    out: List[ExtractedRow] = []
    if not headers:
        return out

    rows = page.rows
    headers = _headers_that_explain_numbers(headers, rows)

    for hi, header in enumerate(headers):
        body = _row_chunks_below_header(headers, rows, hi)

        # Describe every body row once: what symbol it names, what numbers it
        # holds. Both halves are needed up front because they are frequently
        # on *different* rows (see _pair_split_row).
        scan: List[dict] = []
        for body_row in body:
            if not body_row.text:
                continue
            values = _values_for_row(body_row, header.cols)
            scan.append(dict(
                row=body_row,
                sym=_detect_symbol_on_row(mfr, body_row, header.cols),
                values=values,
                has_num=any(_is_numeric_token(v) for v in values.values()),
            ))

        for i, item in enumerate(scan):
            if not item["sym"]:
                continue
            if item["has_num"]:
                value_rows = [item["row"]]
            else:
                value_rows = _pair_split_rows(scan, i)
            for value_row in value_rows:
                values = (item["values"] if value_row is item["row"]
                          else _values_for_row(value_row, header.cols))
                symbol = item["sym"].symbol
                unit = _unit_from_column(value_row, header.cols, symbol)
                if unit is None and value_row is not item["row"]:
                    # On a split row the unit is printed once, against the
                    # label — vishay/SiSS126DN puts "Ohm" there while the
                    # condition row carries only numbers. Reading only the
                    # value row left the unit unknown, and an unknown
                    # resistance unit is not a gap: Field then treats 0.00685
                    # as already-canonical mOhm instead of 6.85.
                    unit = _unit_from_column(item["row"], header.cols, symbol)
                out.append(ExtractedRow(symbol=symbol,
                                        row=value_row,
                                        values=values,
                                        unit=unit,
                                        cond=_cond_from_column(value_row, header.cols),
                                        page_num=page.page_num))
    return out
