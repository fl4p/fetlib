"""Physical-consistency checks on parsed MOSFET specs.

These REPORT, they do not assert. That distinction is the point of the module.

The pre-existing checks live in MosfetSpecs.__init__ as bare asserts, and main.py's
get_fet_specs catches the AssertionError by deleting the part from parts_db and purging
five parse_datasheet cache entries (main.py:410-417). So a check that fires does not flag a
part -- it erases it, and pays ~177 s to re-parse it on the next run before erasing it
again. That is a very expensive way to be wrong, and it WAS wrong: the FoM bound of 20000
rejected 43 records, every one of them a part whose Rds_on had just been corrected from a
1000x-low value. The corrupt reading passed; the true reading was deleted.

So: violations land in DatasheetFields.errors and flow to the CSV's `errors` column. A part
with a suspicious ratio stays visible and reviewable.

WHY THESE CHECKS -- dynamic range is the whole design criterion
    A bound is only as sensitive as the natural spread of the quantity it bounds. Measured
    over the shipped DB (p99/p1, lower is tighter):

        Qg/(Qgs+Qgd)        2.7      <- tightest available
        Vgs_th/Vsd          8.1
        Qgd/Qgs            15.3
        ID_25*Rds_on       25.2
        tRise/tFall        49.3
        FoM (the assert)  246        <- what we currently rely on
        Ciss/Coss         388
        Ciss/Crss        1475

    A unit error is a factor of 1000, so a check's headroom is roughly 1000/range. FoM at
    246 leaves a 1000x error only ~4x outside the natural band, which is exactly why it
    both missed the corruption and rejected good parts. Qg/(Qgs+Qgd) at 2.7 leaves ~370x.

    Ratios of LIKE-dimensioned quantities win twice: they are dimensionless (immune to the
    "which unit is this in" question that caused the corruption), and a unit error on
    either operand still moves them by 1000.

    Best of all are the exact structural identities, which have NO dynamic range and need
    no calibration: Ciss = Cgs+Cgd and Crss = Cgd, so Ciss > Crss with Cgs > 0. There is no
    legitimate part that fails it.

UNCHECKED IS NOT PASS
    Every check returns one of pass / fail / unchecked, and missing or NaN inputs give
    UNCHECKED. An empty violation list means "nothing among the checks that could run",
    never "this part is good" -- most records cannot run most checks. Callers wanting a
    verified-clean signal must look at n_passed, not at violations being empty.
"""
import math
from typing import Callable, List, NamedTuple, Optional

PASS = 'pass'
FAIL = 'fail'
UNCHECKED = 'unchecked'


class CheckResult(NamedTuple):
    name: str
    status: str
    message: Optional[str] = None


# --- bounds, calibrated against the shipped DB -----------------------------------------
# Qg/(Qgs+Qgd): p99=3.17, p99.9=3.93, max=6.50. At 4.5 this rejects a handful of records
# while sitting clear of p99.9. The LOWER bound is the exact identity (Qg includes both),
# so it is 1.0 exactly and is reported as its own check.
QG_SUM_RATIO_MAX = 4.5

# Qgd/Qgs: p0.5=0.192, p1=0.226, p50=0.848, p99=3.45, p99.5=4.45, max=32. The band below
# rejects 38 records (0.67%). Looser than Qg/(Qgs+Qgd) but independent of it -- this one
# compares the two components to EACH OTHER, so it still fires when Qg is absent, and it
# catches a swap or a per-symbol scale slip that leaves the sum intact.
QGD_QGS_MIN, QGD_QGS_MAX = 0.15, 5.0

# NOT IMPLEMENTED, and deliberately: FoM/Vds^k.
# The theory is sound -- the silicon limit gives Rds_on*A ~ Vbr^2.5 and Qg ~ A, so FoM
# should go as Vbr^2.5 and normalising ought to collapse the spread. Measured over 4061
# records it does not (p99/p1): unnormalised 319, /Vds 193, /Vds^1.5 218, /Vds^2 279,
# /Vds^2.5 663, /Vds^3 1816. The 2.5 exponent makes it WORSE. The relation holds at fixed
# technology and current density; across a catalogue mixing die sizes, generations and
# superjunction parts (which exist precisely to beat the limit) the area term does not
# cancel. Even the best case, /Vds at 193, is ~70x looser than Qg/(Qgs+Qgd) -- a bound that
# wide cannot separate a 1000x unit error from an ordinary part.

