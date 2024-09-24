import math
from typing import Literal


def isnum(v):
    return v is not None and not math.isnan(v)

QgsQgs2_ratio_estimate = 0.45 # 0.3 ... 0.6
class MosfetSpecs:

    def __init__(self, Vds_max, Rds_on, Qg, tRise, tFall, Qrr, Qgd=None, Qgs=None, Qgs2=None, Qg_th=None, Qsw=None,
                 Vpl=None, Vsd=None, Coss=None):
        """

        :param Vds_max:
        :param Rds_on:
        :param Qg: total gate charge
        :param tRise:
        :param tFall:
        :param Qrr: reverse recovery charge (german: Sperrverzugsladung)
        :param Qgd: gate-drain charge across miller plateau
        :param Qgs: gate-source charge until the start of miller plateau (toshiba: before and after MP)
        :param Qgs2: charge between Qg_th and start of MP (toshiba: charger after MP)
        :param Qg_th: charge until V_th (Qg_th + Qgs2 = Qgs)
        :param Qsw: Qgs2 + Qgd
        :param Vpl: miller plateau voltage
        :param Vsd: body diode forward voltage
        :param Coss: output capacity (eff. energy related)
        """
        self.Vds = Vds_max

        if isinstance(Rds_on, str):
            if Rds_on.endswith('mOhm'):
                Rds_on = float(Rds_on[:-4].strip()) * 1e-3

        if isinstance(Qg, str):
            if Qg.endswith('nC'):
                Qg = float(Qg[:-2].strip()) * 1e-9
            else:
                raise ValueError('Qg must be either nC: %s' % Qg)

        self.Rds_on = Rds_on

        if not isnum(Qgs2) and isnum(Qsw):
            assert Qsw > Qgd
            Qgs2 = Qsw - Qgd

        if not isnum(Qg_th) and isnum(Qsw) and isnum(Qgd):
            if isnum(Qgs):
                Qg_th = Qgs + Qgd - Qsw
                assert 0 < Qg_th < Qgs, Qg_th
            elif isnum(Qgs2):
                Qg_th = Qsw - Qgd
                Qgs = Qsw + Qg_th - Qgd
                assert 0 < Qg_th < Qgs
                assert Qgs > 0
            else:
                Qg_th = (Qsw - Qgd) * (1 / QgsQgs2_ratio_estimate - 1)
                Qgs = Qg_th - Qgd - Qsw

        if not isnum(Qg_th) and isnum(Qgs2):
            Qg_th = Qgs - Qgs2
            assert Qg_th > 0, Qg_th

        if not isnum(Qgs) and isnum(Qg_th) and isnum(Qgs2):
            Qgs = Qg_th + Qgs2

        self.Qg = Qg or math.nan
        self.Qgd = Qgd or math.nan
        self.Qgs = Qgs or math.nan
        self._Qgs2 = Qgs2 or math.nan
        self.Qg_th = Qg_th or math.nan
        self._Qsw = Qsw or math.nan # untouched!

        assert not isnum(Qg_th) or Qg_th < Qgs, (Qgs, Qg_th,)

        if isnum(Qsw) and isnum(Qgd) and isnum(Qgs2):
            print('WARNING: Qsw=(%.1fn) != (%.1fn + %.1fn)=Qgd+Qgs2' % (Qsw*1e9, Qgd*1e9, Qgs2*1e9))
            # assert Qsw == (Qgd + Qgs2)

        self._Vpl = Vpl or math.nan
        assert not isnum(Vpl) or (2 <= Vpl <= 9), "Vpl %s must be between 2 and 8" % Vpl

        self.Coss = Coss or math.nan
        self.tRise = tRise or math.nan
        self.tFall = tFall or math.nan
        self.Qrr = math.nan if Qrr is None else Qrr  # GaN have Qrr = 0
        self.Vsd = Vsd  # body diode forward

        assert math.isnan(Qg) or .5e-9 < Qg < 1000e-9, (Qg, Rds_on, Qg * Rds_on)
        assert math.isnan(self.Qrr) or 0 <= self.Qrr < 4000e-9, self.Qrr  # GaN have 0 qrr
        assert math.isnan(self.tRise) or .5e-9 <= self.tRise < 1000e-9, self.tRise
        assert math.isnan(self.tFall) or .5e-9 < self.tFall < 1000e-9, self.tFall
        if isnum(Vsd): Vsd = abs(Vsd)
        assert not isnum(Vsd) or 0.2 < Vsd < 3, Vsd  # FBG10N30BC: 2.5V

        assert math.isnan(Qg * Rds_on) or 2e-11 < Qg * Rds_on < 1e-08, (Qg, Rds_on, Qg * Rds_on)

    @staticmethod
    def from_mpn(mpn, mfr) -> 'MosfetSpecs':
        import dslib.store

        part = dslib.store.load_part(mpn, mfr)
        assert part.is_fet
        return part.specs

    @property
    def V_pl(self):
        # aka Vgp, read from datasheet
        # https://www.vishay.com/docs/73217/an608a.pdf#page=4
        # Vgp = VTH + IDS/gfs
        # better to read from datasheet curves
        # return (self.Qgs + self.Qgd) - self.Qg_th
        # Qg_th = Qgs - Q_pl
        if not math.isnan(self._Vpl):
            return self._Vpl
        else:
            return math.nan
            raise NotImplemented()
            # return (self.Qgs + self.Qgd) - self.Qg_th
        # return 4.2
        # raise NotImplemented

    @property
    def Qgs2(self):
        if not math.isnan(self._Qgs2):
            return self._Qgs2
        if not math.isnan(self.Qg_th):
            return self.Qgs - self.Qg_th
        return self.Qgs * QgsQgs2_ratio_estimate  # TODO estimate

    @property
    def Qsw(self):
        if not math.isnan(self._Qsw):
            return self._Qsw
        return self.Qgd + self.Qgs2

    def __str__(self):
        return f'MosfetSpecs({self.Vds}V,{round(self.Rds_on * 1e3, 1)}mR Qg={round(self.Qg * 1e9)}n trf={round(self.tRise * 1e9)}/{round(self.tFall * 1e9)}n Qrr={round(self.Qrr * 1e9)}n)'


