"""Find the Miller plateau voltage (Vpl) by extracting the Gate Charge curve from a MOSFET datasheet PDF.

Usage:
    python3 vpl_from_chart.py <datasheet.pdf> [--debug]

The program:
  1. Scans each page for a chart whose X-axis is Q_gate (nC) and Y-axis is V_GS (V),
     using the positions of numeric tick labels in the PDF text layer.
  2. Rasterises the chart region at high DPI and isolates the dark curve pixels
     (the gate-charge curve(s), one per parametric V_DS).
  3. Builds a histogram of curve-pixel rows: the Miller plateau, being the only
     horizontal segment of the curve, shows up as a sharp peak.
  4. Maps the peak back to V_GS coordinates and returns it as Vpl.
"""
from __future__ import annotations

import argparse
import re
import sys
import warnings
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import fitz  # PyMuPDF
import numpy as np

X_AXIS_KEYWORDS = ('q', 'qg', 'qgate', 'charge', 'gate charge', 'nc')
# Y axis covers V_GS for MOSFETs and V_GE for IGBTs — the Miller-plateau
# mechanism is the same.
Y_AXIS_KEYWORDS = ('vgs', 'v gs', 'gate-source', 'gate to source', 'gate-to-source',
                   'vge', 'v ge', 'gate-emitter', 'gate to emitter', 'gate-to-emitter')
# Compiled word-bounded versions of the keyword lists — substring matching
# like 'nc' in 'Resistance' was giving false positives, so each keyword has to
# match as a whole word (or unit-style "(nC)" / "[nC]").
_KW_RE_CACHE: dict = {}


def _kw_regex(words):
    """Compile a regex that matches any of *words* at a word boundary."""
    key = tuple(words)
    if key in _KW_RE_CACHE:
        return _KW_RE_CACHE[key]
    pat = re.compile(
        r'(?<![a-z0-9_])(?:' + '|'.join(re.escape(w) for w in words) + r')(?![a-z0-9_])',
        re.I,
    )
    _KW_RE_CACHE[key] = pat
    return pat

# Caption regex used to locate gate-charge chart titles like
#   "14 Typ. gate charge"          (Infineon recent)
#   "Diagram 14: Typ. gate charge" (Infineon older)
#   "Fig.7 Gate-Charge Characteristics"
#   "Typical Gate Charge Waveform"
# Anchored on the phrase "gate charge" (with optional hyphen / underscore /
# whitespace).  We deliberately accept anything else around it so unusual
# layouts still match — the *positional* check that an image sits below the
# caption keeps false positives away.
CAPTION_RE = re.compile(r'(?i)\bgate[\s\-_]*charge\b')
# Phrases that indicate this is NOT the parametric V_GS(Q_g) chart we want:
# "gate charge waveforms" is the Q_GS/Q_GD/Q_SW definition schematic,
# spec-table rows mention "total"/"Q_gs"/"Q_gd"/"Q_sw".
CAPTION_REJECT_RE = re.compile(
    r'(?i)('
    r'\bwaveforms?\b'
    r'|\btotal\b'
    r'|\bq[\s_]*gs\b|\bq[\s_]*gd\b|\bq[\s_]*sw\b'
    r'|see\s+figure'
    r'|\b(at|to)\s+threshold\b'
    r'|sync(\.|hronous)?\s*fet'
    # Spec-table headers and feature-list bullets that mention "gate charge"
    # but aren't chart titles.
    r'|\bcharacteristics\)?\s*[\'"”]?\s*$'
    r'|\bexcellent\b'
    r'|\bx\s+R\s*(ds|os)'
    r')'
)
# A real chart caption typically starts with one of these prefixes, e.g.
#   "14 Typ. gate charge"            (just a number)
#   "Diagram 14: Typ. gate charge"
#   "Fig. 7 Gate-Charge Characteristics"
CAPTION_PREFIX_RE = re.compile(
    r'(?i)^\s*(?:'
    r'\d+[\s:.]'                            # bare numeric prefix "14 "
    r'|(?:diagram|fig\.?|figure|chart)\b'   # "Diagram", "Fig.", optionally followed by a number
    r')'
)

# Chart titles whose axes look like a gate-charge chart but whose CONTENT is
# something else: the Q_GS/Q_GD/Q_SW definition schematic, the body-diode
# V_SD curve, or the switching-time test schematic.  Words may be separated
# by spaces, hyphens, underscores, NBSP, or stray control chars (PDF tooling
# emits all of these).
_TITLE_SEP = r'[\s\-_\x00-\x1f\xa0]+'
CHART_TITLE_REJECT_RE = re.compile(
    r'(?i)('
    r'gate' + _TITLE_SEP + r'charge' + _TITLE_SEP + r'waveform'
    r'|source' + _TITLE_SEP + r'drain' + _TITLE_SEP + r'diode'
    r'|switching' + _TITLE_SEP + r'time' + _TITLE_SEP + r'test'
    r'|output' + _TITLE_SEP + r'characteristics'
    r')'
)


@dataclass
class AxisAP:
    """An arithmetic-progression axis: tick values + their PDF coords."""
    values: List[float]
    cx: List[float]  # tick label centre x in PDF points
    cy: List[float]  # tick label centre y in PDF points


@dataclass
class ChartFrame:
    """A detected XY chart: X-axis (horizontal AP), Y-axis (vertical AP), and surrounding text."""
    x_axis: AxisAP
    y_axis: AxisAP
    x_label_text: str
    y_label_text: str
    nearby_text: str  # title / caption text near the chart
    page_index: int


def _parse_number(text: str) -> Optional[float]:
    # Normalise unicode dashes and strip whitespace.  Some PDFs render "−10"
    # as a single span with a space ("– 10") so we also collapse the dash and
    # the digits when only whitespace separates them.
    t = text.strip().replace('−', '-').replace('–', '-').replace('—', '-')
    if not t:
        return None
    if t[0] == '-' and len(t) > 1 and t[1].isspace():
        t = '-' + t[1:].lstrip()
    try:
        return float(t)
    except ValueError:
        return None


def _get_spans(page) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    spans = []
    for block in page.get_text('dict')['blocks']:
        if 'lines' not in block:
            continue
        for line in block['lines']:
            for span in line['spans']:
                text = span['text'].strip()
                if text:
                    spans.append((text, tuple(span['bbox'])))
    return spans


