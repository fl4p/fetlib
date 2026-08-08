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

A packing code is REVIEWED, never guessed (_is_packing_code): Infineon's
documented fixed-width block, or an entry of the cross-vendor
PACKAGING_SUFFIXES list that DigiKey matching and discovery consolidation
already share. Anything else is refused — the correct failure direction: an
uncurated part must get None, never a neighbor's curated data.

This used to be a loose `[A-Z]{2,5}\\d` shape test, which cannot tell a
packing code from a die/package letter FOLLOWED by one, and it was serving
curated data across genuinely different parts (2026-08-08). See the comment
on _INFINEON_PACKING_RE for the corpus census that settles the question, and
PackingCodeIsDocumentedNotGuessed in unit/test_mpn_match.py for the four live
mis-attachments it fixed.

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

# Infineon's DOCUMENTED packing block, and the ONLY shape accepted as a bare
# (separator-less, vendor-specific) packing code. Fixed width 5: [A]mmo-pack/tube,
# [X] tape&reel or [F], a package/pack-size letter, S or M, then A + a pack-size
# digit. Mirrors _INFINEON_PACKING in dslib/prices, which owns the same rule for
# price joins.
#
# It REPLACED a loose `[A-Z]{2,5}\d` (2026-08-08). That shape cannot tell a packing
# code from a die/package letter followed by one, and the corpus proves the
# difference is real, not theoretical: censusing every Infineon MPN whose stem is
# ALSO a corpus part gives 661 width-5 blocks, all 14 of them documented codes, and
# the only width-6 "codes" (AXTMA1, TATMA1, GATMA1, AFKSA1) are this same block with
# a letter stolen off the stem — IAUTN15S6N025 is TOLL, IAUTN15S6N025G is TOLG and
# IAUTN15S6N025T is TOLT, three packages with three datasheets. The loose rule
# served the TOLL part's curated qrr_layout row (a LAYOUT-dependent quantity) to the
# other two packages.
_INFINEON_PACKING_RE = re.compile(r"[AXF][KTU][SM]A\d", re.I)
_PACKING_BLOCK_WIDTH = 5  # the block is fixed-width; keep in sync with the regex

_LAYOUT_CODE_PREFIX_RE = re.compile(r"CGSC|CG|SC")  # longest alternative first
_LAYOUT_CODE_FAMILIES = ("IQD", "IQE", "ISC")  # Infineon source-down only


def _is_packing_code(remainder):
    """True if `remainder` is a code that only changes how the SAME die is packed.

    Two sources, both reviewed, neither a general pattern:

    * the Infineon packing block above;
    * PACKAGING_SUFFIXES (dslib.prices) — the cross-vendor list the DigiKey match
      tiers and discovery's consolidation already share (t1g, pbf, -ge3, ,118 ...).
      Every entry is a suffix somebody looked at, which is the point: a generic
      letter/digit continuation is a DIFFERENT part (IRFB4110 vs IRFB4110G).

    Anything else is refused, including well-formed-LOOKING codes. That is the
    correct failure direction — an uncurated part must get None, never a neighbor's
    curated data.
    """
    from dslib.prices import PACKAGING_SUFFIXES  # local: avoids a dslib.store cycle
    if not remainder:
        return False
    return (bool(_INFINEON_PACKING_RE.fullmatch(remainder))
            or remainder.lower() in PACKAGING_SUFFIXES)


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
    if _is_packing_code(remainder):
        return True
    if not base_mpn.upper().startswith(_LAYOUT_CODE_FAMILIES):
        return False
    # layout variant, optionally itself packed: CG / SC / CGSC / CGSCATMA1
    m = _LAYOUT_CODE_PREFIX_RE.match(remainder)
    if not m:
        return False
    tail = remainder[m.end():]
    return not tail or _is_packing_code(tail)


_MIN_SHARED_STEM = 6  # same floor _INFINEON_PACKING uses for the die part of an OPN


