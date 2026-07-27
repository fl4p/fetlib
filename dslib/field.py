import datetime
import math
import re
import time
import warnings
from copy import copy
from typing import List, Iterable, Dict, Literal, Tuple, Union, cast, Optional

from dslib import round_to_n_dec
from dslib.conditions import normalize_conditions
from dslib.pdf.expr import any_unit
from dslib.pdf.pdf2txt import normalize_text, whitespaces_to_space


def get_value_with_unit(s):
    if not isinstance(s, str) or not s:
        return s, None

    ss = re.sub(r'\s+', ' ', s).split(' ')
    if len(ss) != 2:
        return s, None

    v = parse_field_value(ss[0], no_raise=True)
    if not math.isnan(v) and re.match(f'({any_unit})', ss[1]):
        return v, ss[1]
    return s, None


# --- resistance units: ONE definition, shared by the writer and the reader -----------
# U+03A9 GREEK CAPITAL OMEGA and U+2126 OHM SIGN are DISTINCT codepoints and both occur
# in real sheets, so they are written as escapes and must not be collapsed to one. O/Q/QO/W
# are OCR and Symbol-font renderings of omega; keep in sync with expr.py's R unit_regex.
#
# ':' 'o' 'OQ' are the same class of artefact, measured on the shipped DB: in many sheets
# the omega is a Symbol-font glyph with NO ToUnicode map, so it extracts as nothing at all
# (IRFP4768PBF: "max 17.5m", HY5012W: "3.6 m") or as whatever the table extractor puts in
# an empty cell. Ground truth for ':' is exact -- Vishay MPNs encode the resistance, and
# SQD50N10-8M9L/SQM120N10-3M8/SUM90N10-8M2P all read back at ratio 1.00 when ':' is taken
# as omega. 'm:' likewise checks out against the IRFP4768PBF and HY5012W datasheet text.
_OHM_BODY = {'\u03a9', '\u2126', 'O', 'Q', 'QO', 'OQ', 'o', 'Ohm', 'ohm', 'OHM', 'W', ':'}
_OHM_PREFIX_TO_MILLI = {'m': 1.0, '': 1e3, 'k': 1e6, 'M': 1e9}

# Cell-border debris that table extractors glue to the FRONT of a unit cell ('|mQ', 'ImO',
# 'JmQ', '}mQ', '|(mQ'). Deliberately excludes 'O'/'Q'/'o' -- they are omega renderings and
# stripping them would eat the unit itself ('Ohm', 'O'). Stripping is safe only because a
# non-match still returns None: debris that does not leave a valid ohm unit behind (j|nA,
# l) falls through to NaN exactly as before.
_OHM_NOISE_PREFIX = '|(){}[]IijJl'

# Scale assumed when a resistance Field carries NO unit at all. Encodes the pre-existing
# conventions so this refactor changes no value:
#   Rds_on      canonical milliohm
#   Rds_on_10v  ohm-scale (100% unitless in the shipped DB; ratio to Rds_on has median
#               exactly 1.0 after x1000)
#   Rg          ohm-scale (matches the old field_mul rule: a non-'m' unit meant ohms)
_RESISTANCE_UNITLESS_TO_MILLI = {'Rds_on': 1.0, 'Rds_on_10v': 1e3, 'Rg': 1e3}

# Symbols whose unit Field.__init__ canonicalises to mΩ. An EXPLICIT set, not the
# `symbol[0] == 'R'` prefix it replaced: thermal resistance also starts with 'R'
# (RthJC/RthJA, and expr.py:577 has RthJC inside the electrical-resistance head_regex),
# and it is quoted in °C/W or K/W. The prefix test only looked safe because 'K'/'C' are
# not in the mkM prefix table, so 'K/W' happened not to match -- but a bare 'W' or 'mW'
# capture on a thermal row WOULD have become milliohms. Widening _OHM_BODY to ':'/'o'/
# 'OQ' plus noise stripping widened that latent hazard, so the gate is now exact.
# Measured: 0 Rth fields among the 61046 R-fields in the shipped DB (Rds_on 24475,
# Rg 25663, Rds_on_10v 10908) and detect_fields exposes no Rth symbol -- i.e. this was
# LATENT, not firing, so scoping it changes no current value. Keep it exact anyway: the
# cost of being wrong here is a 1000x on the quantity the tool ranks on.
_WRITER_CANONICAL_SYMBOLS = frozenset(_RESISTANCE_UNITLESS_TO_MILLI)


def ohm_unit_to_milli_mul(unit):
    """Multiplier converting a value in `unit` to milliohm, or None if `unit` is not a
    recognised resistance unit (including empty/None, so callers must decide explicitly
    what a missing unit means). NEVER inspects magnitude -- guessing scale from how big a
    number looks is what made main.py's `if rds_on_max < 0.1: *= 1000` anti-monotone."""
    u = (unit or '').strip()
    if not u:
        return None

    # 'm Ω' -- the prefix and the glyph land in the cell with a separator between them.
    u = u.replace(' ', '').replace(' ', '')
    u = u.lstrip(_OHM_NOISE_PREFIX)
    if not u:
        return None

    if u in _OHM_BODY:
        return _OHM_PREFIX_TO_MILLI['']
    if len(u) > 1 and u[0] in 'mkM' and u[1:] in _OHM_BODY:
        return _OHM_PREFIX_TO_MILLI[u[0]]

    # Bare 'm': the omega did not extract at all. Only 'm' is recovered, never a bare 'k'
    # or 'M' -- those are ambiguous with a stray letter, whereas an 'm' on a resistance
    # symbol can only be milliohm.
    #
    # This used to justify itself with "the sole caller is get_resistance_milliohm". That
    # became false the moment Field.__init__ started calling this too, and a one-caller
    # argument does not survive a second caller. It holds on the narrower ground that BOTH
    # callers are gated on a resistance symbol: the reader by _RESISTANCE_UNITLESS_TO_MILLI
    # and the writer by _WRITER_CANONICAL_SYMBOLS, which are the same three symbols. If a
    # third, ungated caller ever appears, this recovery has to be revisited -- so keep the
    # gate at the call sites, not a promise about how many there are.
    if u == 'm':
        return _OHM_PREFIX_TO_MILLI['m']
    return None


