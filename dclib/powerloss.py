"""

Literature

https://epc-co.com/epc/Portals/0/epc/documents/application-notes/AN030%20Hard%20Switching%20Losses%20Calculation.pdf

https://www.ti.com/lit/an/slyt664/slyt664.pdf
https://www.ti.com/lit/an/slua341a/slua341a.pdf
    - tf, tr approximation


DCDC design guide with losses https://www.infineon.com/dgdl/iraudps1.pdf?fileId=5546d462533600a40153569af6412c01


https://www.allaboutcircuits.com/technical-articles/introduction-to-mosfet-switching-losses/

Revers recovery loss
https://www.eetimes.com/how-fet-selection-can-optimize-synchronous-buck-converter-efficiency/


DCDC
https://www.coilcraft.com/en-us/tools/dc-dc-optimizer/#/
https://www.ti.com/tool/download/SYNC-BUCK-FET-LOSS-CALC

"""

import math
import numpy as np
import warnings
from typing import Tuple

from dslib import round_to_n, dotdict, round_to_n_dec, rel_err
from dslib.mosfet import Qgs2_Qgs_ratio_estimate, MosfetSpecs, GateDrive
from dslib.spec_models import DcDcLoadParams
from maglib.cores import MagneticCoreSpecs
from maglib.wire import d2awg, MaterialResistivity, acr_factor_micrometals, skin_depth

µ0 = 4 * math.pi * 1e-7

Qrr_temp_rise_default = 1.2


def qrr_rankable_at_operating_point(op_requested, qrr_src) -> bool:
    """May a part with this `Qrr_src` sit in a ranking built AT the operating point?

    Lives here, beside the code that produces `Qrr_src`, so the vocabulary and its
    meaning-for-ranking cannot drift apart in two files.

    ALLOWLIST, not a denylist: when an operating point was requested, a row is rankable
    only if it carries an `op-` state, i.e. one the model actually evaluated there
    (`op-1pt`, `op-1pt-parsed`, `op-2pt`, `op-zero`). Anything else -- today's
    `datasheet-flat*`, and any state a future edit to dcdc_buck_ls introduces -- is
    excluded. A new low-confidence tier must not become rankable just by not matching one
    hard-coded bad string; unrecognised has to mean unverified, not fine.
    `op-zero` (GaN) stays: zero charge is an evaluated result, not a missing one.

    `op_requested` is the CONFIG FLAG, deliberately not "did we end up with a di/dt".
    Keying on the di/dt being None conflated two different states -- flag off, and flag
    on but ls_commutation_didt() could not form an operating point because the HS gate
    charges were missing. The second then fell through to the flat charge labelled
    `datasheet-flat`, indistinguishable in the CSV from a legitimate flag-off row, and
    the filter waved it through. Measured at the fugu3 point: 75 parts hit that path and
    9 of them reached the ranking, ranked on the un-rescaled vendor charge -- a narrower
    instance of exactly the bias this filter exists to remove.

    A non-`op-` row is not merely uncertain, it is biased: it keeps the vendor's gentle
    test-point charge while every fitted row pays the real commutation charge (p50 ~6x
    larger at the fugu3 point). Ranked together, missing data reads as a good part --
    measured: 8 of the top 10 LS parts were such rows before this filter existed.
    """
    if not op_requested:
        # No operating point asked for -> `datasheet-flat` is the ANSWER, not a failure.
        # Filtering here would empty the CSV of every part.
        return True
    return bool(qrr_src) and qrr_src.startswith('op-')


class GateLoopInfeasible(ValueError):
    """The gate-loop voltages do not describe a switchable device at this gate drive.

    Raised instead of asserting because these are DATA conditions, not code invariants:
    the plateau voltage is read off a digitized gate-charge chart and the threshold is
    derived from parsed charges, so either can arrive impossible. An assert here aborts a
    6000-part run over one bad datasheet, and its only alternative -- substituting
    `fallback_V_pl` -- would invent a working part out of a reading we know is broken.

    So the part is refused, WITH the numbers that refused it, and the caller drops it from
    the ranking. Refusing is not the same as "no loss": a part that cannot be evaluated
    must never end up ranked as a cheap one.
    """

    def __init__(self, part, msg):
        self.part = part
        self.msg = msg
        super().__init__('%s: %s' % (getattr(part, 'mpn', part), msg))


Pcl_ParallelMistmatchFactor = 0.9  # HS: one switch takes most of the dynamic load, the rest stay cooler


class SwitchPowerLoss():
    def __init__(self, P_cl, P_gd, P_sw=math.nan, P_coss=math.nan, P_rr=math.nan, P_dt=math.nan, cond=None):
        """
        :param P_cl: conduction loss
        :param P_gd: gate drive loss
        :param P_sw:  switching loss
        :param P_coss: output capacitance loss
        :param P_rr:  reverse recovery loss
        :param P_dt:  dead-time loss during body diode conduction
        """
        self.P_cl = P_cl
        self.P_sw = P_sw
        self.P_coss = P_coss
        self.P_rr = P_rr
        self.P_gd = P_gd
        self.P_dt = P_dt

        self._cond = cond

    def get_cond(self, tag):
        if not self._cond:
            return {}
        cond = {}
        t = '_' + tag.split('_')[-1]
        for k, v in self._cond.items():
            if k.endswith(t):
                cond.update(v)
        return cond

    def values(self):
        d = self.__dict__.copy()
        d.pop('_cond', None)
        return d.values()

    def items(self):
        d = self.__dict__.copy()
        d.pop('_cond', None)
        return d.items()

    def parallel(self, n=2):
        """
        Compute total power loss for n parallel switches.

        For P_sw we assume that the fastest switch takes all the losses

        :return:
        """
        if n == 1:
            return self
        return SwitchPowerLoss(
            P_cl=self.P_cl / n * Pcl_ParallelMistmatchFactor,
            P_sw=self.P_sw,
            P_coss=self.P_coss * n,
            P_rr=n * self.P_rr,
            P_gd=n * self.P_gd,
            P_dt=self.P_dt,
            cond=self._cond,
        )

    def buck_hs(self):
        """
        The attributed (not dissipated) power loss when used as high-side (control) switch in buck topology.
        :return:
        """
        p = self.P_cl + self.P_coss + self.P_gd + self.P_sw
        return p

    def buck_ls(self):
        # attributed (not dissipated)
        # P_rr and P_coss is induced but not self-dissipated!
        p = self.P_cl + self.P_coss + self.P_gd + self.P_dt + self.P_rr
        # Qoss is recovered, not lost!
        return p

    def sum(self):
        return sum(v for v in self.values() if not math.isnan(v))

    def __iter__(self):
        return iter(self.values())