def are_packing_siblings(a, b):
    """True if `a` and `b` are the same die under two different PACKING codes.

    IPP039N10N5AKSA1 <-> IPP039N10N5XKSA1, and either of those <-> the bare
    IPP039N10N5. Equal MPNs are False (do the exact lookup first).

    Two cases, because the safe rule differs:

    * ONE SIDE IS THE BASE (b == a + code). _is_packing_code on the single
      remainder. What is NOT applied is the CG/SC LAYOUT allowance of
      is_orderable_variant: layout variants have their own datasheets and are
      curated apart (COSS_CURVES holds three distinct curves across
      IQD020N10NM5's six spellings), so they must not collapse into one family.

    * NEITHER SIDE IS A BASE (AKSA1 vs XKSA1). Here the base has to be inferred,
      and inferring it is where this goes wrong if done loosely. Two traps:

      - Splitting on the two MPNs' COMMON PREFIX cuts inside the code whenever
        the codes share a leading character: AKSA1 vs ATMA1 both start with 'A',
        leaving 'KSA1'/'TMA1'. So the split is at the DOCUMENTED block length,
        and the stems in front of it must be equal.
      - A loose `[A-Z]{2,5}\\d` on both tails at once reads a die-distinguishing
        LETTER as a code: ISC007N06LM6 vs ISC007N06NM6 leaves 'LM6' vs 'NM6',
        well-formed and the same length, structurally identical to the real
        AKSA1 vs XKSA1 — no generic rule separates them. Hence the fixed-width
        documented block. (Same reason IPB017N10N5ATMA1 vs IPB017N10N5LATMA1, an
        L-series die, is refused.)

    Only the Infineon block works for the no-base case: the separator-led
    PACKAGING_SUFFIXES entries are not fixed-width, so there is nothing to split at.
    """
    a, b = str(a or ""), str(b or "")
    if not a or not b or a == b:
        return False
    for base, mpn in ((a, b), (b, a)):
        if mpn.startswith(base):
            return len(base) >= _MIN_SHARED_STEM and _is_packing_code(mpn[len(base):])
    w = _PACKING_BLOCK_WIDTH
    return (len(a) == len(b) and len(a) - w >= _MIN_SHARED_STEM
            and a[:-w] == b[:-w]
            and bool(_INFINEON_PACKING_RE.fullmatch(a[-w:]))
            and bool(_INFINEON_PACKING_RE.fullmatch(b[-w:])))


def lookup_base_variant(registry, mfr, mpn):
    """Resolve (mfr, mpn) against a {(mfr, base_mpn): value} curated registry.

    Tries the exact key (as given, then lowercased mfr), then the orderable-
    suffix fallback via is_orderable_variant, in BOTH directions. Returns the
    registry VALUE uncopied (callers copy as appropriate) or None.
    """
    if not mfr or not mpn:
        return None
    hit = registry.get((mfr, mpn)) or registry.get((str(mfr).lower(), mpn))
    if hit is not None:
        return hit
    mfr_l = str(mfr).lower()
    candidates = [(base, v) for (m, base), v in registry.items()
                  if str(m).lower() == mfr_l and is_orderable_variant(base, mpn)]
    if candidates:
        # longest base wins, so a registry carrying both a part and a longer
        # sibling never resolves the sibling's orderable code to the short base
        return max(candidates, key=lambda kv: len(kv[0]))[1]

    # Packing-sibling direction: the registry keys one packing code and the query
    # is another spelling of the SAME die -- a curve landed as IPP039N10N5AKSA1
    # while discovery ranked IPP039N10N5 or ...XKSA1. Without this, which of
    # three interchangeable spellings the ranking happened to pick decided
    # whether the part got its digitized curve or the unverified scalar fallback.
    #
    # Runs last, so an exact key and the base direction still win. Layout
    # variants stay apart: IQD020N10NM5 resolves to ...ATMA1 and IQD020N10NM5CG
    # to ...CGATMA1, each to its own curve, not both to all six spellings.
    siblings = sorted((key, v) for (m, key), v in registry.items()
                      if str(m).lower() == mfr_l and are_packing_siblings(mpn, key))
    if not siblings:
        return None
    if len(siblings) > 1:
        # packing siblings must carry identical data; if a future entry curates
        # them differently, say so rather than silently serving the first
        print('mpn_match: %s %s matches %d curated packing siblings (%s), using %s'
              % (mfr, mpn, len(siblings), ', '.join(k for k, _ in siblings), siblings[0][0]))
    return siblings[0][1]
