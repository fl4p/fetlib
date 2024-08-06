import math


class MosfetSpecs:

    def __init__(self, Rds_on, Qg, tRise, tFall, Qrr):
        if isinstance(Rds_on, str):
            if Rds_on.endswith('mOhm'):
                Rds_on = float(Rds_on[:-4].strip()) * 1e-3

        if isinstance(Qg, str):
            if Qg.endswith('nC'):
                Qg = float(Qg[:-2].strip()) * 1e-9
        self.Rds_on = Rds_on
        self.Qg = Qg
        self.tRise = tRise or math.nan
        self.tFall = tFall or math.nan
        self.Qrr = math.nan if Qrr is None else Qrr # GaN have Qrr = 0

    @staticmethod
    def mpn(mpn, mfr):
        datasheet_path = os.path.join('datasheets', mfr, mpn + '.pdf')
        from dslib.parse import parse_datasheet
        ds = parse_datasheet(datasheet_path, mfr=mfr, mpn=mpn)
        return MosfetSpecs()



class DcDcSpecs:

    def __init__(self, vi, vo, f, Vgs, io=None, ii=None, pin=None, dil=None, ripple_factor=None):
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

        self.dIl = dil if not dil is None else math.nan

        self.f = f
        # self.Ir = Ir # ripple current
        self.Vgs = Vgs

    @property
    def Pout(self):
        return self.Io * self.Vo

    def __str__(self):
        return 'DcDcSpecs(%.1fV/%.1fV=%.2f Io=%.1fA Po=%.1fW)' % (
        self.Vi, self.Vo, self.Vo / self.Vi, self.Io, self.Pout)

