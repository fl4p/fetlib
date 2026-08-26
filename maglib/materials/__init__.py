import math
import os.path
import re
import warnings
from math import isfinite, nan
from typing import Callable, Literal

from dslib.cache import mem_cache


def _finite_or_raise(fn: Callable, mfr, mpn, what: str):
    """Wrap a material curve so a non-finite result RAISES.

    A curve built from unknown coefficients returns nan, and nan is the worst
    possible answer here because it does not stay nan. ``dclib/powerloss.py``
    combines the two core-loss methods with ``max(P_core1, P_core2)``, and
    ``max(0, nan)`` is ``0`` in CPython -- so a material whose loss CANNOT BE
    COMPUTED is reported as a core with NO LOSS, which is the single most
    favourable answer the model can give. It then wins the ranking on the
    strength of the thing nobody could evaluate. The same run reports
    ``mthd: 1`` because ``nan > 0`` is False, claiming a method that never ran.

    Absence of evidence must not encode absence of loss, so this raises
    instead. Loud beats plausible: an unusable material should stop a design,
    not quietly top it.

    Not hypothetical. ``KDM_SendustKS_125`` used to be written with literal
    ``nan`` exponents while backing ``KDM_KS184_125A`` in ``maglib/cores.py``;
    this guard is what turned that into a stop rather than a free win, and it
    held for as long as the coefficients were missing. It now carries the
    vendor's printed law (``kdm_sendust_core_loss``), so that particular hole
    is closed -- but the CLASS of defect is not: the same path is reachable for
    any Micrometals material whose CSV cell fails to parse, because
    ``try_float`` turns a ValueError into nan and feeds it straight into the
    coefficient tuple. Do not remove this guard on the strength of the one
    example that no longer trips it.
    """
    if fn is None:
        return None

    def guarded(*args, **kwargs):
        v = fn(*args, **kwargs)
        if not isfinite(v):
            raise ValueError(
                '%s/%s: %s is not usable (returned %r for %s). Its curve '
                'coefficients are unknown or failed to parse; supply them '
                'rather than letting the value flow on -- nan reads as zero '
                'loss downstream.' % (mfr, mpn, what, v, kwargs or args))
        return v

    return guarded


