"""Normalization of :class:`dslib.field.Field` ``cond`` dicts.

The ``cond`` attribute of a Field comes in several shapes depending on which
parser produced it:

* ``None`` / ``''`` / empty dict — no conditions known.
* Dict with string keys, possibly non-canonical (``'V DS'``, ``'VDD'``,
  ``'VV GS'``, ``'IF'``, ``'didt'``, ``'F/dt'`` ...) and string-or-float values.
* Dict with integer keys (raw table cells), where the condition is embedded in
  one of the string values, e.g.
  ``{0: 'Output charge1)', 1: 'Qoss', ..., 6: 'VDS=75 V, VGS=0 V'}``.
* List of cell strings.

:func:`normalize_conditions` collapses all of these into a flat
``{canonical_symbol: float_value}`` dict.
"""
import math
import re


# Maps raw cond keys to canonical symbols.
# Keys here are pre-normalized: whitespace stripped, lowercased, leading-V dedup, common OCR
# l<->I confusion folded ("dlf/dt" -> "dif/dt"). See _canon_cond_key().
_COND_KEY_ALIASES = {
    # drain-source / bus / body-diode reverse voltage
    'vds': 'Vds', 'vdd': 'Vds', 'vr': 'Vds', 'vcc': 'Vds', 'vbus': 'Vds', 'vdr': 'Vds',
    # gate-source voltage
    'vgs': 'Vgs', 'vge': 'Vgs',
    # gate-driver supply / generator voltage
    'vgen': 'Vgen',
    # body-diode forward / source-drain current
    'if': 'I', 'is': 'I', 'isd': 'I', 'idr': 'I', 'i_f': 'I', 'i': 'I', 'geif': 'I',
    # drain current
    'id': 'Id', 'ids': 'Id', 'aid': 'Id', 'ic': 'Id',
    # diode current slew rate during reverse recovery
    'di/dt': 'di/dt', 'didt': 'di/dt', 'dif/dt': 'di/dt', 'dis/dt': 'di/dt',
    'didr/dt': 'di/dt', 'disd/dt': 'di/dt', 'dt': 'di/dt', 'd/dt': 'di/dt',
    'f/dt': 'di/dt',  # OCR/regex artifact of diF/dt
    # voltage slew rate
    'dv/dt': 'dv/dt',
    # temperatures
    'tj': 'Tj', 'tvj': 'Tj', 'thj': 'Tj',
    'tc': 'Tc', 'ta': 'Ta', 'tmb': 'Tmb',
    # gate resistance
    'rg': 'Rg', 'rgs': 'Rg',
    'rgon': 'Rg_on', 'rg_on': 'Rg_on',
    'rgoff': 'Rg_off', 'rg_off': 'Rg_off',
    'rgext': 'Rg_ext', 'rg_ext': 'Rg_ext', 'rg(ext)': 'Rg_ext',
    'rl': 'RL', 'rgen': 'Rgen',
    # other
    'f': 'f', 'frequency': 'f',
    'tdead': 'tdead',
    'ig': 'Ig',
    'ls': 'Ls',
    # common OCR misreads (kept narrow to avoid false positives)
    'vpp': 'Vds',   # OCR of 'VDD' on some Infineon PDFs ("V pp = 50 V")
    'ves': 'Vgs',   # OCR of 'VGS' on the same family
    'dr/dt': 'di/dt',  # truncation artifact of 'dIDR/dt' when 'dI' is split into a prior cell
}

# Matches "Key = Value [Unit]" assignments inside concatenated cell strings, e.g.
#   "VDS=75 V, VGS=0 V"        -> [("VDS", "75", "V"), ("VGS", "0", "V")]
#   "diF/dt = 100 A/μs"        -> [("diF/dt", "100", "A/μs")]
#   "Tj=150 °C"                -> [("Tj", "150", "°C")]
_COND_ASSIGN_RE = re.compile(
    r'(?P<key>[A-Za-z][A-Za-z _/()]{0,12}?)'
    r'\s*=\s*'
    r'(?P<val>[-+]?[0-9]+(?:[.,][0-9]+)?(?:[eE][-+]?[0-9]+)?)'
    r'\s*'
    r'(?P<unit>(?:A/[A-Za-zμ]+|[A-Za-zμΩ°%]+))?'
)


