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

from dslib.spec_models import DcDcSpecs, MosfetSpecs


class SwitchPowerLoss():
    def __init__(self, P_on, P_gd, P_sw=math.nan, P_coss=math.nan, P_rr=math.nan, P_dt=math.nan):
        """
        :param P_on: conduction loss
        :param P_gd: gate drive loss
        :param P_sw:  switching loss
        :param P_coss: output capacitance loss
        :param P_rr:  reverse recovery loss
        :param P_dt:  dead-time loss during body diode conduction
        """
        self.P_on = P_on
        self.P_sw = P_sw
        self.P_coss = P_coss
        self.P_rr = P_rr
        self.P_gd = P_gd
        self.P_dt = P_dt

    def values(self):
        return self.__dict__.values()

    def items(self):
        return self.__dict__.items()

    def parallel(self, n=2):
        """
        Compute total power loss for n parallel switches.

        For P_sw we assume that the fastest switch takes all the losses

        :return:
        """
        return SwitchPowerLoss(
            P_on=self.P_on / n * 0.9,  # one switch takes most of the dynamic load, the rest stay cooler
            P_sw=self.P_sw,
            P_rr=n * self.P_rr,
            P_gd=n * self.P_gd,
            P_dt=self.P_dt,  # Vsd body diode voltage drop
            P_coss=n * self.P_coss,
        )

    def buck_hs(self):
        p = self.P_sw + self.P_on + self.P_gd
        if not math.isnan(self.P_coss):
            p += self.P_coss
        # assert not math.isnan(p), (self.P_sw , self.P_on , self.P_gd)
        return p

    def buck_ls(self):
        # P_rr is induced but not self loss !
        p = self.P_rr + self.P_on + self.P_gd + self.P_dt
        if not math.isnan(self.P_coss):
            p += self.P_coss
        # assert not math.isnan(p)
        return p

    def sum(self):
        return sum(v for v in self.values() if not math.isnan(v))


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


def dcdc_buck_hs(dc: DcDcSpecs, mf: MosfetSpecs, rg_total,fallback_V_pl=math.nan):
    # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/power_loss_appli-e.pdf
    # https://www.richtek.com/Design%20Support/Technical%20Document/AN009#Ripple%20Factor

    assert mf.Qg is not None, 'Qg must be set ' + mf.__repr__()
    assert mf.Qrr is not None, 'Qrr must be set ' + mf.__repr__()
    assert math.isnan(dc.Iripple) or dc.Iripple > 0

    i_rms2 = dc.D_buck * dc.Io_mean_squared_on

    return SwitchPowerLoss(
        P_on=i_rms2 * mf.Rds_on,
        # P_sw=mosfet_switching_trf(dc, mf),
        P_sw=sum(mosfet_switching_hs(dc, mf, rg_total=rg_total, fallback_V_pl=fallback_V_pl)),
        P_rr=0,  # body diode never conducts
        P_gd=dc.Vgs * dc.f * 2 * mf.Qg,
        # P_coss=.5 * dc.f * dc.Vi ** 2 * mf.Coss, # https://www.onelectrontech.com/power-mosfet-capacitance-coss-and-switching-loss/
        # P_coss=.5 * dc.f * dc.Vi * mf.Qoss,  #<- https://www.ti.com/lit/an/slpa009a/slpa009a.pdf#page=8
    )


def dcdc_buck_ls(dc: DcDcSpecs, mf: MosfetSpecs):
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
        vsd = mf.Vsd

    return SwitchPowerLoss(
        P_on=(1 - dc.D_buck) * dc.Io_mean_squared_on * mf.Rds_on * (1 - dc.D_buck),
        P_dt=vsd * dc.Io * (dc.tDead * 2) * dc.f,
        P_rr=dc.Vi * dc.f * mf.Qrr,  # this is dissipated in HS
        P_gd=dc.Vgs * dc.f * 2 * mf.Qg,
        # P_coss=.5 * dc.f * dc.Vi ** 2 * mf.Coss,
    )


class CoilSpecs():
    def __init__(self, Rdc):
        # TODO skin effect
        self.Rdc = Rdc


def dcdc_buck_coil(dc: DcDcSpecs, coil: CoilSpecs):
    """

    * Wire Loss
        * dcr wire loss
        * skin effect TODO
    * Core Loss

    Well designed coils have a 80/20% distribution of Wire and Core Loss


    ref https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_converter_efficiency_app-e.pdf


    :param dc:
    :param coil:
    :return:
    """

    assert math.isnan(dc.Iripple) or dc.Iripple > 0

    if math.isfinite(dc.Iripple):
        assert dc.Iripple < 2 * dc.Io, 'CCM required, DCM not supported TODO'
        ip = (dc.Io + dc.Iripple / 2)
        iv = (dc.Io - dc.Iripple / 2)
        P_dcr = (dc.Io ** 2 + ((ip - iv) ** 2 / 12)) * coil.Rdc
    else:
        P_dcr = dc.Io ** 2 * coil.Rdc

    return dict(
        P_dcr=P_dcr,
    )