# ID_25 * Rds_on = the conduction drop at rated current, in mV. This is the only check that
# validates the Rds_on SCALE against an independently parsed symbol, which is what makes it
# the direct detector for the 1000x-low class. The distribution is bimodal with an EMPTY
# gap: any floor from 10 mV to 100 mV rejects the same 7 records (0.15%) and catches 99.9%
# of records were they 1000x low. 100 mV takes the top of that gap.
# (IXTX46N50L: correct 160 mOhm x 46 A = 7360 mV; the corrupt reading gave 7.4 mV.)
VDROP_MIN_MV = 100.0


def _get(ds, sym):
    """typ-or-max-or-min for `sym`, or None when absent/NaN. None means UNCHECKED."""
    f = ds.fields_filled.get(sym)
    if not f:
        return None
    try:
        v = f.typ_or_max_or_min
    except Exception:
        return None
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def _rds_milliohm(ds):
    try:
        v = ds.get_resistance_milliohm('Rds_on')
    except Exception:
        return None
    return None if (v is None or math.isnan(v)) else v


def _ordering(ds, name, hi_sym, lo_sym, why):
    hi, lo = _get(ds, hi_sym), _get(ds, lo_sym)
    if hi is None or lo is None:
        return CheckResult(name, UNCHECKED)
    if hi > lo:
        return CheckResult(name, PASS)
    return CheckResult(name, FAIL, '%s (%s=%g, %s=%g) %s' % (name, hi_sym, hi, lo_sym, lo, why))


def check_ciss_gt_crss(ds):
    """Ciss = Cgs + Cgd and Crss = Cgd, so Ciss > Crss unless Cgs <= 0. Exact."""
    return _ordering(ds, 'Ciss>Crss', 'Ciss', 'Crss', '- implies Cgs<=0')


def check_coss_gt_crss(ds):
    """Coss = Cds + Cgd and Crss = Cgd, so Coss > Crss unless Cds <= 0. Exact."""
    return _ordering(ds, 'Coss>Crss', 'Coss', 'Crss', '- implies Cds<=0')


def check_vpl_gt_vth(ds):
    """The plateau sits beyond threshold in MAGNITUDE, on the device's own polarity.

    Two traps, and they pull opposite ways:

      - A signed `Vpl > Vgs_th` is wrong for negative-gate parts. IJCQ75RM16J1 legitimately
        quotes Vpl=-6.1 V against Vgs_th=-5.3 V; signed, that reads as a violation, though
        -6.1 is further from zero exactly as it should be.
      - abs() on both would fix that and simultaneously go blind to the real error it is
        meant to see: IPA60R125 has Vpl=-7.4 with Vth=+3.5, a mixed-sign pair that cannot
        both be right, and |7.4| > |3.5| would wave it through.

    So: require the two to share a nonzero sign FIRST -- a mismatch is itself the finding --
    and only then compare magnitudes.
    """
    vpl, vth = _get(ds, 'Vpl'), _get(ds, 'Vgs_th')
    if vpl is None or vth is None or vpl == 0 or vth == 0:
        return CheckResult('Vpl>Vgs_th', UNCHECKED)
    if (vpl > 0) != (vth > 0):
        return CheckResult('Vpl>Vgs_th', FAIL,
                           'Vpl/Vgs_th sign mismatch (Vpl=%g, Vgs_th=%g)' % (vpl, vth))
    if abs(vpl) > abs(vth):
        return CheckResult('Vpl>Vgs_th', PASS)
    return CheckResult('Vpl>Vgs_th', FAIL,
                       'Vpl>Vgs_th (Vpl=%g, Vgs_th=%g) - plateau at or below threshold'
                       % (vpl, vth))


def check_qg_covers_parts(ds):
    """Total gate charge includes the gate-source and gate-drain components, so
    Qg >= Qgs + Qgd exactly. Violation means the three were read off different rows or
    scaled differently."""
    qg, qgs, qgd = _get(ds, 'Qg'), _get(ds, 'Qgs'), _get(ds, 'Qgd')
    if qg is None or qgs is None or qgd is None:
        return CheckResult('Qg>=Qgs+Qgd', UNCHECKED)
    s = qgs + qgd
    if s <= 0:
        return CheckResult('Qg>=Qgs+Qgd', UNCHECKED)
    if qg >= s:
        return CheckResult('Qg>=Qgs+Qgd', PASS)
    return CheckResult('Qg>=Qgs+Qgd', FAIL,
                       'Qg>=Qgs+Qgd (Qg=%g < Qgs+Qgd=%g)' % (qg, s))


