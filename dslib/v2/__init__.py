"""
dslib.v2 — a minimal spatial PDF parser for MOSFET datasheets.

Public entry point::

    from dslib.v2 import parse_datasheet
    ds = parse_datasheet('datasheets/onsemi/FDD86367.pdf')
    ds.print()

It walks PDF characters with pdfminer.six, groups them into spatially
clustered rows and words, detects table headers via the project's existing
``head_re``, then per detected parameter symbol (``get_field_detect_regex``)
picks values from the columns under the corresponding header row.

Scanned/OCR-only PDFs are skipped; the caller gets back an empty
``DatasheetFields``.
"""
from __future__ import annotations

import hashlib
import math
import os
import warnings
from typing import Optional

from dslib.cache import disk_cache
from dslib.field import DatasheetFields, Field
from dslib.v2.chars import extract_pages_with_rows, page_likely_needs_ocr
from dslib.v2.tables import (ExtractedRow, _num_with_unit, find_headers,
                             parse_rows_for_page)

_V2_DIR = os.path.dirname(os.path.abspath(__file__))
_V2_SOURCES = ('chars.py', 'tables.py')
_code_sig_memo = {}


def v2_code_salt():
    """Cache salt covering the code that *derives* the result.

    ``hash_func_code=True`` only hashes ``parse_datasheet``'s own source, so
    without this an edit to ``chars.py`` or ``tables.py`` would keep serving
    the old — plausible, silently wrong — cached value forever. The symbol
    regex table is folded in for the same reason.

    Callable so decoration doesn't force ``expr``'s lazy regex tables
    (~1.7 s of regex.compile) at import time.
    """
    key = tuple(os.path.getmtime(os.path.join(_V2_DIR, n)) for n in _V2_SOURCES)
    sig = _code_sig_memo.get(key)
    if sig is None:
        h = hashlib.sha256()
        for n in _V2_SOURCES:
            with open(os.path.join(_V2_DIR, n), 'rb') as f:
                h.update(f.read())
        sig = h.hexdigest()[:16]
        _code_sig_memo.clear()
        _code_sig_memo[key] = sig
    from dslib.pdf.expr import get_field_detect_regex
    from dslib.v2.chars import DEFAULT_BACKEND
    # the backend is chosen by env var, not by an argument, so it would
    # otherwise be invisible to the cache key — one backend's results would be
    # served for the other's.
    return 'v2-src:' + sig, DEFAULT_BACKEND, get_field_detect_regex('any')


def _mfr_mpn_from_path(pdf_path: str):
    parts = pdf_path.replace("\\", "/").split("/")
    mpn = os.path.basename(parts[-1]).rsplit(".", 1)[0]
    mfr = parts[-2] if len(parts) >= 2 else ""
    return mfr, mpn


# Symbols whose value is meaningless without a unit, because the datasheet may
# print them in either of two scales 1000x apart.
#
# Measured trade, on a 60-part sample: dropping this rule recovers 7 correct
# values (4 Rds_on, 3 Rg) and admits 5 wrong ones. The 5 are wrong-CONDITION
# picks (ratios 0.42-0.58), a separate bug this rule only masks by accident —
# which argued for removing it. What settled the matter is that the sample
# contained no unscalable case at all: vishay/SUM60020E, which is not in it,
# emits 0.00175 against a true 1.75 mOhm, exactly 1000x. The "no factor-1000
# errors either way" reading was sample coverage, not absence of the class.
_UNIT_REQUIRED = frozenset({"Rds_on", "Rg", "Rds_on_10v"})

# Below this (in mOhm) a unitless resistance is read as Ohm-denominated rather
# than believed. Grounded in device physics, not in this corpus: the best
# trench MOSFETs bottom out near 0.5-1 mOhm, so 0.00175 is not a 1.75 micro-ohm
# part, it is 1.75 mOhm whose "Ohm" was lost. The DB's own Rds_on distribution
# is bimodal with a void between ~0.01 and ~0.9 mOhm, and the 383 entries below
# it are this same bug already baked into the reference.
#
# This gates TRUST only — it decides whether to emit a value, and never alters
# one, which is why it is not the same kind of rule as main.py:652
# (`if rds_on_max < 0.1: *= 1000`). That line is NOT a blind band-aid and must
# not be deleted: it is the undocumented Ohm->mOhm conversion for the
# `Rds_on_10v` fallback immediately above it, and `Rds_on_10v` is stored
# ohm-scale by convention (n=5476, 100% unitless, median ratio exactly 1.0
# against Rds_on x1000). Its real defect is narrower — it misses the >=100 mOhm
# tail, where an ohm-scale value >= 0.1 stays unconverted and lands 1000x LOW,
# which drives P_on to ~0 and promotes that part to the top of the ranking.
#
# Measured: relative to refusing every unitless resistance, this recovers 11
# values on a 60-part sample — 7 correct, and 4 that are wrong for an unrelated
# reason (wrong test condition, ~2x high, on the ao parts). It is kept anyway,
# because suppressing those 4 was never this rule's doing: the same
# condition-selection bug already emits wrong values on every row whose unit
# *is* readable, so gating them on unit-readability suppressed an arbitrary
# subset of one bug via an unrelated mechanism. Unit provenance and condition
# selection are independent concerns and are better fixed independently.
_MIN_PLAUSIBLE_MILLIOHM = 0.5