def _cluster_1d(items, key_idx, tol):
    items = sorted(items, key=lambda x: x[key_idx])
    groups, cur = [], []
    for it in items:
        if not cur or abs(it[key_idx] - cur[-1][key_idx]) < tol:
            cur.append(it)
        else:
            groups.append(cur)
            cur = [it]
    if cur:
        groups.append(cur)
    return groups


def _maximal_arithmetic_progressions(items, pos_idx, eps_v=0.05, eps_x=0.20, min_len=4):
    """Find all maximal sequences in *items* that are arithmetic in both value
    (index 0) and position (index *pos_idx*).  Each item is (value, cx, cy, bbox).
    """
    items = sorted(items, key=lambda x: x[pos_idx])
    n = len(items)
    if n < min_len:
        return []
    found = []
    for i in range(n):
        for j in range(i + 1, n):
            dv = items[j][0] - items[i][0]
            dx = items[j][pos_idx] - items[i][pos_idx]
            if abs(dv) < 1e-9 or abs(dx) < 1e-9:
                continue
            idxs = [i, j]
            cur = items[j]
            for k in range(j + 1, n):
                ndv = items[k][0] - cur[0]
                ndx = items[k][pos_idx] - cur[pos_idx]
                if (abs(ndv - dv) < eps_v * abs(dv) + 1e-9 and
                        abs(ndx - dx) < eps_x * abs(dx)):
                    idxs.append(k)
                    cur = items[k]
            if len(idxs) >= min_len:
                found.append(tuple(idxs))
    # keep only maximal (not strict subsets of longer ones)
    sets = [set(s) for s in found]
    maximal = []
    for i, s in enumerate(found):
        if any(j != i and sets[i] < sets[j] for j in range(len(found))):
            continue
        maximal.append([items[k] for k in s])
    return maximal


_DASH_CHARS = frozenset({'-', '–', '—', '−', '‐', '‑', '‒'})


def _is_minus_token(t: str) -> bool:
    s = t.strip()
    return bool(s) and all(c in _DASH_CHARS for c in s)