def mosfet_switching_trf(dc: DcDcLoadParams, mf: MosfetSpecs):
    tr = mf.tRise
    tf = mf.tFall
    if math.isnan(tr) and not math.isnan(tf):
        warnings.warn('tRise nan, assuming tFall')
        tr = tf

    elif math.isnan(tf) and not math.isnan(tr):
        warnings.warn('tFall nan, assuming 1.5*tRise')
        tf = tr * 1.5

    if math.isfinite(dc.Iripple):
        assert dc.is_ccm, 'CCM required, DCM not supported TODO'
        P_sw = 0.5 * dc.Vi * dc.f * (tr * dc.Io_min + tf * dc.Io_max)
    else:
        P_sw = 0.5 * dc.Vi * dc.Io * dc.f * (tr + tf)
    return P_sw


def Rds_on(mf: MosfetSpecs, Id, Tj):
    # TODO https://application-notes.digchip.com/070/70-41484.pdf (pg5)
    # Rds_on(Tj) = Rds_on(Tj=25°C) * (1+alpha/100)**(Tj-25°C)

    # TODO Rds_on(Id) model
    # mostly constant?

    if math.isnan(Tj):
        # this is a rough approximation from looking at various datasheets from different mfn
        # TODO temp rise?
        # if mf.part.specs.isGaN:
        return mf.Rds_on * 1.22
        # return mf.Rds_on * 1.35

    assert Tj == 25
    return mf.Rds_on


def qoss_at(mf: MosfetSpecs, V) -> float:
    """Output charge [C] stored at drain voltage V, on the same Coss(V) ~ 1/sqrt(V) model
    p_coss_eoss integrates. NaN when Coss or V is unusable — an unknown charge stays
    unknown rather than defaulting to a plausible one.

    Extracted so the Qrr decontamination (which needs Qoss at the datasheet's REVERSE
    TEST voltage VR, not at V_bus) cannot drift from the Coss model the Coss/Eoss bucket
    itself uses. Those two must agree: the whole point of subtracting a capacitive share
    from Qrr is that this bucket already books it.
    """
    if V is None or not math.isfinite(V) or V <= 0 or not math.isfinite(mf.Coss):
        return math.nan
    coss_v0 = mf.Coss_V0
    if math.isfinite(coss_v0) and coss_v0 > 0:
        return 2 * mf.Coss * (coss_v0 * V) ** .5
    return 2 * mf.Coss * V


def p_coss_eoss(dc: DcDcLoadParams, mf: MosfetSpecs) -> Tuple[float, float]:
    # for Coss the HS contribution is the energy stored in Coss
    # which is wasted in its own channel during turn-on
    # mf.Coss is Coss at ~V_bus. Coss is ~1/sqrt(V)
    # https://elprivod.nmu.org.ua/files/converters/Robert_Erikson_fundamentals-of-power-electronics-3n_2020.pdf#page=138

    coss_v0 = mf.Coss_V0

    if math.isfinite(coss_v0) and coss_v0 > 0:
        # Coss is ~1/sqrt(V)
        p_coss = 2 / 3 * mf.Coss * dc.Vi ** (3 / 2) * coss_v0 ** .5 * dc.f
    else:
        warnings.warn('%s coss v0 not available, using fallback equation' % mf.part.mpn)
        p_coss = 2 / 3 * mf.Coss * dc.Vi ** 2 * dc.f  # 2/3 comes from integration of Coss(V)

    return p_coss, qoss_at(mf, dc.Vi)


def dcdc_buck_hs(dc: DcDcLoadParams, mf: MosfetSpecs, gd: GateDrive, Tj=math.nan,
                 ls_Qoss=0, Lcsi=0,
                 use_datasheet_timings=False, isGaN=False):
    """
    computes attributed power loss of the high-side mosfet in synchronous buck converter
    attributed means the part generates loss somewhere in the converter (!= self-dissipated loss)

    :param dc:
    :param mf:
    :param gd:
    :param Tj:
    :param ls_Qoss:
    :param Lcsi:
    :param use_datasheet_timings:
    :param isGaN:
    :return:
    """
    # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/power_loss_appli-e.pdf
    # https://www.richtek.com/Design%20Support/Technical%20Document/AN009#Ripple%20Factor

    assert mf.Qg is not None, 'Qg must be set ' + mf.__repr__()
    assert math.isnan(dc.Iripple) or dc.Iripple > 0

    if gd.rg_total < mf.Rg or gd.rg_total_dis < mf.Rg:
        warnings.warn('Rg_total %.1f < MF internal Rg %.1f' % (gd.rg_total, mf.Rg))

    i_rms2 = dc.D_buck * dc.Io_mean_squared_on

    # TODO https://application-notes.digchip.com/070/70-41484.pdf

    if Lcsi > 0:
        assert ls_Qoss > 0
        assert not isGaN
        tr, tf, t_cond = mosfet_hs_sw_timings_lcsi(dc, mf, gd=gd,
                                                   ls_Qoss=ls_Qoss,
                                                   Lcsi=Lcsi,
                                                   )
    else:
        tr, tf = mosfet_hs_sw_timings_hs2(mf, gd, isGaN)
        t_cond = {}

    if use_datasheet_timings:
        tr = max(tr, mf.tRise)
        tf = max(tf, mf.tFall)

    Psw_on = 0.5 * dc.Vi * dc.Io_min * dc.f * tr
    Psw_off = 0.5 * dc.Vi * dc.Io_max * dc.f * tf

    # P_sw=mosfet_switching_trf(dc, mf),

    rds = Rds_on(mf, dc.Io, Tj)

    von = gd.Von_GaN if isGaN else gd.Von
    assert von > 0

    P_coss, qoss = p_coss_eoss(dc, mf)

    return SwitchPowerLoss(
        P_cl=i_rms2 * rds,  # conduction loss
        P_sw=(Psw_on + Psw_off),
        P_dt=0,  # body diode never conducts
        P_rr=0,  # body diode never conducts
        P_gd=(von - gd.Voff) * dc.f * mf.Qg,
        P_coss=P_coss,
        cond=dict(
            P_sw=dict(
                **t_cond,
                tr=round_to_n(tr, 2), tf=round_to_n(tf, 2),
                P_on=Psw_on,
                P_off=Psw_off),
            P_cl=dict(
                Rds=rds, I=i_rms2 ** .5,
            ),
            P_gd=dict(Qg=mf.Qg),
            P_coss=dict(Coss=mf.Coss, Qoss=qoss),
        ),
    )