def mosfet_switching_hs(dc: DcDcSpecs, hs: MosfetSpecs, rg_total: float, fallback_V_pl=math.nan):
    """
    Uses:
    - V_pl (higher Vpl means more loss during turn off at peak ripple current)
    - Qsw

    :param dc:
    :param hs:
    :param rg_total:
    :return:
    """
    # https://www.ti.com/lit/an/slpa009a/slpa009a.pdf#page=3  3.1.1
    vpl = fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl
    ig_on = (dc.Vgs - vpl) / rg_total
    ig_off = (vpl) / rg_total
    t_on = hs.Qsw * 1e-9 / ig_on
    t_off = hs.Qsw * 1e-9 / ig_off
    tr = max(t_on, hs.tRise)
    tf = max(t_off, hs.tFall)
    Psw_on = 0.5 * dc.Vi * dc.f * dc.Io_min * tr
    Psw_off = 0.5 * dc.Vi * dc.f * dc.Io_max * tf
    return Psw_on, Psw_off


def mosfet_switching_hs_lcsi(dc: DcDcSpecs, hs: MosfetSpecs, ls: MosfetSpecs, rg_total: float, Lcsi: float):
    # loss with L_csi considerations
    # https://www.ti.com/lit/an/slpa009a/slpa009a.pdf
    Qgs2 = hs.Qgs2

    # pw on
    ig1_on = (dc.Vgs - hs.V_pl) / (rg_total + (Lcsi * dc.Io_min / Qgs2 * 1e9))
    a = (Lcsi * ls.Qoss / hs.Qgd ** 2 * 1e9) if Lcsi else 0
    b = rg_total
    c = -(dc.Vgs - hs.V_pl)
    ig2_on = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    Psw_on = 0.5 * dc.Vi * dc.Io_min * dc.f * (Qgs2 / ig1_on + hs.Qgd / ig2_on) * 1e-9

    # pw off
    ig1_off = hs.V_pl / (rg_total + Lcsi * dc.Io_max / Qgs2 * 1e9)
    c = - hs.V_pl
    ig2_off = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    Psw_off = 0.5 * dc.Vi * dc.Io_max * dc.f * (Qgs2 / ig1_off + hs.Qgd / ig2_off) * 1e-9

    return Psw_on, Psw_off


def tests():
    dcdc = DcDcSpecs(24, 12, 40_000, 12, 500e-9, 10)
    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 1)

    loss = dcdc_buck_hs(dcdc, mf)
    assert loss.P_on == (10 ** 2) * 10e-3 * .5
    assert loss.P_sw == 24 * 10 * 40e3 * 40e-9
    assert loss.P_gd == (12 * 40e3 * 2 * 100e-9)
    assert math.isnan(loss.P_dt)
    assert loss.buck_hs() == loss.P_on + loss.P_sw + loss.P_gd

    loss = dcdc_buck_ls(dcdc, mf)
    assert loss.P_on == (10 ** 2) * 10e-3 * .5
    assert loss.P_dt == 1 * 10 * (500e-9 * 2) * 40e3
    assert loss.P_rr == 24 * 40e3 * 120e-9
    assert loss.P_gd == (12 * 40e3 * 2 * 100e-9)
    assert math.isnan(loss.P_sw)
    assert loss.buck_ls() == loss.P_rr + loss.P_on + loss.P_gd + loss.P_dt


def tests_lcsi():
    dcdc = DcDcSpecs(70, 35, 40_000, 10, 500e-9, 33, ripple_factor=0.01)
    hs = MosfetSpecs.from_mpn('CSD19503KCS', mfr='ti')
    # ls = MosfetSpecs.from_mpn('CSD19503KCS', mfr='ti')
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

    Pon, Poff = mosfet_switching_hs(dcdc, hs, rg_total=6)
    assert abs(Pon) < abs(Poff)
    assert 0.6 < (Pon / Poff)

    ls = hs
    Pon_lcsi0, Poff_lcsi0 = mosfet_switching_hs_lcsi(dcdc, hs, ls, rg_total=6, Lcsi=.01e-9)
    assert abs(Pon - Pon_lcsi0) / Pon < 0.05
    assert abs(Poff - Poff_lcsi0) / Poff < 0.05

    Pon_lcsi2, Poff_lcsi2 = mosfet_switching_hs_lcsi(dcdc, hs, ls, rg_total=6, Lcsi=2e-9)
    assert Pon_lcsi2 < Poff_lcsi2
    assert Pon_lcsi2 > Pon_lcsi0
    assert Poff_lcsi2 > Poff_lcsi0


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

    Pon, Poff = mosfet_switching_hs(dcdc, hs, rg_total=6)


if __name__ == '__main__':
    # tests()
    tests_lcsi()