# Files whose content decides how a Field STORES a value. Not just this module: the
# conversion reaches out of it, and every edge is a place the old function-granular salt
# was blind.
#   field.py        the unit tables, Field.__init__, get_value_with_unit, parse_field_value
#   dslib/__init__  round_to_n_dec -- rounding changes the stored magnitude
#   conditions.py   normalize_conditions -- decides the cond a stat is selected by
#   pdf/expr.py     any_unit, the regex get_value_with_unit splits a "value unit" cell on
#   pdf/pdf2txt     normalize_text / whitespaces_to_space, applied before the split
_FIELD_REPR_SOURCES = (
    ('field.py',),
    ('__init__.py',),
    ('conditions.py',),
    ('pdf', 'expr.py'),
    ('pdf', 'pdf2txt', '__init__.py'),
)


def field_repr_salt(root=None):
    """Cache salt covering how a Field STORES a value: the magnitude and the unit string.

    Why every Field-producing cache needs this. A pickled Field bypasses __init__, so a
    cache generation written before the writer canonicalised its unit keeps (raw value,
    raw unit). Nothing re-runs the conversion on unpickle. DatasheetFields.fill() then
    copies stats between candidates WITHOUT converting or comparing units, so one stale
    stat and one fresh stat can end up in a single Field under a single unit -- and the
    reader applies that unit to both. Reproduced exactly:

        stale Field(Rds_on, typ=.005, unit=':')   [unpickled, pre-change generation]
      + fresh Field(Rds_on, max=.006, unit=':')   [scaled by the new writer -> max=6, 'mΩ']
      = merged typ=.005, max=6.0, unit=':'
        get_resistance_milliohm(stat='max') -> 6000 mΩ for a 6 mΩ part.

    A silent 1000x on the quantity this tool ranks on, from a cache HIT. Before this salt
    only dslib.v2's v2_code_salt covered field.py; read_sheet (fixed 'v11',
    hash_func_code=False), tabular, extract_fields_from_text and the outer parse_datasheet
    all hashed code that could not see a Field-representation change.

    A CONTENT HASH of the source files, the same shape as v2_code_salt. That shape is what
    made v2 immune to the three co_code holes below -- but NOT to the problem as a whole:
    v2_code_salt's file list omits dslib/__init__.py, conditions.py and pdf/pdf2txt, so v2
    had three representation holes of its own until it started sharing this salt. "Same
    shape" is not "was always correct", and an earlier version of this docstring overstated
    exactly that.

    SNAPSHOT AT IMPORT, not read per call. The hash is computed once when this module is
    imported and `field_repr_salt()` returns that value, because the salt has to name the
    code generation the PROCESS IS RUNNING, not whatever is on disk right now. Reading disk
    per call inverts the guarantee: a long-lived process holding the old Field code would
    compute the NEW salt after someone edits the file, then write OLD-representation Fields
    under the new-generation key -- poisoning the cache for the next process, which reads
    them as new. Staleness is recoverable; a new key filled with old values is not. This is
    not hypothetical in this repo: two agents edit it concurrently.

    This replaces a function-granular version that hashed the unit tables by value plus
    `co_code` of the three converting functions. That was an attempt to buy precision (a
    comment edit would not rebuild the corpus) and it was WRONG, in the specific way this
    whole plan exists to stamp out: it answered "unchanged" when the semantics had changed.
    Three demonstrated holes, two of them found by review after it had already been
    committed:

      1. `co_code` omits `co_consts`. Swapping Field.__init__'s 'mΩ' literal for 'Ω'
         changes what every Field stores and leaves the bytecode byte-for-byte identical.
      2. `co_code` omits nested code objects. Field.__init__ contains `_unit_value`, whose
         entire body was invisible.
      3. Even a perfect fingerprint of those three functions is not the closure.
         Field.__init__ calls parse_field_value; get_value_with_unit uses `any_unit` and
         normalize_text. Monkeypatching parse_field_value to double its result changed
         Field('Qg',1,2,3,'nC') from [1,2,3] to [2,4,6] with the salt unmoved.

    (1) and (2) are fixable by fingerprinting harder. (3) is not: every new call edge out
    of this module is another silent hole, and nothing makes the omission visible. A guard
    with an unbounded number of undetectable holes is a mute button, so the precision
    optimisation is abandoned rather than patched a third time.

    COST, accepted deliberately: any edit to the files above -- INCLUDING A COMMENT --
    rebuilds these four caches. Prose is no longer free. That is the price of the key
    covering the derivation instead of a proxy for it, and v2_code_salt has been paying it
    for field.py all along.

    An unreadable dependency RAISES rather than being skipped: silently dropping a file
    would narrow the key and reintroduce the bug, so it must be louder than a cache miss.

    KNOWN LIMITS -- stated because a guard whose scope is overclaimed is the failure mode
    this replaces, and none of these is currently reachable-and-silent:
      - The file list is depth 1 from this module. normalize_text's own helpers live in the
        same file, so today the closure is complete; a NEW cross-module call added to any
        listed function would not extend the list by itself. Adding an import here means
        checking whether it decides a stored value.
      - unicodedata.normalize is stdlib, so its behaviour is pinned by the Python version
        rather than by anything here. Not in the key: a Python upgrade changes far more than
        this and is not a silent same-environment drift.
      - This says nothing about whether an already-pickled Field is canonical. It stops
        MIXING generations by rebuilding on change; repairing existing DB records is
        Phase 3 in docs/resistance-unit-convention-plan.md.
      - The import snapshot is computed while THIS module body executes, i.e. after the
        loader compiled the Field code above and after the dependency modules may already
        be imported. An edit landing inside that window binds loaded-old semantics to a
        new-disk signature. That is milliseconds at startup rather than the whole run, so
        it is a narrow residual and not the per-call inversion it replaced. Closing it
        properly means hashing each loaded artifact's source as the loader saw it (e.g. via
        each module's __loader__.get_source) or requiring source quiescence at startup.

    `root` exists ONLY so the calibration tests can perturb COPIES under tmp_path instead of
    rewriting live sources -- the previous tests truncated and rewrote production files, and
    a concurrent edit between their snapshot and their restore would have been destroyed
    silently. Production callers pass nothing and get the import snapshot.
    """
    if root is None:
        return _FIELD_REPR_SIG
    return _compute_field_repr_sig(root)