class MagneticCoreMaterialSpecs:
    def __init__(self, mfr, mpn, mu_r,
                 core_loss_density: Callable,
                 dc_bias: Callable,
                 dc_magnetization: Callable = None,
                 coef_source: str = None,
                 dc_bias_coef: tuple = None,
                 dc_bias_floor: float = 0.25,
                 ):
        """:param dc_bias_coef: the (a, b, c) of the vendor percent-permeability
            fit ``%mu_i = 1/(a + b*H_oe**c)`` (Magnetics / Micrometals form, so
            the retained FRACTION is ``0.01/(a + b*H_oe**c)``), kept as DATA so a
            consumer that needs the analytic law (e.g. a closed-form flux linkage,
            which exists only for c == 2) can read it instead of re-fitting the
            opaque ``dc_bias`` callable. Optional; when given it must agree with
            ``dc_bias`` (checked at construction).
        :param dc_bias_floor: lowest retained fraction the vendor curve is
            published for. Magnetics prints "Fit valid only for range shown on
            graph", and the graphs do not all reach the same depth: plain Kool Mu
            is drawn to 25%, Kool Mu MAX only to 30%. Below the floor
            ``permeability_dc_bias`` raises (or warns with no_raise) exactly as it
            always did at the old hard-coded 25%.
        :param coef_source: where the curve coefficients came from --
            ``'datasheet'`` (this exact part's own printed values),
            ``'band'`` (a per-(material, permeability) fit shared across an OD
            range), or None for the hand-entered materials in this module.

        Provenance is carried rather than inferred because the two are not
        equally trustworthy and the difference is one-directional: measured
        against each datasheet's own printed nominals, the band fit runs up to
        35% LOW on core loss and 22% HIGH on retained permeability. A core
        served from the band therefore scores BETTER than the manufacturer
        says, and in a loss ranking that means the worse-sourced a core is, the
        more likely it is to win. A caller has to be able to see which it got.
        """
        self.mfr = mfr
        self.mpn = mpn
        self.mu_r = mu_r
        self.coef_source = coef_source
        assert isinstance(mu_r, int) and 10 <= mu_r <= 6000
        self.core_loss_density = _finite_or_raise(
            core_loss_density, mfr, mpn, 'core_loss_density')
        self.dc_bias = _finite_or_raise(dc_bias, mfr, mpn, 'dc_bias')
        self.dc_magnetization = _finite_or_raise(
            dc_magnetization, mfr, mpn, 'dc_magnetization')
        assert 0 < dc_bias_floor < 1, dc_bias_floor
        self.dc_bias_floor = dc_bias_floor
        self.dc_bias_coef = tuple(dc_bias_coef) if dc_bias_coef is not None else None
        if self.dc_bias_coef is not None:
            a, b, c = self.dc_bias_coef
            for H_oe in (10.0, 100.0):
                want = 0.01 / (a + b * H_oe ** c)
                got = self.dc_bias(H_oe=H_oe)
                assert abs(got - want) <= 1e-6 * max(1.0, abs(want)), (
                    mfr, mpn, 'dc_bias_coef disagrees with dc_bias at H=%g Oe: %r vs %r'
                    % (H_oe, got, want))

    def retained_permeability(self, H_oe, no_raise=False):
        """Retained FRACTION of initial permeability (0..1) at H in OERSTEDS.

        Same range policy as ``permeability_dc_bias`` (raise below
        ``dc_bias_floor``, or warn with ``no_raise``), but returns ``r`` rather
        than ``r * mu_r`` and takes Oe rather than A/m, because the vendor fits
        are written in Oe and a caller deriving ``L_inc(I) = L0 * r(H(I))`` wants
        the fraction. Having one accessor that returns ``r*mu_r`` in A/m and
        nothing that returns ``r`` in Oe made every consumer re-derive both.
        """
        r = self.dc_bias(H_oe=H_oe)
        self._check_bias_range(r, no_raise)
        return r

    def _check_bias_range(self, dc_bias, no_raise):
        in_range = self.dc_bias_floor <= dc_bias <= 1
        if not in_range:
            if not no_raise:
                assert False, "dc bias core saturation too high, %%µi = %.0f%% (validated floor %.0f%%)" % (
                    dc_bias * 100, self.dc_bias_floor * 100)
            warnings.warn(
                '%s/%s: dc-bias permeability is outside the validated '
                '%.0f%%..100%% band; the value is returned unchecked because '
                'no_raise=True. Inductance and every flux/loss figure derived '
                'from it are extrapolated here.' % (self.mfr, self.mpn, self.dc_bias_floor * 100))

    def permeability_dc_bias(self, H, no_raise=False):
        """Effective permeability at DC bias H (A/m).

        ``no_raise=True`` suppresses the saturation check because the design
        sweeps in apps/ legitimately walk past it -- they scan turns counts to
        find one that fits and must not abort on the candidates that do not.

        It used to suppress it SILENTLY, so a caller could not tell a value
        inside the validated 25%-of-mu_i band from one taken deep in
        saturation: KDM_SendustKS_125 at H=1e5 returns 0.283*mu_r with no
        signal whatsoever, and that number then propagates into Ldc and into
        every flux and loss figure derived from it. Suppressing the ABORT is
        reasonable; suppressing the fact is not, so the out-of-range case now
        warns. The message is deliberately constant per material so Python's
        default once-per-location filter collapses a sweep's repeats instead of
        drowning it.
        """
        H_oe = H / .7958e2
        dc_bias = self.dc_bias(H_oe=H_oe)
        self._check_bias_range(dc_bias, no_raise)
        # too much DC bias inductivity drop
        return dc_bias * self.mu_r


