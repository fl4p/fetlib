"""

Literature

https://www.ti.com/lit/an/slyt664/slyt664.pdf?ts=1722820278050
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
import warnings
from typing import Tuple

from dslib import round_to_n, dotdict, round_to_n_dec
from dslib.magnetics.cores import MagneticCoreSpecs
from dslib.spec_models import DcDcSpecs, MosfetSpecs, rel_err, Qgs2_Qgs_ratio_estimate

µ0 = 4 * math.pi * 1e-7


class SwitchPowerLoss():
    def __init__(self, P_cl, P_gd, P_sw=math.nan, P_coss=math.nan, P_rr=math.nan, P_dt=math.nan, cond=None):
        """
        :param P_on: conduction loss
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
        return SwitchPowerLoss(
            P_cl=self.P_cl / n * 0.9,  # one switch takes most of the dynamic load, the rest stay cooler
            P_sw=self.P_sw,
            P_coss=self.P_coss * n,
            P_rr=n * self.P_rr,
            P_gd=n * self.P_gd,
            P_dt=self.P_dt,  # Vsd body diode voltage drop
            cond=self._cond,
            # P_coss=n * self.P_coss,
        )

    def buck_hs(self):
        p = self.P_sw + self.P_cl + self.P_gd + self.P_coss
        return p

    def buck_ls(self):
        # P_rr is induced but not self loss !
        p = self.P_rr + self.P_cl + self.P_gd + self.P_dt
        # Qoss is recovered, not lost!
        return p

    def sum(self):
        return sum(v for v in self.values() if not math.isnan(v))

    def __iter__(self):
        return iter(self.values())


def mosfet_switching_trf(dc: DcDcSpecs, mf: MosfetSpecs):
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


def dcdc_buck_hs(dc: DcDcSpecs, mf: MosfetSpecs, rg_total, fallback_V_pl=math.nan, ls_Qoss=0, Lcsi=0,
                 use_datasheet_timings=True, Rds_temp_rise=1.35):
    # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/power_loss_appli-e.pdf
    # https://www.richtek.com/Design%20Support/Technical%20Document/AN009#Ripple%20Factor

    assert mf.Qg is not None, 'Qg must be set ' + mf.__repr__()
    assert mf.Qrr is not None, 'Qrr must be set ' + mf.__repr__()
    assert math.isnan(dc.Iripple) or dc.Iripple > 0

    if rg_total < mf.Rg:
        warnings.warn('Rg_total %.1f < MF internal Rg %.1f' % (rg_total, mf.Rg))

    i_rms2 = dc.D_buck * dc.Io_mean_squared_on

    # TODO https://application-notes.digchip.com/070/70-41484.pdf

    if Lcsi > 0:
        assert ls_Qoss > 0
        tr, tf, t_cond = mosfet_hs_sw_timings_lcsi(dc, mf, rg_total=rg_total, ls_Qoss=ls_Qoss,
                                                   Lcsi=Lcsi,
                                                   fallback_V_pl=fallback_V_pl)
    else:
        tr, tf = mosfet_hs_sw_timings_hs2(dc, mf, rg_total=rg_total, fallback_V_pl=fallback_V_pl)
        t_cond = {}

    if use_datasheet_timings:
        tr = max(tr, mf.tRise)
        tf = max(tf, mf.tFall)

    Psw_on = 0.5 * dc.Vi * dc.Io_min * dc.f * tr
    Psw_off = 0.5 * dc.Vi * dc.Io_max * dc.f * tf

    # P_sw=mosfet_switching_trf(dc, mf),

    rds = mf.Rds_on * Rds_temp_rise

    return SwitchPowerLoss(
        P_cl=i_rms2 * rds,  # conduction loss
        P_sw=(Psw_on + Psw_off),
        P_dt=0,  # body diode never conducts
        P_rr=0,  # body diode never conducts
        P_gd=dc.Vgs * dc.f * 2 * mf.Qg,
        P_coss=2 / 3 * mf.Coss * dc.Vi ** 2 * dc.f,
        # TODO  ^ compute Coss at given dc.Vi, for 80V fets, this is given at 40V, Coss is ~1/sqrt(V)
        # 2/3 comes from integration of Coss(V)
        # https://elprivod.nmu.org.ua/files/converters/Robert_Erikson_fundamentals-of-power-electronics-3n_2020.pdf#page=138
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
            P_coss=dict(Coss=mf.Coss),
        ),
    )


