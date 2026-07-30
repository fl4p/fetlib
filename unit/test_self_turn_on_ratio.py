"""The LS self-turn-on ratios, and the estimate/measurement distinction between them.

Qgd/Qgs (QgdQgsRatio) divides the Miller charge by the charge to the PLATEAU. The
shoot-through criterion is actually stated against the charge to THRESHOLD, Qgs1 = Qg_th
(QgdQgsThRatio). Qgs > Qg_th always, so the first ratio always reads friendlier -- a part
can pass `Qgd/Qgs < 1` and still be well above 1 on the real criterion.

Qg_th is on only 16.2% of records; otherwise MosfetSpecs.__init__ derives it from
Qgs2_Qgs_ratio_estimate, making the derived ratio a FIXED multiple of the other one and no
new information. These tests pin that the two cases stay distinguishable, because a run
that cannot tell them apart reports a guess as a measurement.
"""

import math
import warnings

import pytest

from dclib.powerloss import dcdc_buck_ls
from dslib.mosfet import GateDrive, MosfetSpecs, Qgs2_Qgs_ratio_estimate
from dslib.spec_models import DcDcLoadParams


def specs(**kw):
    base = dict(Vds_max=100, Rds_on=1e-3, Qg=255e-9, tRise=15e-9, tFall=30e-9,
                Qrr=89e-9, trr=48e-9, Qgd=62e-9, Qgs=69e-9, Qg_th=46e-9, Vsd=0.83)
    base.update(kw)
    return MosfetSpecs(**base)


# ---------------------------------------------------------------- measured Qg_th

def test_datasheet_qg_th_gives_the_exact_ratio_and_is_not_an_estimate():
    """IPF009N10NM8, read off the PDF: Qgd=62 nC, Qgs=69 nC, Qg_th=46 nC."""
    s = specs()
    assert s.QgdQgsRatio == pytest.approx(62 / 69, rel=1e-9)
    assert s.QgdQgsThRatio == pytest.approx(62 / 46, rel=1e-9)
    assert s.QgdQgsThIsEstimate is False


def test_the_threshold_basis_is_always_the_stricter_of_the_two():
    """Qgs = Qg_th + Qgs2 with Qgs2 > 0, so Qgd/Qg_th >= Qgd/Qgs, always. A part passing
    the plateau-basis test can fail the threshold-basis one -- which is the whole reason
    the second column exists."""
    for qgd, qgs, qg_th in ((62e-9, 69e-9, 46e-9), (26e-9, 29e-9, 19e-9),
                            (30e-9, 33e-9, 22e-9), (10e-9, 90e-9, 40e-9)):
        s = specs(Qgd=qgd, Qgs=qgs, Qg_th=qg_th)
        assert s.QgdQgsThRatio >= s.QgdQgsRatio

    # The case that motivated the column: passes on Qgs, fails on Qgs1.
    s = specs()
    assert s.QgdQgsRatio < 1 < s.QgdQgsThRatio


# ---------------------------------------------------------------- estimated Qg_th

def test_estimated_qg_th_is_flagged_and_is_a_fixed_multiple_of_the_other_ratio():
    """Without Qg_th, __init__ sets Qg_th = Qgs*(1 - Qgs2_Qgs_ratio_estimate). The derived
    ratio is then exactly QgdQgsRatio / (1 - ratio_estimate) for EVERY part, i.e. it
    carries no information the first column did not already have. It must not be
    presentable as a measurement.
    """
    s = specs(Qg_th=None, Qgs2=None, Qsw=None)
    assert s.QgdQgsThIsEstimate is True
    expected = (62 / 69) / (1 - Qgs2_Qgs_ratio_estimate)
    assert s.QgdQgsThRatio == pytest.approx(expected, rel=1e-9)
    # 2.22x at the shipped 0.55 -- pinned so a change to the constant is visible here.
    assert s.QgdQgsThRatio / s.QgdQgsRatio == pytest.approx(2.2222, rel=1e-3)


def test_qgs2_derived_qg_th_counts_as_measured_not_estimated():
    """Qg_th = Qgs - Qgs2 is arithmetic on two datasheet numbers, not the 0.55 guess."""
    s = specs(Qg_th=None, Qgs2=23e-9)
    assert s.Qg_th == pytest.approx(69e-9 - 23e-9)
    assert s.QgdQgsThIsEstimate is False