class DcDcSpecs:

    def __init__(self, vi, vo, f, Vgs, tDead=None, io=None, ii=None, pin=None, iripple=None, ripple_factor=None):
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
            iripple = io * ripple_factor

        self.Iripple = iripple if not iripple is None else math.nan

        self.f = f
        self.Vgs = Vgs
        self.tDead = tDead

        p = 1 / self.f
        assert tDead / p < 0.1

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
        return 'DcDcSpecs(%.1fV/%.1fV=%.2f Io=%.1fA Po=%.1fW)' % (
            self.Vi, self.Vo, self.Vo / self.Vi, self.Io, self.Pout)

    def fn_str(self, topo: Literal['buck']):
        if topo == 'buck':
            return f'buck-%.0fV-%.0fV-%.0fA-%.0fkHz' % (self.Vi, self.Vo, self.Io, self.f / 1000)
        raise ValueError(topo)


def tests():
    io = 10
    d1 = DcDcSpecs(24, 12, 40e3, 10, 0, io=io, ripple_factor=0.001)
    assert abs(d1.Io_mean_squared_on - io ** 2) / io ** 2 < 1e-3

    d2 = DcDcSpecs(24, 12, 40e3, 10, 0, io=io, ripple_factor=1)
    assert d2.Io_mean_squared_on > d1.Io_mean_squared_on * 1.05

    d2 = DcDcSpecs(24, 12, 40e3, 10, 0, io=io, ripple_factor=1.99)
    assert d2.Io_mean_squared_on > d1.Io_mean_squared_on * 1.10


if __name__ == '__main__':
    tests()