def _build_axes(page) -> Tuple[List[AxisAP], List[AxisAP]]:
    spans = _get_spans(page)
    # Collect numbers, plus any standalone "minus" tokens — some PDFs (e.g. TI's
    # P-channel datasheets) render axis labels like "−6" as two separate spans
    # ("−" and "6"), so we glue them back together by proximity.
    nums = []
    minus_signs = []  # (cx, cy, x1)
    for text, bb in spans:
        if _is_minus_token(text):
            minus_signs.append(((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, bb[2]))
            continue
        v = _parse_number(text)
        if v is None:
            continue
        nums.append((v, (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, bb))
    # Apply preceding minus signs: a minus token whose right edge sits just
    # left of a positive number AND on the same baseline negates that number.
    if minus_signs:
        attached = []
        for i, (v, cx, cy, bb) in enumerate(nums):
            if v < 0:
                attached.append((v, cx, cy, bb)); continue
            x0 = bb[0]
            for mx, my, mx1 in minus_signs:
                if abs(my - cy) > 4:
                    continue
                gap = x0 - mx1
                if -2 <= gap <= 10:  # immediately to the left
                    v = -v
                    break
            attached.append((v, cx, cy, bb))
        nums = attached
    h_axes: List[AxisAP] = []
    for grp in _cluster_1d(nums, 2, 3.0):  # cluster by cy → horizontal axes
        for ap in _maximal_arithmetic_progressions(grp, pos_idx=1):
            h_axes.append(AxisAP([it[0] for it in ap], [it[1] for it in ap], [it[2] for it in ap]))
    v_axes: List[AxisAP] = []
    for grp in _cluster_1d(nums, 1, 3.0):  # cluster by cx → vertical axes
        for ap in _maximal_arithmetic_progressions(grp, pos_idx=2):
            v_axes.append(AxisAP([it[0] for it in ap], [it[1] for it in ap], [it[2] for it in ap]))
    return h_axes, v_axes


def _text_in_box(spans, x0, y0, x1, y1) -> str:
    out = []
    for text, bb in spans:
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            out.append(text)
    return ' '.join(out)


def _has_any(text_lower: str, keywords) -> bool:
    # Use word-bounded regex matching instead of plain substring; short
    # keywords like 'q' or 'nc' would otherwise match inside unrelated words
    # like 'Resistance', 'frequency', etc., and pull in non-gate-charge
    # charts (transfer characteristics, Rds_on vs Id, ...).
    return bool(_kw_regex(keywords).search(text_lower))


def find_gate_charge_charts(doc) -> List[ChartFrame]:
    """Locate every (V_GS vs Q_gate) chart in the PDF."""
    results: List[ChartFrame] = []
    for page_idx, page in enumerate(doc):
        spans = _get_spans(page)
        h_axes, v_axes = _build_axes(page)
        for h in h_axes:
            hxs = h.cx
            hy = float(np.mean(h.cy))
            hvs = h.values
            # X-axis must be a positive Q_gate axis
            if min(hvs) < 0 or max(hvs) <= 0:
                continue
            # Q_gate typical range is 1..1000 nC
            if max(hvs) < 1 or max(hvs) > 2000:
                continue
            for v in v_axes:
                vys = v.cy
                vx = float(np.mean(v.cx))
                vvs = v.values
                # V_GS axis: roughly 0..(+5..+25)V for N-channel,
                # 0..(-5..-25)V for P-channel.  IGBT V_GE ranges are typically
                # symmetric around zero (e.g. -15..+15V) — accept those too.
                vabs_max = max(abs(min(vvs)), abs(max(vvs)))
                if vabs_max < 4 or vabs_max > 25:
                    continue
                # Geometric corner: vertical axis sits to the left of x-axis labels,
                # horizontal axis sits below vertical axis labels.
                if not (min(hxs) - 35 <= vx <= max(hxs) + 15):
                    continue
                if not (min(vys) - 10 <= hy <= max(vys) + 60):
                    continue
                # X-axis label area: below the X-tick row
                x_label = _text_in_box(
                    spans, min(hxs) - 50, hy + 2, max(hxs) + 50, hy + 30,
                )
                # Y-axis label area: left of the Y-tick column
                y_label = _text_in_box(
                    spans, vx - 90, min(vys) - 30, vx - 1, max(vys) + 30,
                )
                # Nearby (title) text: a band above the chart
                title = _text_in_box(
                    spans, min(hxs) - 80, min(vys) - 80, max(hxs) + 80, min(vys) - 2,
                )
                blob_lower = (x_label + ' ' + y_label + ' ' + title).lower()
                # Score: x-axis label should mention Q/charge/nC, y-axis V_GS
                x_ok = _has_any(x_label.lower() + ' ' + title.lower(), X_AXIS_KEYWORDS)
                y_ok = _has_any(y_label.lower() + ' ' + title.lower(), Y_AXIS_KEYWORDS)
                if not (x_ok and y_ok):
                    continue
                # Reject charts whose title matches a known non-plateau diagram
                # (gate-charge waveform definitions, body-diode V_SD curve, or
                # the switching-time test schematic) — they pass the keyword
                # check but don't carry the parametric V_GS(Q_g) curve.
                # Check only the TITLE band (text above the chart); sibling
                # diagrams below sometimes share keywords with the reject list
                # and would otherwise cause false rejections.
                if CHART_TITLE_REJECT_RE.search(title.lower()):
                    continue
                results.append(ChartFrame(
                    x_axis=h, y_axis=v,
                    x_label_text=x_label,
                    y_label_text=y_label,
                    nearby_text=title,
                    page_index=page_idx,
                ))
    return results


# ---------------------------------------------------------------------------
# Caption-based chart detection for rasterised charts (no text-layer tick labels)
# ---------------------------------------------------------------------------


def _ocr_page_captions(page, dpi: int = 220):
    """OCR the entire page (used for fully-scanned PDFs that have no text
    layer) and return [(text, bbox_pdf), ...] for every CAPTION-LIKE phrase
    on the page.  A "phrase" is a sequence of words on the same OCR line that
    is separated from neighbouring phrases by either a "Diagram"/"Fig"
    keyword (indicating a new caption starts) or a large horizontal gap.
    bbox is in PDF point coordinates.
    """
    try:
        import pytesseract
    except ImportError:
        warnings.warn('pytesseract missing')
        return []
    from PIL import Image
    scale = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                          colorspace=fitz.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    pil = Image.fromarray(img)
    # PSM 4 (column of text of variable sizes) handles multi-column chart
    # captions better than PSM 6.  Try it first, then PSM 6 as a fallback.
    data = None
    for psm in (4, 6):
        try:
            data = pytesseract.image_to_data(
                pil, output_type=pytesseract.Output.DICT, config=f'--psm {psm}')
        except pytesseract.TesseractError as e:
            print('tesseract error', e)
            continue
        # Did we find any candidate caption?  If not, try the next PSM.
        joined = ' '.join(t for t in data['text'] if t)
        if CAPTION_RE.search(joined):
            break
    if data is None:
        return []
    # Collect words grouped by line.
    lines = {}
    for i, t in enumerate(data['text']):
        if not t or not t.strip():
            continue
        try:
            conf = float(data['conf'][i])
        except (ValueError, TypeError):
            conf = -1.0
        if conf < 30:
            continue
        key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
        x = int(data['left'][i]); y = int(data['top'][i])
        w = int(data['width'][i]); h = int(data['height'][i])
        lines.setdefault(key, []).append({'text': t, 'x0': x, 'y0': y,
                                          'x1': x + w, 'y1': y + h})

    out = []
    new_caption_re = re.compile(r'(?i)^(diagram|fig\.?|figure|chart|table)$')
    for words in lines.values():
        if not words:
            continue
        words.sort(key=lambda w: w['x0'])
        # Compute typical character width to detect "large" gaps.
        avg_h = float(np.mean([w['y1'] - w['y0'] for w in words]))
        # Split the line into phrases.
        phrases = [[words[0]]]
        for prev, cur in zip(words, words[1:]):
            gap = cur['x0'] - prev['x1']
            start_new = False
            if gap > avg_h * 3:  # ~3 character-heights of whitespace
                start_new = True
            if new_caption_re.match(cur['text'].rstrip(':.,')):
                start_new = True
            if start_new:
                phrases.append([cur])
            else:
                phrases[-1].append(cur)
        # Emit phrases.
        for phrase in phrases:
            text = ' '.join(w['text'] for w in phrase)
            x0 = min(w['x0'] for w in phrase)
            y0 = min(w['y0'] for w in phrase)
            x1 = max(w['x1'] for w in phrase)
            y1 = max(w['y1'] for w in phrase)
            bb_pdf = (x0 / scale, y0 / scale, x1 / scale, y1 / scale)
            out.append((text, bb_pdf))
    return out


def _find_caption_image_pairs(page):
    """Return [(caption_text, caption_bbox, image_bbox), ...] for any caption
    on the page that matches CAPTION_RE (and isn't excluded by REJECT_RE).

    * If the page has a text layer, we use the PDF spans.  An embedded image
      directly below the caption gives the chart bbox.
    * If the page has no text (fully scanned), we OCR the page to find the
      caption, then use a quadrant heuristic — the chart sits below the
      caption in the same horizontal half of the page, ending at the next
      caption or the bottom margin.

    The returned image_bbox is a `fitz.Rect` in PDF point coordinates.
    """
    spans = _get_spans(page)

    # Collect (a) captions that name a gate-charge chart and (b) any other
    # figure caption on the page — we use (b) only as upper bounds when we
    # need to compute a quadrant fallback bbox.
    captions = []
    other_captions = []
    if spans:
        for text, bbox in spans:
            if CAPTION_RE.search(text) and not CAPTION_REJECT_RE.search(text):
                captions.append((text, bbox))
            elif CAPTION_PREFIX_RE.search(text):
                other_captions.append((text, bbox))
    if not captions:
        # Fall back to OCR (slow).  For OCR we additionally REQUIRE the
        # caption to look like a figure caption ("14 ...", "Diagram 14: ...",
        # "Fig. 7 ..."), because OCR will otherwise drown us in spec-table
        # rows that mention "gate charge".
        ocr_caps = _ocr_page_captions(page)
        for text, bbox in ocr_caps:
            if not CAPTION_PREFIX_RE.search(text):
                continue
            if CAPTION_RE.search(text) and not CAPTION_REJECT_RE.search(text):
                captions.append((text, bbox))
            else:
                other_captions.append((text, bbox))
    if not captions:
        return []

    # Collect embedded image bboxes (for the BSB-style case).
    # Use ``get_image_rects`` rather than ``get_image_bbox``: the latter
    # raises (and noisily logs) for images referenced in the page resource
    # dict but not actually placed on the page; the former returns ``[]``.
    images = page.get_images(full=True)
    image_bboxes = []
    for img in images:
        try:
            rects = page.get_image_rects(img)
        except Exception:  # noqa: BLE001
            continue
        if not rects:
            continue
        bb = rects[0]
        if bb.is_empty:
            continue
        image_bboxes.append(bb)

    page_rect = page.rect
    pairs = []
    for text, bbox in captions:
        cap_x_lo, cap_y_lo, cap_x_hi, cap_y_hi = bbox
        cap_cx = (cap_x_lo + cap_x_hi) / 2

        # 1) Prefer an embedded image directly below.
        best = None
        for ibox in image_bboxes:
            if ibox.y0 < cap_y_hi - 2:
                continue
            if not (ibox.x0 - 60 <= cap_cx <= ibox.x1 + 60):
                continue
            gap = ibox.y0 - cap_y_hi
            if gap > 200:
                continue
            if best is None or gap < best[0]:
                best = (gap, ibox)
        if best:
            pairs.append((text, bbox, best[1]))
            continue

        # 2) Fall back to a quadrant of the page: same horizontal half,
        #    extending from just below the caption down to the next caption
        #    in the same column (or the bottom margin).
        page_w = page_rect.width
        if cap_cx < page_w / 2:
            x0, x1 = 0.0, page_w / 2 + 10
        else:
            x0, x1 = page_w / 2 - 10, page_w
        y0 = cap_y_hi + 2
        y1 = page_rect.height - 30  # leave the footer out
        # Refine upper bound using ANY other figure caption below in the same
        # column (e.g. "Diagram 15: ..." or "Fig. 8 ..." after our chart).
        for o_text, o_bbox in list(captions) + list(other_captions):
            if o_text == text:
                continue
            o_cx = (o_bbox[0] + o_bbox[2]) / 2
            same_column = (cap_cx < page_w / 2) == (o_cx < page_w / 2)
            if not same_column:
                continue
            if o_bbox[1] > cap_y_hi and o_bbox[1] < y1:
                y1 = o_bbox[1] - 2
        chart_box = fitz.Rect(x0, y0, x1, y1)
        if chart_box.width > 30 and chart_box.height > 40:
            pairs.append((text, bbox, chart_box))

    return pairs


def _ocr_pass(gray_img: np.ndarray, psm: int, x_off: int = 0, y_off: int = 0,
              whitelist: Optional[str] = None):
    """Run a single tesseract pass on *gray_img* and yield (value, cx, cy, bbox)
    tuples in the original (un-cropped) coordinate space, shifted by
    (x_off, y_off)."""
    try:
        import pytesseract
    except ImportError:
        return
    from PIL import Image
    pil = Image.fromarray(gray_img)
    cfg = f'--psm {psm}'
    if whitelist:
        cfg += f' -c tessedit_char_whitelist={whitelist}'
    try:
        data = pytesseract.image_to_data(
            pil, output_type=pytesseract.Output.DICT, config=cfg)
    except pytesseract.TesseractError:
        return
    for i, raw in enumerate(data['text']):
        if not raw or not raw.strip():
            continue
        try:
            conf = float(data['conf'][i])
        except (ValueError, TypeError):
            conf = -1.0
        if conf < 30:
            continue
        v = _parse_number(raw)
        if v is None:
            continue
        x = int(data['left'][i]) + x_off
        y = int(data['top'][i]) + y_off
        w = int(data['width'][i]); h = int(data['height'][i])
        bb = (x, y, x + w, y + h)
        yield (v, x + w / 2, y + h / 2, bb)


def _ocr_numeric_labels(gray_img: np.ndarray):
    """OCR the chart image to recover tick labels.

    A single full-image PSM 6 pass typically catches the X-axis ticks (rendered
    as a row) but misses single-digit Y-axis ticks scattered down the left
    side.  We add a second pass over a left strip to harvest those.  Results
    are de-duplicated by (value, cx, cy) proximity.
    """
    H, W = gray_img.shape
    digits = '0123456789.'

    # 1) Full image with PSM 6 — gets the X axis row and axis-aligned labels.
    full = list(_ocr_pass(gray_img, psm=6))

    # 2) Left strip with PSM 6 (digits only) — gets the Y axis column.
    left_w = min(W, max(80, int(0.20 * W)))
    left_strip = gray_img[:, :left_w]
    left = list(_ocr_pass(left_strip, psm=6, whitelist=digits))

    # 3) Bottom strip with PSM 6 (digits only) — robustness for the X axis.
    bot_h = min(H, max(60, int(0.15 * H)))
    bot_strip = gray_img[H - bot_h:, :]
    bottom = list(_ocr_pass(bot_strip, psm=6, y_off=H - bot_h, whitelist=digits))

    # Merge and de-duplicate (treat two detections within a few pixels as the
    # same tick label).
    merged = []
    for tok in full + left + bottom:
        v, cx, cy, _ = tok
        if any(abs(cx - m[1]) < 8 and abs(cy - m[2]) < 8 and m[0] == v for m in merged):
            continue
        merged.append(tok)
    return merged


def _collinear_subsets(items, pos_idx, eps_value_frac=0.05, min_len=4):
    """Find subsets of *items* that lie (approximately) on a straight line in
    (position, value) space.  Unlike _maximal_arithmetic_progressions this
    does NOT require consecutive items to share a common difference — it
    tolerates skipped/missing ticks (handy after OCR drops some labels).

    Returns a list of subsets, each as a list of items.
    """
    items = sorted(items, key=lambda x: x[pos_idx])
    n = len(items)
    if n < min_len:
        return []
    found_sets = []
    # For each pair (i, j) define a candidate line value = a*pos + b.
    for i in range(n):
        for j in range(i + 1, n):
            dv = items[j][0] - items[i][0]
            dp = items[j][pos_idx] - items[i][pos_idx]
            if abs(dv) < 1e-9 or abs(dp) < 1e-9:
                continue
            a = dv / dp
            b = items[i][0] - a * items[i][pos_idx]
            # Collect all items consistent with this line.
            chosen = []
            v_range = max(abs(items[i][0]), abs(items[j][0]), 1.0)
            tol = eps_value_frac * v_range + 0.5
            for it in items:
                predicted = a * it[pos_idx] + b
                if abs(it[0] - predicted) <= tol:
                    chosen.append(it)
            # Drop duplicate-value duplicates at the same position (OCR noise):
            # keep the entry closest to predicted.
            dedup = {}
            for it in chosen:
                key = round(it[pos_idx])
                predicted = a * it[pos_idx] + b
                err = abs(it[0] - predicted)
                if key not in dedup or err < dedup[key][1]:
                    dedup[key] = (it, err)
            chosen = sorted((v[0] for v in dedup.values()), key=lambda x: x[pos_idx])
            if len(chosen) >= min_len:
                found_sets.append(chosen)
    # Deduplicate: keep only maximal sets.
    maximal = []
    sets = [set(id(x) for x in s) for s in found_sets]
    for i, s in enumerate(found_sets):
        if any(j != i and sets[i] < sets[j] for j in range(len(found_sets))):
            continue
        maximal.append(s)
    return maximal


def _build_axes_from_nums(nums):
    """Run AP detection on a list of (value, cx, cy, bbox) tuples and return
    (h_axes, v_axes) as AxisAP objects.  OCR'd inputs use a more tolerant
    co-linear fitter (allows missing/skipped ticks)."""
    h_axes: List[AxisAP] = []
    for grp in _cluster_1d(nums, 2, 12.0):  # cluster by cy (OCR jitter is wider)
        # Try strict AP first; fall back to colinear-subset fitting.
        seqs = _maximal_arithmetic_progressions(grp, pos_idx=1)
        if not seqs:
            seqs = _collinear_subsets(grp, pos_idx=1)
        for ap in seqs:
            h_axes.append(AxisAP([it[0] for it in ap],
                                 [it[1] for it in ap],
                                 [it[2] for it in ap]))
    v_axes: List[AxisAP] = []
    for grp in _cluster_1d(nums, 1, 12.0):  # cluster by cx
        seqs = _maximal_arithmetic_progressions(grp, pos_idx=2)
        if not seqs:
            seqs = _collinear_subsets(grp, pos_idx=2)
        for ap in seqs:
            v_axes.append(AxisAP([it[0] for it in ap],
                                 [it[1] for it in ap],
                                 [it[2] for it in ap]))
    return h_axes, v_axes


def find_gate_charge_charts_by_caption(doc) -> List[ChartFrame]:
    """For each page, look for a caption matching CAPTION_RE that sits above
    an embedded image (typical for rasterised Infineon datasheets like
    BSB056N10NN3GXUMA2).  OCR the image to recover tick labels and build an
    AP-based axis pair just like the text-layer detector would have.
    """
    results: List[ChartFrame] = []
    for page_idx, page in enumerate(doc):
        pairs = _find_caption_image_pairs(page)
        for caption_text, caption_bbox, image_bbox in pairs:
            # Render the image region at high DPI for OCR.
            ocr_dpi = 300
            scale = ocr_dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                                  clip=image_bbox, colorspace=fitz.csGRAY,
                                  alpha=False)
            img_px = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width)
            nums_px = _ocr_numeric_labels(img_px)
            if len(nums_px) < 6:
                continue
            # Translate OCR pixel coordinates back into PDF point coordinates
            # so the same downstream pipeline (extract_curves etc.) works.
            def px_to_pdf_x(px_x):
                return image_bbox.x0 + px_x / scale
            def px_to_pdf_y(px_y):
                return image_bbox.y0 + px_y / scale
            nums_pdf = []
            for v, cx_px, cy_px, bb_px in nums_px:
                cx_pdf = px_to_pdf_x(cx_px)
                cy_pdf = px_to_pdf_y(cy_px)
                bb_pdf = (px_to_pdf_x(bb_px[0]), px_to_pdf_y(bb_px[1]),
                          px_to_pdf_x(bb_px[2]), px_to_pdf_y(bb_px[3]))
                nums_pdf.append((v, cx_pdf, cy_pdf, bb_pdf))

            h_axes, v_axes = _build_axes_from_nums(nums_pdf)
            # Match like the text-layer detector: pick the axis pair whose
            # plausibility matches a gate-charge chart.
            for h in h_axes:
                hvs = h.values
                if min(hvs) < 0 or max(hvs) <= 0:
                    continue
                if max(hvs) < 1 or max(hvs) > 2000:
                    continue
                for v in v_axes:
                    vvs = v.values
                    if min(vvs) < -1 or max(vvs) < 4 or max(vvs) > 25:
                        continue
                    hxs = h.cx
                    vys = v.cy
                    vx = float(np.mean(v.cx))
                    hy = float(np.mean(h.cy))
                    if not (min(hxs) - 35 <= vx <= max(hxs) + 15):
                        continue
                    if not (min(vys) - 10 <= hy <= max(vys) + 60):
                        continue
                    results.append(ChartFrame(
                        x_axis=h, y_axis=v,
                        x_label_text='(ocr)', y_label_text='(ocr)',
                        nearby_text=caption_text,
                        page_index=page_idx,
                    ))
                    break
                else:
                    continue
                break  # only the first matching pair per caption
    return results


