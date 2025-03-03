import math
from typing import Literal, List

from dslib import round_to_n, round_to_n_dec, dotdict
from dslib.discovery import DiscoveredPart
from dslib.mosfet import GateDrive, MosfetSlot


# the smaller this ratio, the greater Qg_th
# .. and the smaller Qsw


class DcDcLoadParams:

    @staticmethod
    def default():
        # return DcDcSpecs(vi=62, vo=27, pin=800, f=40e3, Vgs=12, ripple_factor=0.3, tDead=300e-9)
        # return DcDcSpecs(vi=75, vo=27 * 2, pin=900, f=40e3, ripple_factor=0.3, tDead=300e-9)
        return DcDcLoadParams(vi=70, vo=27, pin=800, f=40e3, ripple_factor=0.3, tDead=300e-9)

    def __init__(self, vi, vo, f, tDead=None, io=None, ii=None, pin=None, iripple=None, ripple_factor=None,
                 L=None):
        """

        :param vi: input voltage
        :param vo: output voltage
        :param f: switching frequency
        :param Vgs: gate drive voltage
        :param tDead: gate driver dead-time
        :param io: output current
        :param ii: input current
        :param pin: input power
        :param iripple: peak-2-peak coil ripple current il(ton) - il(0). CCM if dil<2*il
        :param ripple_factor: peak-2-peak see https://www.richtek.com/Design%20Support/Technical%20Document/AN009#Ripple%20Factor
        """
        self.Vi = vi
        self.Vo = vo

        if ii is not None:
            assert pin is None and io is None
            pin = vi * ii

        if pin is not None:
            assert io is None
            io = pin / vo

        assert io is not None
        self.Io = io

        if ripple_factor is not None:
            assert iripple is None
            assert L is None
            iripple = io * ripple_factor

        if L is not None:
            assert ripple_factor is None
            assert iripple is None
            assert 1e-6 < L < 999e-6
            # https://www.ti.com/lit/ds/symlink/lm5163.pdf#page=18 (18)
            # notice that the ripple current does not depend on io (dc bias current)
            iripple = vo / (f * L) * (1 - vo / vi)
            assert iripple < 2 * io, "CCM mode only (DCM not implemented)"
            assert 0.01 < iripple / io < 2, (iripple, io, round(iripple / io, 2))
        else:
            L = round_to_n(vo / (f * iripple) * (1 - vo / vi), 3)

        self.Iripple = iripple if not iripple is None else math.nan  # dI peak-peak

        self.f = f
        self.tDead = tDead
        self.L = L

        p = 1 / self.f
        if tDead is not None:
            assert tDead / p < 0.1, (tDead / p)

    @property
    def Pout(self):
        """
        :return: Output power
        """
        return self.Io * self.Vo

    @property
    def D_buck(self):
        """
        :return: Buck duty cycle of HS switch
        """
        return self.Vo / self.Vi

    @property
    def ton_buck(self):
        return self.D_buck / self.f

    @property
    def Io_min(self):
        """
        :return: Bottom ripple current
        """
        return self.Io - (self.Iripple / 2)

    @property
    def Io_max(self):
        """
        :return: Peak ripple current
        """
        return self.Io + (self.Iripple / 2)

    @property
    def Il_ac_rms2(self):
        # RMS(∆I)^2 = ∆I^2/3 (triangular waveform)
        # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_converter_efficiency_app-e.pdf
        return ((self.Iripple / 2) ** 2) / 3

    @property
    def is_ccm(self) -> bool:
        """
        :return: Whether the DC-DC converter operates in continuous conduction mode (coil current does not touch zero)
        """
        # if math.isnan(self.Iripple):
        #    return True
        assert self.Iripple >= 0, self.Iripple
        return self.Iripple < 2 * self.Io

    @property
    def Io_mean_squared_on(self):
        """
        :return: Mean squared output current
        """
        assert self.is_ccm
        dc = self
        return (dc.Io_max ** 2 + dc.Io_max * dc.Io_min + dc.Io_min ** 2) / 3

    def __str__(self):
        return 'DcDcSpecs(%.1fV/%.1fV=%.2f Io=%.1fA Po=%sW ΔI=%.1fA L=%sH f=%sHz)' % (
            self.Vi, self.Vo, self.Vo / self.Vi, self.Io, round_to_n_dec(self.Pout, 4), self.Iripple,
            round_to_n_dec(self.L, 2), round_to_n_dec(self.f, 2))

    def fn_str(self, topo: Literal['buck']):
        if topo == 'buck':
            return f'buck-%.0fV-%.0fV-%.0fA-%.0fkHz' % (self.Vi, self.Vo, self.Io, self.f / 1000)
        raise ValueError(topo)

    def vds_in_range(self, vds):
        if abs(vds) < 2:  # probably invalid
            return True
        return not (vds < (self.Vi * 1.1)) and not (vds > (self.Vi * 4))

    def select_mosfets(dcdc, parts: List['DiscoveredPart']):
        rds_on_max = dcdc.Pout * 0.01 / (dcdc.Io ** 2) * 2
        # use inverted comparison to pass-through nan-values
        return [p for p in parts if (
                dcdc.vds_in_range(p.specs.Vds_max)
                and not (p.specs.ID_25 < dcdc.Io_max * 1.2) and not (p.specs.Rds_on_10v_max > rds_on_max))]

    def C_out_min(self, vout_ripple):
        # https://www.ti.com/lit/ds/symlink/lm5163.pdf
        return self.Iripple / (8 * self.f * vout_ripple)

    def C_in_min(self, vin_ripple, R_esr=0):
        # https://www.ti.com/lit/ds/symlink/lm5163.pdf
        return self.Io * self.D_buck * (1 - self.D_buck) / (self.f * (vin_ripple - self.Io * R_esr))


