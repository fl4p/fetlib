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
                # A trailing Conditions column runs to the edge of the table,
                # and its content is routinely many times wider than the word
                # "Conditions" — so deriving its right edge from the label
                # truncates it. infineon/IPW65R040CM8 prints
                # "V GS=10V, I D=25.0A, T j=25°C" and the label-derived bound
                # cut it at "V GS=10V, I", which silently discarded Tj. That
                # loss is not a missing extra: the 25°C row (40 mOhm) and the
                # 150°C row (73 mOhm) then carry IDENTICAL conditions, and no
                # consumer can tell them apart afterwards.
                #
                # Only the trailing edge of `cond` is opened up. The leading
                # edge of `param` is deliberately left alone — it feeds symbol
                # detection in _detect_symbol, where a wider span changes which
                # phrase wins.
                x2 = math.inf if g == "cond" else w.bbox.x2 + max(w.bbox.width, 8.0)
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


def _clamp_open_cond(cols: Dict[str, Tuple[float, float]]) -> None:
    """Close an open-ended Conditions column against its real right neighbour.

    ``_header_columns`` opens ``cond`` to infinity when nothing was detected to
    its right, but it decides that from ONE candidate row, and a two-row header
    is merged afterwards. A Conditions label that is rightmost on its own row
    stops being rightmost once Min/Typ/Max/Unit arrive from the row below, and
    its span then lies across every value column.

    Measured on crmicro/CS20N50FA9R: cond stayed (251.0, inf) over min
    (413.3, 444.7) and max (477.7, 512.4), so the V(BR)DSS condition cell read
    "Voltage VGS=0V, ID=250uA 500 -- -- V" and contributed Id=500 A against a
    printed 250 uA. 25 of 564 detected headers in a 267-file sample were
    geometrically exposed this way.
    """
    span = cols.get("cond")
    if span is None or span[1] != math.inf:
        return
    right = [x1 for k, (x1, _) in cols.items() if k != "cond" and x1 > span[0]]
    cols["cond"] = (span[0], min(right) if right else math.inf)


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
        _clamp_open_cond(merged)
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
    # How ``cond`` was established: "cell" when the sheet's own ruling lines
    # bounded the Conditions cell, "wrap" when it was inferred from proximity.
    # These are not equally trustworthy and must not look alike downstream --
    # a detector that silently degrades to a guess while reporting success is
    # worse than one that says it had no boundary evidence.
    cond_src: Optional[str] = None


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


# How far apart (in row heights) the two halves of one logical row may sit.
_SIBLING_MAX_ROW_GAP = 1.5


def _unit_from_symbol_sibling(scan: List[dict], idx: int,
                              cols: Dict[str, Tuple[float, float]],
                              symbol: str) -> Optional[str]:
    """Find the unit on an adjacent row that names the SAME symbol.

    One logical table row is sometimes typeset on two baselines, with the
    symbol, conditions and unit on one and the parameter wording and the
    numbers on the other. ao/AOB66515L splits them by 1.6 pt::

        y368.7  Qrr                                 IF=20A, di/dt=500A/ms   uC
        y367.1  Body Diode Reverse Recovery Charge                        1.18

    Both rows resolve to Qrr -- the lower one via its wording -- but the lower
    one carries the numbers, so it is taken as its own value row and the unit
    on the line above is never consulted. The result is a bare 1.18 that
    ``Field`` reads as nC where the sheet says microcoulombs: 1000x low, on a
    symbol printed in BOTH scales across this corpus.

    Charge cannot be rescued the way resistance is, by refusing implausibly
    small values: the DB's own Qrr population runs to a 1% point of 1.2 nC and
    a minimum of 0.18 nC, so a lost-microcoulomb 1.18 sits *inside* the real
    distribution and no floor separates the two. Reading the unit that is
    printed on the sheet is the only honest fix.

    The pairing evidence required is deliberately narrow: an immediate
    neighbour, naming the same symbol, holding no numbers of its own (so it is
    the other half of this row and not the next parameter). If both neighbours
    offer a unit and they disagree, this returns None -- an ambiguous unit is
    the failure being prevented, not an acceptable guess.
    """
    row = scan[idx]["row"]
    h = max(row.bbox.height, 1.0)
    found: List[str] = []
    for j in (idx - 1, idx + 1):
        if not (0 <= j < len(scan)):
            continue
        sib = scan[j]
        if sib["has_num"] or not sib["sym"]:
            continue
        if sib["sym"].symbol != symbol:
            continue
        if abs(row.bbox.cy - sib["row"].bbox.cy) > _SIBLING_MAX_ROW_GAP * h:
            continue
        got = _unit_from_column(sib["row"], cols, symbol)
        if got is not None:
            found.append(got)
    # Agreement between both neighbours is not ambiguity, only disagreement is.
    if len(set(found)) != 1:
        return None
    return found[0]


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