# ---------------------------------------------------------------------------
# Curve pixel extraction
# ---------------------------------------------------------------------------


def _axis_arrays(chart: ChartFrame):
    """Return (x_pdf, x_val, y_pdf, y_val) numpy arrays of tick positions.

    For P-channel parts the Y-axis labels are all ≤ 0 (e.g. 0, −2, −4, … −10);
    we flip them to absolute V_GS so the rest of the pipeline (plateau
    detection, plausibility checks) stays sign-agnostic.
    """
    xs = np.array(chart.x_axis.cx)
    xv = np.array(chart.x_axis.values)
    ys = np.array(chart.y_axis.cy)
    yv = np.array(chart.y_axis.values)
    if yv.max() <= 0:
        yv = -yv
    return xs, xv, ys, yv


def _linear_fit(p, v):
    # least squares: v = a*p + b
    A = np.vstack([p, np.ones_like(p)]).T
    sol, *_ = np.linalg.lstsq(A, v, rcond=None)
    return float(sol[0]), float(sol[1])


def _render_chart_region(page, x0_pdf, x1_pdf, y0_pdf, y1_pdf, dpi):
    """Render the given PDF Rect at *dpi*; return greyscale uint8 image and
    transform (pixel_x = (pdf_x - x0_pdf) * scale; pixel_y = (pdf_y - y0_pdf) * scale)."""
    scale = dpi / 72.0
    clip = fitz.Rect(x0_pdf, y0_pdf, x1_pdf, y1_pdf)
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, clip=clip, colorspace=fitz.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return img, scale


