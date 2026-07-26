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
import re
import warnings
from typing import Optional

from dslib.cache import disk_cache
from dslib.field import DatasheetFields, Field
from dslib.v2.chars import extract_pages_with_rows, page_likely_needs_ocr
from dslib.v2.tables import (ExtractedRow, _num_with_unit, find_headers,
                             parse_rows_for_page)

_V2_DIR = os.path.dirname(os.path.abspath(__file__))
_DSLIB_DIR = os.path.dirname(_V2_DIR)
_V2_SOURCES = ('__init__.py', 'chars.py', 'tables.py')

# Code OUTSIDE dslib/v2 that helps derive a parsed field. Each is reached from
# parse_datasheet and each can change the numbers it returns, so each belongs
# in the key exactly as much as chars.py does:
#   pdf/expr.py        symbol regexes, any_unit, DIMENSIONS — which cells count
#                      as values, and which unit is accepted for a symbol
#   pdf/parse.py       detect_fields — which symbol a row is attributed to
#   pdf/sheet/__init__ parse_cond_str — the conditions a Field carries
#   field.py           get_value_with_unit and Field's unit canonicalisation —
#                      the stored magnitude; Ohm vs mOhm is decided there
_V2_DEP_SOURCES = (
    os.path.join(_DSLIB_DIR, 'pdf', 'expr.py'),
    os.path.join(_DSLIB_DIR, 'pdf', 'parse.py'),
    os.path.join(_DSLIB_DIR, 'pdf', 'sheet', '__init__.py'),
    os.path.join(_DSLIB_DIR, 'field.py'),
)


def v2_code_salt():
    """Cache salt covering the code that *derives* the result.

    ``hash_func_code=True`` only hashes ``parse_datasheet``'s own source, so
    without this an edit anywhere else would keep serving the old — plausible,
    silently wrong — cached value forever.

    The scope is deliberately the whole derivation and not just this package,
    because a stale-but-plausible number is the worst thing this cache can
    produce and it has already happened twice. ``__init__.py`` was missing from
    the list, so everything ``parse_datasheet`` delegates to here —
    ``_make_field``, the unit rules, the condition canonicalisation — was
    invisible to the key; editing the condition handling and re-running served
    the previous answer and looked exactly like a fix that had not worked. The
    external four are the same hole one level out: another agent editing
    ``pdf/parse.py`` changes which symbol a row becomes, and v2 would have gone
    on serving the old attribution.

    An unreadable dependency RAISES rather than being skipped. Dropping a file
    that cannot be read would silently narrow the key and reintroduce this bug,
    so it has to be louder than a cache miss, not quieter.

    Callable so decoration doesn't force ``expr``'s lazy regex tables
    (~1.7 s of regex.compile) at import time.
    """
    # Private, but same project. Memoized by (path, mtime, size), so once warm
    # this is a stat per file per call rather than a re-hash.
    from dslib.cache import _file_content_sig
    h = hashlib.sha256()
    for n in _V2_SOURCES:
        h.update(_file_content_sig(os.path.join(_V2_DIR, n)).encode())
    for p in _V2_DEP_SOURCES:
        h.update(_file_content_sig(p).encode())
    sig = h.hexdigest()[:16]
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
#
# The floor is PER SYMBOL, because "plausible" is a property of the quantity
# and not of the dimension. Rds_on and Rg are both resistances and their
# physical ranges do not overlap at the bottom: a gate resistance is a real
# resistor in series with the gate, 0.4-20 Ohm on real parts, so 1.3 "mOhm" is
# not a low value, it is an Ohm-denominated number that lost its unit.
# infineon/BSZ070N08LS5ATMA1 prints "Gate resistance RG - 1.3 2 -" with the
# Ohm living outside the row, and a single 0.5 floor believed it and emitted
# 1.3 against a true 1300 mOhm — the exact 1000x this rule exists to stop,
# reintroduced by tuning the threshold for the other symbol.
_MIN_PLAUSIBLE_MILLIOHM = {
    "Rds_on": 0.5,     # best trench parts bottom out near 0.5-1 mOhm
    "Rds_on_10v": 0.5,
    "Rg": 50.0,        # 0.05 Ohm, an order of magnitude below any real Rg
}


