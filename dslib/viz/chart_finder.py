"""
Locate gate-charge characteristic charts on a PDF page.

A "gate-charge chart" plots V_GS (y) vs Q_G (x). Manufacturers style these
charts very differently — some embed the curve as vector lines, others as a
raster image — but the label conventions are consistent enough to find them
from the text layer:

  - the y-axis carries "VGS" / "V_GS" / "Gate-Source Voltage"
  - the x-axis carries the *unit* "(nC)" preceded by "Qg" / "QG" / "Gate
    Charge"
  - tick labels along both axes are numeric

This module looks for those text anchors and uses them to:
  1. identify each chart's plotting bbox on the page
  2. collect the (value → pdf-coordinate) calibration for both axes
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

import pymupdf


_NUM_RE = re.compile(r'^-?[0-9]+(?:\.[0-9]+)?$')
_FIG_PREFIX_RE = re.compile(r'(?i)^(Fig|Figure|Diagram)\.?[0-9]*$')


@dataclass
class ChartLocation:
    """A located gate-charge chart on a page.

    ``bbox`` is the plotting area in pymupdf coordinates (top-left origin).
    ``y_ticks`` and ``x_ticks`` are (value, pdf_coord) pairs read from the
    text layer.
    """
    page_num: int
    bbox: pymupdf.Rect
    y_ticks: List[Tuple[float, float]] = field(default_factory=list)
    x_ticks: List[Tuple[float, float]] = field(default_factory=list)
    title: Optional[str] = None
    y_axis_word_bbox: Optional[pymupdf.Rect] = None
    x_axis_word_bbox: Optional[pymupdf.Rect] = None

    def has_calibration(self) -> bool:
        # At least two y-ticks for a linear fit; x-ticks are nice-to-have
        # for sanity checking but not strictly required.
        return len(self.y_ticks) >= 2

    @property
    def width(self) -> float:
        return self.bbox.x1 - self.bbox.x0

    @property
    def height(self) -> float:
        return self.bbox.y1 - self.bbox.y0


@dataclass
class _Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return 0.5 * (self.x0 + self.x1)

    @property
    def cy(self) -> float:
        return 0.5 * (self.y0 + self.y1)


def _page_words(page: pymupdf.Page) -> List[_Word]:
    raw = page.get_text('words')
    return [_Word(text=w[4], x0=w[0], y0=w[1], x1=w[2], y1=w[3]) for w in raw]


# ---------- text-anchor detection ----------


def _is_charge_word(s: str) -> bool:
    s = s.strip(',;.()[]')
    if not s:
        return False
    lower = s.lower()
    if lower in ('qg', 'q_g', 'qgate', 'qgs', 'qgd'):
        return True
    return s in ('Qg', 'QG', 'Q_G') or lower.startswith('qg')


def _is_unit_word(s: str) -> bool:
    return s.strip(',;.') in ('(nC)', 'nC', '[nC]', 'nC,', '[nc]', '(nc)', '(nC),')


def _find_x_axis_anchors(words: List[_Word]) -> List[Tuple[_Word, _Word]]:
    """Find every x-axis charge label on the page.

    Returns (charge_word, end_word) pairs. ``end_word`` is either a unit
    word on the same baseline ("(nC)" / "[nC]" / "nC") or — when only the
    charge word is present — the charge word itself.

    Two detection strategies, run sequentially:
      1. forward: a charge-like word optionally followed by a unit
      2. backward: a unit word preceded by a charge-like word on the same
         baseline (this rescues split text like ``"Q" "gate" "[nC]"``)
    """
    out: List[Tuple[_Word, _Word]] = []
    seen: set = set()

    def add(start: _Word, end: _Word) -> None:
        key = (round(start.cx, 1), round(start.cy, 1), round(end.cx, 1))
        if key in seen:
            return
        seen.add(key)
        out.append((start, end))

    # strategy 1: charge-word, possibly followed by unit
    for i, w in enumerate(words):
        if not _is_charge_word(w.text):
            continue
        end = w
        for j in range(i + 1, min(i + 12, len(words))):
            w2 = words[j]
            if abs(w2.cy - w.cy) > 4:
                continue
            if _is_unit_word(w2.text):
                end = w2
                break
        add(w, end)

    # strategy 2: unit-word with a Q-ish word to its left on the same line
    for j, u in enumerate(words):
        if not _is_unit_word(u.text):
            continue
        # look backward on the same line for a charge or "gate" word
        for i in range(j - 1, max(-1, j - 12), -1):
            w = words[i]
            if abs(w.cy - u.cy) > 4:
                continue
            t = w.text.lower().strip('.,;')
            if (t in {'q', 'qg', 'q_g', 'qgate', 'gate'}
                    or _is_charge_word(w.text)
                    or t.startswith('gate')):
                add(w, u)
                break
    return out


_Y_HINTS_STRONG = ('VGS', 'V_GS', 'Vgs')      # specific gate-source labels
_Y_HINTS_WEAK = ('V', 'GS')                    # fragments of vertical text


def _y_hint_strength(s: str) -> int:
    """Higher = stronger evidence that ``s`` labels a V_GS y-axis."""
    s = s.strip(',;.()[]').upper()
    if not s:
        return 0
    if s in ('VGS', 'V_GS'):
        return 3
    if s.startswith('VGS') or s.startswith('V_GS'):
        return 3
    if s == 'GS':
        return 2
    if s == 'V':
        return 1
    return 0


def _find_y_axis_anchor(words: List[_Word], near_x_anchor: pymupdf.Rect
                        ) -> Optional[_Word]:
    """Find the y-axis label (a "VGS"-ish word) above the chart.

    Prefer strong matches ("VGS") over weak fragments ("V") so a stray
    body-text "V" can't outscore the real axis label.
    """
    cand: List[Tuple[int, float, _Word]] = []
    for w in words:
        strength = _y_hint_strength(w.text)
        if strength == 0:
            continue
        if w.cy >= near_x_anchor.y0:
            continue
        if w.cx > near_x_anchor.x1 + 40:
            continue
        if w.cx < near_x_anchor.x0 - 250:
            continue
        cand.append((strength, near_x_anchor.y0 - w.cy, w))
    if not cand:
        return None
    # sort: strongest first, then closest to the x-axis label
    cand.sort(key=lambda t: (-t[0], t[1]))
    return cand[0][2]


# ---------- tick label clustering ----------


def _cluster(seq, key, tol: float):
    out: List[List] = []
    for it in sorted(seq, key=key):
        if out and abs(key(it) - sum(map(key, out[-1])) / len(out[-1])) < tol:
            out[-1].append(it)
        else:
            out.append([it])
    return out


def _longest_equispaced_run(items, pos=None, rel_tol: float = 0.25) -> list:
    """Convenience wrapper: returns the longest run from
    ``_all_equispaced_runs``. Kept for the x-tick path where ties are
    rare."""
    runs = _all_equispaced_runs(items, pos=pos, rel_tol=rel_tol)
    if not runs:
        return list(items)
    return max(runs, key=len)


def _all_equispaced_runs(items, pos=None, rel_tol: float = 0.25,
                         min_len: int = 3,
                         allow_gap_k: int = 2) -> list:
    """Return every contiguous run of length ≥ ``min_len`` whose spacing
    is approximately constant.

    A spacing that is *k* times the running mean for an integer k ∈
    [1, ``allow_gap_k``] is accepted as a "missing intermediate tick"
    rather than a chart boundary.
    """
    if pos is None:
        pos = lambda w: w.cy  # type: ignore[assignment]
    if len(items) < min_len:
        return []
    runs: List[list] = []
    cur: list = [items[0]]
    cur_mean: Optional[float] = None
    for it in items[1:]:
        if len(cur) == 1:
            cur.append(it)
            cur_mean = abs(pos(it) - pos(cur[0]))
            continue
        d = abs(pos(it) - pos(cur[-1]))
        if cur_mean is None or cur_mean <= 0:
            cur_mean = d
        if d <= 0:
            if len(cur) >= min_len:
                runs.append(cur)
            cur = [it]
            cur_mean = None
            continue
        # accept this item if d matches k * cur_mean for any k in 1..allow_gap_k
        matched = False
        for k in range(1, allow_gap_k + 1):
            target = cur_mean * k
            if abs(d - target) <= rel_tol * target:
                cur.append(it)
                # don't poison cur_mean with the multiplied spacing
                if k == 1:
                    cur_mean = ((cur_mean * (len(cur) - 2)) + d) / (len(cur) - 1)
                matched = True
                break
        if not matched:
            if len(cur) >= min_len:
                runs.append(cur)
            cur = [it]
            cur_mean = None
    if len(cur) >= min_len:
        runs.append(cur)
    return runs


def _values_linear_in_position(words, key_pos, rel_tol: float = 0.2) -> bool:
    """True if numeric values along ``words`` change linearly with their
    pdf coordinate. Compares each pair's slope against the run's overall
    slope — tolerates missing intermediate ticks because both ``dv`` and
    ``dp`` scale together when one row is skipped."""
    try:
        vals = [float(w.text) for w in words]
    except ValueError:
        return False
    poss = [key_pos(w) for w in words]
    if len(vals) < 3:
        return False
    overall_slope = (vals[-1] - vals[0]) / (poss[-1] - poss[0] + 1e-12)
    if overall_slope == 0:
        return False
    for i in range(len(vals) - 1):
        dv = vals[i + 1] - vals[i]
        dp = poss[i + 1] - poss[i]
        if dp == 0:
            return False
        slope = dv / dp
        if slope * overall_slope <= 0:
            return False
        if abs(slope - overall_slope) > rel_tol * abs(overall_slope):
            return False
    return True


def _longest_linear_subrun(words, key_pos, rel_tol: float = 0.2,
                           min_len: int = 3) -> list:
    """Among value-monotonic, slope-consistent contiguous sub-runs of
    ``words``, return the longest. Lets a single equispaced position run
    be split on value discontinuities — e.g. a tick column shared by two
    stacked charts where positions are evenly spaced across both but
    *values* aren't.
    """
    if len(words) < min_len:
        return list(words) if _values_linear_in_position(words, key_pos, rel_tol) else []

    try:
        vals = [float(w.text) for w in words]
    except ValueError:
        return []
    poss = [key_pos(w) for w in words]

    best: list = []
    n = len(words)
    for i in range(n - min_len + 1):
        for j in range(i + min_len, n + 1):
            sub = words[i:j]
            if _values_linear_in_position(sub, key_pos, rel_tol):
                if len(sub) > len(best):
                    best = list(sub)
    return best


def _calibrate_axes(words: List[_Word],
                    yword: _Word,
                    xword_left: _Word,
                    xword_right: _Word
                    ) -> Tuple[pymupdf.Rect, List[Tuple[float, float]],
                               List[Tuple[float, float]]]:
    """Given the located axis-label words, find tick labels and the
    plotting bbox.

    Constraints:
      - y-ticks are numeric, in a single vertical column, x roughly
        between the y-axis label and the chart
      - x-ticks are numeric, in a single horizontal row, y roughly between
        the chart and the x-axis label
    """
    # search region: a vertical band reaching well above the y-axis label
    # (the y-axis label is centered next to the chart, so the topmost tick
    # can sit hundreds of points above its top). Reach down to just above
    # the x-axis caption.
    search = pymupdf.Rect(
        yword.x0 - 5,
        min(yword.y0, xword_left.y0) - 400,
        max(xword_right.x1, yword.x1 + 400),
        xword_left.y0 - 1)

    nums = [w for w in words
            if _NUM_RE.match(w.text)
            and search.x0 <= w.cx <= search.x1
            and search.y0 <= w.cy <= search.y1]

    # y-ticks: vertical column to the left of the chart. Cluster by x,
    # then within each cluster pick the equispaced run whose vertical
    # range brackets the y-axis label (handles stacked charts that share
    # a tick x-position).
    x_clusters = _cluster(nums, lambda w: w.cx, 6.0)
    y_col: Optional[List[_Word]] = None
    y_col_score = float('inf')
    for cl in x_clusters:
        if len(cl) < 3:
            continue
        cx = sum(w.cx for w in cl) / len(cl)
        if cx > xword_left.x0 - 4:
            continue
        sorted_cl = sorted(cl, key=lambda w: w.cy)
        for run in _all_equispaced_runs(sorted_cl):
            # An equispaced position run shared by two stacked charts can
            # contain a value discontinuity (e.g. 1.05→0.90 followed by
            # 10→0). Take the longest value-linear sub-run to recover
            # the actual chart's ticks.
            run = _longest_linear_subrun(run, key_pos=lambda w: w.cy)
            if len(run) < 3:
                continue
            ys = [w.cy for w in run]
            y_lo, y_hi = min(ys), max(ys)
            if y_lo <= yword.cy <= y_hi:
                score = 0.0
            else:
                score = min(abs(yword.cy - y_lo), abs(yword.cy - y_hi))
            # also reward runs whose bottom sits just above the x-axis row
            score += 0.05 * abs(xword_left.y0 - y_hi)
            if score < y_col_score:
                y_col_score = score
                y_col = run

    # x-ticks: horizontal row near the bottom of the chart. Cluster by y,
    # then within each row try every equispaced run — the right one is
    # the run whose leftmost tick sits just right of the y-axis column,
    # not necessarily the longest run (the longest can belong to a
    # neighbouring chart that shares the same baseline).
    y_clusters = _cluster(nums, lambda w: w.cy, 4.0)
    x_row: Optional[List[_Word]] = None
    x_row_score = float('inf')
    # right edge of the y-axis tick column = chart's left bound
    y_col_right = max((w.x1 for w in y_col), default=yword.x1) if y_col else yword.x1
    for cl in y_clusters:
        if len(cl) < 3:
            continue
        cy = sum(w.cy for w in cl) / len(cl)
        if cy < yword.cy:
            continue
        if cy > xword_left.y0 - 1:
            continue
        sorted_cl = sorted(cl, key=lambda w: w.cx)
        for run in _all_equispaced_runs(sorted_cl,
                                        pos=lambda w: w.cx):
            run = _longest_linear_subrun(run, key_pos=lambda w: w.cx)
            if len(run) < 3:
                continue
            # distance from the run's leftmost tick to the y-axis column.
            # Small distance = this chart's x-axis. Large positive distance
            # = a neighbouring chart on the same baseline. Negative
            # distance = a run that starts before the y-axis column (not
            # this chart either).
            left_gap = run[0].x0 - y_col_right
            if left_gap < -8 or left_gap > 60:
                continue
            score = abs(left_gap)
            if score < x_row_score:
                x_row_score = score
                x_row = run

    y_ticks: List[Tuple[float, float]] = []
    x_ticks: List[Tuple[float, float]] = []
    if y_col:
        for w in sorted(y_col, key=lambda w: w.cy):
            y_ticks.append((float(w.text), w.cy))
    if x_row:
        for w in sorted(x_row, key=lambda w: w.cx):
            x_ticks.append((float(w.text), w.cx))

    # bbox: span from the leftmost tick column to past the rightmost x-tick
    bbox = pymupdf.Rect(
        (max(w.x1 for w in y_col) + 1) if y_col else yword.x1 + 1,
        min(w.y0 for w in y_col) - 4 if y_col else yword.y0,
        max(w.x1 for w in x_row) + 4 if x_row else xword_right.x1,
        xword_left.y0 - 1)

    return bbox, y_ticks, x_ticks


# ---------- public API ----------


def _extend_bbox_to_drawings(page: pymupdf.Page,
                             bbox: pymupdf.Rect,
                             y_band_lo: float,
                             y_band_hi: float) -> pymupdf.Rect:
    """Extend bbox horizontally to cover drawings within the y-tick band.

    When x_ticks are missing the text-derived bbox is usually too narrow
    on the right. Walk drawings vertically straddling the tick band and
    grow the chart x_max as long as their bounding rects are contiguous
    with the existing bbox (allows a small horizontal gap so two pieces
    of the same curve still join).
    """
    cont_gap = 12.0
    x_max = bbox.x1
    while True:
        grew = False
        for d in page.get_drawings():
            r = d['rect']
            if r.y0 > y_band_hi + 2 or r.y1 < y_band_lo - 2:
                continue
            if r.x0 > x_max + cont_gap or r.x1 < bbox.x0:
                continue
            if r.x1 > x_max:
                x_max = r.x1
                grew = True
        if not grew:
            break
    return pymupdf.Rect(bbox.x0, bbox.y0, x_max, bbox.y1)


def find_gate_charge_charts(page: pymupdf.Page) -> List[ChartLocation]:
    """Return every gate-charge chart that can be confidently identified."""
    words = _page_words(page)
    out: List[ChartLocation] = []

    for charge_word, unit_word in _find_x_axis_anchors(words):
        x_anchor = pymupdf.Rect(charge_word.x0, charge_word.y0,
                                unit_word.x1, unit_word.y1)
        yword = _find_y_axis_anchor(words, x_anchor)
        if yword is None:
            continue
        try:
            bbox, y_ticks, x_ticks = _calibrate_axes(
                words, yword, charge_word, unit_word)
        except Exception:
            continue

        # when text-derived x_ticks are missing the chart bbox is usually
        # truncated. Extend it using the vector drawings that span the
        # y-tick band.
        if not x_ticks and y_ticks:
            ys = [t[1] for t in y_ticks]
            bbox = _extend_bbox_to_drawings(page, bbox, min(ys), max(ys))

        loc = ChartLocation(
            page_num=page.number,
            bbox=bbox,
            y_ticks=y_ticks,
            x_ticks=x_ticks,
            y_axis_word_bbox=pymupdf.Rect(yword.x0, yword.y0, yword.x1, yword.y1),
            x_axis_word_bbox=x_anchor,
        )

        if not loc.has_calibration():
            continue
        out.append(loc)

    # dedupe in case the same chart was matched twice
    dedup: List[ChartLocation] = []
    for loc in out:
        for d in dedup:
            if d.bbox.intersects(loc.bbox) and abs(d.bbox.x0 - loc.bbox.x0) < 5 \
                    and abs(d.bbox.y0 - loc.bbox.y0) < 5:
                break
        else:
            dedup.append(loc)
    return dedup


_CHART_TITLE_RE = re.compile(
    # A chart caption / header that introduces a gate-charge plot.
    # Built from the title patterns observed across infineon, MCC,
    # panjit, onsemi, vishay, littelfuse, TI and EPC datasheets.
    #
    # Anchored to the start of the line so unrelated body-text mentions
    # of "gate charge" (table rows, FOM blurbs, axis labels like
    # "Qg, Gate Charge (nC)") can't accidentally match. Either a
    # non-empty *prefix* introduces the caption, or the whole line *is*
    # the bare "Gate Charge" caption.
    #
    #   A) ``Figure 16.`` / ``Fig.6`` / ``Fig. 11.`` / ``Figure 4-4.``
    #      / ``Diagram 14:`` — optionally followed by ``Typ.`` /
    #      ``Typical`` before ``Gate Charge``.
    #   B) ``14 Typ. gate charge`` — bare numbered header, ``Typ.`` is
    #      required. Tolerates pdfminer-split punctuation
    #      (``14 : Typ . gate charge``).
    #   C) ``Typ. gate charge`` / ``Typical gate charge`` — header
    #      without a number.
    #   D) Bare ``Gate Charge`` standalone caption (Vishay convention)
    #      — the line is just the words "Gate Charge" optionally
    #      followed by "Characteristics" / "Curve" / "vs. …", with
    #      nothing else preceding. Body-text mentions
    #      ("Total Gate Charge at 10 V", "Threshold Gate Charge", …)
    #      have other words *before* "Gate Charge" so this alternative
    #      doesn't fire on them.
    r"^\s*(?:"
    # A
    r"(?:Diagram|Figure|Fig\.?)\s*[0-9]+(?:-[0-9]+)?[\s.:\-]+"
    r"(?:Typ(?:ical|ycal)?\s*\.?\s+)?"
    r"Gate[\s-]+Charge.*"
    r"|"
    # B
    r"[0-9]+\s*[.:]?\s+Typ(?:ical|ycal)?\s*\.?\s+"
    r"Gate[\s-]+Charge.*"
    r"|"
    # C
    r"Typ(?:ical|ycal)?\s*\.?\s+"
    r"Gate[\s-]+Charge.*"
    r"|"
    # D
    r"Gate[\s-]+Charge"
    r"(?:\s+(?:Characteristics?|Curves?|vs\.?\b.*))?"
    r"\s*$"
    r"|"
    # E) ``Gate charge characteristic[s]`` followed by anything
    # (parenthetical conditions, comma-separated qualifiers).
    # Optionally preceded by a section number ("6.3.") — Toshiba
    # datasheets use that as the chart's anchor heading. Infineon
    # F3L3 / IGBT-module datasheets use the unprefixed variant.
    r"(?:[0-9]+(?:\.[0-9]+)*\.?\s+)?"
    r"Gate[\s-]+Charge\s+Characteristics?\b.*"
    r"|"
    # F) ``Dynamic Input/Output Characteristics`` — Toshiba convention
    # for gate charge charts. Optionally preceded by a figure prefix.
    r"(?:Diagram|Figure|Fig\.?)\s*[0-9]+(?:[-\.][0-9]+)?\s*[.:\-]?\s+"
    r"Dynamic\s+Input/Output\s+Characteristics?.*"
    r"|"
    r"Dynamic\s+Input/Output\s+Characteristics?\b.*"
    r")",
    re.IGNORECASE,
)


_CAPTION_BREAK_RE = re.compile(r'^(Fig|Figure|Diagram)\.?$', re.IGNORECASE)


def _group_words_by_line(words: List[_Word], y_tol: float = 3.0,
                         x_gap_split: float = 50.0
                         ) -> List[List[_Word]]:
    """Group words by baseline (cy within ``y_tol``), then split each line:

      * on horizontal gaps larger than ``x_gap_split``
      * also whenever a new ``"Fig" / "Figure" / "Diagram"`` token
        appears mid-line — two side-by-side chart captions on the same
        baseline ("Fig 5. ... Fig 6. ...") may have a column gap < 50 pt
        which would otherwise leave them glued together.
    """
    if not words:
        return []
    by_y = sorted(words, key=lambda w: (w.cy, w.x0))
    raw_lines: List[List[_Word]] = [[by_y[0]]]
    for w in by_y[1:]:
        if abs(w.cy - raw_lines[-1][0].cy) <= y_tol:
            raw_lines[-1].append(w)
        else:
            raw_lines.append([w])

    out: List[List[_Word]] = []
    for line in raw_lines:
        line.sort(key=lambda w: w.x0)
        if not line:
            continue
        chunk: List[_Word] = [line[0]]
        for w in line[1:]:
            gap = w.x0 - chunk[-1].x1
            break_on_caption = (gap > 3.0
                                and len(chunk) >= 2
                                and _CAPTION_BREAK_RE.match(w.text or ''))
            if gap > x_gap_split or break_on_caption:
                out.append(chunk)
                chunk = [w]
            else:
                chunk.append(w)
        if chunk:
            out.append(chunk)
    return out


_FOOTNOTE_START_RE = re.compile(r'^(\*+\)|[0-9]+\)|See\b|see\b|cf\.)')
# Captions that mention "gate charge" but refer to a *circuit* / timing
# waveform diagram, not the V_GS-vs-Q_G curve.
_NON_CURVE_TITLE_RE = re.compile(
    r'(?i)('
    r'test[\s-]+circuit'
    r'|circuit\s*&\s*waveform'
    r'|circuit\s+and\s+waveform'
    # Caption variants we never want to anchor on:
    #   - "Fig. 13. Gate charge waveform definitions"   (test waveform)
    #   - "Source-Drain Diode Forward Voltage"           (V_SD vs I_F)
    #   - "Switching Time Test Circuit"                  (timing diagram)
    # Word separators may be spaces *or* dashes/hyphens, so ``[\s-]+``
    # is used uniformly between tokens.
    r'|gate[\s-]+charge[\s-]+waveform[\s-]+definitions?'
    r'|source[\s-]+drain[\s-]+diode[\s-]+forward[\s-]+voltage'
    r'|switching[\s-]+time[\s-]+test[\s-]+circuit'
    r')'
)


def _find_chart_title_lines(words: List[_Word]
                            ) -> List[List[_Word]]:
    """Lines whose joined text matches the chart-title regex.

    Filters out:
      * lines starting with footnote markers (``"*) See …"`` etc.) that
        happen to contain ``"gate charge waveforms"`` as a reference
      * captions for circuit / timing diagrams ("Gate Charge Test
        Circuit & Waveform") — those don't carry a Miller plateau
      * when more than one match remains, drops "waveform" lines so the
        switching-diagram caption can't outrank the canonical V_GS-vs-Q_G
        chart title sharing the same page.
    """
    out: List[List[_Word]] = []
    for line in _group_words_by_line(words):
        text = ' '.join(w.text for w in line).strip()
        if not text:
            continue
        if _FOOTNOTE_START_RE.match(text):
            continue
        if _NON_CURVE_TITLE_RE.search(text):
            continue
        # Some PDFs (CRTT, certain Chinese-mfr datasheets) draw caption
        # text in three overlapping passes for a bold-stroke effect.
        # Pdfminer surfaces every glyph, so the joined line text comes
        # out as "Fig Fig Fig 7: 7: 7: Gate Gate Gate Charge ...". Dedup
        # consecutive identical tokens so the title regex can still
        # match.
        toks = text.split()
        deduped = []
        for t in toks:
            if not deduped or deduped[-1] != t:
                deduped.append(t)
        text_dedup = ' '.join(deduped)
        if _CHART_TITLE_RE.search(text) or _CHART_TITLE_RE.search(text_dedup):
            out.append(line)
    if len(out) >= 2:
        non_wave = [l for l in out
                    if 'waveform' not in ' '.join(w.text for w in l).lower()]
        if non_wave:
            return non_wave
    return out


def _scan_numeric_tick_row(words: List[_Word],
                           search_bbox: pymupdf.Rect
                           ) -> List[Tuple[float, float, float]]:
    """Find a horizontal row of numeric tick labels inside ``search_bbox``.

    Returns ``[(value, cx, cy), ...]`` sorted by cx, or ``[]`` if no
    plausible run is found.

    Companion to ``_scan_numeric_tick_column``. Used by the title-
    anchored chart finder for OCRed PDFs whose vertical Y-axis label
    is illegible: the chart's horizontal extent and its position
    relative to the title can be read off the x-axis tick numbers
    instead (``0  40  80  120`` under the curve gives both the chart
    width and the orientation, which the bare ``"Gate Charge"``
    caption alone can't).
    """
    nums = [w for w in words
            if _NUM_RE.match(w.text)
            and search_bbox.x0 <= w.cx <= search_bbox.x1
            and search_bbox.y0 <= w.cy <= search_bbox.y1]

    y_clusters = _cluster(nums, lambda w: w.cy, 4.0)
    best_run: Optional[List[_Word]] = None
    for cl in y_clusters:
        if len(cl) < 3:
            continue
        sorted_cl = sorted(cl, key=lambda w: w.cx)
        for run in _all_equispaced_runs(sorted_cl, pos=lambda w: w.cx):
            run = _longest_linear_subrun(run, key_pos=lambda w: w.cx)
            if len(run) < 3:
                continue
            try:
                _vals = [float(w.text) for w in run]
            except ValueError:
                continue
            # X-axis ticks are typically monotonic-increasing left-to-
            # right. _longest_linear_subrun already checks slope sign;
            # additionally span at least ~20% of search_bbox width.
            span = run[-1].cx - run[0].cx
            if span < 0.2 * (search_bbox.x1 - search_bbox.x0):
                continue
            if best_run is None or len(run) > len(best_run):
                best_run = run
    if not best_run:
        return []
    return [(float(w.text), w.cx, w.cy)
            for w in sorted(best_run, key=lambda w: w.cx)]


def _scan_numeric_tick_column(words: List[_Word],
                              chart_bbox: pymupdf.Rect
                              ) -> List[Tuple[float, float]]:
    """Find a vertical column of numeric tick labels inside ``chart_bbox``.

    Used by the title-anchored chart finder when the standard yword
    cannot be located (typical of OCRed PDFs whose vertical "V_GS" axis
    label garbles during recognition). Returns the captured ticks in
    ``[(value, cy)]`` form, or ``[]`` if no plausible run is found.
    """
    nums = [w for w in words
            if _NUM_RE.match(w.text)
            and chart_bbox.x0 <= w.cx <= chart_bbox.x1
            and chart_bbox.y0 <= w.cy <= chart_bbox.y1]

    x_clusters = _cluster(nums, lambda w: w.cx, 6.0)
    best_run: Optional[List[_Word]] = None
    for cl in x_clusters:
        if len(cl) < 3:
            continue
        sorted_cl = sorted(cl, key=lambda w: w.cy)
        for run in _all_equispaced_runs(sorted_cl):
            run = _longest_linear_subrun(run, key_pos=lambda w: w.cy)
            if len(run) < 3:
                continue
            # Reject Q_G-like x-axis runs (large values, positive going
            # rightward) by requiring the tick values to span a small
            # absolute range — V_GS ticks are 0..20.
            try:
                vals = [float(w.text) for w in run]
            except ValueError:
                continue
            if max(vals) > 25 or min(vals) < -5:
                continue
            # Reject narrow, non-zero-anchored ranges (e.g. V_GS(th) vs
            # temperature charts whose y axis runs 1.2..3.2). A real
            # gate-charge V_GS axis either starts very near 0 or spans
            # at least ~5 V across the visible ticks.
            v_min, v_max = min(vals), max(vals)
            if v_min > 0.5 and (v_max - v_min) < 5.0:
                continue
            if best_run is None or len(run) > len(best_run):
                best_run = run
    if not best_run:
        return []
    return [(float(w.text), w.cy) for w in sorted(best_run, key=lambda w: w.cy)]


def _find_curve_top_y(page: pymupdf.Page,
                      plot_frame: pymupdf.Rect) -> Optional[float]:
    """Return the topmost (smallest y, in PDF coords) point reached by
    a non-frame stroke segment that's part of the largest connected
    polyline inside ``plot_frame``.

    Wireframe-style charts (ST datasheets) don't expose their Y-axis
    range as text; the curve's apex is the most reliable anchor for
    "this y = V_drive". Frame edges, gridlines, and tick stubs are
    excluded; the remaining segments are grouped by shared endpoints
    and only the largest chain (the actual data curve) contributes to
    the apex, so isolated in-plot glyph strokes from labels like
    ``"VGS = 10 V"`` don't drag the anchor up to the legend region.
    """
    drawings = page.get_drawings()
    fx0, fy0, fx1, fy1 = plot_frame.x0, plot_frame.y0, plot_frame.x1, plot_frame.y1
    width = fx1 - fx0
    height = fy1 - fy0
    if width <= 0 or height <= 0:
        return None

    segments: List[Tuple[float, float, float, float]] = []
    for d in drawings:
        items = d.get('items', [])
        for it in items:
            if it[0] != 'l':
                continue
            p0, p1 = it[1], it[2]
            if not (fx0 - 1 <= p0.x <= fx1 + 1 and fy0 - 1 <= p0.y <= fy1 + 1):
                continue
            if not (fx0 - 1 <= p1.x <= fx1 + 1 and fy0 - 1 <= p1.y <= fy1 + 1):
                continue
            dx = p1.x - p0.x
            dy = p1.y - p0.y
            cy = 0.5 * (p0.y + p1.y)
            cx = 0.5 * (p0.x + p1.x)
            if abs(dy) < 0.5 and (abs(cy - fy0) < 1.5 or abs(cy - fy1) < 1.5):
                continue
            if abs(dx) < 0.5 and (abs(cx - fx0) < 1.5 or abs(cx - fx1) < 1.5):
                continue
            if abs(dy) < 1.0 and abs(dx) > 0.8 * width:
                continue
            if abs(dx) < 1.0 and abs(dy) > 0.8 * height:
                continue
            segments.append((p0.x, p0.y, p1.x, p1.y))

    if not segments:
        return None

    # Build connected-component clusters keyed by quantised endpoints
    # (within ~1.5 pt, generous enough for stroke-end rounding errors).
    parent = list(range(len(segments)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    tol = 1.5
    # bucket endpoints into a coarse 2-D grid for O(n) lookup
    from collections import defaultdict
    grid: dict = defaultdict(list)
    cell = 3.0
    for i, (x0, y0, x1, y1) in enumerate(segments):
        for ex, ey in ((x0, y0), (x1, y1)):
            grid[(int(ex / cell), int(ey / cell))].append((ex, ey, i))
    for i, (x0, y0, x1, y1) in enumerate(segments):
        for ex, ey in ((x0, y0), (x1, y1)):
            gx, gy = int(ex / cell), int(ey / cell)
            for dx_c in (-1, 0, 1):
                for dy_c in (-1, 0, 1):
                    for ox, oy, j in grid[(gx + dx_c, gy + dy_c)]:
                        if j == i:
                            continue
                        if abs(ox - ex) < tol and abs(oy - ey) < tol:
                            union(i, j)

    # Find the largest cluster by *total stroke length* — a chunk of
    # text glyphs ("V_GS = 10 V" labels) is many short segments that
    # cluster together, while the curve is fewer but much longer
    # segments. Picking by total length suppresses the text cluster.
    cluster_length: dict = defaultdict(float)
    cluster_members: dict = defaultdict(list)
    for i, (x0, y0, x1, y1) in enumerate(segments):
        root = find(i)
        cluster_length[root] += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        cluster_members[root].append(i)

    biggest = max(cluster_length, key=cluster_length.get)
    if cluster_length[biggest] < 20.0:
        return None
    members = cluster_members[biggest]
    best_y = min(min(segments[i][1], segments[i][3]) for i in members)
    return best_y


def _find_chart_wireframe(page: pymupdf.Page,
                          title_bbox: pymupdf.Rect,
                          starts_with_fig: bool,
                          header_only: bool = False
                          ) -> Optional[Tuple[pymupdf.Rect, pymupdf.Rect]]:
    """Detect a wireframe-style chart (vector rectangle frame, no text
    labels) adjacent to ``title_bbox``.

    ST datasheets (e.g. STB55NF06LT4 page 7 "Figure 7. Gate charge vs
    gate-source voltage") draw the chart as a vector outline rectangle
    with the curve inside; axis tick labels are rendered as glyphs that
    pdfminer/pymupdf can't extract as text. In that layout neither
    ``page.get_image_info`` nor ``_scan_numeric_tick_column`` returns
    anything, so the existing image/tick-column paths give up.

    Returns ``(outer_box, inner_plot_frame)`` if a plausible wireframe
    sits within ~40 pt of the caption on its prefix-implied side, or
    ``None`` if no such rectangle is found. The outer box is typically
    a "filled background" rect that encloses the plot frame, axis labels
    and tick marks; the inner stroke rect is the actual plot region (the
    one the curve coordinates are measured against).
    """
    drawings = page.get_drawings()

    # Collect every rectangle-shaped drawing. A rectangle drawing has a
    # single ``re`` or ``qu`` item, or its bbox is consistent with a
    # closed rectangle outline (4 line items).
    rects: List[pymupdf.Rect] = []
    for d in drawings:
        items = d.get('items', [])
        if not items:
            continue
        is_rect = False
        if len(items) == 1 and items[0][0] in ('re', 'qu'):
            is_rect = True
        # An outline can also be 4 connected line segments forming a
        # closed rectangle — keep this case so manufacturers who draw
        # the frame piecewise (e.g. four ``l`` strokes) are caught too.
        if not is_rect and len(items) == 4 and all(it[0] == 'l' for it in items):
            r = d.get('rect')
            if r is not None and r.width > 50 and r.height > 50:
                is_rect = True
        if not is_rect:
            continue
        r = d.get('rect')
        if r is None:
            continue
        # Reasonable chart-frame size: 80–500 pt wide & tall.
        if not (80 < r.width < 500 and 80 < r.height < 500):
            continue
        rects.append(pymupdf.Rect(r))

    # Some manufacturers (ST STL70N4LLF5) don't draw a full rectangle —
    # the plot frame is implied by an L-shape made of two thin filled
    # strips: a vertical y-axis line on the left and a horizontal x-axis
    # line at the bottom that share a corner. Reconstruct a virtual
    # rectangle from any such pair, but only when no explicit
    # rectangle drawings of similar dimensions exist (otherwise the
    # L-shape might combine a page-wide divider with a chart-column
    # axis and synthesize a way-too-wide rect that engulfs the real
    # plot frame).
    if not rects:
        thin = 1.5  # max thickness of an axis strip
        verticals = []
        horizontals = []
        for d in drawings:
            r = d.get('rect')
            if r is None:
                continue
            if r.width < thin and r.height > 60:
                verticals.append(r)
            elif r.height < thin and r.width > 60:
                horizontals.append(r)
        for v in verticals:
            for h in horizontals:
                # bottom of vertical strip must meet left of horizontal
                # strip (matching corner ≈ shared coordinate)
                if abs(v.y1 - h.y1) > 3 or abs(v.x0 - h.x0) > 3:
                    continue
                synth = pymupdf.Rect(
                    min(v.x0, h.x0),
                    min(v.y0, h.y0),
                    max(v.x1, h.x1),
                    max(v.y1, h.y1),
                )
                # Reasonable single-chart proportions: roughly square,
                # 80..500 pt on each side and aspect ratio within 2×.
                if not (80 < synth.width < 500 and 80 < synth.height < 500):
                    continue
                aspect = synth.width / synth.height
                if aspect > 2.0 or aspect < 0.5:
                    continue
                rects.append(synth)

    if not rects:
        return None

    # Prefer the side implied by the caption prefix, but fall back to
    # the other side when nothing fits. Section-number headings only
    # ever have their content below the heading line.
    title_cx = 0.5 * (title_bbox.x0 + title_bbox.x1)
    if header_only:
        sides = (False,)
    else:
        sides = (starts_with_fig, not starts_with_fig)
    best: Optional[Tuple[float, pymupdf.Rect]] = None
    best_side: Optional[bool] = None
    for try_caption in sides:
        for r in rects:
            if try_caption:
                # caption convention — chart sits *above* the caption
                if r.y1 > title_bbox.y0:
                    continue
                d = title_bbox.y0 - r.y1
            else:
                if r.y0 < title_bbox.y1:
                    continue
                d = r.y0 - title_bbox.y1
            if d > 40:
                continue
            # title must sit roughly above/below this rect horizontally
            if not (r.x0 - 8 <= title_cx <= r.x1 + 8):
                continue
            if best is None or d < best[0]:
                best = (d, r)
                best_side = try_caption
        if best is not None:
            break
    if best is None:
        return None
    _d, outer = best

    # Look for a smaller stroke rectangle nested *inside* the outer
    # frame — that's the plot region the curve coordinates use. Inset
    # by at least 2 pt on each side, otherwise we'd just pick the outer
    # frame again.
    inner: Optional[pymupdf.Rect] = None
    for r in rects:
        if r == outer:
            continue
        if r.x0 < outer.x0 - 1 or r.y0 < outer.y0 - 1 \
                or r.x1 > outer.x1 + 1 or r.y1 > outer.y1 + 1:
            continue
        if (r.x0 - outer.x0) < 2 and (outer.x1 - r.x1) < 2 \
                and (r.y0 - outer.y0) < 2 and (outer.y1 - r.y1) < 2:
            continue
        if inner is None or r.width * r.height > inner.width * inner.height:
            inner = r
    if inner is None:
        inner = outer
    return outer, inner


def _find_infineon_raster_charts(page: pymupdf.Page) -> List[ChartLocation]:
    """Detect raster gate-charge charts by their title text.

    A chart-title line matching ``_CHART_TITLE_RE`` — e.g.

      * ``"Typ. gate charge"`` (Infineon)
      * ``"Gate Charge vs. Gate-to-Source Voltage"`` (onsemi)
      * ``"Figure 16. Gate Charge ..."`` (onsemi / TI / IRF)

    anchors the chart. The associated bitmap is the page image whose
    bbox sits next to that title (above for "Figure N." captions
    underneath the chart, below for "Typ. gate charge" headers above it).
    The y-axis is calibrated to 0 V at the plot bottom and 10 V at the
    top; the raster extractor refines this against the detected plot
    frame inside the bitmap.
    """
    words = _page_words(page)

    title_lines = _find_chart_title_lines(words)
    if not title_lines:
        return []

    images = page.get_image_info(hashes=False)

    out: List[ChartLocation] = []
    for grp in title_lines:
        title_bbox = pymupdf.Rect(
            min(w.x0 for w in grp), min(w.y0 for w in grp),
            max(w.x1 for w in grp), max(w.y1 for w in grp))

        # The chart bitmap can be either below the title (header style:
        # "Typ. gate charge") or above it (caption style: "Figure 16.
        # Gate Charge ..."). Pick the closest image / tick column that
        # is also horizontally aligned with the title — try both sides
        # and let the data decide. Some manufacturers (MCC) use the
        # ``Fig.N`` prefix as a header even though it conventionally is
        # a caption.
        title_text = ' '.join(w.text for w in grp)
        # default ordering: try caption side first if "Fig"/"Figure"
        # prefix is present, otherwise try header side first
        starts_with_fig = bool(re.match(r'(?i)\s*Fig', title_text))
        # A bare section-number prefix like "6.3. Gate Charge
        # Characteristics" is always a *header* (the chart, table, or
        # text body for that section sits below it). Treat these as
        # header-only — don't fall back to probing the caption side,
        # because the content above a section heading belongs to the
        # *previous* section (e.g. Toshiba TK024Z60Z1 page 3, where
        # the Switching Time Test Circuit schematic sits directly
        # above the "6.3. Gate Charge Characteristics" heading and
        # would otherwise be mistaken for the heading's chart).
        starts_with_section = bool(re.match(
            r'\s*[0-9]+(?:\.[0-9]+)+\.?\s', title_text))

        title_cx = 0.5 * (title_bbox.x0 + title_bbox.x1)

        # find the page rect (for the full-page-image fallback below)
        try:
            page_rect = page.rect
        except Exception:
            page_rect = None

        img_rect: Optional[pymupdf.Rect] = None
        is_caption = starts_with_fig
        best_d = float('inf')
        full_page_image: Optional[pymupdf.Rect] = None
        extra_charts: List[ChartLocation] = []
        for img in (images or []):
            b = img.get('bbox')
            if not b:
                continue
            r = pymupdf.Rect(b)
            # Track full-page images (typical of OCRed PDFs): the chart
            # bbox here can't come from the image rect; we'll fall back
            # to a synthetic region near the title.
            if page_rect is not None:
                pw = page_rect.width
                ph = page_rect.height
                if (r.width >= 0.9 * pw and r.height >= 0.9 * ph):
                    full_page_image = r
                    continue
            # Try both sides. ``side==-1`` is "image above title"
            # (caption style), ``side==+1`` is "image below title"
            # (header style). Within the same side preference, take the
            # closer image. We try the title's prefix-implied side first
            # so the right interpretation wins on the typical case. For
            # section-number headings ("6.3. Gate Charge ..."), the
            # chart can only be below — never look above.
            if starts_with_section:
                sides_to_try = (False,)
            else:
                sides_to_try = (starts_with_fig, not starts_with_fig)
            for try_caption in sides_to_try:
                if try_caption:
                    if r.y1 > title_bbox.y0:
                        continue
                    d = title_bbox.y0 - r.y1
                else:
                    if r.y0 < title_bbox.y1:
                        continue
                    d = r.y0 - title_bbox.y1
                if d > 40:
                    continue
                if not (r.x0 - 5 <= title_cx <= r.x1 + 5):
                    continue
                if d < best_d:
                    best_d = d
                    img_rect = r
                    is_caption = try_caption
                break
        if img_rect is None and full_page_image is not None and page_rect is not None:
            # OCRed PDF — the whole page is one image. Synthesize a chart
            # bbox tightly anchored to the title's x extent: the chart's
            # left frame sits a few points before the title's leftmost
            # character, and the plot extends to the right past the
            # title's rightmost character.
            col_x0 = max(page_rect.x0, title_bbox.x0 - 8)
            col_x1 = min(page_rect.x1, title_bbox.x1 + 110)
            chart_h = 220.0
            # If we can find an X-axis tick row near the title, use it
            # to (1) decide caption vs header orientation (which side
            # of the title the chart sits on) and (2) set the bbox's
            # x range from the tick run's leftmost / rightmost cx —
            # the title is sometimes off-centre relative to the chart
            # (siliup centres the caption under the *x-axis-label*,
            # not under the plot frame), so anchoring to the title's
            # own x extent miscrops the rendered chart.
            tick_search_pad_x = 80.0
            tick_search_pad_y = chart_h + 20.0
            x_tick_above = _scan_numeric_tick_row(words, pymupdf.Rect(
                max(page_rect.x0, title_bbox.x0 - tick_search_pad_x),
                max(page_rect.y0, title_bbox.y0 - tick_search_pad_y),
                min(page_rect.x1, title_bbox.x1 + tick_search_pad_x),
                title_bbox.y0 - 2))
            x_tick_below = _scan_numeric_tick_row(words, pymupdf.Rect(
                max(page_rect.x0, title_bbox.x0 - tick_search_pad_x),
                title_bbox.y1 + 2,
                min(page_rect.x1, title_bbox.x1 + tick_search_pad_x),
                min(page_rect.y1, title_bbox.y1 + tick_search_pad_y)))

            def _has_gc_axis_label_near(tick_y: float, max_dist: float = 30.0
                                        ) -> bool:
                """True if a Q_g/charge axis label sits near ``tick_y``.

                The Gate Charge chart's x-axis label uniquely says
                ``"Q_G — Gate Charge (nC)"`` (or vendor variants like
                ``"Qg-Total Gate Charge (nC)"``). No other chart on
                a MOSFET datasheet uses ``"Charge"`` / ``"(nC)"`` /
                ``"Qg"`` / ``"Q_G"`` near its axis. Picking the tick
                row that has this label nearby unambiguously selects
                the gate-charge chart's tick row even when a
                neighbouring chart's ticks are closer to the title.
                """
                for ow in words:
                    if abs(ow.cy - tick_y) > max_dist:
                        continue
                    txt = (ow.text or '').lower().strip(' .,:;')
                    if not txt:
                        continue
                    if txt in ('charge', 'gate', '(nc)', 'qg', 'qg-total',
                               'q_g', 'qe', 'qe-total', 'q_g-total'):
                        return True
                    if txt.endswith('-total') or txt.startswith('q_g'):
                        return True
                    if 'charge' in txt and ('q' in txt or '(nc' in txt):
                        return True
                return False

            above_has_label = (bool(x_tick_above)
                               and _has_gc_axis_label_near(
                                   max(t[2] for t in x_tick_above)))
            below_has_label = (bool(x_tick_below)
                               and _has_gc_axis_label_near(
                                   min(t[2] for t in x_tick_below)))

            chosen_tick_row: Optional[List[Tuple[float, float, float]]] = None
            if above_has_label and not below_has_label:
                chosen_tick_row, is_caption = x_tick_above, True
            elif below_has_label and not above_has_label:
                chosen_tick_row, is_caption = x_tick_below, False
            elif above_has_label and below_has_label:
                # Both flagged — pick the row closer to the title.
                above_dist = title_bbox.y0 - max(t[2] for t in x_tick_above)
                below_dist = min(t[2] for t in x_tick_below) - title_bbox.y1
                if above_dist <= below_dist:
                    chosen_tick_row, is_caption = x_tick_above, True
                else:
                    chosen_tick_row, is_caption = x_tick_below, False
            # Neither side carries the gate-charge axis label —
            # leave the default ``is_caption`` and ``col_x0/col_x1``
            # untouched. The synthesizer's existing title-anchored
            # bbox handles the "Fig N. Gate Charge" / "Diagram N. Typ.
            # gate charge" charts where the axis label may have been
            # OCR'd into unrecognisable fragments.
            if chosen_tick_row:
                xs = [t[1] for t in chosen_tick_row]
                # widen by a tick-spacing on each side so the chart's
                # plot frame (which sits a tick-spacing past the first
                # / last labelled tick on charts that start at 0) is
                # included.
                if len(xs) >= 2:
                    tick_step = (max(xs) - min(xs)) / (len(xs) - 1)
                else:
                    tick_step = 20.0
                pad = max(20.0, 0.5 * tick_step)
                col_x0 = max(page_rect.x0, min(xs) - pad)
                col_x1 = min(page_rect.x1, max(xs) + pad)
            if is_caption:
                cy0 = max(page_rect.y0, title_bbox.y0 - chart_h - 4)
                cy1 = title_bbox.y0 - 2
                # If another chart's caption (any "Fig N." / "Figure N.")
                # sits above us within the chart_h window, that's the
                # previous chart's bottom — clip cy0 to just below it so
                # the bbox can't bleed into the chart above. Without
                # this, the synthetic bbox can include the previous
                # chart's plot frame and the raster pipeline picks its
                # bottom edge as the gate-charge chart's top, miscaling
                # the y-axis.
                for ow in words:
                    txt = (ow.text or '').strip()
                    if not txt:
                        continue
                    if not re.match(r'(?i)^(?:figure|fig\.?)$', txt):
                        continue
                    if ow.y1 >= title_bbox.y0 - 4:
                        continue
                    if ow.y1 <= cy0:
                        continue
                    # vertically aligned with our title (allow generous
                    # horizontal overlap — captions are usually centred)
                    if ow.x1 < title_bbox.x0 - 30 or ow.x0 > title_bbox.x1 + 30:
                        continue
                    cy0 = max(cy0, ow.y1 + 2)
            else:
                cy0 = title_bbox.y1 + 2
                cy1 = min(page_rect.y1, title_bbox.y1 + chart_h + 4)
            img_rect = pymupdf.Rect(col_x0, cy0, col_x1, cy1)
        # Probe both sides of the title. The prefix-implied side is
        # tried first (caption above for "Fig.N", header below for
        # "Typ. gate charge"); when the first side has no usable tick
        # column, the other side is used. Both sides may also produce
        # candidates — those are emitted as alternates and the
        # downstream plateau scorer picks the one that actually shows
        # a rising curve. ``find_plateau`` and ``find_plateau_raster``
        # both reject charts whose curve doesn't sweep most of the
        # vertical range, so a flat reference chart can't outscore the
        # real V_GS curve.
        # Carry the ticks discovered while searching for a tick column
        # *outside* the eventual chart bbox — the chart bbox uses a
        # narrower x-range that may exclude the y-axis tick labels,
        # so re-scanning inside it later would miss them.
        primary_ticks: List[Tuple[float, float]] = []
        if page_rect is not None:
            if starts_with_section:
                # Section-number heading — header side only.
                ordered_sides = (False,)
            else:
                ordered_sides = (starts_with_fig, not starts_with_fig)
            for try_caption in ordered_sides:
                if try_caption:
                    search_y0 = max(page_rect.y0, title_bbox.y0 - 260)
                    search_y1 = title_bbox.y0 - 2
                else:
                    search_y0 = title_bbox.y1 + 2
                    search_y1 = min(page_rect.y1, title_bbox.y1 + 260)
                search_x0 = max(page_rect.x0, title_bbox.x0 - 80)
                search_x1 = min(page_rect.x1, title_bbox.x1 + 200)
                search_box = pymupdf.Rect(search_x0, search_y0,
                                          search_x1, search_y1)
                ticks = _scan_numeric_tick_column(words, search_box)
                if len(ticks) < 2:
                    continue
                ys = [y for _, y in ticks]
                col_x0 = max(page_rect.x0, title_bbox.x0 - 60)
                col_x1 = min(page_rect.x1, title_bbox.x1 + 160)
                # Clip horizontally to the nearest neighbouring chart
                # caption on the same row. Datasheet pages routinely lay
                # out two charts side by side (e.g. ST's "Figure 5.
                # Typical gate charge characteristics" next to "Figure 6.
                # Typical drain-source on-resistance" at the same y).
                # Without this clip the title-anchored bbox bleeds into
                # the neighbour, pulling its plot frame and curve into
                # the raster trace.
                for ow in words:
                    if ow.y1 < title_bbox.y0 - 2 or ow.y0 > title_bbox.y1 + 2:
                        continue
                    txt = (ow.text or '').strip()
                    if not re.match(r'(?i)^(?:figure|fig\.?)$', txt):
                        continue
                    if ow.x0 <= title_bbox.x1 + 2:
                        continue
                    if ow.x0 < col_x1:
                        col_x1 = max(title_bbox.x1 + 8, ow.x0 - 4)
                    if ow.x1 > title_bbox.x0 - 2:
                        continue
                    if ow.x1 > col_x0:
                        col_x0 = min(title_bbox.x0 - 8, ow.x1 + 4)
                # Extend the bbox by ~one tick-spacing past the topmost
                # and bottommost tick labels. Some charts (e.g. vishay
                # SUP-series gate-charge) draw the plot frame and curve
                # well above the topmost tick label, so a tight crop
                # around the tick column would exclude the curve segment
                # carrying the Miller plateau.
                sorted_ys = sorted(ys)
                if len(sorted_ys) >= 2:
                    diffs = [sorted_ys[i + 1] - sorted_ys[i]
                             for i in range(len(sorted_ys) - 1)]
                    tick_spacing = max(diffs)
                else:
                    tick_spacing = 6.0
                pad = max(6.0, tick_spacing)
                candidate_bbox = pymupdf.Rect(col_x0,
                                              min(ys) - pad,
                                              col_x1,
                                              max(ys) + pad)
                if img_rect is not None and abs(img_rect.y0 - candidate_bbox.y0) < 10:
                    continue
                if img_rect is None:
                    img_rect = candidate_bbox
                    is_caption = try_caption
                    primary_ticks = ticks
                elif try_caption == is_caption and not primary_ticks:
                    # img_rect was set by the full-page-image synthesizer
                    # earlier; this tick-column scan probed the same side
                    # as our title, so its tick list is the most accurate
                    # calibration we'll get for our chart. Use it as
                    # primary_ticks instead of adding a redundant
                    # extra_chart with a wider bbox. The wider bbox tends
                    # to pull the raster trace away from the real plateau
                    # because it includes neighbouring chart chrome.
                    primary_ticks = ticks
                else:
                    extra_charts.append(ChartLocation(
                        page_num=page.number,
                        bbox=candidate_bbox,
                        y_ticks=ticks,
                        x_ticks=[],
                        title=title_text,
                        y_axis_word_bbox=None,
                        x_axis_word_bbox=title_bbox,
                    ))
        if img_rect is None:
            # Last-resort: detect a wireframe rectangle adjacent to the
            # caption. ST-style datasheets render chart axes as vector
            # glyphs (not text), so neither image-based nor tick-column
            # search yields anything; the only signal is the plot
            # frame's outline.
            wf = _find_chart_wireframe(page, title_bbox, starts_with_fig,
                                       header_only=starts_with_section)
            if wf is None:
                continue
            _outer, inner = wf
            img_rect = inner
            # The wireframe path doesn't reveal numeric ticks. Calibrate
            # V_GS axis assuming the chart's plotted curve ends at
            # V_drive = 10 V at its rightmost / topmost point — that's
            # the standard data-sheet convention (Q_g curve plotted up
            # to the rated drive voltage). Using the *curve's* top y as
            # the 10 V anchor instead of the plot-frame top handles ST
            # datasheets whose Y axis extends past V_drive (e.g.
            # STL70N4LLF5 with a 0..14 V scale and a 10 V curve end).
            curve_top_y = _find_curve_top_y(page, inner)
            if curve_top_y is None or curve_top_y < inner.y0 + 1:
                # No usable curve detected, or curve reaches the frame
                # top — fall back to the simple synthesis.
                primary_ticks = [(10.0, inner.y0), (0.0, inner.y1)]
            else:
                primary_ticks = [(10.0, curve_top_y), (0.0, inner.y1)]

        # Refine y_ticks by looking for an OCRed numeric tick column in
        # the chart's expected y-range. This is much more accurate than
        # the default "10V at top of image, 0V at bottom" synthesis,
        # which assumes the image edges == the plot frame. When the
        # chart's text-axis ticks were already discovered in the wider
        # search box above (i.e. ``primary_ticks`` is populated), use
        # those — re-scanning inside ``img_rect`` will miss them when the
        # tick labels sit slightly outside the synthesized chart bbox.
        if primary_ticks and len(primary_ticks) >= 2:
            y_ticks = primary_ticks
        else:
            y_ticks = _scan_numeric_tick_column(words, img_rect)
            if not y_ticks:
                y_ticks = [(10.0, img_rect.y0), (0.0, img_rect.y1)]

        # OCR often only catches a contiguous run of the V_GS axis ticks
        # — typically the lower half (e.g. 0/2/4 for siliup, where 6/8/10
        # are OCR'd as garbled glyphs and excluded by the equispaced-run
        # filter). The plot interior bbox in ``raster_extract`` then
        # crops to the detected ticks' y-range, missing the upper plot
        # area where the Miller plateau lives.
        #
        # Recover the missing top tick by:
        #   1. Searching the y-axis column for an OCR'd ``"10"`` (or
        #      similar V_drive value) above the detected ticks at the
        #      same x. This is the most accurate anchor — the label
        #      position is read straight from the page.
        #   2. Falling back to linear extrapolation from the existing
        #      ticks when no usable OCR label is found.
        if (len(y_ticks) >= 2 and len(y_ticks) < 6
                and img_rect is not None):
            vs = sorted(y_ticks)
            ys = [y for _, y in y_ticks]
            ys_v = [v for v, _ in y_ticks]
            # Establish the y-axis column's x extent from the detected
            # tick labels (each y-tick label sits next to its tick line).
            # We use it to filter the search for additional labels.
            tick_cxs = []
            for ow in words:
                txt = (ow.text or '').strip()
                if not txt:
                    continue
                try:
                    val = float(txt)
                except ValueError:
                    continue
                # match this OCR label against an existing y_tick by cy
                for v, y in y_ticks:
                    if abs(ow.cy - y) < 3.0 and abs(val - v) < 0.1:
                        tick_cxs.append(ow.cx)
                        break
            if tick_cxs:
                cx_min = min(tick_cxs) - 8.0
                cx_max = max(tick_cxs) + 8.0
            else:
                cx_min = img_rect.x0
                cx_max = img_rect.x1

            extrapolated: List[Tuple[float, float]] = list(y_ticks)

            # Search for OCR labels at typical V_drive values that lie
            # above the topmost detected tick (smaller y) in the same
            # x column. The y-axis labels usually appear at the same
            # x as the detected tick run.
            top_y = min(ys)
            for target_v in (10.0, 20.0):
                if any(abs(v - target_v) < 0.1 for v, _ in y_ticks):
                    continue
                best_w = None
                for ow in words:
                    txt = (ow.text or '').strip()
                    if not txt:
                        continue
                    try:
                        val = float(txt)
                    except ValueError:
                        continue
                    if abs(val - target_v) > 0.5:
                        continue
                    if not (cx_min <= ow.cx <= cx_max):
                        continue
                    # Must sit ABOVE (smaller y) the topmost detected
                    # tick by at least a tick-spacing — guards against
                    # picking the existing top tick as itself.
                    if ow.cy >= top_y - 5.0:
                        continue
                    if ow.cy < img_rect.y0 - 30:
                        continue
                    if best_w is None or ow.cy > best_w.cy:
                        best_w = ow
                if best_w is not None:
                    extrapolated.append((target_v, best_w.cy))
                    break

            # Linear-fit fallback for V=10 / V=0 endpoints not yet
            # covered. Uses least squares on the detected ticks.
            try:
                n = len(y_ticks)
                sx = sum(ys_v)
                sy = sum(ys)
                sxx = sum(v * v for v in ys_v)
                sxy = sum(v * y for v, y in zip(ys_v, ys))
                denom = n * sxx - sx * sx
                if denom != 0:
                    m = (n * sxy - sx * sy) / denom
                    c = (sy - m * sx) / n
                    for target_v in (0.0, 10.0):
                        if any(abs(v - target_v) < 0.1 for v, _ in extrapolated):
                            continue
                        target_y = m * target_v + c
                        if img_rect.y0 - 30 <= target_y <= img_rect.y1 + 30:
                            extrapolated.append((target_v, target_y))
            except (ValueError, ZeroDivisionError):
                pass

            if len(extrapolated) > len(y_ticks):
                y_ticks = sorted(extrapolated, key=lambda t: -t[0])

        loc = ChartLocation(
            page_num=page.number,
            bbox=img_rect,
            y_ticks=y_ticks,
            x_ticks=[],
            title=title_text,
            y_axis_word_bbox=None,
            x_axis_word_bbox=title_bbox,
        )
        out.append(loc)
        out.extend(extra_charts)
    return out


def find_in_pdf(pdf_path: str) -> List[ChartLocation]:
    """Open the PDF and return every detected gate-charge chart."""
    doc = pymupdf.open(pdf_path)
    out: List[ChartLocation] = []
    for page in doc.pages():
        text = page.get_text()
        if 'gate charge' not in text.lower() and 'qg' not in text.lower():
            continue
        out.extend(find_gate_charge_charts(page))
        out.extend(_find_infineon_raster_charts(page))
    return out
