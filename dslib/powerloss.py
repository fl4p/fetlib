import math

from dslib.spec_models import DcDcSpecs, MosfetSpecs


class SwitchPowerLoss():
    def __init__(self, P_on, P_sw, P_rr, P_gd):
        self.P_on = P_on
        self.P_sw = P_sw
        self.P_rr = P_rr
        self.P_gd = P_gd

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
        )

    def sum(self):
        return self.P_on + self.P_sw + self.P_rr + self.P_gd


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
        P_rr=dc.Vi * dc.f * mf.Qrr,
        P_gd=dc.Vgs * dc.f * 2 * mf.Qg,
    )