def micrometals_core_loss_model(a, b, c, d):
    def core_loss(Bpk_tesla, f_khz):
        Bpk = Bpk_tesla * 1e4
        f = f_khz * 1e3
        denominator = a / Bpk ** 3 + b / Bpk ** 2.3 + c / Bpk ** 1.65
        return f / denominator + d * Bpk ** 2 * f ** 2

    return core_loss


def micrometals_dc_mag_model(µi, a, b, c, d, e):
    # Initial BH Curve or Initial Magnetization Curve,

    def flux_density_tesla(H_oe):
        H = H_oe
        denominator = 1 / (H + a * H ** b) + 1 / (c * H ** d) + 1 / e
        Bpk_gauss = µi / denominator
        return Bpk_gauss * 1e-4

    return flux_density_tesla


def maginc_dc_magnetization_model(a, b, c, d, e, x):
    def flux_density_tesla(H_oe):
        H = H_oe
        B_tesla = ((a + b * H + c * H ** 2) / (1 + d * H + e * H ** 2)) ** x
        return B_tesla

    return flux_density_tesla


def micrometals_dc_bias_model(a, b, c, d):
    # dc saturation, "Percent Perm vs. H"
    return lambda H_oe: 0.01 / (a + b * H_oe ** c) + d


# https://semic.cz/!old/files/pdf_www/Ljf_KDM.pdf
# https://semic.cz/!old/files/pdf_www/Ljf_KS.pdf
# https://www.semic.cz/!KATEGORIE/6K/k6_Catalogue%20Alloy%20Powder%20Core.pdf#page=18


def kdm_sendust_core_loss(Bpk_tesla, f_khz):
    """KDM's own printed Sendust core-loss law.

        P = B**2.225 * (4.584*f + 0.0238*f**1.966)      P mW/cm3, B kGauss, f kHz

    Printed inside the "Core Loss Curves (Typical)" panel of the KDM Sendust
    spec sheets, under a header naming FOUR permeabilities at once --
    "Sendust 60u, 75u, 90u, 125u". The chart's six curves are the six
    FREQUENCIES (8/10/16/25/50/100 kHz), not the permeabilities, so the law is
    written by the vendor as permeability-independent and one function serves
    every KS material here. That is why 60u and 125u share this callable rather
    than each carrying a copy: two copies can drift, and the 125u copy was
    previously a row of ``nan`` placeholders (see ``_finite_or_raise``).

    Verified against a printed value the same sheets carry INDEPENDENTLY of the
    curve panel -- the "Core Loss / 50kHz/1000Gs" row of the Electrical
    Parameters table, 350 mW/cm3 (Max.). This law returns 281 mW/cm3 there,
    i.e. a typical sitting under a max, which is the only relation those two
    numbers may have. Read at 600 dpi off
    ee/datasheets/kdm/KS184-125A_semic_Ljf_T184-S-125A_KD.pdf
    (sha256 5aa7be7a03717a95cd75b527c0cfddaf1e9f46f3a174ad2d2bf33410244e632d);
    the sheet is SCANNED, pdftotext returns one byte, so it must be rendered.
    At 150 dpi the f exponent misreads as 1.866 -- it is 1.966.

    NOT a substitute for a measurement: it is the vendor's typical curve, and
    the sheet gives no tolerance band on it.
    """
    b, k1, k2, e = KDM_SENDUST_LOSS_COEF
    return (Bpk_tesla * 10) ** b * (k1 * f_khz + k2 * f_khz ** e)