# A bare voltage parenthesised in the symbol cell, as in "Qg(4.5V)".
_LABEL_VOLTAGE_RE = re.compile(r'\(\s*(\d+(?:\.\d+)?)\s*V\s*\)', re.I)

# Symbols where that voltage is the GATE DRIVE. Qg alone, deliberately.
# For Qg the parenthesised voltage is the VGS the charge was measured at --
# that is the whole point of printing two of them.
#
# The first version listed every gate-charge symbol, which was wrong on
# physics, not merely broad: Qoss is OUTPUT charge versus DRAIN voltage, so
# "Qoss(100V)" names VDS and calling it VGS = 100 V invents a gate drive no
# part has. That is the failure this whole function exists to prevent, so
# guessing the key from the symbol's family is not good enough -- each symbol
# has to earn its entry with grounded semantics. Extending to resistance would
# likewise need its own evidence: "RDS(on)" already parenthesises a word, and
# while "(on)" cannot match a number, some vendor's "R(4.5V)" might mean
# something else entirely.
_LABEL_VOLTAGE_SYMBOLS = frozenset({"Qg"})


def _cond_from_symbol_label(row: TextRow,
                            cols: Dict[str, Tuple[float, float]],
                            symbol: str) -> Optional[str]:
    """Recover a condition printed inside the SYMBOL, not the Conditions cell.

    ao/AOT284L states the gate drive in the parameter's own name::

        Qg (10V)  Total Gate Charge   71   100 nC
        Qg(4.5V)  Total Gate Charge  33.5   48 nC

    both under ONE merged "VDS=40V, VGS=10V, ID=20A" conditions cell. No
    amount of cell-boundary work reaches this: the cell is genuinely shared,
    and the thing that separates the rows was never in it. Without the label
    the two rows are indistinguishable, so ``_get_by_cond`` asking for VGS=10
    can return the 4.5 V charge -- and Qg times gate-drive voltage is a loss
    term the tool ranks on, so that is a wrong number rather than a lost one.

    Measured over 100 random sheets: this pattern occurs 6 times and is `Qg`
    every time, always as a 10 V / 4.5 V pair. It is narrow on purpose.
    """
    if symbol not in _LABEL_VOLTAGE_SYMBOLS or "sym" not in cols:
        return None
    x1, x2 = cols["sym"]
    cell = ' '.join(w.text for w in row.words if x1 <= w.bbox.cx <= x2)
    m = _LABEL_VOLTAGE_RE.search(cell)
    if not m:
        return None
    return "VGS = %s V" % m.group(1)


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
        if not _header_has_structure(headers[hi]):
            continue
        for body_row in _row_chunks_below_header(headers, rows, hi):
            values = _values_for_row(body_row, headers[hi].cols)
            if any(_is_numeric_token(v) for v in values.values()):
                keep.append(headers[hi])
                break
    return keep


# A header offering nothing but a "typ"/"values" column carries no structure:
# it is a FIGURE CAPTION that matched head_re on the word "Typ.".
_CAPTION_ONLY_COLS = frozenset({"typ", "values"})


def _header_has_structure(header: HeaderRow) -> bool:
    """Reject a caption that merely contains the word "Typ.".

    Validating that a header explains NUMBERS is necessary but not sufficient,
    because a chart page trivially satisfies it -- axis ticks are numbers. The
    two live cases both come from figure captions::

        infineon/IPA65R110CFDXKSA1 pg12
            "Typ. capacitances Typ. COUU stored energy"   -> cols {typ}
        nxp/GAN3R2-100CBEAZ pg8
            "charge; typical values values"               -> cols {typ, values}

    which then read an axis tick as a value: Crss.typ=1.0 and Id.typ=0.0 (0
    and 1 being axis ORIGINS is the tell). Id.typ=0.0 is not a stray extra --
    ``DatasheetFields.fill`` merges it into the real Id rating field, so a
    consumer selects 0.0 for a rating.

    A genuine parameter-table header always says more than "typical": it names
    a symbol, a parameter, a unit, conditions, or a min/max to sit beside the
    typ. Requiring one of those is a statement about table STRUCTURE, so
    unlike a word blacklist it does not care about vendor, language or decade.
    """
    return bool(set(header.cols) - _CAPTION_ONLY_COLS)


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


