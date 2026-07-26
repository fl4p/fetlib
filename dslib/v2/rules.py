"""
Table cell boundaries, read from the PDF's own ruling lines.

Why this exists
---------------
A Conditions cell is routinely merged across several value rows: the sheet
states "VGS = 10 V; Tmb = 25 °C" once and rules it against three rows of
numbers. Reading conditions row-by-row gives them to at most one of those rows,
and every heuristic that tries to spread them further has the same defect --
a row that states no condition is structurally indistinguishable from a row
whose neighbour's conditions are *irrelevant to it*. An abs-max Vds row sitting
under an "ID drain current | VGS = 5 V" row must NOT inherit VGS.

Proximity cannot tell those apart. The table's rulings can, and they are
already in the file.

The signal
----------
PDF producers emit rulings PER CELL, each segment carrying its own x-range. So
a vertically merged cell shows up as a *missing* ruling over that column while
its neighbours are ruled at the same y. On nxp/BUK763R8-80E page 1 the narrow
left column yields a different band per row (655.3-638.4, 638.4-621.5,
621.5-604.6) while the merged "Simplified outline" column yields one band,
655.3-556.2, for all three.

What is deliberately refused
----------------------------
* A band open at either end. Unbounded is not "merged", it is "unruled", and
  spreading conditions across it would attach them to rows that never shared a
  cell.
* A band with no interior ruling in a *neighbouring* column. That is the
  degenerate case where only the table outline is drawn: every column then
  reports one band spanning the whole table, which looks exactly like a merge
  of everything. Requiring a neighbour to be ruled inside the band is what
  proves the producer rules individual rows and omitted this boundary on
  purpose. 55 of 60 sampled sheets have that granularity; the other 5 get
  nothing from this module rather than a guess.

Cost
----
``page.get_drawings()`` walks vector operators that ``chars.py`` deliberately
skips for speed (~34% on top of text extraction, and chart-heavy pages are the
worst). Extraction is therefore lazy and memoized per (path, page): a page only
pays when something actually asks it for a cell boundary.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional, Tuple

# A segment thinner than this (pt) is a rule; thicker is a filled box.
_MAX_RULE_THICKNESS = 1.5
# Ignore hairline ticks: a rule must be at least this long (pt).
_MIN_RULE_LENGTH = 3.0
# Fraction of a column's width a ruling must span to count as its boundary.
_COVER_FRAC = 0.6
# A ruling within this many pt of a band edge is that edge, not an interior one.
_INTERIOR_EPS = 1.0

Rule = Tuple[float, float, float]      # (y, x1, x2), y in PDF-up coordinates


@lru_cache(maxsize=64)
def page_rules(pdf_path: str, page_num: int) -> Tuple[Rule, ...]:
    """Horizontal rulings on one page, deduplicated, y descending.

    Returns an empty tuple when the page has none or cannot be read. That is
    an honest "no cell information", and every consumer here treats it as
    refusing to infer rather than as "no merge".
    """
    try:
        import fitz
    except Exception:
        return ()
    if not os.path.exists(pdf_path):
        return ()
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return ()
    try:
        if page_num >= len(doc):
            return ()
        page = doc[page_num]
        height = page.rect.height
        out = set()
        try:
            drawings = page.get_drawings()
        except Exception:
            return ()
        for item in drawings:
            for seg in item.get("items", ()):
                if seg[0] == "l":
                    a, b = seg[1], seg[2]
                    if (abs(a.y - b.y) < _MAX_RULE_THICKNESS
                            and abs(a.x - b.x) > _MIN_RULE_LENGTH):
                        out.add((round(height - a.y, 1),
                                 round(min(a.x, b.x), 1),
                                 round(max(a.x, b.x), 1)))
                elif seg[0] == "re":
                    r = seg[1]
                    # a thin filled rectangle is a rule drawn as a box
                    if (r.height <= _MAX_RULE_THICKNESS
                            and r.width > _MIN_RULE_LENGTH):
                        out.add((round(height - r.y0, 1),
                                 round(r.x0, 1), round(r.x1, 1)))
        return tuple(sorted(out, reverse=True))
    except Exception:
        return ()
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _covers(rule: Rule, x1: float, x2: float) -> bool:
    _, rx1, rx2 = rule
    ov = min(rx2, x2) - max(rx1, x1)
    return ov > 0 and ov / max(x2 - x1, 1e-6) >= _COVER_FRAC


def cell_band(rules: Tuple[Rule, ...], x1: float, x2: float,
              y: float) -> Optional[Tuple[float, float]]:
    """(top, bottom) of the cell containing baseline ``y`` in column [x1,x2].

    None when the cell is not bounded on BOTH sides -- see the module note on
    why an open band must not be treated as a merge.
    """
    top = bottom = None
    for r in rules:
        if not _covers(r, x1, x2):
            continue
        if r[0] > y:
            if top is None or r[0] < top:
                top = r[0]
        elif r[0] < y:
            if bottom is None or r[0] > bottom:
                bottom = r[0]
    if top is None or bottom is None:
        return None
    return top, bottom


def band_is_credible(rules: Tuple[Rule, ...], band: Tuple[float, float],
                     x1: float, x2: float) -> bool:
    """Is this band a real merged cell rather than an unruled table?

    Requires a ruling that lies strictly INSIDE the band and covers something
    OUTSIDE this column. That is the evidence that the producer draws
    per-row boundaries and left this one out deliberately. Without it the band
    is just the table outline, and every column would claim to be merged.
    """
    top, bottom = band
    for y, rx1, rx2 in rules:
        if not (bottom + _INTERIOR_EPS < y < top - _INTERIOR_EPS):
            continue
        # a segment reaching materially beyond this column, or sitting wholly
        # beside it, belongs to a neighbouring cell
        if rx2 <= x1 + _INTERIOR_EPS or rx1 >= x2 - _INTERIOR_EPS:
            return True
    return False


def rows_in_band(row_ys: List[float], band: Tuple[float, float]) -> List[int]:
    """Indices of baselines falling inside a band (exclusive of its edges)."""
    top, bottom = band
    return [i for i, y in enumerate(row_ys) if bottom < y < top]