def dcdc_buck_ls(dc: DcDcLoadParams, mf: MosfetSpecs, gd: GateDrive, Tj=math.nan,
                 Qrr_temp_rise=Qrr_temp_rise_default,
                 isGaN=False, qrr_didt=None, qrr_factor=1.0):
    # https://www.ti.com/lit/an/slua341a/slua341a.pdf?ts=1722843631468&ref_url=https%253A%252F%252Fwww.google.com%252F
    """
    tBDR + tBDF = 10 ns (assumption)
    P_bd = V_f * Io * fsw *  (t_BRT + t_BDF) # todo?

    :param qrr_didt: commutation di/dt [A/s] of the converter, from
        ls_commutation_didt(). None (default) keeps the historical behaviour: the flat
        datasheet Qrr, which is only valid at the datasheet's own (IF, di/dt) test
        point. When given, the charge is re-evaluated at THIS converter's operating
        point (IF = dc.Io_min, the valley current the body diode carries through the
        dead time) via the Lauritzen-Ma fit in dslib/qrr_model.py. Which path ran is
        reported in cond['P_rr']['Qrr_src'] — the two are NOT comparable numbers and a
        consumer that mixes them must be able to tell them apart.
    :param qrr_factor: fraction of the recovery charge that actually commutates through
        this switch, in [0, 1] (YAML syncFet.reverseRecoveryFactor). 1.0 = all of it, the
        default and the only value any shipped config uses. Below 1 it de-rates the
        booked charge for a design where the body diode does not carry the full
        commutation — a parallel Schottky taking part of it, or a topology that avoids
        hard commutation. It is a DESIGN de-rating applied to the charge the datasheet
        or the model produced, NOT a correction to either, so it multiplies last and is
        reported separately in cond['P_rr'].
    :return:
    """

    assert dc.tDead and not math.isnan(dc.tDead), "no dead-time specified %s" % dc.tDead
    assert mf.Qrr is not None, 'Qrr must be set ' + mf.__repr__()

    if not mf.Vsd or math.isnan(mf.Vsd):
        # warnings.warn('no Vsd specified, assuming 1 V')
        vsd = 1
    else:
        vsd = abs(mf.Vsd)

    # Base charge, then the temperature factor. The (IF, di/dt) axes and the Tj axis are
    # deliberately handled by DIFFERENT mechanisms here:
    #   * (IF, di/dt) — `qrr_didt` selects the Lauritzen-Ma operating-point charge.
    #   * Tj          — always the flat `Qrr_temp_rise` scalar, on either path.
    # qrr_model CAN extrapolate Tj (tau ~ T^N_TAU), but its own module docstring records
    # that N_TAU=1.2 is a deliberately conservative bound, ~2x steeper than the five
    # measured AO dies. Stacking that guess on top of the existing 1.2 factor would
    # double-count the temperature rise AND confound the thing this flag exists to
    # measure. So the model is evaluated at its calibration Tj (25 C, tj_extrapolated
    # False) and only the (IF, di/dt) rescale changes between the two paths.
    Qrr_base, qrr_src, qrr_detail = mf.Qrr, 'datasheet-flat', None
    if qrr_didt is not None:
        from dslib.qrr_model import LMFitError
        assert math.isfinite(qrr_didt) and qrr_didt > 0, ('qrr_didt', qrr_didt)
        # Qoss at the datasheet's REVERSE TEST voltage, so the single-point fit can be
        # calibrated on diffusion charge alone (see the Qrr_base selection below). NaN ->
        # None -> no decontamination, reported via Qrr_decont.
        vr = (getattr(mf, 'qrr_cond', None) or {}).get('VR')
        q_vr = qoss_at(mf, vr)
        try:
            qrr_detail = mf.Qrr_op(IF=dc.Io_min, didt=qrr_didt, Tj=25.0, detail=True,
                                   qoss_vr=None if math.isnan(q_vr) else q_vr)
            # detail=True is a mapping by contract; assert it rather than let a future
            # signature slip put a bare float into Qrr_base and multiply on quietly.
            assert isinstance(qrr_detail, dict), qrr_detail
            # DIFFUSION charge, not the measured-equivalent headline. The datasheet Qrr
            # integral also contains the diode's own junction displacement charge, and
            # P_coss below already books that (doubled) for this same part — booking the
            # headline here would charge the capacitive share twice. This is exactly the
            # contract qrr_model.best_lm_fit states: q0 is calibration provenance, and a
            # consumer that adds it back recreates the double-count.
            #
            # It only bites where there is evidence to remove: q0 comes from the part's
            # own two-di/dt rows (2pt) or QRR_QOSS_FRACTION*Qoss(VR) (1pt, when Coss and
            # VR are both available). With neither, q0 is 0 and this is the old number —
            # `decontaminated` says which, and it is NOT a claim of correctness, only of
            # what was subtracted.
            Qrr_base = float(qrr_detail['qrr_diffusion'])
            # Where the TEST POINT came from is part of the answer, not a footnote:
            # 'op-1pt' (hand-read from the PDF) > 'op-1pt-layout' (machine-read from the
            # table geometry) > 'op-1pt-parsed' (keyed parse). Descending evidence
            # quality, and the CSV must let a reader sort on it. Only the 1pt path has a
            # condition source; 2pt fits datasheet rows directly.
            qrr_src = 'op-' + (qrr_detail.get('method') or 'zero')
            _cs = qrr_detail.get('cond_source')
            if _cs in ('parsed', 'layout'):
                qrr_src += '-' + _cs
        except LMFitError as e:
            # No curated test conditions / an LM-inconsistent datasheet pair. Keep the
            # flat value (that is what the caller had before asking), but never let it
            # pass as an operating-point number — see the Qrr_src contract above.
            qrr_src = 'datasheet-flat-nofit'
            qrr_detail = dict(nofit_reason=str(e))

    assert 0 <= qrr_factor <= 1, ('qrr_factor', qrr_factor)
    Qrr_eff = Qrr_base * Qrr_temp_rise * qrr_factor  # Qrr temp rise 63 + ((75-25) * 0.25) ~1.2
    # TODO Qrr Id (IPT025N15NM6ATMA1)
    # TODO https://application-notes.digchip.com/070/70-41484.pdf
    # TODO Qrr(didt) https://www.mouser.com/datasheet/2/268/mscos08164_1-2275581.pdf#page=7

    rds = Rds_on(mf, dc.Io, Tj)  # temp rise Tj=100°C

    if mf.QgdQgsRatio > 1:
        warnings.warn('%s: Qgd/Qgs %.1f > 1! LS might suffer from self turn-on' % (mf.part, mf.QgdQgsRatio))

    von = gd.Von_GaN if isGaN else gd.Von
    assert von > 0

    P_coss, qoss = p_coss_eoss(dc, mf)
    # charge in Coss is recovered during discharge
    # the only loss is during turn-off through the charge "resistor"
    # P_coss = (V_bus * Qoss - Eoss) * f
    # With Coss ∝ 1/√V rescaled from datasheet coss_v0 (see HS path):
    #   Qoss = 2 * Coss * √(coss_v0 * V_bus)
    #   Eoss = (2/3) * Coss * √coss_v0 * V_bus^(3/2)
    # → P_coss = (4/3) * Coss * √coss_v0 * V_bus^(3/2) * f
    #
    # LS Coss loss = (E_supply - E_stored) × f = 2 × HS loss
    # See: Erickson, Fundamentals of Power Electronics, §4.3
    P_coss = P_coss * 2  # charge is recovered, but charging over a resistance path, so it is doubled

    return SwitchPowerLoss(
        P_cl=(1 - dc.D_buck) * dc.Io_mean_squared_on * rds,
        P_dt=vsd * (dc.Io_max + dc.Io_min) * (dc.tDead) * dc.f,  # https://www.ti.com/lit/an/slyt664/slyt664.pdf
        P_rr=dc.Vi * dc.f * Qrr_eff,  # this is dissipated in HS
        P_gd=(von - gd.Voff) * dc.f * mf.Qg,
        P_sw=0,
        P_coss=P_coss,
        cond=dict(
            R_on=dict(Rds=rds),
            P_dt=dict(Vsd=vsd, tDead=dc.tDead),
            P_rr=dict(Qrr=Qrr_eff, Qrr_ds=mf.Qrr, Qrr_src=qrr_src,
                      # A de-rated P_rr must never be mistaken for the part's own charge.
                      **(dict(qrr_factor=qrr_factor) if qrr_factor != 1.0 else {}),
                      **(dict(qrr_didt=qrr_didt, qrr_IF=dc.Io_min) if qrr_didt else {}),
                      # Qrr_q0 is the capacitive share EXCLUDED from the booked charge
                      # (0.0 when there was no evidence to exclude any); Qrr_decont says
                      # whether that exclusion rested on data or defaulted to zero.
                      **(dict(Qrr_q0=qrr_detail.get('q0'),
                              Qrr_decont=qrr_detail.get('decontaminated'),
                              Qrr_n_tau=qrr_detail.get('n_tau_state'))
                         if qrr_detail and 'q0' in qrr_detail else {}),
                      **(dict(qrr_nofit=qrr_detail['nofit_reason'])
                         if qrr_detail and 'nofit_reason' in qrr_detail else {})),
            P_gd=(dict(Qg=mf.Qg)),
            P_coss=dict(Coss=mf.Coss, Qoss=qoss),
        )
    )


