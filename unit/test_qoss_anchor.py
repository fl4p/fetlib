"""The datasheet-Qoss anchor for the scalar Coss loss model, and its physical floor.

`Coss` is a small-signal capacitance at one bias; `Qoss` is the integral quantity the loss
model actually needs. Anchoring the 1/sqrt(V) law on Coss under-books charge -- measured
across the 1420 cross-checkable corpus records, Qoss/(Coss*V) runs p25 1.87 / p50 2.35 /
p95 28.2 against the law's implicit 2.0. These tests pin the anchor, the fail-closed paths,
and the ONE guard (a physical floor, not a tuned band).
"""

import math
import warnings

import pytest

from dclib.coss_loss import CossEnergyModel, MODEL_STATE_CURVE
from dslib.mosfet import MosfetSpecs, attach_qoss_anchor


def specs(**kw):
    """MosfetSpecs with only the fields the Coss model reads."""
    base = dict(Vds_max=100, Rds_on=1e-3, Qg=255e-9, tRise=15e-9, tFall=30e-9,
                Qrr=89e-9, trr=48e-9, Qgd=62e-9, Qgs=69e-9, Qg_th=46e-9, Vsd=0.83)
    base.update(kw)
    return MosfetSpecs(**base)


def model_for(**kw):
    return CossEnergyModel.from_mosfet(specs(**kw), operating_frequency_hz=40e3)


# ---------------------------------------------------------------- the anchor itself

def test_qoss_anchor_reproduces_the_datasheet_charge_at_its_own_voltage():
    """The whole point: Q(V_q) == Qoss, exactly. The Coss anchor cannot do this."""
    m = model_for(Coss=2400e-12, Coss_Vds=50.0, Qoss=499e-9, Qoss_Vds=50.0)
    assert m.model_state == "scalar-qoss-anchored-inverse-sqrt"
    assert m.at(50.0).qoss_c == pytest.approx(499e-9, rel=1e-12)


def test_qoss_anchor_is_preferred_over_coss_and_books_more_charge():
    """IPF009N10NM8: Coss=2400 pF @ 50 V vs Qoss=499 nC @ 50 V -> r=4.16, so the Coss
    anchor under-books by 2.08x at every voltage."""
    kw = dict(Coss=2400e-12, Coss_Vds=50.0)
    coss_only = model_for(**kw)
    qoss = model_for(Qoss=499e-9, Qoss_Vds=50.0, **kw)

    assert coss_only.metadata.get("scalar_anchor_source") == "Coss_Vds"
    assert qoss.metadata.get("scalar_anchor_source") == "Qoss"
    assert coss_only.at(72.0).qoss_c == pytest.approx(288e-9, rel=1e-3)
    assert qoss.at(72.0).qoss_c == pytest.approx(599e-9, rel=1e-3)
    # Same functional form -- only the anchor moved, so the ratio is voltage-independent.
    for v in (10.0, 50.0, 72.0, 100.0):
        r = qoss.at(v).qoss_c / coss_only.at(v).qoss_c
        assert r == pytest.approx(499e-9 / (2 * 2400e-12 * 50.0), rel=1e-9)


def test_qoss_anchor_records_its_inputs_for_provenance():
    m = model_for(Coss=2400e-12, Coss_Vds=50.0, Qoss=499e-9, Qoss_Vds=50.0)
    assert m.metadata["qoss_anchor_c"] == pytest.approx(499e-9)
    assert m.metadata["qoss_anchor_v"] == pytest.approx(50.0)
    assert m.metadata["qoss_over_coss_v_ratio"] == pytest.approx(4.158, rel=1e-3)
    assert "Qoss" in m.provenance
    # Still a one-point fit to an unknown curve shape: never claims to be verified.
    assert m.evidence_quality == "UNVERIFIED"
    assert "nonlinear-curve-missing:scalar-parametric-fallback" in m.extrapolation_flags


def test_a_digitized_curve_still_outranks_the_qoss_anchor():
    """Qoss is one point; the curve is the actual C(V). Precedence must not invert."""
    m = CossEnergyModel.from_mosfet(
        specs(Coss=2400e-12, Coss_Vds=50.0, Qoss=499e-9, Qoss_Vds=50.0,
              coss_curve=[(0.0, 4000.0, 0.0), (100.0, 1000.0, 0.0)],
              coss_curve_meta=dict(provenance="synthetic", evidence_quality="PASS")),
        operating_frequency_hz=40e3)
    assert m.model_state == MODEL_STATE_CURVE
    assert m.metadata.get("scalar_anchor_source") is None


