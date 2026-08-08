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

    Not hypothetical. ``KDM_SendustKS_125`` is written with literal ``nan``
    exponents (see below) and backs ``KDM_KS184_125A`` in ``maglib/cores.py``.
    The same path is reachable for any Micrometals material whose CSV cell
    fails to parse, because ``try_float`` turns a ValueError into nan and feeds
    it straight into the coefficient tuple.
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
                 ):
        self.mfr = mfr
        self.mpn = mpn
        self.mu_r = mu_r
        assert isinstance(mu_r, int) and 10 <= mu_r <= 6000
        self.core_loss_density = _finite_or_raise(
            core_loss_density, mfr, mpn, 'core_loss_density')
        self.dc_bias = _finite_or_raise(dc_bias, mfr, mpn, 'dc_bias')
        self.dc_magnetization = _finite_or_raise(
            dc_magnetization, mfr, mpn, 'dc_magnetization')

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
        in_range = 0.25 <= dc_bias <= 1
        if not in_range:
            if not no_raise:
                assert False, "dc bias core saturation too high, %%µi = %.0f%%" % (dc_bias * 100)
            warnings.warn(
                '%s/%s: dc-bias permeability is outside the validated '
                '25%%..100%% band; the value is returned unchecked because '
                'no_raise=True. Inductance and every flux/loss figure derived '
                'from it are extrapolated here.' % (self.mfr, self.mpn))
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
KDM_SendustKS_60 = MagneticCoreMaterialSpecs(
    'kdm', 'KS60', mu_r=60,

    core_loss_density=lambda Bpk_tesla, f_khz: (Bpk_tesla * 10) ** 2.225 * (4.584 * f_khz + 0.0238 * f_khz ** 1.966),
    dc_bias=lambda H_oe: 1 / (1 + 3.57e-4 * H_oe ** 1.748),
    # this is a very rough fit from looking at this chart: https://www.semic.cz/!KATEGORIE/6K/k6_Catalogue%20Alloy%20Powder%20Core.pdf#page=18
    dc_magnetization=micrometals_dc_mag_model(60, a=9E-03, b=2E+00, c=2E+09, d=0.000E-08, e=1.6E+02),
)

KDM_SendustKS_125 = MagneticCoreMaterialSpecs(
    'kdm', 'KS125', mu_r=125,

    core_loss_density=lambda Bpk_tesla, f_khz: (Bpk_tesla * 10) ** nan * (nan * f_khz + nan * f_khz ** nan),
    dc_bias=lambda H_oe: 1 / (1 + 1.34e-3 * H_oe ** 1.78),
    # this is a very rough fit from looking at this chart: https://www.semic.cz/!KATEGORIE/6K/k6_Catalogue%20Alloy%20Powder%20Core.pdf#page=18
    # dc_magnetization=micrometals_dc_mag_model(60, a=9E-03, b=2E+00, c=2E+09, d=0.000E-08, e=1.6E+02),
)

# https://www.mag-inc.com/Media/Magnetics/File-Library/Product%20Literature/Powder%20Core%20Literature/Magnetics-Powder-Core-Catalog-2024.pdf#page=106
MagInc_KoolMu_60 = MagneticCoreMaterialSpecs(
    'maginc', 'KoolMµ60', mu_r=60,
    core_loss_density=lambda Bpk_tesla, f_khz: 44.30 * (Bpk_tesla ** 1.988) * (f_khz ** 1.541),  # pg 65
    dc_bias=lambda H_oe: 0.01 / (0.01 + 2.142E-06 * H_oe ** 1.855),  # pg.61
    dc_magnetization=maginc_dc_magnetization_model(3.601E-02, 1.721E-02, 5.401E-04, 5.624E-02, 5.156E-04, 1.577),
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


def try_float(s):
    try:
        return float(s)
    except ValueError:
        return float('nan')


MicroMetalsMatLiteral = Literal['MS', 'OE', 'OC', 'GX', 'SM', 'MP']


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
