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

import math
import os
import warnings
from typing import Optional

from dslib.cache import disk_cache
from dslib.field import DatasheetFields, Field
from dslib.v2.chars import extract_pages_with_rows, page_likely_needs_ocr
from dslib.v2.tables import (ExtractedRow, find_headers, parse_rows_for_page)


def _mfr_mpn_from_path(pdf_path: str):
    parts = pdf_path.replace("\\", "/").split("/")
    mpn = os.path.basename(parts[-1]).rsplit(".", 1)[0]
    mfr = parts[-2] if len(parts) >= 2 else ""
    return mfr, mpn


def _make_field(ex: ExtractedRow) -> Optional[Field]:
    nan = math.nan
    raw = ex.values

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
            s = s[2:] if s.startswith("+-") else s[1:]
        try:
            return float(s)
        except ValueError:
            return nan

    mn = to_val(raw.get("min"))
    typ = to_val(raw.get("typ"))
    mx = to_val(raw.get("max"))

    # nothing meaningful captured
    if all(math.isnan(v) for v in (mn, typ, mx)):
        return None

    unit = (ex.unit or "").strip(",; ") or None
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


@disk_cache(ttl='999d', file_dependencies=[0], hash_func_code=True)
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