# ---------------------------------------------------------------- the physical floor

def test_qoss_below_the_physical_floor_is_refused_and_keeps_the_coss_anchor():
    """Coss(V) decreases monotonically, so Qoss(V) = int_0^V C dV >= C(V)*V. Below that is
    impossible -- a parse error -- AND it would lower the booked loss. Real corpus case:
    IPT020N10N3, Qoss=55 nC against Coss*V = 2010 pF * 50 V = 100.5 nC (r=0.547).
    """
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m = model_for(Coss=2010e-12, Coss_Vds=50.0, Qoss=55e-9, Qoss_Vds=50.0)
        msgs = [str(x.message) for x in w]

    # The RIGHT thing survived: Coss anchor, not the impossible charge.
    assert m.model_state == "scalar-inverse-sqrt-fallback"
    assert m.metadata.get("scalar_anchor_source") == "Coss_Vds"
    assert m.metadata["qoss_anchor_refused"].startswith("below-physical-floor")
    assert m.at(50.0).qoss_c == pytest.approx(2 * 2010e-12 * 50.0, rel=1e-9)
    assert any("below the physical floor" in s for s in msgs), msgs


def test_the_floor_fires_just_below_and_not_just_above_one():
    """Monotone at the boundary, tested from both sides rather than only the near-miss."""
    coss, v = 1000e-12, 50.0
    floor = coss * v                     # r == 1.0 exactly
    assert model_for(Coss=coss, Coss_Vds=v, Qoss=floor * 0.999,
                     Qoss_Vds=v).model_state == "scalar-inverse-sqrt-fallback"
    assert model_for(Coss=coss, Coss_Vds=v, Qoss=floor * 1.001,
                     Qoss_Vds=v).model_state == "scalar-qoss-anchored-inverse-sqrt"


def test_no_upper_bound_superjunction_ratios_are_accepted():
    """r=30 is real physics for a superjunction part whose Coss collapses ~100x below 50 V
    (IPQC60R010S7A: Qoss=1714 nC, Coss=188 pF @ 300 V). The distribution runs continuously
    into that tail, so a ceiling would drop legitimate anchors -- there is no void for one.
    """
    m = model_for(Coss=188e-12, Coss_Vds=300.0, Qoss=1714e-9, Qoss_Vds=300.0)
    assert m.model_state == "scalar-qoss-anchored-inverse-sqrt"
    assert m.metadata["qoss_over_coss_v_ratio"] == pytest.approx(30.39, rel=1e-3)


def test_ratio_is_monotone_in_qoss():
    """As the input gets worse (more charge), the booked energy must only ever increase."""
    e = [model_for(Coss=1000e-12, Coss_Vds=50.0, Qoss=q, Qoss_Vds=50.0).at(72.0).eoss_j
         for q in (60e-9, 100e-9, 200e-9, 500e-9, 2000e-9)]
    assert e == sorted(e)
    assert all(x > 0 for x in e)


def test_uncrosscheckable_qoss_is_accepted_but_says_so():
    """No same-voltage Coss to test against. Qoss is still the better quantity, so it is
    used -- but the report must not imply a check that never ran."""
    m = model_for(Coss=2400e-12, Coss_Vds=25.0, Qoss=499e-9, Qoss_Vds=50.0)
    assert m.model_state == "scalar-qoss-anchored-inverse-sqrt"
    assert m.metadata["qoss_anchor_crosscheck"] == "unavailable:no-same-voltage-Coss"
    assert "qoss_over_coss_v_ratio" not in m.metadata


# ---------------------------------------------------------------- fail-closed paths

@pytest.mark.parametrize("qoss,qoss_v", [
    (math.nan, 50.0),      # no charge parsed
    (None, 50.0),
    (0.0, 50.0),           # zero: this repo's corrupt-parse class AND the best loss number
    (-499e-9, 50.0),       # negative: the OCR dash-fusion class
    (499e-9, None),        # charge without the voltage it was specified at
    (499e-9, 0.0),
])
def test_unusable_qoss_falls_back_to_the_coss_anchor(qoss, qoss_v):
    m = model_for(Coss=2400e-12, Coss_Vds=50.0, Qoss=qoss, Qoss_Vds=qoss_v)
    assert m.model_state == "scalar-inverse-sqrt-fallback"
    assert m.metadata.get("scalar_anchor_source") == "Coss_Vds"