def dcdc_buck_ls(dc: DcDcSpecs, mf: MosfetSpecs, rds_temp_rise=1.35, Qrr_temp_rise=1.2):
    # https://www.ti.com/lit/an/slua341a/slua341a.pdf?ts=1722843631468&ref_url=https%253A%252F%252Fwww.google.com%252F
    """
    tBDR + tBDF = 10 ns (assumption)
    P_bd = V_f * Io * fsw *  (t_BRT + t_BDF) # todo?
    :return:
    """

    assert dc.tDead and not math.isnan(dc.tDead), "no dead-time specified %s" % dc.tDead

    if not mf.Vsd or math.isnan(mf.Vsd):
        # warnings.warn('no Vsd specified, assuming 1 V')
        vsd = 1
    else:
        vsd = abs(mf.Vsd)

    Qrr_eff = mf.Qrr * Qrr_temp_rise  # Qrr temp rise 63 + ((75-25) * 0.25) ~1.2
    # TODO Qrr di/dit, Id, (IPT025N15NM6ATMA1)
    # TODO https://application-notes.digchip.com/070/70-41484.pdf
    # TODO Qrr(didt) https://www.mouser.com/datasheet/2/268/mscos08164_1-2275581.pdf#page=7

    rds = mf.Rds_on * rds_temp_rise  # temp rise Tj=100°C

    if mf.QgdQgsRatio > 1:
        warnings.warn('Qgd/Qgs %.1f > 1! LS might suffer from self turn-on' % mf.QgdQgsRatio)

    return SwitchPowerLoss(
        P_cl=(1 - dc.D_buck) * dc.Io_mean_squared_on * rds,
        P_dt=vsd * dc.Io * (dc.tDead * 2) * dc.f,  # TODO https://www.ti.com/lit/an/slyt664/slyt664.pdf
        P_rr=dc.Vi * dc.f * Qrr_eff,  # this is dissipated in HS
        P_gd=dc.Vgs * dc.f * 2 * mf.Qg,
        P_sw=0,  # negligible
        P_coss=0,  # negligible (charge is recovered)
        cond=dict(
            R_on=dict(Rds=rds),
            P_dt=dict(Vsd=vsd, tDead=dc.tDead),
            P_rr=dict(Qrr=Qrr_eff),
            P_gd=(dict(Qg=mf.Qg)),
        )
        # P_coss=.5 * dc.f * dc.Vi ** 2 * mf.Coss,
    )


P2 = Tuple[float, float]


class CoilSpecs():
    def __init__(self, Rdc, L=None, turns=None, core: MagneticCoreSpecs = None):
        """

        :param L: inductivity in H
        :param Rdc: ESR in Ω
        :param turns: number of turns
        """
        # TODO skin effect

        if turns is None:
            assert L > 0
            turns = round_to_n((L / core.A_L) ** .5, 3)

        l = turns ** 2 * core.A_L
        if L is None:
            L = round_to_n(l, 3)

        self.Rdc = Rdc
        self.turns = turns

        self.core: MagneticCoreSpecs = core
        self.L = L

        assert abs(rel_err(L, l)) < 0.05

    def __repr__(self):
        return f'CoilSpecs(Rdc={round_to_n_dec(self.Rdc, 3)}, L={round_to_n_dec(self.L, 3)}, T={self.turns}, core={(self.core)})'


def dcdc_buck_coil(dc: DcDcSpecs, coil: CoilSpecs):
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
    assert abs(rel_err(dc.L, coil.L)) < 0.05

    # require ripple current since core loss computation needs it anyways
    assert math.isfinite(dc.Iripple), "no ripple current"

    if math.isfinite(dc.Iripple):
        assert dc.Iripple < 2 * dc.Io, 'CCM required, DCM not supported TODO'
        P_dcr = (dc.Io ** 2 + (dc.Iripple ** 2 / 12)) * coil.Rdc  # https://www.ti.com/lit/an/slvaeq9/slvaeq9.pdf#page=5
    else:
        P_dcr = dc.Io ** 2 * coil.Rdc

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
    from dslib.magnetics.powerloss import core_loss_from_dc_bias, core_loss_from_dc_magnetization

    P_core1, Bpk1, cld1 = core_loss_from_dc_magnetization(dc, coil)  # method 1
    P_core2, Bpk2, cld2 = core_loss_from_dc_bias(dc, coil)  # method 2

    # TODO the mac-inc methods do not consider core saturation
    # L drops with rising dc bias current, which will increase ripple current and Bpk and hysteresis loss

    return dotdict(
        P_dcr=P_dcr,
        P_core=max(P_core1, P_core2),
        get_cond=lambda k: dict(
            P_dcr=dict(Rdc=coil.Rdc),
            P_core=dict(
                ΔI=dc.Iripple,
                Bpk=max(Bpk1, Bpk2),  # peak ac flux density
                CLD=round_to_n_dec(max(cld1, cld2), 3) + 'mW/cm3',  # core loss density
                mthd=2 if cld2 > cld1 else 1,
            ),
        ).get(k)
    )


