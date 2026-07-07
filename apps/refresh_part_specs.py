"""
Refresh stored MosfetSpecs for parts with missing fields.

Iterates ``dslib.store.parts_db``, finds every ``Part`` whose ``MosfetSpecs``
is missing one of the fields the web backend renders (see ``WEB_FIELDS``),
re-runs ``compile_part_datasheet`` on its ``DiscoveredPart``, recomputes a
``MosfetSpecs`` via ``DatasheetFields.get_mosfet_specs()`` (the same path
used by ``compute_part_powerloss``), wraps it back into a ``Part`` and
writes the result back to ``parts_db``.

A field counts as *present* only when its evaluated value (often a
``@property`` that derives from other fields) is **finite and non-zero**.
This matches what ``web/backend/app.py:_clean`` and ``_similarity_score``
treat as a usable value — a stored ``0.0`` is just as useless to the UI as
a ``NaN``.

Usage::

    python3 refresh_part_specs.py                 # refresh all incomplete parts
    python3 refresh_part_specs.py --dry-run       # show what would be updated
    python3 refresh_part_specs.py --limit 50      # only process the first 50
    python3 refresh_part_specs.py --mfr infineon  # restrict by manufacturer
    python3 refresh_part_specs.py --no-cache      # bypass disk/parts caches
    python3 refresh_part_specs.py --no-ocr        # skip OCR fallback
    python3 refresh_part_specs.py -j 8            # run 8 parts in parallel
"""
from __future__ import annotations

import argparse
import copy
import math
import os
import traceback
from typing import Any, List, Optional, Set, Tuple, Union

from dslib import get_datasheets_path
from dslib.discovery import DiscoveredPart
from dslib.field import DatasheetFields
from dslib.store import Part, parts_db

# Symbols asked of ``parse_datasheet`` when a refresh is triggered. Picked
# to cover everything the web app reads off ``MosfetSpecs`` (whether by
# direct attribute or via a derived @property).
NEED_SYMBOLS: Set[Union[str, Tuple[str, ...]]] = {
    'tRise', 'tFall',                  # rise/fall times
    'Qg', 'Qgd',                       # gate charges
    ('Qgs', 'Qg_th', 'Qgs2'),          # any of these → derives Qgs2 → Qsw
    #'Qrr',                             # reverse-recovery charge
    'Vsd',                             # body-diode forward voltage
    'Vpl',                             # miller plateau voltage (→ V_pl)
}


# Attribute paths the web backend (``web/backend/app.py:_serialize``)
# evaluates against ``Part.specs`` / ``Part.discovered.specs``. The web app
# treats *any* of these returning NaN/inf/None as "missing", and the
# similarity ranker additionally drops candidates with zero on the required
# fields — so we must enforce finite-and-non-zero, not just "key exists".
#
# Each entry: (label, where, attr, valid_range).
#   ``where`` is 'specs' (MosfetSpecs) or 'basic' (DiscoveredPart.specs).
#   ``valid_range`` is (min, max) in the field's storage units — a value
#   outside this range is treated as missing, on the theory that an
#   implausibly large or tiny stored value is more likely a parse error than
#   a real spec.
WEB_FIELDS: Tuple[Tuple[str, str, str, Tuple[float, float]], ...] = (
    ('Vds_max',      'specs', 'Vds',         (10.0,    10000.0)),
    ('Rds_on_max',   'specs', 'Rds_on',      (1e-5,    10.0)),     # Ω
    ('Id',           'specs', 'Id',          (0.1,     2000.0)),   # A; has fallback (basic.ID_25)
    ('Qsw',          'specs', 'Qsw',         (1e-10,   1e-6)),     # C  (0.1 nC .. 1 µC)
    ('Qg',           'specs', 'Qg',          (1e-10,   1e-5)),     # C  (0.1 nC .. 10 µC)
    #('Qrr',          'specs', 'Qrr',         (1e-10,   1e-5)),    # C
    ('Vsd',          'specs', 'Vsd',         (0.3,     2.5)),      # V
    ('V_pl',         'specs', 'V_pl',        (2.0,     9.0)),      # V (matches _VPL_MIN/_VPL_MAX) # TODO for SiC Vpl can be higher! and for GaN probably smaller
    ('QgdQgs_ratio', 'specs', 'QgdQgsRatio', (0.05,    10.0)),     # dimensionless
    #('Vgs_th',       'basic', 'Vgs_th_max',  (0.5,     8.0)),     # V
)