def check_qg_ratio(ds):
    """The tightest band available (p99/p1 = 2.7). Catches a charge-unit error on any of
    the three symbols, since a 1000x move on one lands ~370x outside the band."""
    qg, qgs, qgd = _get(ds, 'Qg'), _get(ds, 'Qgs'), _get(ds, 'Qgd')
    if qg is None or qgs is None or qgd is None:
        return CheckResult('Qg/(Qgs+Qgd)', UNCHECKED)
    s = qgs + qgd
    if s <= 0:
        return CheckResult('Qg/(Qgs+Qgd)', UNCHECKED)
    r = qg / s
    if r <= QG_SUM_RATIO_MAX:
        return CheckResult('Qg/(Qgs+Qgd)', PASS)
    return CheckResult('Qg/(Qgs+Qgd)', FAIL,
                       'Qg/(Qgs+Qgd)=%.2f > %.1f' % (r, QG_SUM_RATIO_MAX))


def check_qgd_qgs_ratio(ds):
    """Miller charge against gate-source charge. Independent of check_qg_ratio: it needs no
    Qg, and it still fires when a per-symbol scale slip leaves Qgs+Qgd looking sane."""
    qgs, qgd = _get(ds, 'Qgs'), _get(ds, 'Qgd')
    if qgs is None or qgd is None or qgs <= 0:
        return CheckResult('Qgd/Qgs', UNCHECKED)
    r = qgd / qgs
    if QGD_QGS_MIN <= r <= QGD_QGS_MAX:
        return CheckResult('Qgd/Qgs', PASS)
    return CheckResult('Qgd/Qgs', FAIL,
                       'Qgd/Qgs=%.3g outside [%.2f,%.1f]' % (r, QGD_QGS_MIN, QGD_QGS_MAX))


def check_conduction_drop(ds):
    """ID_25 * Rds_on, the drop at rated current. Cross-validates the Rds_on SCALE against
    an independently parsed current, so it is the direct detector for a 1000x-low Rds_on --
    the failure that a dropped ohm unit produces."""
    i = _get(ds, 'ID_25')
    r = _rds_milliohm(ds)
    if i is None or r is None or i <= 0:
        return CheckResult('ID_25*Rds_on', UNCHECKED)
    mv = i * r
    if mv >= VDROP_MIN_MV:
        return CheckResult('ID_25*Rds_on', PASS)
    return CheckResult('ID_25*Rds_on', FAIL,
                       'ID_25*Rds_on=%.3g mV < %g (Rds_on may be 1000x low)' % (mv, VDROP_MIN_MV))


CHECKS: List[Callable] = [
    check_ciss_gt_crss,
    check_coss_gt_crss,
    check_vpl_gt_vth,
    check_qg_covers_parts,
    check_qg_ratio,
    check_qgd_qgs_ratio,
    check_conduction_drop,
]


def run_checks(ds) -> List[CheckResult]:
    """Every check, each pass/fail/unchecked. A check that raises is UNCHECKED, never PASS
    -- a validator must not report clean because it fell over."""
    out = []
    for fn in CHECKS:
        try:
            out.append(fn(ds))
        except Exception as e:
            out.append(CheckResult(getattr(fn, '__name__', '?'), UNCHECKED, 'check error: %s' % e))
    return out


def violations(ds) -> List[str]:
    """Failure messages, PLUS any check that could not evaluate itself.

    The second half is not optional. run_checks records a crashed check as UNCHECKED with a
    'check error:' message; if this filtered on FAIL alone, that message would go nowhere
    and a validator that fell over would be indistinguishable from a clean part -- the
    exact absence-of-evidence-as-absence-of-problem shape these checks exist to catch. It
    also made spec_violations' outer try/except unreachable, since run_checks had already
    swallowed the exception.

    A plain UNCHECKED (inputs simply absent) stays silent -- that is the normal case for
    most records and is not a finding. Only UNCHECKED *carrying a message* surfaces.

    NB an empty list still means "nothing failed and nothing crashed", NOT "verified" --
    see run_checks() for how many checks actually ran.
    """
    out = []
    for r in run_checks(ds):
        if r.message and r.status in (FAIL, UNCHECKED):
            out.append(r.message)
    return out