#: The four printed constants of ``kdm_sendust_core_loss``, exposed as DATA so a
#: test can lock the TRANSCRIPTION independently of the arithmetic. They are read
#: off a scanned sheet, and the failure mode is a misread digit, not a wrong
#: formula: at 150 dpi the last exponent resolves as 1.866 and is 1.966. A test
#: that only evaluates the callable cannot see that -- see
#: KDM_SENDUST_DATASHEET_LOSS_MAX for exactly how far the one printed number
#: constrains these, which is less far than it looks.
#: (B exponent, linear-f coefficient, power-f coefficient, f exponent)
KDM_SENDUST_LOSS_COEF = (2.225, 4.584, 0.0238, 1.966)

#: The one operating point where KDM prints core loss as a NUMBER rather than a
#: curve: "Core Loss / 50kHz/1000Gs -> 350 mW/cm3 (Max.)" in the Electrical
#: Parameters table, which is a different rendering of the material from the
#: curve panel the law is printed in. (f_khz, Bpk_tesla, max mW/cm3).
#:
#: MIND THE BLIND SPOT: 1000 Gs is exactly 1 kGauss, and the law's B term is
#: ``B_kGauss ** b``, so this anchor returns 1 for ANY b. It corroborates the
#: f axis and says NOTHING about the B exponent. The B axis is transcription-
#: locked only, until someone digitizes the curve panel (dsdig) and adds a
#: second anchor off a curve at B != 1 kGauss.
KDM_SENDUST_DATASHEET_LOSS_MAX = (50.0, 0.1, 350.0)

KDM_SendustKS_60 = MagneticCoreMaterialSpecs(
    'kdm', 'KS60', mu_r=60,

    core_loss_density=kdm_sendust_core_loss,
    dc_bias=lambda H_oe: 1 / (1 + 3.57e-4 * H_oe ** 1.748),
    # this is a very rough fit from looking at this chart: https://www.semic.cz/!KATEGORIE/6K/k6_Catalogue%20Alloy%20Powder%20Core.pdf#page=18
    dc_magnetization=micrometals_dc_mag_model(60, a=9E-03, b=2E+00, c=2E+09, d=0.000E-08, e=1.6E+02),
    coef_source='datasheet',
)

KDM_SendustKS_125 = MagneticCoreMaterialSpecs(
    'kdm', 'KS125', mu_r=125,

    # Was ``(Bpk*10)**nan * (nan*f + nan*f**nan)``, which made every consumer of
    # KDM_KS184_125A raise out of _finite_or_raise. The placeholders were never
    # unknown data -- the sheet's own curve panel covers 125u in the same breath
    # as 60u; nobody had filled them in.
    core_loss_density=kdm_sendust_core_loss,
    dc_bias=lambda H_oe: 1 / (1 + 1.34e-3 * H_oe ** 1.78),
    # this is a very rough fit from looking at this chart: https://www.semic.cz/!KATEGORIE/6K/k6_Catalogue%20Alloy%20Powder%20Core.pdf#page=18
    # dc_magnetization=micrometals_dc_mag_model(60, a=9E-03, b=2E+00, c=2E+09, d=0.000E-08, e=1.6E+02),
    coef_source='datasheet',
)

# https://www.mag-inc.com/Media/Magnetics/File-Library/Product%20Literature/Powder%20Core%20Literature/Magnetics-Powder-Core-Catalog-2024.pdf#page=106
MagInc_KoolMu_60 = MagneticCoreMaterialSpecs(
    'maginc', 'KoolMµ60', mu_r=60,
    core_loss_density=lambda Bpk_tesla, f_khz: 44.30 * (Bpk_tesla ** 1.988) * (f_khz ** 1.541),  # pg 65
    dc_bias=lambda H_oe: 0.01 / (0.01 + 2.142E-06 * H_oe ** 1.855),  # pg.61
    dc_magnetization=maginc_dc_magnetization_model(3.601E-02, 1.721E-02, 5.401E-04, 5.624E-02, 5.156E-04, 1.577),
)