WEB_FIELDS: Tuple[Tuple[str, str, str, Tuple[float, float]], ...] = (
    ('Rds_on_max', 'specs', 'Rds_on', (1e-5, 10.0)),  # Ω
    #('Vds_max',      'specs', 'Vds',         (10.0,    10000.0)),
    #('Qg', 'specs', 'Qg', (1e-10, 1e-5)),  # C  (0.1 nC .. 10 µC)
    ('V_pl',         'specs', 'V_pl',        (2.0,     9.0)),
    #('Qrr',          'specs', 'Qrr',         (1.5e-9,   1e-5)),    # C

) # todo temporarily disabled other fields

# Fields where the web allows a fallback from DiscoveredPart.specs when the
# primary MosfetSpecs value is missing.
ID_FALLBACK = ('basic', 'ID_25')


def _finite_nonzero(v: Any) -> bool:
    """Mirror ``web.backend.app._clean`` + the > 0 guard from the similarity
    ranker. Anything that ends up as ``None`` / NaN / inf / 0 in the UI is
    considered missing here."""
    if v is None:
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    if math.isnan(f) or math.isinf(f):
        return False
    return f != 0.0


def _in_range(v: Any, valid_range: Tuple[float, float]) -> bool:
    """True iff *v* is finite, non-zero, and inside [valid_range[0], valid_range[1]]."""
    if not _finite_nonzero(v):
        return False
    lo, hi = valid_range
    return lo <= float(v) <= hi


def _read_web_field(part: Part, where: str, attr: str) -> Any:
    """Read a web-rendered field off a Part, swallowing the same exceptions
    the web backend swallows (AttributeError, missing chain, etc.)."""
    try:
        if where == 'specs':
            obj = part.specs
        elif where == 'basic':
            disc = part.discovered
            obj = getattr(disc, 'specs', None) if disc is not None else None
        else:
            return None
        if obj is None:
            return None
        return getattr(obj, attr, None)
    except Exception:
        return None


# The ID_FALLBACK target shares the Id field's valid range.
_ID_RANGE: Tuple[float, float] = next(
    (rng for lbl, _, _, rng in WEB_FIELDS if lbl == 'Id'),
    (0.1, 2000.0),
)


def missing_web_fields(part: Part) -> List[str]:
    """Return the labels of WEB_FIELDS whose value isn't finite, non-zero, and
    within its valid range.

    Applies the Id→ID_25 fallback the web app does so we don't refresh a
    part for a missing ``Id`` that is rescued by ``discovered.specs.ID_25``.
    """
    miss: List[str] = []
    #if 'IXFH120N25T' in part.mpn:
    #    miss.append('Qrr')
    miss.append('V_pl')
    for label, where, attr, valid_range in WEB_FIELDS:
        v = _read_web_field(part, where, attr)
        if _in_range(v and abs(v), valid_range):
            continue
        if label == 'Id':
            fb = _read_web_field(part, *ID_FALLBACK)
            if _in_range(fb and abs(fb), _ID_RANGE):
                continue
        miss.append(label)
    return miss


# Sanity bounds for Vpl. ``MosfetSpecs.__init__`` enforces 2 ≤ Vpl ≤ 9; we
# use the same here so a noisy chart estimate can't corrupt a stored Part.
_VPL_MIN = 2.0
_VPL_MAX = 9.0


def _ds_path(part: Part) -> Optional[str]:
    """Locate the datasheet PDF for a Part, or None when unavailable."""
    disc = part.discovered
    if disc is None:
        return None
    try:
        path = os.path.join(get_datasheets_path() , disc.get_ds_path())
        path = path.replace('datasheets/datasheets/', 'datasheets/')
    except Exception:
        return None
    return path if path and os.path.isfile(path) else None


def _try_fill_vpl_from_chart(part: Part,
                             enable_ocr: bool = False) -> Optional[Part]:
    """Read V_pl off the gate-charge curve in the part's datasheet PDF.

    Returns a copy of ``part`` with ``specs._Vpl`` populated, or None if
    we couldn't find a plausible Miller-plateau value. The caller decides
    whether to keep the copy.
    """
    if part.specs is None:
        return None
    pdf_path = _ds_path(part)
    if pdf_path is None:
        return None

    # viz pulls in pymupdf — import lazily so callers that don't need it
    # still load the script fast.
    try:
        from dslib.viz import find_vpl
    except Exception as e:  # pragma: no cover
        print(f'  viz unavailable: {type(e).__name__}: {e}')
        return None

    try:
        vpl = find_vpl(pdf_path, enable_ocr=enable_ocr)
    except Exception as e:
        print(f'  viz error on {pdf_path}: {type(e).__name__}: {e}')
        return None

    if vpl is None:
        print(f'vpl not found in {pdf_path}', )
        from vpl_from_chart import vpl_from_pdf, _pick_best
        vpl = _pick_best(vpl_from_pdf(pdf_path))
        if vpl is None:
            return None
        vpl = vpl['vpl']
        print('vpl_from_chart found it', pdf_path, vpl)
    try:
        vpl_f = float(vpl)
    except (TypeError, ValueError):
        return None
    if not (_VPL_MIN <= vpl_f <= _VPL_MAX):
        # outside the physically plausible range — probably a misdetected
        # plateau (legend swatch, top of the chart, …). Skip silently.
        return None

    new = copy.copy(part)
    new.specs = copy.copy(part.specs)
    new.specs._Vpl = vpl_f
    return new