def mosfet_hs_sw_timings_hs(dc: DcDcSpecs, hs: MosfetSpecs, rg_total: float, fallback_V_pl=math.nan):
    # https://www.ti.com/lit/an/slpa009a/slpa009a.pdf#page=3  3.1.1
    assert math.isnan(hs.Qsw) or 0 < hs.Qsw < 1000e-9
    vpl = fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl
    # TODO igon1 + igon2
    assert vpl < dc.Vgs, "Vpl >= VGS"
    ig_on = (dc.Vgs - vpl) / rg_total
    ig_off = (vpl) / rg_total
    tr = hs.Qsw / ig_on
    tf = hs.Qsw / ig_off
    return tr, tf


def mosfet_hs_sw_timings_hs2(dc: DcDcSpecs, hs: MosfetSpecs, rg_total: float, fallback_V_pl=math.nan):
    # https://www.tij.co.jp/jp/lit/an/slvaeq9/slvaeq9.pdf#page=4
    # SLVAEQ9–July 2020
    # An Accurate Approach for Calculating the Eff. of a Synch. Buck Converter Using the MOSFET Plateau Voltage
    # equation (6) appears to be wrong.

    assert math.isnan(hs.Qsw) or 0 < hs.Qsw < 1000e-9
    vpl = fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl
    vgs_th = vpl * (hs.Qg_th / hs.Qgs)
    v_ir = .5 * (vpl + vgs_th)  # average voltage charging Qgs2
    tr = (hs.Qgs2 / (dc.Vgs - v_ir) + hs.Qgd / (dc.Vgs - vpl)) * rg_total # (5)
    tf = (hs.Qgs2 / (v_ir) + hs.Qgd / (vpl)) * rg_total          # (6) *corrected
    return tr, tf

def mosfet_hs_sw_timings_hs_vishay(dc: DcDcSpecs, hs: MosfetSpecs, rg_total: float, fallback_V_pl=math.nan):
    # https://www.vishay.com/docs/73217/an608a.pdf
    # Cgd(Vds)
    # needs Ciss(at dc.Vi)

    assert math.isnan(hs.Qsw) or 0 < hs.Qsw < 1000e-9
    vpl = fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl
    vgs_th = vpl * (hs.Qg_th / hs.Qgs)
    v_ir = .5 * (vpl + vgs_th)  # average voltage charging Qgs2
    tr = (hs.Qgs2 / (dc.Vgs - v_ir) + hs.Qgd / (dc.Vgs - vpl)) * rg_total # (5)
    tf = (hs.Qgs2 / (v_ir) + hs.Qgd / (vpl)) * rg_total          # (6) *corrected
    return tr, tf


def mosfet_hs_sw_timings_lcsi(dc: DcDcSpecs, hs: MosfetSpecs, ls_Qoss, rg_total: float, Lcsi: float,
                              fallback_V_pl=math.nan):
    # loss with L_csi considerations
    # https://www.ti.com/lit/an/slpa009a/slpa009a.pdf
    Qgs2 = hs.Qgs2
    vpl = fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl

    # pw on
    ig1_on = (dc.Vgs - vpl) / (rg_total + (Lcsi * dc.Io_min / Qgs2))
    a = (Lcsi * ls_Qoss / hs.Qgd ** 2) if Lcsi else 0
    b = rg_total
    c = -(dc.Vgs - vpl)
    ig2_on = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    tr = (Qgs2 / ig1_on + hs.Qgd / ig2_on)

    # pw off
    ig1_off = vpl / (rg_total + Lcsi * dc.Io_max / Qgs2)
    c = - vpl
    ig2_off = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    tf = (Qgs2 / ig1_off + hs.Qgd / ig2_off)

    return tr, tf, dict(Lcsi=Lcsi, Qoss_ls=ls_Qoss, Qsw=Qgs2 + hs.Qgd, Vpl=vpl)