def _plausible_as_milliohm(symbol: str, *values: float) -> bool:
    """True if a unitless resistance can be believed as already-mOhm.

    An unknown symbol and an all-nan value both answer False — refuse. This is
    a trust gate, so "cannot tell" has to mean "do not emit", never "fine".
    Falling back to some other symbol's floor is the specific mistake that put
    a 1000x Rg through, so a symbol without a measured floor gets none.
    """
    floor = _MIN_PLAUSIBLE_MILLIOHM.get(symbol)
    if floor is None:
        return False
    seen = [v for v in values if not math.isnan(v)]
    return bool(seen) and min(seen) >= floor


# The condition names the consumers actually query by. dslib/field.py:458 asks
# for Rds_on with cond=dict(Vgs=...) and :502 for Qg the same way; the scorer at
# :572 iterates the REQUESTED keys and reads each out of the candidate with
# d.get(k, 0). So a candidate spelled "V GS" contributes 0 for Vgs, its error
# term blows up, and the correct row LOSES to whatever was merged first —
# condition-aware selection is silently inoperative rather than merely
# imprecise, which is why the spelling has to be normalised here and not left
# for the consumer to be liberal about.
_COND_ALIASES = {
    "vgs": "Vgs", "vds": "Vds", "vsd": "Vsd", "vg": "Vgs", "vd": "Vds",
    "id": "Id", "is": "Is", "ids": "Id", "if": "IF", "isd": "Isd",
    "tj": "Tj", "tc": "Tc", "ta": "Ta", "tcase": "Tc", "tamb": "Ta",
    "rg": "Rg", "vbr": "Vbr", "didt": "didt", "dvdt": "dvdt",
    "f": "f", "freq": "f",
}

# The canonical names themselves, for paths that must reject anything they
# cannot recognise rather than pass it through.
_CANONICAL_COND_NAMES = frozenset(_COND_ALIASES.values())


def _canonical_cond(cond: Optional[dict]) -> Optional[dict]:
    """Map condition keys onto the canonical names consumers select by.

    ``parse_cond_str`` only recognises an exact case-insensitive 'vgs'/'id'/
    'vds', so a subscript typeset as its own run — "V GS=10V" on
    infineon/IPW65R040CM8 — survives as the literal key "V GS". Separators are
    dropped before lookup so "V GS", "V_GS" and "VGS" all land on Vgs.

    An unrecognised key is kept verbatim rather than guessed at. A bare "V"
    could be Vgs or Vds and inventing one would hand the selector a confident
    wrong condition, which is worse than the inert unknown key it gets now.
    """
    if not cond:
        return cond
    out = {}
    for k, v in cond.items():
        if isinstance(k, str):
            flat = re.sub(r"[\s_.\-]+", "", k).lower()
            k = _COND_ALIASES.get(flat, k)
        # First spelling wins: a row repeating a condition under two spellings
        # is stating it once.
        out.setdefault(k, v)
    return out


# One "<symbol> = <number><unit>" statement. The value is the FIRST number
# after the "=", and nothing past its unit is part of it.
_COND_ITEM_RE = re.compile(
    r"([^,;=]{1,24})[=≈]\s*([+-]?\d[\d.]*\s*[a-zA-Zµμ°Ω%]{0,3})")

# Both micro codepoints appear in the wild — MICRO SIGN (U+00B5) and GREEK
# SMALL LETTER MU (U+03BC) — and the char class above accepts either so the
# unit is captured. SCALING them is parse_cond_str's job and it now handles
# both; v2 deliberately does NOT normalise first. A local workaround here
# would keep working if that shared fix were ever reverted, which would hide
# the regression from v2 while legacy extractors silently went back to reading
# "250 μA" as 250.