def _compute_field_repr_sig(root=None):
    """Hash the representation sources under `root` (default: this package directory)."""
    # Private, but same project. Memoized by (path, mtime, size), so once warm this is a
    # stat per file rather than a re-hash.
    from dslib.cache import _file_content_sig
    import hashlib
    import os
    d = root or os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha256()
    for rel in _FIELD_REPR_SOURCES:
        h.update(_file_content_sig(os.path.join(d, *rel)).encode())

    # unidecode is the thing that maps Ω -> 'O', and 'O' is in _OHM_BODY. A version bump
    # changes which glyphs collapse to which ASCII, i.e. it changes what counts as an ohm
    # unit, from outside every file above. Third-party, so no content hash -- version only.
    #
    # Read from package metadata, NOT `unidecode.__version__`: this package does not define
    # that attribute, so the first version of this used getattr(..., 'unknown') and recorded
    # the same constant on every run. An inert component that looks present is worse than an
    # absent one, and it is the same anti-monotone shape as the bug this salt exists for.
    # A version that cannot be read RAISES rather than degrading to a placeholder.
    from importlib.metadata import version as _pkg_version
    h.update(('unidecode=' + _pkg_version('Unidecode')).encode())

    return 'field-repr:' + h.hexdigest()[:16]


# Bound to the generation this process IMPORTED, computed once, here. Deliberately eager:
# resolving it per call would let a process that loaded the old Field code compute the NEW
# salt after an on-disk edit and write old-representation Fields under the new key. Cheap
# enough to do at import -- five memoized content hashes and one metadata lookup.
_FIELD_REPR_SIG = _compute_field_repr_sig()


