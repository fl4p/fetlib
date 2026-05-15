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
            try:
                if not _values_linear_in_position(run, key_pos=lambda w: w.cy):
                    continue
            except ValueError:
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

    # x-ticks: horizontal row near the bottom of the chart. Cluster by y.
    y_clusters = _cluster(nums, lambda w: w.cy, 4.0)
    x_row: Optional[List[_Word]] = None
    for cl in sorted(y_clusters, key=lambda c: -len(c)):
        if len(cl) < 3:
            continue
        cy = sum(w.cy for w in cl) / len(cl)
        if cy < yword.cy:
            continue
        if cy > xword_left.y0 - 1:
            continue
        run = _longest_equispaced_run(sorted(cl, key=lambda w: w.cx),
                                      pos=lambda w: w.cx)
        if len(run) < 3:
            continue
        try:
            if not _values_linear_in_position(run, key_pos=lambda w: w.cx):
                continue
        except ValueError:
            continue
        x_row = run
        break

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


def find_in_pdf(pdf_path: str) -> List[ChartLocation]:
    """Open the PDF and return every detected gate-charge chart."""
    doc = pymupdf.open(pdf_path)
    out: List[ChartLocation] = []
    for page in doc.pages():
        text = page.get_text()
        if 'gate charge' not in text.lower() and 'qg' not in text.lower():
            continue
        out.extend(find_gate_charge_charts(page))
    return out