def _parse_cond_text(text: str, parse_cond_str) -> dict:
    """Parse conditions out of one cell's text, one statement at a time.

    ``parse_cond_str`` must never see more than a single ``sym = value``: its
    regex repeats the value group after the ``=``, so it consumes every
    remaining number in the string and the LAST one wins. Handed a phrase that
    also contains the row's numbers, ``"VGS=10V 7.8 9.5"`` returns
    ``{'Vgs': 9.5}`` — the right key with the wrong value. That is more
    dangerous than an unparseable key, because ``dslib/field.py:572`` scores a
    canonical key with a near value as a near MATCH, so a corrupted row can
    win the selection outright.
    """
    out = {}
    for m in _COND_ITEM_RE.finditer(text):
        val = m.group(2).strip()
        # The symbol is the tail of whatever precedes the "=", and how much of
        # that tail is narrowed down by trying the shortest reading first.
        # parse_cond_str's symbol pattern allows one embedded space, so given
        # "Voltage VGS=0V" it reads the symbol as "ge VGS"; given "V GS=10V"
        # the space is genuine and one token is not enough. Preferring the
        # 1-token reading when it names something a consumer queries resolves
        # both without a per-vendor rule.
        words = m.group(1).strip().split()
        for n in (1, 2, len(words)):
            if not n or n > len(words):
                continue
            got = _canonical_cond(
                parse_cond_str("%s=%s" % (" ".join(words[-n:]), val))) or {}
            if got:
                if any(k in _CANONICAL_COND_NAMES for k in got) or n == len(words):
                    for k, v in got.items():
                        out.setdefault(k, v)
                    break
    return out


def _cond_from_phrases(row, parse_cond_str) -> dict:
    """Recover conditions printed outside the Conditions column.

    ao sheets print "RDS(ON) Static Drain-Source On-Resistance TJ=125°C 7.8
    9.5": the Conditions column lands on the description, so the cell parses
    to nothing and two temperature variants of one parameter become
    indistinguishable.

    Parsed PHRASE BY PHRASE, never over the whole row. The condition regex
    permits a space inside a symbol — it has to, for subscripts typeset as
    their own run like "V GS" — so run across a full row it happily reads
    "On-Resis|tance TJ" as a symbol "ce TJ", yielding {"ce TJ": ...}. Phrases
    are the row's own cell boundaries, so the description and "TJ=125°C" are
    separated before matching.

    Only keys that canonicalise to a name a consumer actually queries are
    kept. Anything else is a mis-parse of prose, and this path has no column
    position to justify trusting it. Note that this filter guards the SYMBOL
    only — a wrong VALUE on a right symbol passes it untouched, which is what
    ``_parse_cond_text`` exists to prevent.
    """
    out = {}
    for ph in row.phrases():
        text = " ".join(w.text for w in ph).strip()
        if "=" not in text:
            continue
        for k, v in _parse_cond_text(text, parse_cond_str).items():
            if k in _CANONICAL_COND_NAMES:
                out.setdefault(k, v)
    return out


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

    cond_parsed = None
    if ex.cond or "=" in ex.row.text:
        try:
            # parse_cond_str lives in dslib.pdf.sheet which has heavy deps;
            # import lazily, and only for a row that could carry a condition
            # at all — v2 exists partly to keep that dependency off the hot
            # path.
            from dslib.pdf.sheet import parse_cond_str  # noqa
            if ex.cond:
                # The column's own text goes through the same one-statement-at-
                # a-time parser: the cond column routinely over-reaches into the
                # value columns, so it is exposed to the identical
                # last-number-wins corruption as the phrase path.
                cond_parsed = _parse_cond_text(ex.cond, parse_cond_str) or None
            if not cond_parsed:
                cond_parsed = _cond_from_phrases(ex.row, parse_cond_str) or None
        except Exception:
            cond_parsed = None

    if (unit is None and ex.symbol in _UNIT_REQUIRED
            and not _plausible_as_milliohm(ex.symbol, mn, typ, mx)):
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