# Magnetics Powder Core Catalog (current edition, fetched 2026-08-20 from
# https://www.mag-inc.com/Media/Magnetics/File-Library/Product%20Literature/Powder%20Core%20Literature/Magnetics-Powder-Core-Catalog.pdf
# -- the "-2024" URL used above now 404s). Printed page numbers:
#   p.63  Permeability vs DC Bias fit, "Kool Mµ MAX Toroids", 40µ: a=0.01 b=2.500E-07 c=2.000
#   p.109 Core Loss Density P = a B^b f^c (mW/cm3, T, kHz), "Kool Mµ MAX Toroids",
#         26/40/60/75/90µ: a=113.53 b=2.072 c=1.379
#   p.128 DC Magnetization fit, "Kool Mµ MAX Toroids", 40µ row.
# The bias exponent is EXACTLY 2.000 in the vendor table (MAX 60µ and 75µ too); that is
# what makes the arctan closed-form flux linkage in pa/spwm/SPICE-SIMULATION-PLAN.md valid
# for this material, and it is not true of plain Kool Mµ (c=1.704..1.855 above).
# coef_source is 'band', not 'datasheet': these are the catalog's per-material curves, not
# coefficients printed on the 0079736A7 datasheet -- that sheet only guarantees MINIMUM
# retained permeability of 80% at 85 Oe and 50% at 180 Oe (the typical fit gives 84.7%
# and 55.3%). The catalog states "Fit valid only for range shown on graph" (p.63) and the
# MAX graph (p.48) is drawn down to 30%, hence dc_bias_floor=0.30 rather than the 25%
# the plain Kool Mµ graph supports.
MagInc_KoolMuMAX_40 = MagneticCoreMaterialSpecs(
    'maginc', 'KoolMµMAX40', mu_r=40,
    core_loss_density=lambda Bpk_tesla, f_khz: 113.53 * (Bpk_tesla ** 2.072) * (f_khz ** 1.379),  # p.109
    dc_bias=lambda H_oe: 0.01 / (0.01 + 2.500E-07 * H_oe ** 2.000),  # p.63
    dc_magnetization=maginc_dc_magnetization_model(4.927E-02, 1.443E-02, 5.832E-04, 7.862E-02, 4.579E-04, 1.626),  # p.128
    coef_source='band',
    dc_bias_coef=(0.01, 2.500E-07, 2.000),
    dc_bias_floor=0.30,
)

# https://s3.amazonaws.com/micrometals-production/filer_public/db/06/db06aae2-7ebf-4690-a80c-cd90e892ac65/ms-060-datasheet.pdf
# TODO import from https://s3.amazonaws.com/micrometals-production/filer_public/a7/22/a722ffb5-f2e4-4418-a4cc-f64472001cb4/mmcurvefitcoefficientsall.xlsx
Micrometals_Sendust_60u = MagneticCoreMaterialSpecs(
    'micrometals', 'MS60u', mu_r=60,

    core_loss_density=micrometals_core_loss_model(a=7.890E+09, b=7.111E+08, c=8.980E+06, d=2.846E-14),
    dc_bias=micrometals_dc_bias_model(1.000E-02, 2.151E-06, 1.841E+00, 0.000E+00),
    dc_magnetization=micrometals_dc_mag_model(60, a=8.848E-03, b=1.991E+00, c=2.003E+09, d=1.000E-08, e=1.467E+02),
)


@mem_cache(ttl='1h')
def load_micrometals_materials():
    import pandas as pd
    df = pd.read_csv(os.path.dirname(__file__) + '/micrometals.csv')
    # df = pd.read_csv(os.path.dirname(__file__) + '/mmcurvefitcoefficientsall.csv', skiprows=8)
    # df = df.iloc[:, 1:]
    return df