def tests():
    dcdc = DcDcSpecs(24, 12, 40_000, 12, 500e-9, 10, iripple=1e-9)
    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9, Qsw=2e-9,
                     Qgs=2e-9, Qgs2=2e-9 * Qgs2_Qgs_ratio_estimate, Coss=0)

    loss = dcdc_buck_hs(dcdc, mf, rg_total=1e-6, fallback_V_pl=4, Rds_temp_rise=1)
    assert loss.P_cl == (10 ** 2) * 10e-3 * .5
    assert loss.P_sw == 24 * 10 * 40e3 * 40e-9
    assert loss.P_gd == (12 * 40e3 * 2 * 100e-9)
    assert math.isnan(loss.P_dt) or loss.P_dt == 0
    assert loss.buck_hs() == loss.P_cl + loss.P_sw + loss.P_gd + loss.P_coss

    loss = dcdc_buck_ls(dcdc, mf, rds_temp_rise=1, Qrr_temp_rise=1)
    assert loss.P_cl == (10 ** 2) * 10e-3 * .5
    assert loss.P_dt == 1 * 10 * (500e-9 * 2) * 40e3
    assert loss.P_rr == 24 * 40e3 * 120e-9
    assert loss.P_gd == (12 * 40e3 * 2 * 100e-9)
    assert math.isnan(loss.P_sw) or loss.P_sw == 0
    assert loss.buck_ls() == loss.P_rr + loss.P_cl + loss.P_gd + loss.P_dt

    dcdc = DcDcSpecs(vi=62, vo=27, pin=800, f=40e3, Vgs=12, ripple_factor=0.3, tDead=500e-9)
    mf = MosfetSpecs.from_mpn('DMT10H9M9SCT', 'diodes')
    l = mosfet_hs_sw_timings_hs(dcdc, mf, 6, 4.5)
    pr = 0.5 * dcdc.Vi * dcdc.Io_min * dcdc.f * l[0]
    pf = 0.5 * dcdc.Vi * dcdc.Io_max * dcdc.f * l[1]
    assert abs(pr - 0.3) < 0.1
    assert abs(pf - 0.7) < 0.1

    l2 = mosfet_hs_sw_timings_hs2(dcdc, mf, 6, 4.5)
    assert l2

    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9,
                     Qgd=80e-9,
                     Qgs=2e-9,
                     Qgs2=1e-9,
                     Coss=0)
    l1 = mosfet_hs_sw_timings_hs(dcdc, mf, 5, 4)

    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9,
                     Qgd=80e-9,
                     Qgs=4e-9,  # timings are independent of Qgs
                     Qgs2=1e-9,
                     Coss=0)
    l2 = mosfet_hs_sw_timings_hs(dcdc, mf, 5, 4)

    assert l1 == l2

    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9,
                     Qgd=80e-9,
                     Qgs=2e-9,
                     Qgs2=1e-9,
                     Coss=0)
    assert mf.Qg_th == 1e-9

    tr, tf = mosfet_hs_sw_timings_hs2(dcdc, mf, 5, 4)
    tr_ref = (mf.Qgs2 / (dcdc.Vgs - .5 * (4 + 2)) + mf.Qgd / (dcdc.Vgs - 4)) * 5
    assert abs(rel_err(tr, tr_ref)) < 1e-5
    assert tf == (mf.Qgs2 / (.5 * (4 + 2)) + mf.Qgd / (4)) * 5

    tr1, tf1 = mosfet_hs_sw_timings_hs(dcdc, mf, 5, 4)
    assert abs(rel_err(tr, tr1)) < 1e-2
    assert abs(rel_err(tf, tf1)) < 1e-2


def tests_lcsi():
    dcdc = DcDcSpecs(70, 35, 40_000, 10, 500e-9, 33, ripple_factor=0.01)
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

    tr, tf = mosfet_hs_sw_timings_hs(dcdc, hs, rg_total=6)
    assert abs(tr) < abs(tf)
    assert 0.6 < (tr / tf) < 0.9

    ls = hs
    tr_lcsi0, tf_lcsi0, _ = mosfet_hs_sw_timings_lcsi(dcdc, hs, ls, rg_total=6, Lcsi=.01e-9)
    assert abs(tr - tr_lcsi0) / tr < 0.05
    assert abs(tf - tf_lcsi0) / tf < 0.05

    tr_lcsi2, tf_lcsi2, _ = mosfet_hs_sw_timings_lcsi(dcdc, hs, ls, rg_total=6, Lcsi=2e-9)
    assert tr_lcsi2 < tf_lcsi2
    assert tr_lcsi2 > tr_lcsi0
    assert tf_lcsi2 > tf_lcsi0


def plot_vpl_curve():
    dcdc = DcDcSpecs(70, 35, 40_000, 10, 500e-9, 33, ripple_factor=0.01)
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