class Field():
    StatLiteral = Literal['min', 'max', 'typ']
    StatKeys = cast(List[StatLiteral], ['min', 'typ', 'max'])
    not_zero_symbols = {'Qg', 'Qgs', 'Qgd'}

    def __init__(self, symbol: str, min, typ, max, unit=None, mul=1, cond=None, source=None):
        self.symbol = symbol
        self._sources: Dict[Field.StatLiteral, str] = {k: source for k in Field.StatKeys}

        def _unit_value(v):
            nonlocal unit
            v2, u = get_value_with_unit(v)
            if u:
                assert not unit or unit == u
                unit = u
                return v2
            return v

        min = _unit_value(min)
        max = _unit_value(max)
        typ = _unit_value(typ)

        if unit and symbol in {'tFall', 'tRise'} and unit.lower() == 'ms':
            unit = 'ns'  # ocr confusion

        if unit in {'uC', 'μC', '∝C', 'uc'}:
            assert mul == 1
            mul = 1000
            unit = 'nC'

        if unit in {'nF'}:
            assert mul == 1
            mul = 1e3
            unit = 'pF'

        if unit in {'uF', 'μF'}:
            assert mul == 1
            mul = 1e6
            unit = 'pF'

        if symbol in _WRITER_CANONICAL_SYMBOLS:
            # ONE definition, actually shared now. This used to hardcode {'mW'} and
            # {'W','Ω'}, so every other spelling the reader understands ('mΩ', 'kΩ', 'O',
            # 'Q', ':', '|mQ', ...) fell through unscaled and unrenamed, and the reader had
            # to re-derive the scale from the raw unit on every read. Both halves now agree
            # by construction.
            #
            # Scaling and RENAMING are one step on purpose: the unit is rewritten to 'mΩ'
            # exactly when the value is multiplied, so a Field can never be scaled twice --
            # a second pass sees 'mΩ' and multiplies by 1. Keep them together.
            r_mul = ohm_unit_to_milli_mul(unit)
            if r_mul is not None:
                assert mul == 1
                mul = r_mul
                unit = 'mΩ'

        min = parse_field_value(min, no_raise=True) * mul
        typ = parse_field_value(typ, no_raise=True) * mul
        max = parse_field_value(max, no_raise=True) * mul

        fill_max_dims = {'Q', 't', 'Vsd', 'Coss'}
        is_fill_max = symbol[0] in fill_max_dims or symbol in fill_max_dims

        if is_fill_max and math.isnan(max) and not math.isnan(min) and not math.isnan(typ):
            max = typ
            typ = min
            min = math.nan

        if is_fill_max and math.isnan(max) and not math.isnan(min) and math.isnan(typ):
            typ = min
            min = math.nan
            max = math.nan

        if symbol == 'Vpl' and 30 < typ < 60:
            warnings.warn('Vpl %s out of range, assuming /10' % typ)
            typ /= 10

        if symbol == 'Vds':
            if abs(typ) < 1: typ = math.nan
            if abs(min) < 1: min = math.nan
            if abs(max) < 1: max = math.nan

        mtm = (min, typ, max)

        if symbol == 'Qrr' and (not unit or unit.lower() == 'c'):
            # fix Qrr in uC -> nC
            if sum(math.isnan(v) or 0.1 < v < 0.9 for v in mtm) == 3:
                min *= 1e3
                typ *= 1e3
                max *= 1e3

        if symbol in {'Qgd', 'Qgs', 'Qg', 'tRise', 'tFall'}:
            if not math.isnan(max) and math.isnan(min) and math.isnan(typ):
                typ = max
                max = math.nan

        if symbol == 'Vsd' and max < typ and (typ / max) < 1.5:
            # Vsd confusion
            a = max
            max = typ
            typ = a

        if unit and symbol == 'Vds' and ('/°C' in unit or 'mV' in unit):
            raise ValueError('invalid Vds unit %s' % unit)

        if not math.isnan(max) and not math.isnan(typ):
            max_typ_ratio = 30 if symbol == 'Crss' else 5
            assert 1 < max / typ < max_typ_ratio, (typ, max)

        self.min = min
        self.typ = typ
        self.max = max

        self.unit = unit

        self.cond: dict = cond

        self.timestamp = time.time()

        assert not math.isnan(self.typ) or not math.isnan(self.min) or not math.isnan(
            self.max), 'all nan ' + self.__repr__()

    def __repr__(self):
        return f'Field("{self.symbol}",{self.min},{self.typ},{self.max},"{self.unit}",cond={repr(self.cond)})'  # ,cond={repr(self.cond)}

    def __str__(self):
        return f'{self.symbol} = %5.1f,%5.1f,%5.1f [%s] (%s)' % (self.min, self.typ, self.max, self.unit, self.cond)

    def __len__(self):
        return 3 - math.isnan(self.min) - math.isnan(self.typ) - math.isnan(self.max)

    @property
    def typ_or_max_or_min(self):
        if not math.isnan(self.typ):
            return self.typ
        elif not math.isnan(self.max):
            return self.max
        elif not math.isnan(self.min):
            return self.min
        raise ValueError()

    @property
    def max_or_min(self):
        if not math.isnan(self.max):
            return self.max
        elif not math.isnan(self.min):
            return self.min
        return math.nan

    @property
    def max_or_typ(self):
        if not math.isnan(self.max):
            return self.max
        elif not math.isnan(self.typ):
            return self.typ
        return math.nan

    @property
    def max_or_min_or_typ(self):
        if not math.isnan(self.max_or_min):
            return self.max_or_min
        elif not math.isnan(self.typ):
            return self.typ
        return math.nan

    @property
    def max_or_typ_or_min(self):
        if not math.isnan(self.max):
            return self.max
        elif not math.isnan(self.typ):
            return self.typ
        elif not math.isnan(self.min):
            return self.min
        raise ValueError()

    def fill(self, f: 'Field', update_min_max=False):
        if update_min_max:
            raise NotImplemented()
            # TODO min, max updates?

        # if f has more values, use all of them
        # todo this is questionable
        # is_sup = len(f) > len(self) and (not self._sources or 'ref' in self._sources)
        is_sup = False

        nz = self.symbol in self.not_zero_symbols
        lower = 0 if nz else -float('inf')

        for s in Field.StatKeys:
            if is_sup or (math.isnan(getattr(self, s)) and not math.isnan(getattr(f, s))
                          and getattr(f, s) >= lower) or (nz and getattr(self, s) == 0):
                setattr(self, s, getattr(f, s))
                self._sources[s] = f._sources[s]
            if not math.isnan(getattr(self, s)):
                lower = getattr(self, s)

        # NOT re-validated here on purpose. A post-hoc check at this point cannot be
        # correct: fill() has already mutated self, so the only thing left to sacrifice is
        # a stat that may well be the GOOD one. Measured on ao/AOB66515L, where text's
        # correct max=1180 arrives first and v2's wrong typ=1.18 merges second: a
        # "discard the impossible max" guard threw away the only sound value and kept the
        # wrong one -- worse than the incoherent field it was meant to prevent. The fix is
        # transactional: validate the INCOMING candidate's unit/source against the already
        # selected stats and reject the candidate BEFORE mutating. Tracked as step 2 of
        # docs/resistance-unit-convention-plan.md; deliberately absent rather than wrong.
        # TODO dont fill (n,8,9) with (8,9,n)

    def __getitem__(self, item):
        assert item in {'min', 'max', 'typ'}
        return getattr(self, item)

    def values(self) -> List[float]:
        return [self.min, self.typ, self.max]

    def __eq__(self, other):
        """Compare against another Field or a (min, typ, max) triple.

        Anything else returns NotImplemented rather than True. This used to fall through
        to `return True` for ANY unsupported operand, so `field == 0.62` was vacuously
        true and assertions written that way could never fail -- five in the test suite
        were silently passing, three of them against values 1000x off. A comparison we
        cannot evaluate must not report "equal": be explicit about which stat you mean
        (`field.typ == x`) or pass a full triple.
        """
        if isinstance(other, Field):
            assert self.unit == other.unit
            if self.symbol != other.symbol:
                return False
            other = other.values()

        if isinstance(other, (tuple, list)):
            assert len(other) == 3, other
            ks = ('min', 'typ', 'max')
            for i in range(0, 3):
                v = self.__dict__[ks[i]]
                if math.isnan(v) and math.isnan(other[i]):
                    continue
                if v != other[i]:
                    return False
            return True

        return NotImplemented

    def assert_values(self, min=None, typ=None, max=None):
        if isinstance(min, (tuple, list)):
            assert typ is None and max is None
            return self.assert_value(*min)
        elif isinstance(min, (dict)):
            assert typ is None and max is None
            return self.assert_value(**min)

        for k, b in dict(min=min, typ=typ, max=max).items():
            if b is None:
                continue
            a = self.__dict__[k]
            if math.isnan(a) and math.isnan(b):
                continue

            assert a == b, (k, self, self.cond, self._sources)

    def assert_value(self, min=None, typ=None, max=None):
        return self.assert_values(min=min, typ=typ, max=max)