@mem_cache(ttl='1h')
def load_micrometals_parts():
    """Per-PART curve-fit coefficients, keyed by full part number.

    ``micrometals.csv`` is per (material, permeability) with a coarse OD band;
    this is per orderable part, straight off each datasheet's own printed
    coefficients. It exists because the band model cannot represent every
    split: OC 125u changes coefficients at exactly T250 and the band CSV has no
    qualified row for it at all, so a T250 OC core silently used the small-size
    fit -- 25% low on core loss, 22% high on retained permeability.

    Built by parsing 804 datasheets; 761 carry a usable coefficient block.
    Every row was validated against the calibration point printed on its OWN
    datasheet (Core Loss nominal at cal_bpk_g/cal_f_khz, %Initial Perm nominal
    at cal_h_oe) and rows that disagreed by more than 2% were dropped rather
    than kept with a caveat. The calibration columns are carried here so that
    check is re-runnable as a test rather than a claim about a past run --
    see test_micrometals_per_part_coefficients. Worst residual: 0.32%.

    COVERAGE IS INCOMPLETE. 43 datasheet URLs return HTTP 403 AccessDenied (an
    S3 error document, not a PDF), unchanged on re-fetch with browser headers.
    Those part numbers ARE catalogued -- all 43 appear in the Micrometals
    catalogue -- so this is a fetch gap, not a nonexistent-part gap, and it
    falls on sizes 250-775 at mu 125-205, i.e. exactly the large cores a
    loss ranking favours. An earlier version of this docstring called them
    404s and said the parts did not exist; nothing had ever computed that, and
    it was wrong on both halves.
    """
    import pandas as pd
    return pd.read_csv(os.path.dirname(__file__) + '/micrometals_parts.csv',
                       dtype={'size': str})


def try_float(s):
    try:
        return float(s)
    except ValueError:
        return float('nan')


MicroMetalsMatLiteral = Literal['MS', 'SH', 'MP', 'HF', 'FS', 'OC', 'OD', 'OE', 'SM', 'GX']


class MaterialNotFound(Exception):
    pass


class AmbiguousMaterialSize(Exception):
    """Coefficients for this (material, shape, perm) depend on the core's OD.

    Deliberately NOT a subclass of MaterialNotFound. Sweeps wrap the lookup in
    ``except MaterialNotFound: continue`` to skip combinations that are not
    manufactured; if this inherited from it, an ambiguous size would be
    silently skipped or -- worse, before this existed -- silently resolved to
    the small-size row. Callers must widen their except clause on purpose.
    """


# "T(OD=5.22-6.00 in)" -> ('T', 5.22, 6.00). Micrometals publishes separate
# curve fits above a per-material OD threshold; the plain, unqualified row is
# the SMALL-size fit and is implicitly bounded above by the qualified range.
_PART_TYPE_OD_RE = re.compile(
    r'^(?P<shape>[A-Z.]+)\(OD=(?P<lo>[\d.]+)-(?P<hi>[\d.]+)\s*in\)$')

# The catalogue quotes the bounds rounded to 0.01 in, and real ODs sit just
# outside them: T520 is 132.54 mm = 5.2181 in against a stated range start of
# 5.22 in. A strict comparison drops T520 out of its own band and back onto the
# small-size fit -- the exact silent-flattery this function exists to stop.
_OD_BOUND_TOL_IN = 0.02


def _part_type_od_range(part_type: str):
    """(shape, od_min_m, od_max_m); an unqualified row spans (0, inf)."""
    m = _PART_TYPE_OD_RE.match(part_type.strip())
    if not m:
        return part_type.strip(), 0.0, math.inf
    lo = (float(m.group('lo')) - _OD_BOUND_TOL_IN) * 25.4e-3
    hi = (float(m.group('hi')) + _OD_BOUND_TOL_IN) * 25.4e-3
    return m.group('shape'), lo, hi


class PartNotFound(Exception):
    pass