def test_absent_qoss_leaves_the_existing_behaviour_byte_for_byte():
    """The 79% of records with no Qoss must be unaffected."""
    before = model_for(Coss=2400e-12, Coss_Vds=50.0)
    assert before.model_state == "scalar-inverse-sqrt-fallback"
    assert before.at(72.0).qoss_c == pytest.approx(288e-9, rel=1e-3)
    assert "Qoss" not in before.provenance


# ---------------------------------------------------------------- the populator

class FakeField:
    def __init__(self, typ, cond):
        self.symbol, self.typ, self.max, self.min, self.cond = "Qoss", typ, math.nan, math.nan, cond
        self.unit = "nC"

    @property
    def typ_or_max_or_min(self):
        return self.typ


class FakeDs:
    def __init__(self, qoss_nc, cond, extra=()):
        fields = [FakeField(q, c) for q, c in extra]
        if qoss_nc is not None:
            fields.append(FakeField(qoss_nc, cond))
        self.fields_lists = {"Qoss": fields} if fields else {}
        self._q = qoss_nc

    def get_typ_or_max_or_min(self, sym):
        # Deliberately returns the FIRST field's value, the way DatasheetFields priority
        # does. Any implementation that reads the value from here and the condition from
        # fields_lists separately will mis-pair them -- see the pair-split test below.
        fl = self.fields_lists.get("Qoss") or []
        return fl[0].typ if fl else math.nan


def test_attach_reads_charge_and_its_vds_condition():
    s = specs(Coss=2400e-12, Coss_Vds=50.0)
    attach_qoss_anchor(s, FakeDs(499.0, {"Vds": 50.0}))
    assert s.Qoss == pytest.approx(499e-9)
    assert s.Qoss_Vds == pytest.approx(50.0)


def test_charge_and_its_voltage_come_from_the_same_field():
    """Regression, real corpus case. BSZ300N15NS5 carries a conditionless Qoss=2837 nC
    (a parse artifact) FIRST, then the real Qoss=28 nC @ 75 V. Taking the value from
    DatasheetFields priority and the voltage from a separate scan pairs 2837 nC with 75 V:
    a 101x over-book that the r>=1 physical floor cannot catch, because too-HIGH charge is
    not the direction it tests. It cost P_coss 0.05 W -> 5.34 W on that part.
    """
    s = specs(Coss=180e-12, Coss_Vds=None)
    attach_qoss_anchor(s, FakeDs(28.0, {"Vds": 75.0, "Vgs": 0.0},
                                 extra=[(2837.0, {})]))
    assert s.Qoss == pytest.approx(28e-9), "took the conditionless artifact's value"
    assert s.Qoss_Vds == pytest.approx(75.0)


def test_a_conditionless_charge_alone_is_not_an_anchor():
    s = specs(Coss=180e-12, Coss_Vds=50.0)
    attach_qoss_anchor(s, FakeDs(None, None, extra=[(2837.0, {})]))
    assert not (s.Qoss == s.Qoss)


def test_attach_applies_the_same_5v_condition_floor_as_the_coss_bucket():
    """'Vds=1' in this bucket is a mis-bucketed f=1 MHz-style artifact, 317x in the corpus.
    Without a usable voltage the charge cannot anchor anything."""
    s = specs(Coss=2400e-12, Coss_Vds=50.0)
    attach_qoss_anchor(s, FakeDs(499.0, {"Vds": 1.0}))
    assert not (s.Qoss == s.Qoss)  # NaN
    assert s.Qoss_Vds is None


def test_attach_takes_the_magnitude_for_p_channel_conditions():
    s = specs(Coss=2400e-12, Coss_Vds=50.0)
    attach_qoss_anchor(s, FakeDs(499.0, {"Vds": -50.0}))
    assert s.Qoss_Vds == pytest.approx(50.0)


def test_attach_is_fill_if_absent_and_never_overwrites():
    s = specs(Coss=2400e-12, Coss_Vds=50.0, Qoss=111e-9, Qoss_Vds=25.0)
    attach_qoss_anchor(s, FakeDs(499.0, {"Vds": 50.0}))
    assert s.Qoss == pytest.approx(111e-9)
    assert s.Qoss_Vds == pytest.approx(25.0)


def test_attach_tolerates_no_datasheet_and_no_specs():
    assert attach_qoss_anchor(None, FakeDs(499.0, {"Vds": 50.0})) is None
    s = specs(Coss=2400e-12, Coss_Vds=50.0)
    assert attach_qoss_anchor(s, None) is s
    assert not (s.Qoss == s.Qoss)