# ---------------------------------------------------------------- unevaluatable

def test_missing_qgd_makes_the_ratio_unavailable_not_fine():
    """`ratio > 1` is False for NaN, so an unevaluatable ratio must be reported as its own
    state and never collapse into the passing branch."""
    s = specs(Qgd=math.nan)
    assert s.QgdQgsThIsEstimate is None
    assert not isinstance(s.QgdQgsThIsEstimate, bool)
    assert math.isnan(s.QgdQgsThRatio)
    assert math.isnan(s.QgdQgsRatio)
    # The anti-monotone shape this guards against, stated as an assertion.
    assert not (s.QgdQgsRatio > 1)
    assert not (s.QgdQgsRatio <= 1)


# ---------------------------------------------------------------- the model's warning

DCDC = DcDcLoadParams(72, 27, 40e3, tDead=100e-9, io=33, ripple_factor=0.33)
GD = GateDrive(rg_total=6.0, rg_total_dis=3.0, Von=11.0, Voff=0, fallback_V_pl=4.5,
               tDead=100e-9)


def turn_on_warnings(mf):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        dcdc_buck_ls(DCDC, mf, gd=GD, isGaN=False)
        return [str(x.message) for x in w if "turn-on" in str(x.message)]


def test_unevaluatable_ratio_warns_unverified():
    """The hole this closes: `if mf.QgdQgsRatio > 1` alone is False for NaN, so a part with
    no gate-charge data passed the screen silently -- 190 of 3081 ranked parts at the fugu2
    point. Absence of evidence must not read as absence of the problem."""
    msgs = turn_on_warnings(specs(Qgd=math.nan))
    assert len(msgs) == 1, msgs
    assert "UNVERIFIED" in msgs[0]
    assert "not screened either way" in msgs[0]


def test_a_ratio_above_one_is_reported_by_the_csv_count_not_a_per_part_warning():
    """Qgd/Qgs > 1 applies to ~26% of the corpus and is a gate-driver constraint, so it is
    counted once next to the CSV path (main.generate_LS_power_loss_csv) rather than warned
    per part. Only the UNVERIFIED case warns here -- asserted so a future edit cannot
    reintroduce 798 lines of noise without this failing.
    """
    assert turn_on_warnings(specs(Qgd=69e-9 * 1.6)) == []
    assert turn_on_warnings(specs()) == []


def test_a_finite_ratio_never_produces_the_unverified_warning():
    """Direction, not just firing: the UNVERIFIED branch must not fire for good data."""
    for qgd in (10e-9, 34.5e-9, 62e-9, 110e-9):
        assert turn_on_warnings(specs(Qgd=qgd)) == []


# ---------------------------------------------------------------- the web column

def test_web_backend_serves_the_ratio_only_when_qg_th_was_measured():
    """The API column is numeric with no room for a provenance tag, and an estimated value
    is exactly QgdQgs_ratio/(1-0.55) -- a rescale of the column beside it. Serving it would
    present a guess as a measurement for 84% of records while adding no information, so the
    contract is: measured -> number, estimated or unavailable -> None.
    """
    app = pytest.importorskip("web.backend.app")

    def served(sp):
        est = app._safe_attr(sp, "QgdQgsThIsEstimate")
        return (app._clean(app._safe_attr(sp, "QgdQgsThRatio"))
                if est is False else None)

    assert served(specs()) == pytest.approx(62 / 46, rel=1e-9)          # measured
    assert served(specs(Qg_th=None, Qgs2=None, Qsw=None)) is None       # estimated
    assert served(specs(Qgd=math.nan)) is None                          # unevaluatable
    assert served(object()) is None                                     # not a spec at all

    assert "QgdQgsth_ratio" in app.NUMERIC_COLUMNS
    assert "QgdQgsth_ratio" in app.SLIDER_COLUMNS
    # Left out of similarity scoring on purpose: it is null for most parts, and adding a
    # weight would silently move the existing "similar parts" ranking.
    assert "QgdQgsth_ratio" not in app.SIMILARITY_WEIGHTS
