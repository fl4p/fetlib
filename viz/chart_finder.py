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
    # 1. bare "<n>? Typ. gate charge" — no trailing suffix required.
    # "Typ." and the number prefix may be separated by punctuation /
    # spaces ("14 : Typ . gate charge") — pdfminer/tesseract sometimes
    # break tokens apart.
    r"([0-9]*[\s.:]*typ\s*\.?\s*gate[\s-]+charge\b.*"
    r"|[0-9]*[\s.:]*typycal\s+gate[\s-]+charge\b.*"
    # 2. "[Typ.] gate charge curve/vs/waveforms"
    r"|(typ\s*\.?\s+)?gate[\s-]+charge\s+(curve|vs|waveforms?).*"
    # 3. "Figure / Diagram N. Gate Charge ..." (separator is optional —
    # some manufacturers write "Fig.6 Gate Charge" without "." or ":")
    r"|(Diagram|Fig.?(ure)?)\s*[0-9]+\s*[.:]?\s+Gate[\s-]+Charge.*)",
    re.IGNORECASE,
)


def _group_words_by_line(words: List[_Word], y_tol: float = 3.0,
                         x_gap_split: float = 50.0
                         ) -> List[List[_Word]]:
    """Group words by baseline (cy within ``y_tol``), then split each line
    on horizontal gaps larger than ``x_gap_split`` — two charts' captions
    that share a baseline (Infineon table-style layouts) must end up as
    *separate* title candidates, not a single merged line.
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
            if w.x0 - chunk[-1].x1 > x_gap_split:
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
    r'(?i)(test\s+circuit|circuit\s*&\s*waveform|circuit\s+and\s+waveform)'
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
        if _CHART_TITLE_RE.search(text):
            out.append(line)
    if len(out) >= 2:
        non_wave = [l for l in out
                    if 'waveform' not in ' '.join(w.text for w in l).lower()]
        if non_wave:
            return non_wave
    return out


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
            if best_run is None or len(run) > len(best_run):
                best_run = run
    if not best_run:
        return []
    return [(float(w.text), w.cy) for w in sorted(best_run, key=lambda w: w.cy)]


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
            # so the right interpretation wins on the typical case.
            for try_caption in (starts_with_fig, not starts_with_fig):
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
            chart_h = 260.0
            if is_caption:
                cy0 = max(page_rect.y0, title_bbox.y0 - chart_h - 4)
                cy1 = title_bbox.y0 - 2
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
        extra_charts: List[ChartLocation] = []
        if page_rect is not None:
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
                candidate_bbox = pymupdf.Rect(col_x0,
                                              min(ys) - 6,
                                              col_x1,
                                              max(ys) + 6)
                if img_rect is not None and abs(img_rect.y0 - candidate_bbox.y0) < 10:
                    continue
                if img_rect is None:
                    img_rect = candidate_bbox
                    is_caption = try_caption
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
            continue

        # Refine y_ticks by looking for an OCRed numeric tick column in
        # the chart's expected y-range. This is much more accurate than
        # the default "10V at top of image, 0V at bottom" synthesis,
        # which assumes the image edges == the plot frame.
        y_ticks = _scan_numeric_tick_column(words, img_rect)
        if not y_ticks:
            y_ticks = [(10.0, img_rect.y0), (0.0, img_rect.y1)]

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