# A wrapped condition line sits within this many row-heights of the line it
# continues. Tighter than _PAIR_MAX_ROW_GAP: this is the next line of one cell,
# not a neighbouring row of the table.
_COND_WRAP_MAX_GAP = 1.6
# Reach allowed when the line above ends on a dangling "," or ";". The
# separator is the evidence that a continuation exists; distance is only a
# sanity bound, so it can be looser. Measured need: st/ST8L65N044M9 puts the
# overflow 1.77 row-heights below its line, past the 1.6 above.
_COND_DANGLING_MAX_GAP = 2.5


def _scan_index(scan: List[dict], row: TextRow) -> Optional[int]:
    for k, it in enumerate(scan):
        if it["row"] is row:
            return k
    return None


def _cond_with_continuation(scan: List[dict], idx: int,
                            cols: Dict[str, Tuple[float, float]]) -> Optional[str]:
    """Condition text of a row plus any wrapped continuation lines below it.

    A condition cell that does not fit on one line wraps, and the overflow
    becomes a row of its own holding nothing else. nxp/GANE3R9-150QBAZ::

        QGD gate-drain charge  ID = 30 A; VDS = 75 V; VGS = 5 V;  - 3.5 - nC
                               Tj = 25 °C; Fig. 11; Fig. 12
        QG(tot) total gate charge                                 -  20 - nC

    Reading only the first line loses Tj entirely, and Tj is exactly what
    separates a 25 °C row from a 125 °C one.

    Attached DOWNWARD, and that is the whole trick: the continuation sits 10.8
    pt below the row it belongs to but only 4.4 pt above the NEXT parameter
    row, so nearest-row would hand it to the wrong one. Text wraps downward, so
    line two belongs to the cell that began on line one — direction decides it,
    distance cannot.

    Only rows naming no symbol and holding no numbers are eaten. A row with
    either owns its own conditions, and absorbing it would merge two
    parameters' test setups into one.

    Deliberately NOT block inheritance: this does not give QG(tot) above its
    conditions, even though on this sheet the cell is vertically merged across
    the whole gate-charge block and they do apply to it. A row that states no
    condition is structurally identical to one whose neighbour's conditions are
    none of its business — in the same sample, an abs-max Vds row sits directly
    under "ID drain current VGS = 5 V; Tmb = 25 °C", which it must not inherit.
    Without ruling lines the two cannot be told apart, and inventing a
    condition is worse than missing one: it makes a candidate confidently
    selectable under a setup the datasheet never claimed.
    """
    row = scan[idx]["row"]
    base = _cond_from_column(row, cols)
    parts = [base] if base else []
    h = max(row.bbox.height, 1.0)
    prev_cy = row.bbox.cy
    for j in range(idx + 1, len(scan)):
        nxt = scan[j]
        if nxt["has_num"]:
            break
        dangling = bool(parts and parts[-1].rstrip().endswith((',', ';')))
        reach = h * (_COND_DANGLING_MAX_GAP if dangling else _COND_WRAP_MAX_GAP)
        if prev_cy - nxt["row"].bbox.cy > reach:
            break
        # A wrapped line does not always get a row to itself. On
        # st/ST8L65N044M9 the overflow shares a row with the NEXT parameter's
        # symbol:
        #     trr Reverse recovery time  ISD = 58 A, di/dt = 100 A/us,  - 410 ns
        #     Qrr                        VDD = 60 V, TJ = 150 C
        #     Reverse recovery charge                                   - 0.8 uC
        # so requiring the row to name no symbol drops TJ = 150 C, and TJ is the
        # only thing separating that trr from the 25 C one printed above it.
        #
        # The signal that it IS a continuation comes from the text, not the
        # geometry: the line above ends on a comma or semicolon, i.e. the list
        # is unfinished. A row whose own conditions merely happen to sit nearby
        # does not follow a dangling separator, so this stays out of the case
        # the block-inheritance note below refuses to guess at.
        if nxt["sym"] and not dangling:
            break
        text = _cond_from_column(nxt["row"], cols)
        if not text:
            break
        parts.append(text)
        prev_cy = nxt["row"].bbox.cy
    if not parts:
        return None
    return ' '.join(parts).strip() or None