P2 = Tuple[float, float]


class CoilSpecs():
    def __init__(self, Rdc, L0=None, turns=None, wire_diameter=None, wire_awg=None, wire_strands=None,
                 core: MagneticCoreSpecs = None):
        """

        :param L0: inductivity in H
        :param Rdc: ESR in Ω
        :param turns: number of turns
        """
        # TODO skin effect

        if turns is None:
            assert L0 > 0
            turns = round_to_n((L0 / core.A_L) ** .5, 3)

        l = turns ** 2 * core.A_L
        if L0 is None:
            L0 = round_to_n(l, 3)

        self.Rdc = Rdc
        self.turns = turns

        if wire_awg:
            assert wire_diameter is None
            from maglib.wire import awg2d
            wire_diameter = awg2d(wire_awg)

        self.wire_diameter = wire_diameter

        self.wire_strands = wire_strands

        self.core: MagneticCoreSpecs = core
        self.L0 = L0

        assert abs(rel_err(L0, l)) < 0.05, (L0, l)

    def Ldc(self, dc_bias_current, no_raise=False):
        tpl = (self.turns / self.core.l_e)
        Hdc = tpl * dc_bias_current
        Ldc = self.L0 * self.core.mat.permeability_dc_bias(Hdc, no_raise=no_raise) / self.core.mat.mu_r
        return Ldc

    def __repr__(self):
        return f'CoilSpecs(Rdc={round_to_n_dec(self.Rdc, 3)}, L={round_to_n_dec(self.L0, 3)}, T={self.turns}, core={(self.core)})'

    @property
    def awg(self):
        return round(d2awg(self.wire_diameter), 1)

    @property
    def bundle_diameter(self):
        # https://calculator.academy/bundle-diameter-calculator/
        return (4 * (self.wire_strands * (math.pi * self.wire_diameter ** 2 / 4)) / math.pi) ** .5

    def micrometals_analyzer(self, dc: DcDcLoadParams):
        strands = self.wire_strands or 1
        awg = self.awg
        mpn = self.core.mpn
        stack = 1
        if mpn.startswith('2s('):
            stack = 2
            mpn = mpn[3:-1]
        args = dict(
            name="",
            inductor_type="D",  # D=DC inductor
            l=50,  # ??
            iavg=round(dc.Io, 2),
            vin_rms_min=dc.Vi - dc.Vo,  # VLon = Vin - Vout (buck)
            vin_rms_max=dc.Vo,  # VLoff = Vout (buck)
            f_switching=int(round(dc.f)),
            ambient_temp=40,
            max_temp_rise=50,
            temp_rise=1,
            min_l=40,
            part_type="A",
            winding="F",
            num_cores=stack,
            wire_strands=strands,
            full_ratio=0.90,
            min_awg=30,
            pct_win_fill_max_e=100,
            energy_cost=0.2,
            continuous_use=0.5,
            conductor_material="Cu",
            n=self.turns,
            strandsxawg=f'{strands}xAWG%23{awg}',
            partnumber=mpn,
            awg=awg,
        )
        import urllib.parse
        u = "https://www.micrometals.com/design-and-applications/design-tools/inductor-analyzer/?"
        u += urllib.parse.urlencode(args)
        return u