def _plausible_as_milliohm(*values: float) -> bool:
    """True if a unitless resistance can be believed as already-mOhm."""
    seen = [v for v in values if not math.isnan(v)]
    return bool(seen) and min(seen) >= _MIN_PLAUSIBLE_MILLIOHM


def _make_field(ex: ExtractedRow) -> Optional[Field]:
    nan = math.nan
    raw = ex.values

    inline_units = []

    def to_val(s: Optional[str]) -> float:
        if s is None:
            return nan
        s = s.strip().strip(",;")
        if not s:
            return nan
        if s in {"-", "--", "---", "—", "~", "nan", "N/A", "n/a"} or set(s) <= {"-", "~"}:
            return nan
        # strip a possible leading "+-" (e.g. "+-100 nA")
        if s.startswith("+-") or s.startswith("±"):
            s = (s[2:] if s.startswith("+-") else s[1:]).strip()
        try:
            return float(s)
        except ValueError:
            pass
        # a cell that carries its own unit ("150 V", "3700 pF") — some sheets
        # have no unit column at all
        v, u = _num_with_unit(s)
        if v is not None:
            if u:
                inline_units.append(u)
            return v
        return nan

    mn = to_val(raw.get("min"))
    typ = to_val(raw.get("typ"))
    mx = to_val(raw.get("max"))

    # nothing meaningful captured
    if all(math.isnan(v) for v in (mn, typ, mx)):
        return None

    unit = (ex.unit or "").strip(",; ") or None
    if unit is None and inline_units:
        # only trust an inline unit when every cell that had one agreed;
        # a disagreement means the columns are misread, and guessing which
        # one is right would silently rescale the value
        if len(set(inline_units)) == 1:
            unit = inline_units[0]
    if unit and "(cid:" in unit:
        # pdfminer often emits "(cid:N)" for the Ω/μ glyphs in onsemi /
        # infineon resistance & capacitance cells. Map the common cases.
        import re as _re
        unit = _re.sub(r"\(cid:2\)", "Ω", unit)
        unit = _re.sub(r"\(cid:4\)", "μ", unit)

    cond_str = ex.cond
    cond_parsed = None
    if cond_str:
        # parse_cond_str lives in dslib.pdf.sheet which has heavy deps; only
        # import lazily on demand
        try:
            from dslib.pdf.sheet import parse_cond_str  # noqa
            cond_parsed = parse_cond_str(cond_str)
        except Exception:
            cond_parsed = None

    if (unit is None and ex.symbol in _UNIT_REQUIRED
            and not _plausible_as_milliohm(mn, typ, mx)):
        # Resistance is printed in either Ohm or mOhm and dslib canonicalises
        # to mOhm only when it can see which. Without a unit the value cannot
        # be placed on the scale, and emitting it anyway is not a neutral
        # guess: Field reads the bare number as mOhm, so an Ohm-denominated
        # sheet silently yields 0.00685 where it means 6.85. Rds_on drives
        # P_on = I^2 * Rds_on, the quantity the tool ranks on, so a wrong
        # value there is worse than a gap another method can fill.
        return None

    src = ["v2", f"pg{ex.page_num + 1}", f"y{round(ex.row.bbox.y2)}"]

    try:
        return Field(ex.symbol,
                     min=mn, typ=typ, max=mx,
                     unit=unit,
                     cond=cond_parsed,
                     source=src)
    except Exception as e:
        warnings.warn(f"v2: Field({ex.symbol}) failed: {e!r}")
        return None


@disk_cache(ttl='999d', file_dependencies=[0], salt=(v2_code_salt, 'v01'),
            hash_func_code=True)
def parse_datasheet(pdf_path: str,
                    mfr: Optional[str] = None,
                    mpn: Optional[str] = None,
                    max_pages: int = 0) -> DatasheetFields:
    """Parse a datasheet PDF and return a populated ``DatasheetFields``.

    A scanned PDF (no extractable text) returns an *empty* DatasheetFields —
    OCR is out of scope for v2.
    """
    fmfr, fmpn = _mfr_mpn_from_path(pdf_path)
    mfr = mfr or fmfr
    mpn = mpn or fmpn

    ds = DatasheetFields(mfr=mfr, mpn=mpn)
    if not os.path.exists(pdf_path):
        ds.errors.append("file not found")
        return ds

    try:
        pages = extract_pages_with_rows(pdf_path, max_pages=max_pages)
    except Exception as e:
        warnings.warn(f"v2: pdfminer failed on {pdf_path}: {e!r}")
        ds.errors.append(f"pdfminer: {e!r}")
        return ds

    if page_likely_needs_ocr(pages):
        warnings.warn(f"v2: {pdf_path} looks like a scanned PDF — skipping (needs OCR)")
        ds.errors.append("needs OCR")
        return ds

    extracted_fields: list = []
    for page in pages:
        if page.char_count < 30:
            continue
        headers = find_headers(page.rows)
        rows = parse_rows_for_page(mfr, page, headers)
        for ex in rows:
            f = _make_field(ex)
            if f is not None:
                extracted_fields.append(f)

    # Add the most complete instance of each symbol first. Field.fill skips a
    # nan->value update when the merged Field already has a higher-rank value
    # filled (the ">= lower" guard in dslib.field.Field.fill), so adding the
    # richer record first guarantees that any later summary-page row only
    # fills *additional* gaps instead of locking in the early nans.
    extracted_fields.sort(key=lambda f: -len(f))
    for f in extracted_fields:
        ds.add(f)

    return ds


__all__ = ["parse_datasheet"]