def _cond_from_cell(page: Page, scan: List[dict], idx: int,
                    cols: Dict[str, Tuple[float, float]]) -> Optional[str]:
    """Condition text of the whole ruled Conditions CELL containing this row.

    This is the answer to the case ``_cond_with_continuation`` documents and
    refuses: a Conditions cell merged down several value rows. Where the sheet
    draws its table, the cell's extent is a fact rather than a proximity guess,
    so the two shapes that look identical to a heuristic --

        QG(tot)  <- shares the gate-charge block's merged condition cell
        VDS      <- abs-max row that must NOT inherit "VGS = 5 V" above it

    -- are separated by whether a ruling runs between them in this column.

    Returns None whenever the page cannot answer: no rulings, an unbounded
    band, or a band with no interior ruling in a neighbouring column (which
    means only the table outline is drawn, so every column would claim to be
    one merged cell). The caller then falls back to the wrap heuristic, i.e.
    exactly today's behaviour -- this only ever adds knowledge, never
    substitutes a guess for a gap.
    """
    if "cond" not in cols or not page.pdf_path:
        return None
    # Rulings are read via fitz in fitz's coordinate space. When the text came
    # from pdfminer the two frames are only guaranteed to agree for an
    # unrotated page whose cropbox matches its mediabox; a reviewer reproduced
    # a synthetic cropbox where they do not, which would put bands and
    # baselines in different spaces and attach silently wrong conditions.
    # No datasheet in a 1000-PDF sample trips it, so this costs nothing today
    # and is not worth guessing a transform for -- refuse instead.
    #
    # The first version tested chars.DEFAULT_BACKEND, which is "auto" in every
    # normal run: auto resolves per FILE and hands back pdfminer pages whenever
    # fitz lost a glyph (~20% of the corpus), and an explicit
    # extract_pages_with_rows(backend="pdfminer") never consults the default at
    # all. So the guard read "pdfminer" almost never, and the case it exists to
    # refuse walked straight through it -- a precondition checked against the
    # wrong variable is not checked. The page now carries its resolved backend.
    #
    # Non-fitz pages are then tested on the thing that actually matters rather
    # than turned away: whether fitz's frame coincides with theirs. Refusing
    # them outright measured as 474 lost conditions over 126 pdfminer parts,
    # all the inspected ones correct -- the guard would have fired hard and in
    # the wrong direction.
    from dslib.v2 import rules as _rules

    if not page.backend:
        # Unknown provenance refuses outright, as Page.backend's own docstring
        # says it must. frame_matches would be the wrong question here: it
        # checks that FITZ's geometry is ordinary, which says nothing about the
        # frame an unidentified producer put these baselines in. Letting "" fall
        # through to it would answer a question nobody asked and call the answer
        # evidence. No production constructor omits backend today, so this is
        # the latent case -- kept explicit so the claim and the code agree.
        return None
    if page.backend != "fitz":
        mb = page.mediabox
        if not _rules.frame_matches(page.pdf_path, page.page_num,
                                    (mb.x1, mb.y1, mb.x2, mb.y2)):
            return None

    rs = _rules.page_rules(page.pdf_path, page.page_num)
    if not rs:
        return None

    x1, x2 = cols["cond"]
    if not math.isfinite(x2):
        # An open-ended Conditions column has no right edge to measure a
        # ruling against; bound it by the widest ruling on the page so
        # "covers 60% of the column" stays a meaningful test.
        x2 = max((r[2] for r in rs), default=x1)
        if x2 <= x1:
            return None

    # The neighbours are this table's OWN other columns, so "a neighbour is
    # ruled inside the band" is a statement about this table rather than about
    # any stroke that happens to sit elsewhere on the page.
    neighbours = [v for k, v in cols.items()
                  if k != "cond" and math.isfinite(v[0]) and math.isfinite(v[1])]

    row = scan[idx]["row"]
    band = _rules.cell_band(rs, x1, x2, row.bbox.cy)
    if band is None or not _rules.band_is_credible(rs, band, x1, x2, neighbours):
        return None

    top, bottom = band
    symbol = scan[idx]["sym"].symbol if scan[idx].get("sym") else None
    parts: List[str] = []
    same_symbol = 0
    own_cond_rows = 0
    for item in scan:
        cy = item["row"].bbox.cy
        if not (bottom < cy < top):
            continue
        if symbol and item.get("sym") and item["sym"].symbol == symbol:
            same_symbol += 1
        text = _cond_from_column(item["row"], cols)
        if text:
            parts.append(text)
            # A row that carries conditions AND is itself a value row states
            # its own; a bare continuation line (no symbol, no numbers) is the
            # rest of somebody else's cell.
            if item["has_num"] or item.get("sym"):
                own_cond_rows += 1

    # A merged cell holds ONE cell's worth of text, however many lines it wraps
    # onto. If several VALUE rows inside the band each carry their own
    # condition text, the column is not merged there -- it simply was not ruled
    # between them, and joining them produces a blob that destroys the
    # distinctions the sheet did draw. rohm/RJ1P04BBHTL1 prints
    #     VGS = 10V   -  38.0  -
    #     VDD = 50V   -  25.0  -
    # as two separately-conditioned Qg rows; concatenating them gave both the
    # same conditions and made two different values answer the same question.
    if own_cond_rows > 1:
        return None

    # If the SAME symbol occurs twice inside one condition cell, the cell
    # cannot be what separates those rows -- something outside it does, and on
    # this corpus that something is the symbol's own label: ao/AOT284L prints
    #     Qg (10V)  Total Gate Charge   71  100 nC
    #     Qg(4.5V)  Total Gate Charge  33.5  48 nC
    # under one merged "VDS=40V, VGS=10V" cell. Giving both rows VGS=10 attaches
    # to the 4.5 V row a condition the datasheet never claimed for it, and makes
    # two different values look like equally valid answers to the same question.
    # Refusing here costs a condition; inheriting would manufacture a false one,
    # and a wrong condition is worse than a missing one because it is
    # confidently selectable.
    if same_symbol > 1:
        return None
    if not parts:
        return None
    return ' '.join(parts).strip() or None


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
                if unit is None:
                    # The other half of a two-baseline row: same symbol, no
                    # numbers of its own, carrying the unit this row lacks.
                    # Index 0 is falsy, so this must test for None explicitly.
                    u_idx = (i if value_row is item["row"]
                             else _scan_index(scan, value_row))
                    if u_idx is not None:
                        unit = _unit_from_symbol_sibling(
                            scan, u_idx, header.cols, symbol)
                # Continuation is looked up from the VALUE row's own position:
                # on a split row the wrapped condition line follows the row the
                # condition was printed against, not the label above it.
                v_idx = i if value_row is item["row"] else _scan_index(scan, value_row)
                cond_src = None
                if v_idx is None:
                    cond = _cond_from_column(value_row, header.cols)
                else:
                    # The ruled cell is authoritative where the sheet draws
                    # one; the wrap heuristic is what we have when it does not.
                    cond = _cond_from_cell(page, scan, v_idx, header.cols)
                    cond_src = "cell" if cond else None
                    if not cond:
                        cond = _cond_with_continuation(scan, v_idx, header.cols)
                        cond_src = "wrap" if cond else None
                # A condition printed in the symbol's own name is MORE specific
                # than anything the shared Conditions cell says. It goes FIRST
                # because _parse_cond_text keeps the first statement of a key,
                # matching the first-wins priority used throughout dslib — so
                # "Qg(4.5V)" under a merged "VGS=10V" cell reads as 4.5 V.
                label = _cond_from_symbol_label(value_row, header.cols, symbol)
                if label is None and value_row is not item["row"]:
                    label = _cond_from_symbol_label(item["row"], header.cols,
                                                    symbol)
                if label:
                    cond = ("%s; %s" % (label, cond)) if cond else label
                    cond_src = (cond_src + "+label") if cond_src else "label"
                out.append(ExtractedRow(symbol=symbol,
                                        row=value_row,
                                        values=values,
                                        unit=unit,
                                        cond=cond,
                                        page_num=page.page_num,
                                        cond_src=cond_src))
    return out