def dcdc_buck_coil(dc: DcDcLoadParams, coil: CoilSpecs):
    """

    * Wire Loss
        * dcr wire loss
        * skin effect TODO
    * Core Loss
        * hysteresis loss (core volume) x (area of B-H hysteresis loop) ~ peak ac flux density ΔB
            ΔB = 2Bpk = B_acmax - B_acmin (https://www.mag-inc.com/design/design-guides/powder-core-loss-calculation)
        * eddy current loss (i2r losses inside core material) ~ f^2

    Well designed coils have a 80/20% distribution of Wire and Core Loss


    ref https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_converter_efficiency_app-e.pdf

    ref https://elprivod.nmu.org.ua/files/converters/Robert_Erikson_fundamentals-of-power-electronics-3n_2020.pdf#page=433
    ref https://ieeexplore.ieee.org/document/1196712
        * data sheet data from manufactureres is for sinusodial excitation
        * DC bias affects loss https://sci-hub.se/10.1109/41.649940
                                https://sci-hub.se/10.1109/APEC.1996.500481


    https://www.psma.com/sites/default/files/uploads/tech-forums-magnetics/presentations/2012-apec-134-core-loss-modeling-inductive-components-employed-power-electronic-systems.pdf

    :param dc:
    :param coil:
    :return:
    """

    assert math.isnan(dc.Iripple) or dc.Iripple > 0
    # assert abs(rel_err(dc.L, coil.L0)) < 0.05

    # require ripple current since core loss computation needs it anyways
    assert math.isfinite(dc.Iripple), "no ripple current"

    if math.isfinite(dc.Iripple):
        assert dc.Iripple < 2 * dc.Io, 'CCM required, DCM not supported TODO'
        I_ms = (dc.Io ** 2 + (dc.Iripple ** 2 / 12))  # https://www.ti.com/lit/an/slvaeq9/slvaeq9.pdf#page=5
    else:
        I_ms = dc.Io ** 2

    P_dcr = I_ms * coil.Rdc

    # acf, sd = ac_resistance_factor(MaterialResistivity.CopperAnnealed.value, coil.wire_diameter, dc.f)
    # rac = (acf - 1) * coil.Rdc

    # winding_bore() instead of core.shape.ID/OD: a core defined with only
    # l_e/A_e/Vol has shape=None, and this line then raised
    # "AttributeError: 'NoneType' object has no attribute 'ID'" from inside the
    # loss calculation -- naming neither the core nor the missing quantity.
    # Most of maglib.cores hit it, so this whole function was unreachable for
    # them. The accessor returns the datasheet bore or refuses by name.
    core_id, core_od = coil.core.winding_bore()
    F_se, F_pe = acr_factor_micrometals(MaterialResistivity.CopperAnnealed.value, coil.wire_diameter, dc.f,
                                        coil.wire_strands, coil.turns,
                                        id=core_id, od=core_od,
                                        )
    # Rac is the TOTAL ac resistance and is what gets reported; the loss below
    # charges only the EXCESS, because P_dcr already paid for the ripple's dc
    # component. I_ms is Io^2 + Iripple^2/12 and Il_ac_rms2 is (Iripple/2)^2/3
    # -- the same quantity -- so charging Il_ac_rms2 against the total counted
    # Iac^2*Rdc twice:
    #
    #   was:     Io^2*Rdc + Iac^2*Rdc  +  Iac^2*(1 + Fs + Fp)*Rdc
    #   correct: Io^2*Rdc + Iac^2*Rdc  +  Iac^2*(    Fs + Fp)*Rdc
    #                                  == Io^2*Rdc + Iac^2*Rac
    #
    # The commented-out predecessor above had (acf - 1) and was right: when
    # this moved from ac_resistance_factor (which returns a TOTAL) to
    # acr_factor_micrometals (which returns the EXCESS, see maglib/wire.py) the
    # -1 was flipped to +1 instead of being deleted. Measured by two
    # independent reviewers: +1.13% on P_acr at 8 A ripple, +2.12% at 12 A.
    Rac = (1 + F_se + F_pe) * coil.Rdc
    sd = skin_depth(MaterialResistivity.CopperAnnealed.value, dc.f)

    # notice that this is independent from duty cycle
    # https://www.mouser.com/pdfDocs/Coilcraft_inductorlosses.pdf
    P_acr = dc.Il_ac_rms2 * (F_se + F_pe) * coil.Rdc

    # https://www.quora.com/What-is-the-formula-for-calculating-peak-value-of-flux-density-of-an-inductor
    # TODO DC bias https://www.ti.com/lit/an/snva038b/snva038b.pdf?ts=1730558298197
    # B_pk = (dc.Vi - dc.Vo) * dc.ton_buck / (coil.turns * coil.core.A_e)  # peak flux density in Tesla
    # B_pk2 = coil.L * dc.Io_max / (coil.turns * coil.core.A_e)  # peak flux density in Tesla

    # https://www.eevblog.com/forum/projects/toroidal-core-for-high-power-buck-converter/msg3085987/#msg3085987
    """
    Bmax = (ueff*uo*N*Ipk)/ lc
    ueff = effective permeability
    uo = free space permeability
    N = turns
    Ipk = peak current
    lc = mean core length
    """

    # method 2
    """
    H_dc = tpl * dc.Io
    Hpp = tpl * dc.Iripple
    Bpk2 = .5 * µ0 * coil.core.mat.permeability_dc_bias(H=H_dc) * Hpp

    Bpk22 = .5 * µ0 * coil.core.mat.permeability_dc_bias(H=H_dc) * Hpp

    ur = coil.core.mat.permeability_dc_bias(H=H_dc)

    Lbias = coil.L * ur / coil.core.mat.mu_r
    Iripple_bias = dc.Iripple / (ur / coil.core.mat.mu_r)  # TODO fix model
    # ^ TODO fix mode

    # TODO confirm Iripple_bias with measurement
    Hpk_ac = coil.turns * Iripple_bias / (coil.core.l_e)  # Eq13.14 Fundamentals of Power Electronics. 2nd, p497
    # ^ hysteresis loss is modeled with p2p ac ripple

    Bpk_ac = ur * µ0 * Hpk_ac  # peak ac flux density [T]
    B_pk = ur * µ0 * Hpk_ac
    """
    from maglib.powerloss import core_loss_from_dc_bias

    # P_core1, Bpk1, cld1 = core_loss_from_dc_magnetization(dc, coil)  # method 1
    P_core1, Bpk1, cld1 = 0, 0, 0
    P_core2, Bpk2, cld2 = core_loss_from_dc_bias(dc, coil)  # method 2

    # TODO the mac-inc methods do not consider core saturation
    # L drops with rising dc bias current, which will increase ripple current and Bpk and hysteresis loss

    return dotdict(
        P_dcr=P_dcr,
        P_acr=P_acr,
        P_core=max(P_core1, P_core2),
        get_cond=lambda k: dict(
            P_dcr=dict(Rdc=coil.Rdc),
            P_acr=dict(Rac=Rac, δ=sd, Fskin=F_se, Fprox=F_pe),
            P_core=dict(
                ΔI=dc.Iripple,
                Bpk=max(Bpk1, Bpk2),  # peak ac flux density
                CLD=round_to_n_dec(max(cld1, cld2), 3) + 'mW/cm3',  # core loss density
                mthd=2 if cld2 > cld1 else 1,
            ),
        ).get(k)
    )