def _ds_to_specs(ds: DatasheetFields, prev_part: Part) -> Optional[Part]:
    """Compute MosfetSpecs from a parsed DatasheetFields and wrap as Part.

    Mirrors ``compute_part_powerloss`` without the loss math. Falls back to
    the existing ``prev_part.discovered`` if the parsed DS doesn't carry a
    ``part`` attribute (older pickles).
    """
    from main import get_fet_specs

    fet_specs = get_fet_specs(ds)
    if fet_specs is None:
        return None

    discovered = getattr(ds, 'part', None) or prev_part.discovered
    if not isinstance(discovered, DiscoveredPart):
        # Some legacy DatasheetFields use a bare MpnMfr stub; keep the
        # original DiscoveredPart from the stored Part.
        discovered = prev_part.discovered

    return Part(specs=fet_specs, discovered=discovered)


def refresh_part(part: Part,
                 need: Set[Union[str, Tuple[str, ...]]],
                 no_cache: bool,
                 no_ocr: bool,
                 no_download: bool) -> Optional[Part]:
    """Re-parse the part's datasheet and rebuild its Part with fresh specs."""
    from main import compile_part_datasheet

    if not part.discovered:
        print(f'  skip {part.mfr} {part.mpn}: no DiscoveredPart on record')
        return None

    try:
        ds: DatasheetFields = compile_part_datasheet(
            part.discovered, need, no_cache=no_cache,
            no_ocr=no_ocr, no_download=no_download)
    except Exception as e:
        print(f'  error compiling {part.mfr} {part.mpn}: {type(e).__name__}: {e}')
        print(traceback.format_exc())
        return None

    new_part = _ds_to_specs(ds, part)
    if new_part is None:
        # Couldn't build MosfetSpecs (likely required fields still missing
        # after re-parse). Keep the previous record intact.
        return None

    return new_part


def _filter_parts(parts: dict, mfr: Optional[str],
                  mpn: Optional[str]) -> List[Part]:
    parts_list: List[Part] = list(parts.values())
    if mfr:
        parts_list = [p for p in parts_list if p.mfr == mfr]
    if mpn:
        parts_list = [p for p in parts_list if p.mpn == mpn]
    return parts_list


