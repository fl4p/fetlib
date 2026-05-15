"""Footprint-family normalization for the web parametric search.

Manufacturers invent many names for the same physical package. This module
collapses them into a small set of canonical footprint families so users can
find pin-compatible alternatives for the same PCB land pattern. Small
dimensional tolerances are allowed (e.g. 3.0x3.0 and 3.3x3.3 DFN-8 land
patterns are interchangeable in practice).

Rules are applied top-to-bottom via `re.search`; first match wins. More
specific variants (lead-count differences that change the footprint, like
TO-247-4 vs TO-247) come first.
"""

from __future__ import annotations

import html
import re
from typing import Optional

# Normalize a few unicode characters to ASCII so patterns can stay simple.
_DASH_RE = re.compile(r'[‐-―−]')
_SPACE_RE = re.compile(r'[   ​]')


def _preclean(s: str) -> str:
    s = html.unescape(s)
    s = _DASH_RE.sub('-', s)
    s = s.replace('×', 'x')  # × → x
    s = _SPACE_RE.sub(' ', s)
    return s.strip()


# (regex, canonical name). Order matters.
_RULES: tuple[tuple[str, str], ...] = (
    # ─── Through-hole ─────────────────────────────────────────────────────────
    # 4-lead Kelvin-source TO-247 (extra pin → distinct footprint).
    (r'\bTO[\s\-]?247[\s\-]?4(?:l|[\s\-]?pin)?', 'TO-247-4'),
    (r'\bTO[\s\-]?247.{0,30}?\b4[\s\-]?pin', 'TO-247-4'),
    # TO-247 family (3-lead): TO-247, TO-247AC/AD, TO-247-3, Max247, PLUS-247.
    (r'\bTO[\s\-]?247|\bMax\s?247\b|\bPLUS[\s\-]?247\b', 'TO-247'),
    # TO-3P / TO-264 / TO-268 — bigger-than-TO-247 through-hole.
    (r'\bTO[\s\-]?3PM?|\bTO[\s\-]?(?:264|268)|\bD3PAK\b|\bISOTOP\b', 'TO-3P'),
    # TO-220 (incl. ITO-220 isolated, TO-220F / FullPAK / TO-220AB / TO-220C).
    (r'\bI?TO[\s\-]?220|\bFullPAK[\s\-]?220\b', 'TO-220'),
    # I2PAK / TO-262 (long-lead D2PAK).
    (r'\bI2PAK\b|\bTO[\s\-]?262', 'I2PAK'),
    # IPAK / TO-251 (long-lead DPAK).
    (r'\bIPAK\b|\bTO[\s\-]?251|\bI[\s\-]?PAK[\s\-]?SL\b', 'IPAK'),
    # SOT-227 brick.
    (r'\bSOT[\s\-]?227|\bminiBLOC\b', 'SOT-227'),

    # ─── D2PAK / TO-263 family ────────────────────────────────────────────────
    # 6+ lead D2PAK first (the multi-lead variants are a different footprint).
    (r'\bD2PAK[\s\-]?7P?(?:[\s\-]?pin)?\b|\bD2PAK[\s\-]?7pin\b'
     r'|\bTO[\s\-]?263[\s\-]?[6-8]L?\b|\bTO[\s\-]?263C[AB]\b'
     r'|\bTO[\s\-]?263LV[\s\-]?6L?\b|PG[\s\-]?TO263[\s\-]?7'
     r'|\bD2PAK\s?\(TO[\s\-]?263[\s\-]?7L?\)', 'D2PAK-7'),
    # 3-lead D2PAK / TO-263 / TO-263AA / TO-263AB / D-DPAK.
    (r'\bD2PAK\b|\bTO[\s\-]?263|\bD[\s\-]?DPAK\b', 'D2PAK'),

    # ─── DPAK / TO-252 family ─────────────────────────────────────────────────
    # 4-lead Kelvin DPAK first.
    (r'\bDPAK[\s\-]?4\b|\bTO[\s\-]?252[\s\-]?4L?\b', 'DPAK-4'),
    # DPAK / TO-252 / DPAK+ / H2PAK-2 / SC-63.
    (r'\bDPAK\+?\b|\bTO[\s\-]?252|\bH2PAK[\s\-]?2\b|\bSC[\s\-]?63\b', 'DPAK'),
    # H2PAK-6 (Infineon 6-lead DPAK).
    (r'\bH2PAK[\s\-]?6\b', 'H2PAK-6'),

    # ─── Q-DPAK ───────────────────────────────────────────────────────────────
    (r'\bQ[\s\-]?DPAK\b', 'Q-DPAK'),

    # ─── TOLL / TOLT / TOLG (Infineon 10x11 mm 8-lead) ────────────────────────
    (r'\bTOLT\b', 'TOLT'),
    (r'\bm?TOLG\b|\b[LS][\s\-]?TOGL\b', 'TOLG'),
    (r'\b(?:s|Thin[\s\-]?)?TOLL[A_C]?|\bTOLL[\s\-]?\d*L?', 'TOLL'),

    # ─── 8×8 SO-8 family ──────────────────────────────────────────────────────
    (r'\bLFPAK88\b|\bSOT[\s\-]?1235\b|\bThin[\s\-]?PAK\s*8\s*x\s*8'
     r'|PowerPAK[\s®]*\s*8\s*x\s*8(?:L?|S?W?)?'
     r'|PowerFLAT\s*8\s*x\s*8|\bDFN\s*8\s*x\s*8\b|\bPOWERLEADED\s*8\s*x\s*8\b', 'LFPAK88'),
    # CCPAK (12×12, side-cooled bottom-terminated).
    (r'\bCCPAK[\s\-]?1212\b|\bSOT[\s\-]?800[05]', 'CCPAK'),
    # IR DirectFET.
    (r'\bDirectFET\b', 'DirectFET'),

    # ─── 5×6 dual-die SO-8 (two FETs in one 5x6 case → different pinout) ──────
    (r'\bDual\s?SSO8(?:\s?HB)?\b|\bLFPAK56D\b|\bP?DFN56U?\s?Dual\b'
     r'|\bDSOP\s?Advance(?:\(.+\))?\b|PowerFLAT\s*5\s*x\s*6\s*(?:Dual|double)', 'SO-8 Dual'),

    # ─── 5×6 single-die SO-8 family (the big bucket) ──────────────────────────
    (r'\bLFPAK56E?\b|\bLFPAK5x6[\s\-]?4L?\b|\bLFPAK[\s\-]?4\b', 'SO-8 (5x6)'),
    (r'\bSuper\s?SO8\b|\bSingle\s?SSO8\b|\bSSO10T\b|\bSSO4G\b'
     r'|\bUltraSO[\s\-]?8L?\b', 'SO-8 (5x6)'),
    (r'PowerPAK[\s®]*\s*SO[\s\-]?8', 'SO-8 (5x6)'),
    (r'\bSOP\s?Advance(?:\(.+\))?\b|\bTSON\s?Advance(?:\(.+\))?\b', 'SO-8 (5x6)'),
    (r'PowerFLAT\s*5\s*x\s*6', 'SO-8 (5x6)'),
    (r'\bPQFN\s*5\s*x\s*6\b', 'SO-8 (5x6)'),
    (r'\b\d+[\s\-]?Power(?:TDFN|VDFN|SFN|SMD|WDFN|LDFN)\b', 'SO-8 (5x6)'),
    (r'\bS3O8\b|\bDFNW5\b|\bSC[\s\-]?100\b|\bSOT[\s\-]?669'
     r'|\bSOT[\s\-]?1023|\bSOT[\s\-]?1205|\bSOT[\s\-]?8038'
     r'|\bMLPAK56\b|\bWSON\b|\bVSONP\b'
     r'|\bPG[\s\-]?HSOF[\s\-]?8\b', 'SO-8 (5x6)'),
    # DFN 5x6 numeric forms (DFN-8L(5x6), DFN5x6-8L, DFN-8(5.7x5.1), 5.8x4.9, …).
    (r'\b(?:P|W|F)?DFN[Ww]?[Bb]?[\s\-]?(?:8L?[\s\-]?)?\(?\s*[456](?:\.\d+)?\s*x\s*[456](?:\.\d+)?\s*\)?', 'SO-8 (5x6)'),
    (r'\b(?:P|W|F)?DFN5X6[\s\-]?8L?|\b(?:P|W|F)?DFN56U?_?[A]?\b|\bP?DFN5060', 'SO-8 (5x6)'),

    # ─── 3×3 / 3.3×3.3 DFN single-die family ──────────────────────────────────
    (r'\bLFPAK33\b|\bLFPAK8\b|\bMLPAK33\b|\bSOT[\s\-]?1210|\bSOT[\s\-]?8002', 'DFN 3x3'),
    (r'PowerPAK[\s®]*\s*1212(?:[\s\-]?(?:8S?|F))?'
     r'|PowerFLAT\s*3\.?3\s*x\s*3\.?3', 'DFN 3x3'),
    (r'\bPQFN\s*3(?:\.3)?\s*x\s*3(?:\.3)?\b', 'DFN 3x3'),
    (r'\b(?:P|W|F)?DFN[Ww]?[Bb]?[\s\-]?(?:8L?[\s\-]?B?[\s\-]?)?\(?\s*3(?:\.\d+)?\s*x\s*3(?:\.\d+)?\s*\)?(?:[\s\-]?8L?)?', 'DFN 3x3'),
    (r'\b(?:P|W|F)?DFN(?:33{2,3}|3030)(?:[\s\-]?8)?\b|\bPDFN33\b|\bP?DFN8L?\(0303\)', 'DFN 3x3'),

    # ─── SO-8 / classic SOIC-8 (~5×4 mm) ──────────────────────────────────────
    (r'\bSO[\s\-]?8(?:FL)?\b|\bSOP[\s\-]?8L?\b|\bSOP8L?\b|\bSOIC[\s\-]?8\b|\b8[\s\-]?SOIC\b', 'SO-8'),

    # ─── DFN 2×2 6-lead (small but interchangeable) ───────────────────────────
    (r'\b(?:P|W|F)?DFN[\s\-]?(?:6L?[\s\-]?)?\(?\s*2(?:\.\d+)?\s*x\s*2(?:\.\d+)?\s*\)?(?:[\s\-]?6L?)?', 'DFN 2x2'),
    (r'\bP?DFN2x2[\s\-]?6L?|PowerFLAT\s*2\s*x\s*2', 'DFN 2x2'),

    # ─── Small-signal SOT family ──────────────────────────────────────────────
    (r'\bSOT[\s\-]?23[\s\-]?6L?', 'SOT-23-6'),
    (r'\bT?SOT[\s\-]?23(?:[\s\-]?3L?|F)?', 'SOT-23'),
    (r'\bSOT[\s\-]?223', 'SOT-223'),
    (r'\bSOT[\s\-]?89', 'SOT-89'),
    (r'\bTSOP[\s\-]?6L?F?', 'TSOP-6'),
    (r'\bSOT[\s\-]?323|PowerPAK\s*SC[\s\-]?70', 'SOT-323'),
    (r'\bSOT[\s\-]?(?:343|353|363|763)', 'SOT-363'),
    (r'\bSOT[\s\-]?523', 'SOT-523'),
    (r'\bSOT[\s\-]?(?:553|563|923)', 'SOT-553'),
    (r'\bSOT[\s\-]?(?:416|723|883)', 'SOT-tiny'),
    (r'\bSOT[\s\-]?(?:1118|1220)', 'UDFN-6'),
)

_COMPILED: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), name) for p, name in _RULES
)

_EMPTY_TOKENS = {'', '-', '--', 'nan', 'die form', 'bare die', 'die'}


def normalize(raw: Optional[str]) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    s = _preclean(raw)
    if s.lower() in _EMPTY_TOKENS:
        return None
    for pat, name in _COMPILED:
        if pat.search(s):
            return name
    return s  # leave unmatched as-is so user still sees the raw label


if __name__ == '__main__':
    # Histogram dump for tuning the rules.
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from collections import Counter
    from dslib.store import parts_db

    known = {name for _, name in _RULES}
    raw = parts_db.load()
    bucket = Counter()
    unmatched = Counter()
    for p in raw.values():
        if p is None or p.discovered is None:
            continue
        pkg = p.discovered.package
        n = normalize(pkg)
        if n is None:
            continue
        bucket[n] += 1
        if n not in known:
            unmatched[pkg] += 1

    print('=== Canonical buckets ===')
    for k, c in bucket.most_common():
        print(f'{c:6d}  {k}')
    print()
    print(f'=== Unmatched ({sum(unmatched.values())} parts, {len(unmatched)} strings) ===')
    for k, c in unmatched.most_common(60):
        print(f'{c:6d}  {k}')