def dcdc_buck_caps(dc: DcDcLoadParams, Z_cin: float, Z_cout: float):
    i_ac_rms2 = dc.Il_ac_rms2

    # TODO this appears to be quite high
    i_cin_rms = dc.Io * ((dc.Vi - dc.Vo) * dc.Vo) ** .5 / dc.Vi

    # cout & cin:
    # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_converter_efficiency_app-e.pdf#page=4
    # TODO
    # - ESR = R ?
    # - ESR(f) ?
    # - main part of current is shoot-through/self-turn-on (Qoss, Qrr)??
    # TODO https://www.ti.com/lit/an/slvaeq9/slvaeq9.pdf?ts=1763058938809#page=5
    # https://www.analog.com/en/resources/app-notes/buck-power-stage-design-equations.html

    return dotdict(
        P_cin=i_cin_rms ** 2 * Z_cin,
        P_cout=i_ac_rms2 * Z_cout,
        get_cond=lambda k: dict(
            P_cin=dict(Z=round_to_n_dec(Z_cin, 2), Irms=i_cin_rms),
            P_cout=dict(Z=round_to_n_dec(Z_cout, 2), Irms=i_ac_rms2 ** .5),
        )[k],
    )


def mosfet_hs_sw_timings_hs(hs: MosfetSpecs, gd: GateDrive):
    # https://www.ti.com/lit/an/slpa009a/slpa009a.pdf#page=3  3.1.1
    assert math.isnan(hs.Qsw) or 0 < hs.Qsw < 1000e-9
    rg_total = np.nanmax([hs.Rg, gd.rg_total])
    vpl = gd.fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl
    # TODO igon1 + igon2
    assert vpl < gd.Von, "Vpl >= VGS"
    ig_on = (gd.Voff - vpl) / rg_total
    ig_off = (vpl - gd.Voff) / rg_total
    tr = hs.Qsw / ig_on
    tf = hs.Qsw / ig_off
    return tr, tf


def _hs_gate_phases(hs: MosfetSpecs, gd: GateDrive, isGaN=False):
    """Gate-loop voltages/resistances shared by the two SLVAEQ9 consumers below.

    Extracted verbatim from mosfet_hs_sw_timings_hs2 so the current-rise phase can be
    read on its own (mosfet_hs_current_rise_time) without a second, drifting copy of
    the plateau/threshold derivation.
    """
    # Qsw is a PARSED charge, so it refuses like one. It was the last bare assert on this
    # path, and MosfetSpecs.__init__ does not stand in for it: store records are pickles
    # and unpickling bypasses __init__, so a 1000x unit slip (the recurring failure mode
    # in this DB) arrives on an object no constructor ever checked. Leaving it as an
    # assert kept exactly the 6000-part abort this function was changed to stop.
    if not (math.isnan(hs.Qsw) or 0 < hs.Qsw < 1000e-9):
        raise GateLoopInfeasible(hs.part, 'Qsw=%.3g C is outside 0..1 uC -- a charge '
                                          'parse error, not a switching charge' % hs.Qsw)
    rg_total = np.nanmax([hs.Rg, gd.rg_total])
    rg_total_dis = np.nanmax([hs.Rg, gd.rg_total_dis])

    von = gd.Von_GaN if isGaN else gd.Von
    # von comes from the YAML, not from a datasheet: a bad gate drive is a config error
    # that must stop the run, not a part to skip. These two stay asserts on purpose.
    assert von > 0, (von, isGaN)
    if isGaN:
        assert von < 6
        if not (math.isnan(hs.Qsw) or hs.Qsw < 10e-9):
            raise GateLoopInfeasible(hs.part, 'Qsw=%.3g C exceeds 10 nC for a GaN part'
                                     % hs.Qsw)

    vpl = (gd.fallback_V_pl / 2 if isGaN else gd.fallback_V_pl) if math.isnan(hs.V_pl) else hs.V_pl
    vgs_th = vpl * (hs.Qg_th / hs.Qgs)
    if math.isnan(vgs_th):
        warnings.warn(f'{hs.part.mpn} vgs_th is NaN')
    elif vpl <= vgs_th:
        raise GateLoopInfeasible(hs.part, 'plateau %.2f V is not above threshold %.2f V '
                                          '(Qg_th=%.3g >= Qgs=%.3g -- a charge parse error)'
                                 % (vpl, vgs_th, hs.Qg_th, hs.Qgs))

    # Every denominator below is (von - vpl) or (v_ir - Voff), and v_ir sits between vgs_th
    # and vpl. A plateau at or above the drive rail makes the first zero or negative, i.e.
    # the gate never leaves the plateau and the device never fully enhances. Two ways to
    # get here, and they need the same answer:
    #   * the reading is garbage. `read_charts` digitizes the Qg curve and its failure mode
    #     is returning the END of the curve, which IS the drive rail -- 9 parts in the DB
    #     carry a Vpl >= the Vgs their own Qg row was measured at (62.7 V on one).
    #   * the reading is right and this design simply cannot drive this part.
    # We cannot tell which from here (MosfetSpecs carries no provenance for V_pl), and both
    # mean the same thing for the caller: there is no switching-loss number to report.
    if not (von > vpl):
        raise GateLoopInfeasible(hs.part, 'plateau %.2f V is not below the %.2f V gate '
                                          'drive%s -- no gate-loop solution'
                                 % (vpl, von, ' (GaN)' if isGaN else ''))
    v_ir = .5 * (vpl + vgs_th)  # average voltage charging Qgs2
    return dotdict(von=von, vpl=vpl, vgs_th=vgs_th, v_ir=v_ir,
                   rg_total=rg_total, rg_total_dis=rg_total_dis)