def extract_curves(page, chart: ChartFrame, dpi: int = 300) -> Tuple[np.ndarray, np.ndarray, dict]:
    """Rasterise the chart's plot area and return the clean curve mask plus a
    transform mapping mask pixels to (Q_gate, V_GS) data coordinates.
    """
    xs_pdf, xv, ys_pdf, yv = _axis_arrays(chart)
    a_x, b_x = _linear_fit(xs_pdf, xv)   # Qg = a_x * pdf_x + b_x
    a_y, b_y = _linear_fit(ys_pdf, yv)   # Vgs = a_y * pdf_y + b_y  (a_y < 0)

    # Chart bounding-rect in PDF points: from origin (Q=0,V=0) to the upper-right tick
    qg_min, qg_max = float(np.min(xv)), float(np.max(xv))
    vgs_min, vgs_max = float(np.min(yv)), float(np.max(yv))
    pdf_x_at_qmin = (qg_min - b_x) / a_x
    pdf_x_at_qmax = (qg_max - b_x) / a_x
    pdf_y_at_vmin = (vgs_min - b_y) / a_y
    pdf_y_at_vmax = (vgs_max - b_y) / a_y
    x_lo = min(pdf_x_at_qmin, pdf_x_at_qmax)
    x_hi = max(pdf_x_at_qmin, pdf_x_at_qmax)
    y_lo = min(pdf_y_at_vmin, pdf_y_at_vmax)
    y_hi = max(pdf_y_at_vmin, pdf_y_at_vmax)

    # Add a small margin so the rendered region includes axis lines
    margin = 4.0
    img, scale = _render_chart_region(
        page, x_lo - margin, x_hi + margin, y_lo - margin, y_hi + margin, dpi,
    )

    # PDF->pixel transform inside the rendered image:
    def pdf_to_px(x_pdf, y_pdf):
        return (x_pdf - (x_lo - margin)) * scale, (y_pdf - (y_lo - margin)) * scale

    qg_min_px = pdf_to_px((qg_min - b_x) / a_x, 0)[0]
    qg_max_px = pdf_to_px((qg_max - b_x) / a_x, 0)[0]
    v_min_px_y = pdf_to_px(0, pdf_y_at_vmin)[1]
    v_max_px_y = pdf_to_px(0, pdf_y_at_vmax)[1]

    # Threshold to extract "ink" pixels.  Curve colour varies across vendors:
    # some draw curves in black (~0), others in mid-grey (~110), with gridlines
    # at a lighter grey (~210) and background near white (255).  We pick the
    # threshold by running OTSU on pixels darker than the near-white background
    # — that excludes the bg cluster from the split so OTSU finds the boundary
    # between the *curve* mode and whatever the next-lightest cluster is
    # (gridlines if present, otherwise just the bg fringe).
    dark_pixels = img[img < 230]
    if dark_pixels.size > 0:
        thr_val, _ = cv2.threshold(dark_pixels, 0, 255,
                                    cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        # Safety floor: avoid pathological thresholds < 30 on near-flat images.
        thr_val = max(30, int(thr_val))
    else:
        thr_val = 110
    _, mask = cv2.threshold(img, thr_val, 255, cv2.THRESH_BINARY_INV)

    # Crop strictly to the plotting area (interior of the axes) so axis lines and
    # tick marks don't contaminate the curve.
    pad_in = max(2, int(scale * 1.0))  # 1 PDF point inside the axes
    H, W = mask.shape
    x_l = max(0, int(round(min(qg_min_px, qg_max_px))) + pad_in)
    x_r = min(W, int(round(max(qg_min_px, qg_max_px))) - pad_in)
    y_t = max(0, int(round(min(v_min_px_y, v_max_px_y))) + pad_in)
    y_b = min(H, int(round(max(v_min_px_y, v_max_px_y))) - pad_in)
    inner = mask[y_t:y_b, x_l:x_r]

    # Suppress thin straight gridlines that span the full chart width/height (vertical
    # or horizontal lines lit in every row or column). True curves are slanted in the
    # ramp regions; only the plateau is fully horizontal, but it shouldn't span the
    # entire width because the curve enters and leaves it. So removing rows lit > 90%
    # of the way across is safe.
    row_fill = inner.mean(axis=1) / 255.0
    grid_rows = row_fill > 0.9
    col_fill = inner.mean(axis=0) / 255.0
    grid_cols = col_fill > 0.9
    inner_clean = inner.copy()
    inner_clean[grid_rows, :] = 0
    inner_clean[:, grid_cols] = 0

    debug = {
        'img_full': img,
        'mask_full': mask,
        'inner_mask': inner,
        'inner_clean': inner_clean,
        'inner_origin': (x_l, y_t),
        'plot_rect_px': (x_l, y_t, x_r, y_b),
        'a_x': a_x, 'b_x': b_x, 'a_y': a_y, 'b_y': b_y,
        'scale': scale,
        'pdf_rect': (x_lo - margin, y_lo - margin, x_hi + margin, y_hi + margin),
    }
    # The transform must carry both the rendered-region origin in PDF coords
    # AND the inner-mask offset within the rendered image, so plateau detection
    # works without the debug dict.
    transform = np.array([a_x, b_x, a_y, b_y, scale,
                          x_lo - margin, y_lo - margin,
                          x_l, y_t])
    return inner_clean, transform, debug


# ---------------------------------------------------------------------------
# Plateau detection
# ---------------------------------------------------------------------------


def _has_pixels_in_box(mask, x0, x1, y0, y1) -> bool:
    H, W = mask.shape
    x0 = max(0, int(x0)); x1 = min(W, int(x1))
    y0 = max(0, int(y0)); y1 = min(H, int(y1))
    if x1 <= x0 or y1 <= y0:
        return False
    return bool(mask[y0:y1, x0:x1].any())


def _longest_run_per_row(mask_bin: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (start_x, end_x, run_length) for the longest contiguous lit run in
    each row of *mask_bin* (uint8/0-1).  Rows with no lit pixels have length 0
    and start=end=0.
    """
    H, W = mask_bin.shape
    start = np.zeros(H, dtype=np.int32)
    end = np.zeros(H, dtype=np.int32)
    length = np.zeros(H, dtype=np.int32)
    pad = np.pad(mask_bin.astype(np.uint8), ((0, 0), (1, 1)), mode='constant')
    for r in range(H):
        row = pad[r]
        diff = np.diff(row.astype(np.int16))
        starts = np.where(diff == 1)[0]
        ends = np.where(diff == -1)[0]
        if len(starts) == 0:
            continue
        runs = ends - starts
        i = int(runs.argmax())
        start[r] = starts[i]
        end[r] = ends[i]
        length[r] = int(runs[i])
    return start, end, length


def find_plateau_vpl(inner_mask: np.ndarray, transform: np.ndarray, debug=None) -> Optional[float]:
    """Locate the Miller plateau in *inner_mask* and return Vpl in volts.

    Strategy:
      1. For each row, find the longest contiguous run of curve pixels.
      2. Keep only rows that look like a real plateau:
           - the run length must be a substantial fraction of the chart width;
           - just to the LEFT of the run's left edge, there must be curve
             pixels BELOW the row (ramp 1 entering the plateau);
           - just to the RIGHT of the run's right edge, there must be curve
             pixels ABOVE the row (ramp 2 leaving the plateau).
         This rejects annotation arrows that sit above the curve, separator
         lines under "test conditions" text boxes, and chart frame edges.
      3. Pick the candidate with the longest run, then refine the y position
         by centroid for sub-pixel accuracy.
    """
    a_x, b_x, a_y, b_y, scale, x0_pdf, y0_pdf, inner_off_x, inner_off_y = transform
    H, W = inner_mask.shape
    if H == 0 or W == 0:
        return None

    # Mild dilation merges antialiased curve gaps but keeps shape roughly intact.
    k = max(1, int(round(scale * 0.5)))
    if k > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        mask = cv2.dilate(inner_mask, kernel)
    else:
        mask = inner_mask.copy()

    bin_mask = (mask > 0).astype(np.uint8)
    start, end, length = _longest_run_per_row(bin_mask)
    # Total lit-pixel count per row, used to reject chart frame borders /
    # full-width annotation lines (these have very high fill but are NOT the
    # plateau).  Real plateaus span roughly 10–35 % of the chart width.
    row_fill = bin_mask.sum(axis=1)

    # Search parameters.
    min_run = max(int(0.05 * W), 6)
    max_fill = int(0.70 * W)  # rows fuller than this are frames/full-width lines
    ramp_x = max(3, int(round(scale * 2.5)))
    ramp_y = max(int(round(scale * 4.0)), int(0.08 * H))
    edge_margin = max(int(round(scale * 1.5)), 3)

    candidates = []  # (length, row, x_lo, x_hi)
    for r in range(edge_margin, H - edge_margin):
        if length[r] < min_run:
            continue
        if row_fill[r] > max_fill:
            continue
        x_lo = int(start[r]); x_hi = int(end[r])
        # Ramp 1: curve pixels below the row, just left of the plateau start.
        left_ramp = _has_pixels_in_box(mask, x_lo - ramp_x, x_lo, r + 1, r + ramp_y)
        # Ramp 2: curve pixels above the row, just right of the plateau end.
        right_ramp = _has_pixels_in_box(mask, x_hi + 1, x_hi + ramp_x, r - ramp_y, r)
        if not (left_ramp and right_ramp):
            continue
        candidates.append((int(length[r]), r, x_lo, x_hi))

    if not candidates:
        return None

    # Group neighbouring rows (within a few pixels) and pick the group with the
    # most TOTAL ink.  The actual plateau spans several rows because the curve
    # has finite line thickness and (for parametric V_DS curves) is rendered as
    # a stack of overlapping lines; a stray dimension arrow or text underline
    # near the plateau has the same max-run but only one row of ink, so summing
    # the per-row run lengths reliably distinguishes them.
    candidates.sort(key=lambda c: c[1])  # by row
    groups = [[candidates[0]]]
    band_tol = max(2, int(round(scale * 0.8)))
    for c in candidates[1:]:
        if c[1] - groups[-1][-1][1] <= band_tol:
            groups[-1].append(c)
        else:
            groups.append([c])
    # Score each group: total ink (sum of per-row lengths); fall back to max
    # length on ties.
    def group_score(g):
        return (sum(c[0] for c in g), max(c[0] for c in g))
    best_group = max(groups, key=group_score)
    best = max(best_group, key=lambda c: c[0])
    _, y_plateau, x_lo, x_hi = best

    # The plateau may be slightly INCLINED — datasheet plateaus aren't always
    # perfectly horizontal — and is rendered with finite line thickness from
    # several parametric (V_DS) curves stacked.  Vpl is conventionally defined
    # as V_GS at the *onset* of the Miller plateau (where ramp 1 finishes), so
    # we evaluate the curve's Y centroid at the LEFT end of the plateau's
    # x-range over a generous vertical band.
    band_half = max(int(round(scale * 3.0)), int(0.025 * H))
    band_lo = max(0, y_plateau - band_half)
    band_hi = min(H, y_plateau + band_half + 1)
    # Use only the first 25 % of the plateau width to lock onto the onset.
    onset_w = max(1, int(0.25 * (x_hi - x_lo + 1)))
    onset = bin_mask[band_lo:band_hi, x_lo:x_lo + onset_w]
    if onset.sum() > 0:
        ys = np.arange(band_lo, band_hi, dtype=np.float32)[:, None]
        weight = onset.astype(np.float32)
        centroid_row_local = float((ys * weight).sum() / weight.sum())
    else:
        centroid_row_local = float(y_plateau)

    pixel_y_in_render = centroid_row_local + inner_off_y
    pdf_y = pixel_y_in_render / scale + y0_pdf
    vpl = a_y * pdf_y + b_y

    if debug is not None:
        debug['curve_mask'] = mask
        debug['row_runs'] = length
        debug['plateau_segment'] = (y_plateau, x_lo, x_hi)
        debug['candidates'] = candidates
        debug['centroid_row_local'] = centroid_row_local
    return float(vpl)


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def vpl_from_pdf(pdf_path: str, dpi: int = 300, enable_ocr=False, debug: bool = False):
    doc = fitz.open(pdf_path)
    charts = find_gate_charge_charts(doc)
    if not charts and enable_ocr:
        # Fallback for rasterised charts: find the figure caption ("14 Typ.
        # gate charge", "Fig. 7 Gate-Charge Characteristics", ...), locate
        # the embedded image below it, and OCR its tick labels.
        charts = find_gate_charge_charts_by_caption(doc)
    results = []
    for chart in charts:
        page = doc[chart.page_index]
        try:
            inner_mask, transform, dbg = extract_curves(page, chart, dpi=dpi)
            vpl = find_plateau_vpl(inner_mask, transform, debug=dbg if debug else None)
        except Exception as exc:  # noqa: BLE001
            results.append({
                'page': chart.page_index + 1,
                'error': str(exc),
                'x_axis_values': chart.x_axis.values,
                'y_axis_values': chart.y_axis.values,
            })
            continue
        results.append({
            'page': chart.page_index + 1,
            'vpl': vpl,
            'x_axis_values': chart.x_axis.values,
            'y_axis_values': chart.y_axis.values,
            'title': chart.nearby_text,
            'debug': dbg if debug else None,
        })
    doc.close()
    return results


def _pick_best(results):
    candidates = [r for r in results if r.get('vpl') is not None]
    if not candidates:
        return None
    # Score each candidate so that:
    #   - a "gate charge" mention in the title is a strong positive signal
    #   - Vpl that falls inside the chart's Y-axis range beats one that doesn't
    #   - a chart with finer Y-axis resolution (smaller range) breaks remaining ties
    import re as _re
    def score(r):
        v = r['vpl']
        ys = r['y_axis_values']
        title = (r.get('title') or '').lower()
        # PDF text often has \x03 / NBSP / various whitespace between words. Normalise.
        title_norm = _re.sub(r'[\s\x00-\x1f\xa0]+', ' ', title)
        title_has_gc = ('gate charge' in title_norm or 'gate-charge' in title_norm or
                        'qgate' in title_norm or 'q gate' in title_norm or 'q g ' in title_norm)
        in_range = (min(ys) <= v <= max(ys))
        # Prefer Vpl that is not at the very top/bottom of the chart (margin > 0.5 V).
        v_margin = min(v - min(ys), max(ys) - v) if in_range else -1.0
        return (title_has_gc, in_range, v_margin, -(max(ys) - min(ys)))
    candidates.sort(key=score, reverse=True)
    return candidates[0]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pdf', help='datasheet PDF')
    p.add_argument('--debug', action='store_true', help='write debug visualisations to /tmp/vpl_debug/')
    p.add_argument('--dpi', type=int, default=300)
    p.add_argument('--all', action='store_true', help='print every detected chart, not just the best one')
    args = p.parse_args()

    results = vpl_from_pdf(args.pdf, dpi=args.dpi, debug=args.debug)
    if not results:
        print(f'{args.pdf}: no gate-charge chart found')
        sys.exit(1)

    if args.debug:
        _write_debug(results, args.pdf)

    if args.all:
        for r in results:
            v = r.get('vpl')
            print(f"page {r['page']}  Vpl={v:.2f} V" if v else f"page {r['page']}  Vpl=?  err={r.get('error')}")
        return

    best = _pick_best(results)
    if best is None:
        print(f'{args.pdf}: detected {len(results)} chart(s) but could not estimate Vpl')
        sys.exit(2)
    print(f"Vpl = {best['vpl']:.2f} V  (page {best['page']})")


def _write_debug(results, pdf_path: str):
    import os
    out = '/tmp/vpl_debug'
    os.makedirs(out, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    for r in results:
        dbg = r.get('debug')
        if not dbg:
            continue
        page = r['page']
        cv2.imwrite(f'{out}/{base}_p{page}_full.png', dbg['img_full'])
        cv2.imwrite(f'{out}/{base}_p{page}_mask.png', dbg['inner_clean'])
        if 'curve_mask' in dbg:
            cv2.imwrite(f'{out}/{base}_p{page}_curve.png', dbg['curve_mask'])
        # max-run plot
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(1, 2, figsize=(10, 4))
            ax[0].imshow(dbg.get('curve_mask', dbg['inner_clean']), cmap='gray')
            if 'plateau_band' in dbg:
                lo, hi = dbg['plateau_band']
                ax[0].axhline(lo, color='r', linewidth=0.5)
                ax[0].axhline(hi, color='r', linewidth=0.5)
            ax[0].set_title(f"page {page} curve")
            ax[1].imshow(dbg.get('curve_mask', dbg['inner_clean']), cmap='gray')
            if 'plateau_segment' in dbg:
                y, x1, x2 = dbg['plateau_segment']
                ax[1].plot([x1, x2], [y, y], color='red', linewidth=1.5, label='plateau row')
                # mark the onset region used for the centroid
                onset_w = max(1, int(0.25 * (x2 - x1 + 1)))
                ax[1].axvspan(x1, x1 + onset_w, color='lime', alpha=0.25, label='onset')
            if 'centroid_row_local' in dbg:
                ax[1].axhline(dbg['centroid_row_local'], color='cyan', linewidth=0.8)
            ax[1].legend(loc='lower right', fontsize=8)
            ax[1].set_title(f"detected plateau; Vpl={r['vpl']:.2f} V")
            fig.tight_layout()
            fig.savefig(f'{out}/{base}_p{page}_runs.png', dpi=120)
            plt.close(fig)
        except Exception:  # noqa: BLE001
            pass


if __name__ == '__main__':
    main()