def micrometals_part_material(part: str, dc_magnetization: Callable = None):
    """Material curves from one orderable part's OWN datasheet coefficients.

    Preferred over ``micrometals_material`` wherever the part number is known,
    because it needs no OD band reasoning at all -- the split IS the row.

    ``dc_magnetization`` is not printed as coefficients on the datasheets, so
    it is not carried here; pass it in when a caller needs it. Leaving it None
    means the returned material RAISES on use of that curve (via
    _finite_or_raise) rather than returning nan, which is the right failure:
    absent coefficients must not read as zero.
    """
    df = load_micrometals_parts()
    m = df[df['part'] == part]
    if len(m) == 0:
        raise PartNotFound(part)
    assert len(m) == 1, (part, m)
    r = m.iloc[0]
    return MagneticCoreMaterialSpecs(
        'micrometals', part, mu_r=int(r['ui']),
        core_loss_density=micrometals_core_loss_model(
            r['cl_a'], r['cl_b'], r['cl_c'], r['cl_d']),
        dc_bias=micrometals_dc_bias_model(
            r['ds_a'], r['ds_b'], r['ds_c'], r['ds_d']),
        dc_magnetization=dc_magnetization,
        coef_source='datasheet',
    )


def micrometals_material(mat: MicroMetalsMatLiteral, shape: Literal['B', 'E', 'EQ', 'PQ', 'T'], ui: int,
                         od=None):
    """Curve-fit coefficients for a Micrometals material.

    :param od: core outer diameter in METRES. Required whenever the CSV holds
        more than one row for this (mat, shape, ui) -- i.e. whenever the
        coefficients are size-dependent. See AmbiguousMaterialSize.

    ``micrometals.csv`` carries 16 rows whose PartType is size-qualified
    (``T(OD=5.22-6.00 in)`` and friends). The old exact match on
    ``PartType == 'T'`` could not reach any of them, so every caller silently
    got the SMALL-size fit no matter how big the core. That error is
    one-directional and points the wrong way: for OC 125u -- where the split is
    at exactly T250, the size a design sweep is most likely to land on -- the
    small-size row understates core loss by 25% and overstates retained
    permeability by 22%. A sweep ranking cores by loss therefore promotes
    precisely the large cores whose numbers are wrong, and nothing looks
    broken, because the unreachable rows never surfaced as an error.
    """
    df = load_micrometals_materials()
    rows = df[(df.iloc[:, 0] == mat) & (df.iloc[:, 2] == str(ui))]
    cand = []
    for i in range(len(rows)):
        row_shape, od_lo, od_hi = _part_type_od_range(str(rows.iloc[i, 1]))
        if row_shape == shape:
            cand.append((od_lo, od_hi, rows.iloc[i, :]))
    if not cand:
        raise MaterialNotFound(str((mat, shape, ui)))

    if len(cand) == 1:
        od_lo, od_hi, row = cand[0]
        # A lone row may still be size-qualified; honour its band when we were
        # told the OD, but do not invent a band for an unqualified row.
        if od is not None and not (od_lo <= od <= od_hi):
            raise MaterialNotFound(
                '%s %s %du: the only coefficient set covers OD %.1f-%.1f mm, '
                'but this core is %.1f mm' % (mat, shape, ui, od_lo * 1e3,
                                              od_hi * 1e3, od * 1e3))
    else:
        if od is None:
            raise AmbiguousMaterialSize(
                '%s %s %du has %d size-dependent coefficient sets (%s) -- pass '
                'od=<core OD in m>. Defaulting to any one of them would pick a '
                'fit for the wrong core size, and the small-size fit is the '
                'optimistic one (less loss, more retained permeability).'
                % (mat, shape, ui, len(cand),
                   ', '.join('%.1f-%.1f mm' % (lo * 1e3, hi * 1e3) for lo, hi, _ in cand)))
        # The unqualified row is the SMALL-size fit, so once a qualified band
        # exists the plain row is implicitly bounded ABOVE by where that band
        # begins. Leaving it unbounded would make it a catch-all that quietly
        # serves the small-size coefficients to a core larger than any band
        # covers -- absence of a matching band must not resolve to the
        # optimistic fit.
        qualified = [c for c in cand if math.isfinite(c[1])]
        lo_first = min(c[0] for c in qualified) if qualified else math.inf
        bands = qualified + [(lo, min(hi, lo_first), row)
                             for lo, hi, row in cand if not math.isfinite(hi)]
        # Prefer the narrowest band containing od, so a qualified row always
        # beats the small-size one at a shared boundary.
        match = [c for c in bands if c[0] <= od <= c[1]]
        if not match:
            raise MaterialNotFound(
                '%s %s %du: OD %.1f mm falls in none of the coefficient bands '
                '(%s)' % (mat, shape, ui, od * 1e3,
                          ', '.join('%.1f-%.1f mm' % (lo * 1e3, hi * 1e3) for lo, hi, _ in bands)))
        row = min(match, key=lambda c: c[1] - c[0])[2]

    m = list(map(try_float, row))

    return MagneticCoreMaterialSpecs(
        'micrometals', '%s%03u' % (mat, ui), mu_r=ui,

        core_loss_density=micrometals_core_loss_model(*m[9:13]),
        dc_bias=micrometals_dc_bias_model(*m[5:9]),
        dc_magnetization=micrometals_dc_mag_model(ui, *m[23:28]),
        coef_source='band',
    )