def mosfet_hs_sw_timings_hs2(hs: MosfetSpecs, gd: GateDrive, isGaN=False):
    # https://www.tij.co.jp/jp/lit/an/slvaeq9/slvaeq9.pdf#page=4
    # SLVAEQ9–July 2020
    # An Accurate Approach for Calculating the Eff. of a Synch. Buck Converter Using the MOSFET Plateau Voltage
    # equation (6) appears to be wrong.
    v = _hs_gate_phases(hs, gd, isGaN)
    tr = (hs.Qgs2 / (v.von - v.v_ir) + hs.Qgd / (v.von - v.vpl)) * v.rg_total  # (5)
    tf = (hs.Qgs2 / (v.v_ir - gd.Voff) + hs.Qgd / (v.vpl - gd.Voff)) * v.rg_total_dis  # (6) *corrected
    return tr, tf


def mosfet_hs_current_rise_time(hs: MosfetSpecs, gd: GateDrive, isGaN=False):
    """HS drain-current ramp time 0 -> I_L [s] — the FIRST of the two terms in
    mosfet_hs_sw_timings_hs2's `tr` (the Qgs2 / miller-entry phase).

    This, not the whole `tr`, is the interval over which the LS body diode commutates:
    the second term (Qgd/(Von-Vpl), the drain VOLTAGE fall) happens after the channel
    already carries the full inductor current and the diode is in reverse recovery.
    Charging the commutation to the whole `tr` understates di/dt by 1 + Qgd/Qgs2 —
    typically 2-4x on the parts in this DB, which is a large error on an axis Qrr is
    strongly (exponent ~0.8, see dslib/qrr_conditions.py) sensitive to.
    """
    v = _hs_gate_phases(hs, gd, isGaN)
    return hs.Qgs2 / (v.von - v.v_ir) * v.rg_total


def ls_commutation_didt(dc: DcDcLoadParams, hs: MosfetSpecs, gd: GateDrive, isGaN=False):
    """di/dt [A/s] the LS body diode is commutated at, set by how fast the HS turns on.

    The diode carries the valley current dc.Io_min through the dead time, and the HS
    current ramp steals it over mosfet_hs_current_rise_time.

    Returns None when the HS gate charges needed for the ramp time are missing (NaN
    Qgs2/Qg_th/Vpl) — an unknown di/dt must stay unknown, so callers fall back to the
    flat datasheet Qrr WITH provenance rather than to an invented operating point.
    """
    try:
        t_ir = mosfet_hs_current_rise_time(hs, gd, isGaN)
    except (AssertionError, GateLoopInfeasible):
        # GateLoopInfeasible is listed because _hs_gate_phases used to signal both of its
        # data refusals with `assert`. Dropping AssertionError here when they became a
        # typed exception would have turned a `return None` into an aborted run.
        return None
    if t_ir is None or not math.isfinite(t_ir) or t_ir <= 0:
        return None
    return dc.Io_min / t_ir


def mosfet_hs_sw_timings_hs_vishay(hs: MosfetSpecs, gd: GateDrive):
    # https://www.vishay.com/docs/73217/an608a.pdf
    # Cgd(Vds)
    # needs Ciss(at dc.Vi)

    assert math.isnan(hs.Qsw) or 0 < hs.Qsw < 1000e-9
    rg_total = np.nanmax([hs.Rg, gd.rg_total])
    vpl = gd.fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl
    vgs_th = vpl * (hs.Qg_th / hs.Qgs)
    v_ir = .5 * (vpl + vgs_th)  # average voltage charging Qgs2
    tr = (hs.Qgs2 / (gd.Von - v_ir) + hs.Qgd / (gd.Von - vpl)) * rg_total  # (5)
    tf = (hs.Qgs2 / (v_ir - gd.Voff) + hs.Qgd / (vpl - gd.Voff)) * rg_total  # (6) *corrected
    return tr, tf


def mosfet_hs_sw_timings_lcsi(dc: DcDcLoadParams, hs: MosfetSpecs, ls_Qoss, gd: GateDrive, Lcsi: float,
                              fallback_V_pl=math.nan):
    # loss with L_csi considerations
    # https://www.ti.com/lit/an/slpa009a/slpa009a.pdf
    Qgs2 = hs.Qgs2
    rg_total = np.nanmax([hs.Rg, gd.rg_total])
    vpl = fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl

    # pw on
    ig1_on = (gd.Von - vpl) / (rg_total + (Lcsi * dc.Io_min / Qgs2))
    a = (Lcsi * ls_Qoss / hs.Qgd ** 2) if Lcsi else 0
    b = rg_total
    c = -(gd.Von - vpl)
    ig2_on = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    tr = (Qgs2 / ig1_on + hs.Qgd / ig2_on)

    # pw off
    ig1_off = (vpl - gd.Voff) / (rg_total + Lcsi * dc.Io_max / Qgs2)
    c = - (vpl - gd.Voff)
    ig2_off = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    tf = (Qgs2 / ig1_off + hs.Qgd / ig2_off)

    return tr, tf, dict(Lcsi=Lcsi, Qoss_ls=ls_Qoss, Qsw=Qgs2 + hs.Qgd, Vpl=vpl)