class BuckConverter():
    def __init__(self, name, Io_max, f_sw, coil: 'CoilSpecs', hs: MosfetSlot, ls: MosfetSlot, output_parasitics,
                 cin_imp=0, cout_imp=0
                 ):

        self.name = name
        self.Io_max = Io_max
        self.f_sw = f_sw
        from dclib.powerloss import CoilSpecs
        self.coil: CoilSpecs = coil
        self.hs = hs
        self.ls = ls
        self.output_parasitics = output_parasitics

        self.cout_imp = cout_imp
        self.cin_imp = cin_imp

    def powerloss(self, dcdc: DcDcLoadParams, gd: GateDrive):
        coil = self.coil
        Ldc = coil.Ldc(dcdc.Io)
        dcdc = DcDcLoadParams(vi=dcdc.Vi, vo=dcdc.Vo, io=dcdc.Io, f=dcdc.f, tDead=dcdc.tDead, L=Ldc)

        from dclib.powerloss import dcdc_buck_hs
        p_hs = dcdc_buck_hs(
            dcdc,
            self.hs.mf,
            gd=gd,
            # fallback_V_pl=5.4,
            # Lcsi=4e-9, ls_Qoss=400e-9,  # TODO csd19503 # TODO Qload_HS = Qoss_LS + Qrr_LS ?
            # MosfetSpecs(Rds_on=1e-3, Qg=1e-9, tRise=.5e-9, tFall=.5e-9, Qrr=1e-9)
            # MosfetSpecs(Rds_on=6.8e-3, Qg=39e-9, tRise=39e-9, tFall=46e-9, Qrr=43e-9),  # TK6R8A08QM
            # MosfetSpecs(Rds_on=2.3e-3, Qg=120e-9, tRise=11e-9, tFall=10e-9, Qrr=525e-9),#CSD19506KCS

            # MosfetSpecs.mpn(mpn='TK6R8A08QM', mfr='toshiba')
        )
        p_hs = p_hs.parallel(self.hs.parallel)

        from dclib.powerloss import dcdc_buck_coil
        p_coil = dcdc_buck_coil(dcdc, coil)

        from dclib.powerloss import dcdc_buck_ls
        p_ls = dcdc_buck_ls(dcdc,
                            # MosfetSpecs(Rds_on=2.3e-3, Qg=120e-9, tRise=11e-9, tFall=10e-9, Qrr=525e-9),
                            self.ls.mf,
                            gd
                            )

        from dclib.powerloss import dcdc_buck_cout
        p_cap = dcdc_buck_cout(dcdc, Z_cin=self.cin_imp, Z_cout=self.cout_imp)

        p_misc = dict()
        for k, v in self.output_parasitics.items():
            if k[0] == 'R':
                p_misc['P' + k[1:]] = v * dcdc.Io ** 2
            else:
                raise ValueError(k)

        return dotdict(hs=p_hs, ls=p_ls, coil=p_coil, cap=p_cap, misc=p_misc), dcdc


def tests():
    io = 10
    d1 = DcDcLoadParams(24, 12, 40e3, 10, 0, io=io, ripple_factor=0.001)
    assert abs(d1.Io_mean_squared_on - io ** 2) / io ** 2 < 1e-3

    d2 = DcDcLoadParams(24, 12, 40e3, 10, 0, io=io, ripple_factor=1)
    assert d2.Io_mean_squared_on > d1.Io_mean_squared_on * 1.05

    d2 = DcDcLoadParams(24, 12, 40e3, 10, 0, io=io, ripple_factor=1.99)
    assert d2.Io_mean_squared_on > d1.Io_mean_squared_on * 1.10


if __name__ == '__main__':
    tests()
