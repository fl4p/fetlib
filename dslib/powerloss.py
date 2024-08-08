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
    def __init__(self, P_on, P_gd, P_sw=math.nan, P_rr=math.nan, P_dt=math.nan):
        self.P_on = P_on
        self.P_sw = P_sw
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
            P_on=self.P_on / (n ** 2),
            P_sw=self.P_sw,
            P_rr=n * self.P_rr,
            P_gd=n * self.P_gd,
            P_dt=self.P_dt,  # Vsd body diode voltage drop
        )

    def buck_hs(self):
        p = self.P_sw + self.P_on + self.P_gd
        # assert not math.isnan(p), (self.P_sw , self.P_on , self.P_gd)
        return p

    def buck_ls(self):
        # P_rr is induced but not self loss !
        p = self.P_rr + self.P_on + self.P_gd
        # assert not math.isnan(p)
        return p

    def sum(self):
        return sum(v for v in self.values() if not math.isnan(v))


def dcdc_buck_hs(dc: DcDcSpecs, mf: MosfetSpecs):
    # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/power_loss_appli-e.pdf
    # https://www.richtek.com/Design%20Support/Technical%20Document/AN009#Ripple%20Factor
    assert mf.tRise is not None and mf.tFall is not None, 'tRise and tFall must be set ' + mf.__repr__()
    assert mf.Qg is not None, 'Qg must be set ' + mf.__repr__()
    assert mf.Qrr is not None, 'Qrr must be set ' + mf.__repr__()
    assert math.isnan(dc.dIl) or dc.dIl > 0

    if math.isfinite(dc.dIl):
        assert dc.dIl < 2 * dc.Io, 'CCM required, DCM not supported TODO'
        P_sw = 0.5 * dc.Vi * dc.f * (mf.tRise * (dc.Io - dc.dIl / 2) + mf.tFall * (dc.Io + dc.dIl / 2))
    else:
        P_sw = 0.5 * dc.Vi * dc.Io * dc.f * (mf.tRise + mf.tFall)

    return SwitchPowerLoss(
        P_on=dc.Io ** 2 * mf.Rds_on * dc.Vo / dc.Vi,
        P_sw=P_sw,
        P_rr=0,  # body diode never conducts
        # P_rr=dc.Vi * dc.f * mf.Qrr, # P_rr is caused by LS but dissipated by HS
        P_gd=dc.Vgs * dc.f * 2 * mf.Qg,
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
        warnings.warn('no Vsd specified, assuming 1 V')
        vsd = 1
    else:
        vsd = mf.Vsd

    return SwitchPowerLoss(
        P_on=dc.Io ** 2 * mf.Rds_on * (1 - dc.Vo / dc.Vi),
        P_dt=vsd * dc.Io * (dc.tDead * 2) * dc.f,
        P_rr=dc.Vi * dc.f * mf.Qrr,  # this is dissipated in HS
        P_gd=dc.Vgs * dc.f * 2 * mf.Qg,
    )


class CoilSpecs():
    def __init__(self, Rdc):
        self.Rdc = Rdc


def dcdc_buck_coil(dc: DcDcSpecs, coil: CoilSpecs):
    """

    * Wire Loss
        * dcr wire loss
        * skin effect TODO
    * Core Loss

    Well designed coils have a 50/50% distribution of Wire and Core Loss


    ref https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_converter_efficiency_app-e.pdf


    :param dc:
    :param coil:
    :return:
    """

    assert math.isnan(dc.dIl) or dc.dIl > 0

    if math.isfinite(dc.dIl):
        assert dc.dIl < 2 * dc.Io, 'CCM required, DCM not supported TODO'
        ip = (dc.Io + dc.dIl / 2)
        iv = (dc.Io - dc.dIl / 2)
        P_dcr = (dc.Io ** 2 + ((ip - iv) ** 2 / 12)) * coil.Rdc
    else:
        P_dcr = dc.Io ** 2 * coil.Rdc

    return dict(
        P_dcr=P_dcr,
    )


def tests():
    dcdc = DcDcSpecs(24, 12, 40_000, 12, 500e3, 10)
    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 1)

    loss = dcdc_buck_hs(dcdc, mf)
    assert loss.P_on == (10 ** 2) * 10e-3 * .5
    assert loss.P_sw == 24 * 10 * 40e3 * 40e-9
    assert loss.P_gd == (12 * 40e3 * 2 * 100e-9)
    assert math.isnan(loss.P_dt)
    assert loss.buck_hs() == loss.P_on + loss.P_sw + loss.P_gd

    loss = dcdc_buck_ls(dcdc, mf)
    assert loss.P_on == (10 ** 2) * 10e-3 * .5
    assert loss.P_dt == 1 * 10 * (500e3 * 2) * 40e3
    assert loss.P_rr == 24 * 40e3 * 120e-9
    assert loss.P_gd == (12 * 40e3 * 2 * 100e-9)
    assert math.isnan(loss.P_sw)
    assert loss.buck_ls() == loss.P_rr + loss.P_on + loss.P_gd


if __name__ == '__main__':
    tests()