def _process_one_part(part: Part,
                      miss: List[str],
                      no_cache: bool,
                      no_ocr: bool,
                      no_download: bool) -> Tuple[Optional[Part], List[str]]:
    """Process a single part and return (new_part_or_None, log_lines).

    This is the per-part body of the refresh loop, factored out so it can be
    dispatched to ``run_parallel`` without sharing main-process state.  All
    user-facing prints become *log lines* the caller is responsible for
    flushing in order; this avoids interleaved output from worker processes
    and keeps the function pure (picklable for the multiprocessing backend).
    """
    log: List[str] = []

    # Fast path: V_pl is the only missing web field — read it directly off
    # the gate-charge chart, which is much cheaper than a full re-parse.
    if miss == ['V_pl']:
        viz_part = _try_fill_vpl_from_chart(part, enable_ocr=not no_ocr)
        if viz_part is None:
            log.append('  · viz could not extract Vpl from chart')
            return None, log
        v = _read_web_field(viz_part, 'specs', 'V_pl')
        log.append(f'  + gained from chart: V_pl ≈ {float(v):.2f} V')
        return viz_part, log

    new_part = refresh_part(part, NEED_SYMBOLS,
                            no_cache=no_cache, no_ocr=no_ocr,
                            no_download=no_download)
    if new_part is None:
        return None, log

    # If the recompile still didn't fill V_pl, supplement with the chart
    # extractor — most datasheets don't tabulate V_pl, so this is the normal
    # path for it.
    if 'V_pl' in missing_web_fields(new_part):
        viz_part = _try_fill_vpl_from_chart(new_part, enable_ocr=not no_ocr)
        if viz_part is not None:
            v = _read_web_field(viz_part, 'specs', 'V_pl')
            log.append(f'  + V_pl from chart: ≈ {float(v):.2f} V')
            new_part = viz_part

    # Don't regress.  Every WEB_FIELDS entry that was finite-and-non-zero on
    # the OLD part must remain finite-and-non-zero on the new one.
    old_present = {lbl for lbl, _, _, _ in WEB_FIELDS
                   if lbl not in set(missing_web_fields(part))}
    new_present = {lbl for lbl, _, _, _ in WEB_FIELDS
                   if lbl not in set(missing_web_fields(new_part))}
    dropped = old_present - new_present
    if dropped:
        log.append(f'  · skip write: would drop {sorted(dropped)}')
        return None, log

    new_miss = missing_web_fields(new_part)
    gained = sorted(set(miss) - set(new_miss))
    if gained:
        tail = (f'  (still missing: {sorted(new_miss)})' if new_miss else '')
        log.append(f'  + gained: {gained}{tail}')
    else:
        log.append(f'  · no new fields recovered (still missing: {sorted(new_miss)})')
    return new_part, log


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dry-run', action='store_true',
                   help="don't write back to parts_db")
    p.add_argument('--limit', type=int, default=0,
                   help='process at most N parts (0 = all)')
    p.add_argument('--mfr', help='only parts with this manufacturer')
    p.add_argument('--mpn', help='only this exact MPN (debugging)')
    p.add_argument('--no-cache', action='store_true',
                   help='bypass disk_cache and parts_db when (re-)parsing')
    p.add_argument('--no-ocr', action='store_true',
                   help='disable OCR fallback for image-only PDFs')
    p.add_argument('--download', action='store_true',
                   help='allow downloading missing datasheets (off by default)')
    p.add_argument('-j', '--jobs', type=int, default=1,
                   help='number of parts to process in parallel '
                        '(1 = serial; >1 uses run_parallel from main.py)')
    args = p.parse_args()
    no_download = not args.download

    print('loading parts_db...')
    parts = parts_db.load()
    print(f'loaded {len(parts)} parts')

    candidates = _filter_parts(parts, args.mfr, args.mpn)
    print(f'after mfr/mpn filter: {len(candidates)} candidates')

    # parts with missing required fields (per web-app evaluation)
    todo: List[Tuple[Part, List[str]]] = []
    for part in candidates:
        miss = missing_web_fields(part)
        if miss:
            todo.append((part, miss))

    print(f'parts with missing fields: {len(todo)} / {len(candidates)}')
    if args.limit and len(todo) > args.limit:
        todo = todo[:args.limit]
        print(f'  --limit applied: processing first {len(todo)}')

    if not todo:
        print('nothing to do.')
        return

    if args.dry_run:
        for i, (part, miss) in enumerate(todo, 1):
            print(f'[{i}/{len(todo)}] {part.mfr} {part.mpn}  missing={sorted(miss)}')
        print()
        print('dry-run: not writing to parts_db')
        return

    updated: List[Part] = []
    if args.jobs > 1:
        # Parallel dispatch via main.run_parallel (multiprocessing backend).
        from dslib.util import run_parallel
        jobs = {
            (part.mfr, part.mpn): (_process_one_part, part, miss,
                                   args.no_cache, args.no_ocr, no_download)
            for part, miss in todo
        }
        # Header lines printed up-front so the user sees the work list before
        # the progress bar takes over.
        for i, (part, miss) in enumerate(todo, 1):
            print(f'[{i}/{len(todo)}] {part.mfr} {part.mpn}  missing={sorted(miss)}')
        results = run_parallel(jobs, args.jobs, 'multiprocessing', verbose=0)
        for (mfr, mpn), result in results.items():
            if result is None:
                continue
            new_part, log_lines = result
            if log_lines:
                print(f'{mfr} {mpn}:')
                for line in log_lines:
                    print(line)
            if new_part is not None:
                updated.append(new_part)
    else:
        for i, (part, miss) in enumerate(todo, 1):
            print(f'[{i}/{len(todo)}] {part.mfr} {part.mpn}  missing={sorted(miss)}')
            new_part, log_lines = _process_one_part(
                part, miss, args.no_cache, args.no_ocr, no_download)
            for line in log_lines:
                print(line)
            if new_part is not None:
                updated.append(new_part)

    print()
    print(f'{len(updated)} parts have fresh specs.')

    if updated:
        parts_db.add(updated, overwrite=True)
        print(f'wrote {len(updated)} parts back to parts_db')


if __name__ == '__main__':
    from wakepy import keep
    with keep.running():
        main()
