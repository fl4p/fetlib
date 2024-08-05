import os


class MosfetSpecs:

    def __init__(self, Rds_on, Qg, tRise, tFall, Qrr):
        self.Rds_on = Rds_on
        self.Qg = Qg
        self.tRise = tRise
        self.tFall = tFall
        self.Qrr = Qrr

    @staticmethod
    def mpn(mpn, mfr):
        datasheet_path = os.path.join('datasheets', mfr, mpn + '.pdf')
        from dslib.parse import parse_datasheet
        ds = parse_datasheet(datasheet_path, mfr=mfr, mpn=mpn)
        return MosfetSpecs()


class DcDcSpecs:

    def __init__(self, vi, vo, f, Vgs, io=None, ii=None, pin=None):
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

        self.f = f
        # self.Ir = Ir # ripple current
        self.Vgs = Vgs

    @property
    def Pout(self):
        return self.Io * self.Vo

    def __str__(self):
        return 'DcDcSpecs(%.1fV/%.1fV=%.2f Io=%.1fA Po=%.1fW)' % (
        self.Vi, self.Vo, self.Vo / self.Vi, self.Io, self.Pout)


def buck_hs(dc: DcDcSpecs, mf: MosfetSpecs):
    # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/power_loss_appli-e.pdf
    return dict(
        P_on=dc.Io ** 2 * mf.Rds_on * dc.Vo / dc.Vi,
        P_sw=0.5 * dc.Vi * dc.Io * dc.f * (mf.tRise + mf.tFall),
        P_rr=dc.Vi * dc.f * mf.Qrr,
        P_gd=dc.Vgs * dc.f * 2 * mf.Qg,
    )


if __name__ == '__main__':
    dcdc = DcDcSpecs(vi=62, vo=27, pin=800, f=30e3, Vgs=12)
    p = buck_hs(
        dcdc,
        # MosfetSpecs(Rds_on=1e-3, Qg=1e-9, tRise=.5e-9, tFall=.5e-9, Qrr=1e-9)
        MosfetSpecs(Rds_on=6.8e-3, Qg=39e-9, tRise=39e-9, tFall=46e-9, Qrr=43e-9),  # TK6R8A08QM
        # MosfetSpecs.mpn(mpn='TK6R8A08QM', mfr='toshiba')
    )
    print(dcdc)
    p_total = sum(p.values())
    for k, v in p.items():
        print('%10s = %.2f W (%2.0f%%)' % (k, v, v / p_total * 100))

    print('')
    print('Total P_mosfet = %.2f W (%4.2f%%)' % (p_total, p_total / dcdc.Pout * 100))
