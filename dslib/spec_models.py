import math
from typing import Literal


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
        :param Qgd: charge across miller plateau
        :param Qgs: charge until the start of miller plateau (toshiba: before and after MP)
        :param Qgs2: charge between Qg_th and start of MP (toshiba: charger after MP)
        :param Qg_th: charge until V_th (Qg_th + Qgs2 = Qgs)
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

        if not Qgs2 and Qsw:
            assert Qsw > Qgd
            Qgs2 = Qsw - Qgd

        if not Qg_th and Qgs2:
            Qg_th = Qgs - Qgs2

        self.Qg = Qg
        self.Qgd = Qgd or math.nan
        self.Qgs = Qgs or math.nan
        self._Qgs2 = Qgs2 or math.nan
        self.Qg_th = Qg_th or math.nan

        assert not Qg_th or Qg_th < Qgs, (Qgs, Qg_th,)

        self._Vpl = Vpl or math.nan
        assert not Vpl or (2 <= Vpl <= 9), "Vpl %s must be between 2 and 8" % Vpl

        self.Coss = Coss or math.nan
        self.tRise = tRise or math.nan
        self.tFall = tFall or math.nan
        self.Qrr = math.nan if Qrr is None else Qrr  # GaN have Qrr = 0
        self.Vsd = Vsd  # body diode forward

        assert 1e-9 < Qg < 1000e-9, Qg
        assert math.isnan(self.Qrr) or 0 <= self.Qrr < 4000e-9, self.Qrr  # GaN have 0 qrr
        assert math.isnan(self.tRise) or .5e-9 <= self.tRise < 1000e-9, self.tRise
        assert math.isnan(self.tFall) or 1e-9 < self.tFall < 1000e-9, self.tFall
        assert Vsd is None or 0.2 < Vsd < 2, Vsd

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
        return self.Qgs * 0.5  # TODO estimate

    @property
    def Qsw(self):
        return self.Qgd + self.Qgs2

    def __str__(self):
        return f'MosfetSpecs({self.Vds}V,{round(self.Rds_on * 1e3, 1)}mR Qg={round(self.Qg * 1e9)}n trf={round(self.tRise * 1e9)}/{round(self.tFall * 1e9)}n Qrr={round(self.Qrr * 1e9)}n)'


class DcDcSpecs:

    def __init__(self, vi, vo, f, Vgs, tDead=None, io=None, ii=None, pin=None, dil=None, ripple_factor=None):
        """

        :param vi:
        :param vo:
        :param f:
        :param Vgs:
        :param io:
        :param ii:
        :param pin:
        :param dil: coil ripple current il_ton - il_0. CCM if dil<2*il. see https://www.richtek.com/Design%20Support/Technical%20Document/AN009#Ripple%20Factor
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
            assert dil is None
            dil = io * ripple_factor

        self.Iripple = dil if not dil is None else math.nan

        self.f = f
        # self.Ir = Ir # ripple current
        self.Vgs = Vgs
        self.tDead = tDead

        p = 1 / self.f
        assert tDead / p < 0.1

    @property
    def Pout(self):
        return self.Io * self.Vo

    @property
    def D_buck(self):
        return self.Vo / self.Vi

    @property
    def Io_min(self):
        return self.Io - (self.Iripple / 2)

    @property
    def Io_max(self):
        return self.Io + (self.Iripple / 2)

    @property
    def Io_mean_squared_on(self):
        dc = self
        hrp = (self.Iripple * .5) if math.isfinite(dc.Iripple) else 0
        return ((dc.Io + hrp) ** 2 + (dc.Io + hrp) * (dc.Io - hrp) + (dc.Io - hrp) ** 2) / 3

    def __str__(self):
        return 'DcDcSpecs(%.1fV/%.1fV=%.2f Io=%.1fA Po=%.1fW)' % (
            self.Vi, self.Vo, self.Vo / self.Vi, self.Io, self.Pout)

    def fn_str(self, topo: Literal['buck']):
        if topo == 'buck':
            return f'buck-%.0fV-%.0fV-%.0fA-%.0fkHz' % (self.Vi, self.Vo, self.Io, self.f / 1000)
        raise ValueError(topo)