# https://www.micrometals.com/products/materials/ms/
# These three are the coefficients for the T184-and-below sizes -- the OD is
# stated rather than defaulted, because MS 90u and 125u are size-split at
# 5.22 in (T520) and an unqualified lookup would now refuse.
Micrometals_MS_T_060u = micrometals_material('MS', 'T', 60, od=46.74e-3)
Micrometals_MS_T_090u = micrometals_material('MS', 'T', 90, od=46.74e-3)
Micrometals_MS_T_125u = micrometals_material('MS', 'T', 125, od=46.74e-3)

# https://www.micrometals.com/products/materials/ms/
Micrometals_Sendust_125u_2 = MagneticCoreMaterialSpecs(
    'micrometals', 'MS125u', mu_r=125,

    core_loss_density=micrometals_core_loss_model(a=1.394E+10, b=1.034E+09, c=1.244E+07, d=4.007E-14),
    dc_bias=micrometals_dc_bias_model(a=1.000E-02, b=7.884E-06, c=1.883E+00, d=0.000E+00),
    dc_magnetization=micrometals_dc_mag_model(125, a=2.911E-02, b=1.834E+00, c=2.003E+09, d=1.000E-08, e=7.219E+01),
)

# assert Micrometals_Sendust_125u_2.core_loss_density == Micrometals_MS_T_125u.core_loss_density

# https://www.micrometals.com/products/materials/oe/
Micrometals_OE_60u = MagneticCoreMaterialSpecs(
    'micrometals', 'OE-060', mu_r=60,

    core_loss_density=micrometals_core_loss_model(a=1.000E+06, b=6.811E+08, c=3.796E+06, d=2.696E-14),
    dc_bias=micrometals_dc_bias_model(a=1.000E-02, b=1.076E-07, c=2.308, d=0.000),
    dc_magnetization=micrometals_dc_mag_model(60, 1.147E-02, 1.891E+00, 2.006E+04, 2.633E+00, 2.204E+02),
)

# https://www.micrometals.com/products/materials/oc/
Micrometals_OC_60u = MagneticCoreMaterialSpecs(
    'micrometals', 'OC-060', mu_r=60,

    core_loss_density=micrometals_core_loss_model(a=1.000E+06, b=6.811E+08, c=3.796E+06, d=2.696E-14),
    dc_bias=micrometals_dc_bias_model(a=1.000E-02, b=1.076E-07, c=2.308, d=0.000),
    dc_magnetization=micrometals_dc_mag_model(60, 1.147E-02, 1.891E+00, 2.006E+04, 2.633E+00, 2.204E+02),
)