def _canon_cond_key(k):
    """Normalize a raw cond key to its lowercase, whitespace-free, OCR-folded form."""
    if not isinstance(k, str):
        return None
    s = re.sub(r'\s+', '', k).lower()
    # OCR doubles up the leading 'V' on some PDFs: "VV GS" -> "VGS"
    if s.startswith('vv'):
        s = s[1:]
    # OCR sometimes reads capital 'I' as lowercase 'l': "dlF/dt" -> "dif/dt"
    s = s.replace('l', 'i') if s.startswith('d') and s.endswith('/dt') else s
    return s


def _coerce_cond_value(v):
    """Coerce a cond value to float; return None if not a number."""
    from dslib.field import parse_field_value
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if not (isinstance(v, float) and math.isnan(v)) else None
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in {'none', '-', '~', 'n/a', 'na'}:
            return None
        # strip trailing unit, e.g. "75 V" / "10A" / "0V" / "100 A/μs"
        m = re.match(r'^[-+]?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?', s)
        f = parse_field_value(m.group(0) if m else s, no_raise=True)
        return None if math.isnan(f) else f
    return None


def _resolve_cond_key(raw_key):
    """Resolve a raw key (possibly preceded by noise) to a canonical symbol.

    Tries the full key first, then progressively shorter whitespace-suffixes — this lets
    'Qrr dIF/dt' resolve to 'di/dt' without losing legitimate 2-token keys like 'V DS'.
    """
    if not raw_key:
        return None
    tokens = raw_key.strip().split()
    for i in range(len(tokens)):
        cand = ' '.join(tokens[i:])
        canon = _canon_cond_key(cand)
        sym = _COND_KEY_ALIASES.get(canon) if canon else None
        if sym is not None:
            return sym
    return None


def _parse_cond_string(s):
    """Extract {key: value} pairs from a free-text condition string like 'VDS=75 V, VGS=0 V'."""
    out = {}
    if not s or not isinstance(s, str):
        return out
    for m in _COND_ASSIGN_RE.finditer(s):
        sym = _resolve_cond_key(m.group('key'))
        if not sym:
            continue
        val = _coerce_cond_value(m.group('val'))
        if val is None:
            continue
        # First occurrence wins (datasheet usually states the test condition once).
        out.setdefault(sym, val)
    return out


def normalize_conditions(cond, symbol=None):
    """Normalize the ``cond`` attribute of a :class:`dslib.field.Field`.

    Returns a flat ``{canonical_symbol: float_value}`` dict, e.g.
    ``{'Vds': 75.0, 'Vgs': 0.0}`` for Qoss or ``{'I': 25.0, 'di/dt': 100.0,
    'Vds': 50.0}`` for Qrr.  Unknown / unparseable keys are dropped.
    """
    if not cond:
        return {}

    # str / list: flatten to a single string and run the assignment regex over it.
    if isinstance(cond, str):
        return _parse_cond_string(cond)
    if isinstance(cond, (list, tuple)):
        return _parse_cond_string(' '.join(str(v) for v in cond if v is not None))

    if not isinstance(cond, dict):
        return {}

    out = {}
    leftover_text = []

    for k, v in cond.items():
        if isinstance(k, str):
            canon = _canon_cond_key(k)
            sym = _COND_KEY_ALIASES.get(canon) if canon else None
            if sym is not None:
                val = _coerce_cond_value(v)
                if val is not None:
                    out.setdefault(sym, val)
                continue
            # Unmapped string key — fall through to text parsing of the value too.
            if isinstance(v, str) and '=' in v:
                leftover_text.append(v)
        else:
            # numeric (integer) key — its value is a raw cell; collect for text parsing.
            if isinstance(v, str):
                leftover_text.append(v)

    if leftover_text:
        parsed = _parse_cond_string(' , '.join(leftover_text))
        for sym, val in parsed.items():
            out.setdefault(sym, val)

    return out
