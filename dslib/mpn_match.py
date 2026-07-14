"""Shared orderable-suffix MPN matcher for the curated attach-at-load maps.

The curated registries (coss_curves, qrr_conditions, qrr_points, gate_specs,
bv_specs) key on the BASE MPN, while the parts pickle often carries the
orderable part number (IPP022N12NM6 -> IPP022N12NM6AKSA1: tape/reel/packing
code appended). Each module used to do its own `mpn.startswith(base)`
fallback — which also matches FAMILY VARIANTS: IPP040N06NF2S (a different
die) startswith IPP040N06N, and on 2026-07-14 that served one part's
breakdown line to its neighbor. This helper is the single place that decides
what counts as an orderable suffix; migrate every curated map to it rather
than duplicating the regex.

An orderable code is letters followed by one final digit (AKSA1, AKMA1,
ATMA1, XTSA1, ...). Family/technology suffixes (F2S, L, -GE3) do not fit
that shape, so they are refused — the correct failure direction: an
uncurated part must get None, never a neighbor's curated data.

One vendor-specific allowance: Infineon source-down (IQD/IQE/ISC) parts ship
layout variants CG / SC / CGSC (gate-pad / contact layout, own datasheet
numbers) that ARE the same die — verified 2026-07-14 by comparing the Qrr
spec rows of IQD016N08NM5 vs its CG and SC variants (identical 71/142 and
331/662 nC at identical conditions). A purely orderable-code rule dropped 38
correct qrr_points attachments for them (caught by a before/after
load_parts diff). The allowance is GATED on those base-MPN families — the
evidence covers nothing else, and an unscoped rule would let any part ending
in SC/CG inherit a neighbor's curated data (fetmodel review blocker).
"""

import re

_ORDERABLE_CODE_RE = re.compile(r"[A-Z]{2,5}\d")
_LAYOUT_CODE_RE = re.compile(r"(?:CG|SC|CGSC)(?:[A-Z]{2,5}\d)?")
_LAYOUT_CODE_FAMILIES = ("IQD", "IQE", "ISC")  # Infineon source-down only


def is_orderable_variant(base_mpn, mpn):
    """True if `mpn` is `base_mpn` plus an orderable (packing) code — nothing else.

    Exact equality is NOT handled here (do the exact-key lookup first);
    empty/None inputs are False.
    """
    base_mpn = str(base_mpn or "")
    mpn = str(mpn or "")
    if not base_mpn or not mpn.startswith(base_mpn):
        return False
    remainder = mpn[len(base_mpn):]
    if not remainder:
        return False
    if _ORDERABLE_CODE_RE.fullmatch(remainder):
        return True
    return (base_mpn.upper().startswith(_LAYOUT_CODE_FAMILIES)
            and bool(_LAYOUT_CODE_RE.fullmatch(remainder)))


def lookup_base_variant(registry, mfr, mpn):
    """Resolve (mfr, mpn) against a {(mfr, base_mpn): value} curated registry.

    Tries the exact key (as given, then lowercased mfr), then the orderable-
    suffix fallback via is_orderable_variant. Returns the registry VALUE
    uncopied (callers copy as appropriate) or None.
    """
    if not mfr or not mpn:
        return None
    hit = registry.get((mfr, mpn)) or registry.get((str(mfr).lower(), mpn))
    if hit is not None:
        return hit
    mfr_l = str(mfr).lower()
    candidates = [(base, v) for (m, base), v in registry.items()
                  if str(m).lower() == mfr_l and is_orderable_variant(base, mpn)]
    if not candidates:
        return None
    # longest base wins, so a registry carrying both a part and a longer
    # sibling never resolves the sibling's orderable code to the short base
    return max(candidates, key=lambda kv: len(kv[0]))[1]