def capacitor_out():
    # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_converter_efficiency_app-e.pdf
    raise NotImplemented("see dcdc_buck_cout()")


def tests():
    dcdc = DcDcLoadParams(24, 12, 40_000, 500e-9, 10, iripple=1e-9)
    gd = GateDrive(1e-6, 12, Von=12, fallback_V_pl=4)
    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9, Qsw=2e-9,
                     Qgs=2e-9, Qgs2=2e-9 * Qgs2_Qgs_ratio_estimate, Coss=0)

    loss = dcdc_buck_hs(dcdc, mf, gd=gd, Tj=25)
    assert loss.P_cl == (10 ** 2) * 10e-3 * .5
    assert rel_err(loss.P_sw, 24 * 10 * 40e3 * 40e-9) < 1e-3
    assert loss.P_gd == (12 * 40e3 * 100e-9)
    assert math.isnan(loss.P_dt) or loss.P_dt == 0
    assert loss.buck_hs() == loss.P_cl + loss.P_sw + loss.P_gd + loss.P_coss

    loss = dcdc_buck_ls(dcdc, mf, gd, Tj=25, Qrr_temp_rise=1)
    assert loss.P_cl == (10 ** 2) * 10e-3 * .5
    assert loss.P_dt == 1 * 10 * (500e-9 * 2) * 40e3
    assert loss.P_rr == 24 * 40e3 * 120e-9
    assert loss.P_gd == (12 * 40e3 * 100e-9)
    assert math.isnan(loss.P_sw) or loss.P_sw == 0
    assert loss.buck_ls() == loss.P_rr + loss.P_cl + loss.P_gd + loss.P_dt

    dcdc = DcDcLoadParams(vi=62, vo=27, pin=800, f=40e3, ripple_factor=0.3, tDead=500e-9)
    mf = MosfetSpecs.from_mpn('DMT10H9M9SCT', 'diodes')
    # l = mosfet_hs_sw_timings_hs(mf, GateDrive(6, 12, fallback_V_pl=4.5))
    # pr = 0.5 * dcdc.Vi * dcdc.Io_min * dcdc.f * l[0]
    # pf = 0.5 * dcdc.Vi * dcdc.Io_max * dcdc.f * l[1]
    # assert abs(pr - 0.3) < 0.1
    # assert abs(pf - 0.7) < 0.1

    l2 = mosfet_hs_sw_timings_hs2(mf, GateDrive(6, 12, fallback_V_pl=4.5))
    assert l2

    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9,
                     Qgd=80e-9,
                     Qgs=2e-9,
                     Qgs2=1e-9,
                     Coss=0)
    l1 = mosfet_hs_sw_timings_hs(mf, GateDrive(5, fallback_V_pl=4))

    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9,
                     Qgd=80e-9,
                     Qgs=4e-9,  # timings are independent of Qgs
                     Qgs2=1e-9,
                     Coss=0)
    l2 = mosfet_hs_sw_timings_hs(mf, GateDrive(5, fallback_V_pl=4))

    assert l1 == l2

    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9,
                     Qgd=80e-9,
                     Qgs=2e-9,
                     Qgs2=1e-9,
                     Coss=0)
    assert mf.Qg_th == 1e-9

    tr, tf = mosfet_hs_sw_timings_hs2(mf, GateDrive(5, 10, fallback_V_pl=4))
    tr_ref = (mf.Qgs2 / (10 - .5 * (4 + 2)) + mf.Qgd / (10 - 4)) * 5
    assert abs(rel_err(tr, tr_ref)) < 1e-5
    assert tf == (mf.Qgs2 / (.5 * (4 + 2)) + mf.Qgd / (4)) * 5

    tr1, tf1 = mosfet_hs_sw_timings_hs(mf, GateDrive(5, fallback_V_pl=4))
    assert abs(rel_err(tr, tr1)) < 1e-2
    assert abs(rel_err(tf, tf1)) < 1e-2


def tests_lcsi():
    dcdc = DcDcLoadParams(70, 35, 40_000, 10, 500e-9, 33, ripple_factor=0.01)
    hs = MosfetSpecs.from_mpn('CSD19503KCS', mfr='ti')
    # ls = MosfetSpecs.from_mpn('CSD19503KCS', mfr='ti')
    hs.Qg_th = 6.1e-9
    hs.Qgs = 9.8e-9
    hs.Qoss = 71e-9
    hs.Qgd = 5.4e-9
    hs._Vpl = 4.2
    hs._Qgs2 = math.nan

    """
        hs.Qg_th = 24
    hs.Qgs = 37
    hs.Qoss = 335
    hs.Qgd =17
    """

    tr, tf = mosfet_hs_sw_timings_hs(hs, gd=GateDrive(6))
    assert abs(tr) < abs(tf)
    assert 0.6 < (tr / tf) < 0.9

    ls = hs
    tr_lcsi0, tf_lcsi0, _ = mosfet_hs_sw_timings_lcsi(dcdc, hs, ls, gd=GateDrive(6), Lcsi=.01e-9)
    assert abs(tr - tr_lcsi0) / tr < 0.05
    assert abs(tf - tf_lcsi0) / tf < 0.05

    tr_lcsi2, tf_lcsi2, _ = mosfet_hs_sw_timings_lcsi(dcdc, hs, ls, gd=GateDrive(6), Lcsi=2e-9)
    assert tr_lcsi2 < tf_lcsi2
    assert tr_lcsi2 > tr_lcsi0
    assert tf_lcsi2 > tf_lcsi0


def plot_vpl_curve():
    dcdc = DcDcLoadParams(70, 35, 40_000, 10, 500e-9, 33, ripple_factor=0.01)
    hs = MosfetSpecs.from_mpn('CSD19503KCS', mfr='ti')
    hs.Qg_th = 6.1
    hs.Qgs = 9.8
    hs.Qoss = 71
    hs.Qgd = 5.4
    hs._Vpl = 4.2
    hs._Qgs2 = math.nan

    """
        hs.Qg_th = 24
    hs.Qgs = 37
    hs.Qoss = 335
    hs.Qgd =17
    """

    # Pon, Poff = mosfet_hs_sw_timings_hs(dcdc, hs, rg_total=6)


if __name__ == '__main__':
    tests()
    tests_lcsi()