def parse_field_value(s, no_raise=False):
    if isinstance(s, (float, int)):
        return s
    if not s:
        return math.nan
    s = normalize_text(s.strip().strip(' \x03').rstrip('L.'))
    if not s or s in {'-', '~', '.', '=', '"', "'", '#', '~NA~', 'N/A'} or set(s) == {'-', '~'}:
        return math.nan
    if s.startswith('+- '):
        s = s[3:]
    if s.count(',') == 1:
        s1 = s.split('.')[0]
        if len(s1) >= 5 and s1[-4] == ',':
            s = s.replace(',', '')
    try:
        return float(s)
    except:
        if no_raise:
            return math.nan
        # print('string is %r' % s)
        raise


class MpnMfr:
    def __init__(self, mfr, mpn):
        self.mfr = mfr
        self.mpn = mpn


def conditions_to_str(cond):
    if cond and isinstance(cond, dict) and isinstance(list(cond.keys())[0], str):
        cond_str = ' '.join(f'{f}={round_to_n_dec(v, 3)}' for f, v in sorted(cond.items()))
    else:
        cond_str = whitespaces_to_space(', '.join(
            map(str, (cond.items() if isinstance(cond, dict) else cond)) if cond else []))[:80]
    return cond_str


class DatasheetFields():
    def __init__(self, mfr=None, mpn=None, part: 'DiscoveredPart' = None, fields: Iterable[Field] = None,
                 date_from_text=None, date_from_meta=None):
        from dslib.discovery import DiscoveredPart
        self.part: Union[DiscoveredPart, MpnMfr] = part or MpnMfr(mfr, mpn)
        self.fields_filled: Dict[str, Field] = {}
        self.fields_lists: Dict[str, List[Field]] = {}
        if fields:
            self.add_multiple(fields)

        self.timestamp = datetime.datetime.now()
        self.errors: List[str] = []
        self.date_from_text: Optional[datetime.datetime] = date_from_text
        self.date_from_meta: Optional[datetime.datetime] = date_from_meta

    @property
    def ds_path(self):
        return self.part.get_ds_path()

    def get_row(self):
        ds = self
        part = ds.part

        try:
            fet_specs = ds.get_mosfet_specs()
        except Exception as e:
            warnings.warn('failed to create fet specs: %s' % e)
            fet_specs = None

        # One reader, one scale. This used to take Rds_on_10v (ohm-scale) or fall back to
        # Rds_on (already mΩ) and then multiply BOTH by 1000 at the Rds_max= line, so the
        # fallback path reported 503 parts 1000x too big.
        rds_on_max = ds.get_resistance_milliohm('Rds_on_10v', stat='max')
        if math.isnan(rds_on_max):
            rds_on_max = ds.get_resistance_milliohm('Rds_on', stat='max')

        Id = ds.get_typ_or_max_or_min('ID_25', False)
        if math.isnan(Id):
            Id = ds.get_typ_or_max_or_min('Id', False)

        return dict(
            mfr=part.mfr,
            mpn=part.mpn,
            housing=part.package,

            Vds_max=ds.get_max_or_min('Vds', False),
            Rds_max=rds_on_max,  # already mΩ via get_resistance_milliohm
            Id=Id,

            Qg_max=ds.get_max('Qg'),
            Qgs=ds.get_typ_or_max_or_min('Qgs'),
            Qgd=ds.get_typ_or_max_or_min('Qgd'),
            Qsw=fet_specs and (fet_specs.Qsw * 1e9),

            # C_oss_pF=ds.get('Coss') and ds.get('Coss').max_or_typ_or_min,

            Vsd=ds.get_typ_or_max_or_min('Vsd'),
            Qrr_typ=ds.get_typ('Qrr'),
            Qrr_max=ds.get_max('Qrr'),

            tRise_ns=round(fet_specs.tRise * 1e9, 1),
            tFall_ns=round(fet_specs.tFall * 1e9, 1),

            errors=', '.join(self.errors),
            # dates=', '.join(map(lambda d: d.strftime('%Y-%m'), sorted({min(self.dates), max(self.dates)}))),
            date=self.date_from_text.strftime('%Y-%m') if self.date_from_text else '',
            dateC=self.date_from_meta.strftime('%Y-%m') if self.date_from_meta else '',
        )

    def add(self, f: Field):
        assert not math.isnan(f.typ_or_max_or_min)
        if f.symbol not in self.fields_filled:
            self.fields_filled[f.symbol] = copy(f)
            self.fields_lists[f.symbol] = []
        self.fields_lists[f.symbol].append(f)
        self.fields_filled[f.symbol].fill(f)

    def add_multiple(self, fields: Iterable[Field], source=None):
        for f in fields:
            if source:
                f = copy(f)
                f._sources = {k: copy(source) for k in Field.StatKeys}
            self.add(f)

    def print(self, show_cond=False, show_sources=False):
        print('')
        print(self.part.mfr, self.part.mpn)
        print('Symbol         min     typ     max     unit   ',
              'cond' if show_cond else '',
              '                 source' if show_sources else '')

        # rows = self.fields_filled.values()
        rows = sum(self.fields_lists.values(), [])

        for f in rows:

            src = ''

            cond_str = ''
            if show_cond:
                cond_str = conditions_to_str(f.cond)

            if show_sources:
                v = list('>'.join(v or '') for v in f._sources.values())
                if len(set(v)) == 1:
                    src = v[0]
                else:
                    src = ','.join(v)
                src = src[:40]

            l = '%-12s %7.1f %7.1f %7.1f   %4s  %-25s %-30s' % (
                f.symbol, f.min, f.typ, f.max, f.unit, cond_str, src)
            l = l.replace('nan', ' ⎵ ')
            l = l.replace(' None', '  ⎵  ')
            print(l)

    def get_mosfet_specs(self, Vgs=10):
        mf_fields = [
            'Qrr', 'trr', 'Vsd',  # body diode
            'Qgd', 'Qgs', 'Qgs2', 'Qg_th',  # gate charges
            'Coss', 'Qsw',
            'Rg',
        ]

        def field_mul(sym, v, unit):
            if sym[0] == 'V':
                return v

            if sym == 'Coss':
                return (v * 1e-12)

            if sym == 'Rg':
                # delegate to the single reader (mΩ) -> ohm. The old inline rule
                # "unit starts with m => mΩ, ELSE assume ohms" believed any unit it did
                # not recognise, so Rg=168 from a unit='ns' row was consumed as 168 Ω.
                # stat=typ_or_max_or_min preserves what field_mul actually read before
                # this refactor (it was called with ds.get_typ_or_max_or_min(k)). The
                # default max_or_typ changed Rg by 50% on any field carrying both stats
                # (typ=0.8/max=1.2 -> 1.2 Ohm instead of 0.8), and Rg feeds
                # ig_on = (Voff-vpl)/rg_total. Scale-only refactor must not move values.
                return ds.get_resistance_milliohm('Rg', stat='typ_or_max_or_min') * 1e-3

            return (v * 1e-9)

        ds = self

        # mΩ from a single reader; the *1e3 / bare-fallback pair this replaces assumed
        # Rds_on_10v was ohm-scale and Rds_on was mΩ without ever checking either.
        rds_on = ds.get_resistance_milliohm('Rds_on_10v', cond=dict(Vgs=Vgs))
        if math.isnan(rds_on):
            rds_on = ds.get_resistance_milliohm('Rds_on', cond=dict(Vgs=Vgs))

        Id = ds.get_typ_or_max_or_min('ID_25', False)
        if math.isnan(Id):
            Id = ds.get_typ_or_max_or_min('Id', False)

        def _select_cond_values(symbol, cond_sym):
            cond = []
            for f in self.fields_lists.get(symbol, []):
                v = normalize_conditions(f.cond).get(cond_sym)
                if v:
                    cond.append(v)
            return cond

        # Some datasheet only show Coss at given Vds
        coss_cond = _select_cond_values('Coss', 'Vds') or _select_cond_values('Qoss', 'Vds')

        # Gate-charge TABLE test current: the Id condition on the Qg/Qgs/Vpl rows — the
        # current Vplateau and the charge partition were measured at. NOT the ID_25
        # continuous rating in `Id` above (1.4-4x apart on parts checked 2026-07-14); a
        # channel/gm anchored on the rating is that factor too stiff. Consumers:
        # dcdc-tools loss recon gm + curve-tier channel derivation.
        id_gc_cond = (_select_cond_values('Qg', 'Id') or _select_cond_values('Qgs', 'Id')
                      or _select_cond_values('Vpl', 'Id'))
        id_gfs_cond = _select_cond_values('gfs', 'Id')

        def _sane(v, lo, hi, what):
            # range-sanitize the auxiliary channel anchors to NaN (with a warning)
            # instead of asserting in the MosfetSpecs ctor: an assert there drops the
            # part's ENTIRE spec object (get_row wraps this in except->None) over a
            # mis-parsed free-text condition. Consumers refuse on NaN, loudly.
            if v is None or math.isnan(v) or lo < v < hi:
                return v if v is not None else math.nan
            warnings.warn(f"{self.part}: parsed {what}={v!r} out of range "
                          f"({lo}..{hi}) — dropped to NaN (check the datasheet parse)")
            return math.nan

        from dslib.mosfet import MosfetSpecs
        return MosfetSpecs(
            Vds_max=ds.get_max_or_min_or_typ('Vds'),  # TODO rename 'VdsBR'
            Rds_on=rds_on * 1e-3,
            Id=Id,
            Qg=ds.get_typ_or_max_or_min('Qg', cond=dict(Vgs=Vgs)) * 1e-9,
            tRise=ds.get_typ_or_max_or_min('tRise') * 1e-9,
            tFall=ds.get_typ_or_max_or_min('tFall') * 1e-9,
            **{k: field_mul(k, ds.get_typ_or_max_or_min(k), ds.get_unit(k)) for k in mf_fields},
            Vpl=ds.get_typ_or_max_or_min('Vpl'),
            Coss_Vds=max(coss_cond) if coss_cond else None,  # small numbers are usually wrong
            Id_gc=_sane(max(id_gc_cond) if id_gc_cond else math.nan,
                        0.05, 2000, 'Id_gc'),
            gfs_min=_sane(ds.get('gfs', ('min',)), 0.05, 5000, 'gfs_min'),
            gfs_typ=_sane(ds.get('gfs', ('typ',)), 0.05, 5000, 'gfs_typ'),
            Id_gfs=_sane(max(id_gfs_cond) if id_gfs_cond else math.nan,
                         0.05, 2000, 'Id_gfs'),
            Vgs_th=_sane(ds.get('Vgs_th', ('typ',)), 0.3, 8, 'Vgs_th'),
            part=self.part,
        )

    def get(self, sym, stat: Union[Tuple[Field.StatLiteral], Field.StatLiteral], required=False):
        if isinstance(stat, str):
            stat = (stat,)
        r = self.fields_filled.get(sym)
        assert not required or r
        if not r:
            return math.nan
        for s in stat:
            v = getattr(r, s)
            if not math.isnan(v):
                return v
        return math.nan

    def get_typ_or_max_or_min(self, sym, required=False, cond=None):
        r = self._get_by_cond(sym, cond)
        assert r or not required
        return math.nan if not r else r.typ_or_max_or_min

    def get_max_or_min_or_typ(self, sym, required=False, cond=None):
        r = self._get_by_cond(sym, cond)
        assert r or not required
        return math.nan if not r else r.max_or_min_or_typ

    def get_max_or_min(self, sym, required=False, cond=None):
        r = self._get_by_cond(sym, cond)
        assert r or not required
        return math.nan if not r else r.max_or_min

    def get_max_or_typ(self, sym, required=False, cond=None):
        r = self._get_by_cond(sym, cond)
        assert r or not required
        return math.nan if not r else r.max_or_typ

    def get_typ(self, sym):
        r = self.fields_filled.get(sym)
        return math.nan if not r else r.typ

    def get_resistance_milliohm(self, sym, stat='max_or_typ', cond=None) -> float:
        """The single way to read a resistance symbol. Returns milliohm, or NaN.

        Scale resolution, in order, and NEVER from magnitude:
          1. Field carries a recognised resistance unit -> use it
          2. Field carries no unit at all -> the symbol's documented storage default
          3. Field carries a unit from a DIFFERENT dimension ('ns','pF','V','nC')
             -> NaN

        NB ':' is NOT in that list: it is an omega rendering here (see _OHM_BODY) and is
        ACCEPTED by step 1. This docstring used to list it as cross-dimension while the
        helper converted it, which is the more dangerous direction of disagreement for a
        reader to trust. ':' is not intrinsically omega -- it is a generic broken-font /
        empty-cell filler, and the shipped DB has 693 ':' fields of which 127 are non-R
        (tDon 44, tRise 42, Qoss 38). It is only safe because BOTH callers are gated on the
        three electrical resistance symbols; all 282 ':' Rg values are plausible
        (0.39-14 Ω) and the Rds_on ones check out against the PDFs. Do not generalise ':'
        beyond that gate.

        (3) is the point. A cross-dimension unit means the cell was mis-captured, so the
        number is not a resistance -- e.g. Rg=168 taken from a unit='ns' switching-time
        row. Applying the default scale there converts a parse failure into a believable
        wrong number on the quantity this tool ranks on, and no caller can tell
        afterwards. NaN is recoverable; a plausible wrong resistance is not.

        Replaces four hand-rolled conversions that disagreed: get_row's unconditional
        *1000, get_mosfet_specs' *1e3/*1e-3 pair, field_mul's Rg branch, and main.py's
        `if < 0.1: *= 1000` magnitude guess.
        """
        f = self._get_by_cond(sym, cond) if cond else self.fields_filled.get(sym)
        if not f:
            return math.nan
        v = f.max_or_typ if stat == 'max_or_typ' else getattr(f, stat)
        if v is None or math.isnan(v):
            return math.nan

        milli_mul = ohm_unit_to_milli_mul(f.unit)
        if milli_mul is not None:
            return v * milli_mul

        if (f.unit or '').strip():
            warnings.warn('%s %s has non-resistance unit %r; refusing to guess a scale'
                          % (getattr(getattr(self, 'part', None), 'mpn', '?'), sym, f.unit))
            return math.nan

        default_mul = _RESISTANCE_UNITLESS_TO_MILLI.get(sym)
        return math.nan if default_mul is None else v * default_mul

    def get_unit(self, sym):
        r = self.fields_filled.get(sym)
        return None if not r else r.unit

    def _get_by_cond(self, sym, cond=None):
        e_min = 0.1
        f_min = self.fields_filled.get(sym)
        if not f_min or (f_min.typ_or_max_or_min == 0 and f_min.symbol in Field.not_zero_symbols):
            e_min = float('inf')
        l = self.fields_lists.get(sym)
        if l and cond:
            for f in l:
                if f.typ_or_max_or_min == 0 and f.symbol in Field.not_zero_symbols:
                    continue
                d = f.cond
                if not d or not isinstance(d, dict):
                    d = {}
                # A condition the candidate does not state is a MISMATCH, not a
                # match. The old form read an absent key as 0 via d.get(k, 0),
                # which only penalises while the requested value is non-zero:
                # ask for Vgs=0 -- what every Coss/Ciss/Crss/Vds row is specced
                # at -- and (0-0)/(0+1e-3) scored a candidate with NO conditions
                # at all as a PERFECT match, so it displaced the row that
                # actually says "VGS = 0 V". Measured on 3 toshiba and 3 st
                # parts: Coss at Vgs=0 returned 92 instead of 145, and 80
                # instead of 977. Absence of evidence must not read as
                # agreement; an unstated condition is charged a full relative
                # error, so it loses to any row that states it and still beats
                # a row that states a plainly wrong one.
                e = (sum((1.0 if k not in d else ((d[k] - v) / (abs(v) + 1e-3)) ** 2)
                         for k, v in cond.items()) / len(cond)) ** .5
                if e < e_min:
                    e_min = e
                    f_min = f
        return f_min

    def get_max(self, sym, required=False, cond=None):
        r = self._get_by_cond(sym, cond)
        assert not required or r
        return math.nan if not r else r.max

    def get_min(self, sym, required=False, cond=None):
        r = self._get_by_cond(sym, cond)
        assert not required or r
        return math.nan if not r else r.min

    def items(self):
        return self.fields_filled.items()

    def keys(self):
        return self.fields_filled.keys()

    def __contains__(self, item):
        return item in self.fields_filled

    def __len__(self):
        return len(self.fields_filled)

    def __bool__(self):
        return bool(self.fields_filled)

    def __getattr__(self, item) -> Field:
        if item not in {'fields_filled', '__getstate__'}:
            ff = getattr(self, 'fields_filled')
            if item in ff:
                return ff[item]

            print('trying to get %s, but only have %s' % (item, ', '.join(ff.keys())))
        raise AttributeError(item)

    def shape(self):
        return (len(self), 3)

    def __getitem__(self, item) -> Field:
        return self.fields_filled[item]

    def all_fields(self) -> List[Field]:
        return sum(map(list, self.fields_lists.values()), [])

    # def _apply_on_values(self, symbols=None, reduce_field):
    #    if not symbols:
    #        symbols = b.fields_filled.keys()
    #    for sym in symbols:
    #        for f in b.fields_lists.get(sym, []):
    #
    #            (reduce_field(sym, stat, f[stat]) ):
    #                rv = f[stat]

    def count_equal(self, a: 'DatasheetFields', symbols=None, err_threshold=0.05):
        b = self
        n = 0
        if not symbols:
            symbols = b.fields_filled.keys()
        for sym in symbols:
            for stat in Field.StatKeys:
                min_err = float('inf')
                for f in b.fields_lists.get(sym, []):
                    rv = f[stat]
                    are = abs((a.get(sym, stat) - rv) / rv)
                    if are < min_err:
                        min_err = are

                if min_err < err_threshold:
                    n += 1

        return n

    def show_diff(self, a: 'DatasheetFields', symbols=None, err_threshold=0.001, title=''):
        assert 0 <= err_threshold < 0.2

        b = self
        n = 0
        if not symbols:
            symbols = b.fields_filled.keys()
        for sym in symbols:
            min_err = float('inf')
            for f in b.fields_lists.get(sym, []):
                max_err = 0
                for stat in cast(List[Field.StatLiteral], ['min', 'typ', 'max']):
                    # TODO iterate fields_list and take min err
                    rv = f[stat]
                    v = a.get(sym, stat)
                    if not math.isnan(rv) and math.isnan(v):
                        are = 1
                    else:
                        are = abs((v - rv) / rv)
                    max_err = max(max_err, are)
                if max_err >= err_threshold:
                    fo = a.fields_filled.get(sym, None)

                    if fo:
                        print('')
                        print(title, self.part.mfr, self.part.mpn,
                              f'err {round(max_err, 3)} > {err_threshold}',
                              '\nref=', f,
                              '\noth=', fo, fo and fo._sources,
                              )
                    else:
                        print(title, self.part.mfr, self.part.mpn, sym, 'not in oth', 'ref=', f, )

                    n += 1

                if max_err < min_err:
                    min_err = max_err

        return n

    def __str__(self):
        return f'DatasheetFields({self.part.mfr},{self.part.mpn}, count={len(self)})'

    def __repr__(self):
        return f'DatasheetFields("{self.part.mfr}","{self.part.mpn}",fields={list(self.fields_filled.values())})'

    def rmse(self, b: 'DatasheetFields'):
        raise NotImplemented()

        ref = self

        rmse = {}
        for sym, fl in ref.fields_filled:
            if sym not in b:
                rmse[sym] = math.nan
            rmse[sym] = min(() / r[s] for f in fl)
