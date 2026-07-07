import math
import warnings

from dslib import isnum, rel_err, round_to_n_dec

Qgs2_Qgs_ratio_estimate = 0.55  # 0.3 ... 0.6


class MosfetSpecs:

    def __init__(self, Vds_max, Rds_on, Qg, tRise, tFall, Qrr, trr=None, Qgd=None, Qgs=None, Qgs2=None, Qg_th=None,
                 Qsw=None,
                 Vpl=None, Vsd=None,
                 Coss=math.nan, Coss_Vds=None,
                 Rg=math.nan, Id=math.nan, part=None):
        """

        :param Vds_max: Vds break-down voltage (also referred as `BVdss` or `V (BR)DSS`), in volt
        :param Rds_on: Rds_on max at Tj=25°C and full gate drive voltage (Si: Vgs=10V, GaN: Vgs=5V)
        :param Qg: total gate charge
        :param tRise: Vds rise-time under given conditions (conditions not given, tRise unused)
        :param tFall: Vds fall-time under given conditions (conditions not given, tFall unused)
        :param Qrr: reverse recovery charge (german: Sperrverzugsladung)
        :param Qgd: gate-drain charge across miller plateau
        :param Qgs: gate-source charge until the start of miller plateau (Toshiba: before + after MP)
        :param Qgs2: charge between Qg_th and start of MP (Toshiba: charger after MP)
        :param Qg_th: charge until V_th (Qg_th + Qgs2 = Qgs)
        :param Qsw: Qgs2 + Qgd
        :param Vpl: miller plateau voltage
        :param Vsd: body diode forward voltage
        :param Coss: output capacity (eff. energy related)
        :param Coss_Vds: Vds at which Coss was calculated or measured (test condition)
        """
        self.part = part
        if Vds_max and not math.isnan(Vds_max) and int(Vds_max) == Vds_max:
            Vds_max = int(Vds_max)
        self.Vds: float = Vds_max

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
            assert Qsw > Qgd, (Qsw, Qgd)
            Qgs2 = Qsw - Qgd

        if not isnum(Qgd) and isnum(Qsw) and isnum(Qgs2):
            Qgd = Qsw - Qgs2

        self._Qg_th = None

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
                self._Qg_th = math.nan  # TODO flag as estimate
                Qg_th = (Qsw - Qgd) * (1 / Qgs2_Qgs_ratio_estimate - 1)
                Qgs = Qg_th - Qgd - Qsw

        if not isnum(Qg_th) and isnum(Qgs2):
            Qg_th = Qgs - Qgs2
            self._Qg_th = Qg_th
            assert Qg_th > 0, Qg_th

        if not isnum(Qg_th) and not math.isnan(Qgs):
            self._Qg_th = math.nan  # TODO flag as estimate
            Qg_th = Qgs - (Qgs * Qgs2_Qgs_ratio_estimate)

        if not isnum(Qgs) and isnum(Qg_th) and isnum(Qgs2):
            Qgs = Qg_th + Qgs2

            Qg_th = Qgs - Qgs2

        self.Qg = Qg or math.nan
        self.Qgd = Qgd or math.nan
        self.Qgs = Qgs or math.nan
        self._Qgs2 = Qgs2 or math.nan
        self.Qg_th = Qg_th or math.nan
        if self._Qg_th is None:  # _Qg_th is nan if estimated
            self._Qg_th = self.Qg_th
        self._Qsw = Qsw or math.nan  # untouched!

        assert not isnum(Qg_th) or Qg_th < Qgs, (Qgs, Qg_th,)

        self._Vpl = Vpl or math.nan
        assert not isnum(Vpl) or (2 <= Vpl <= 9), "Vpl %s must be between 2 and 8" % Vpl

        if isnum(Vsd) and abs(Vsd) > 10:
            warnings.warn('abs Vsd is greater than 10, ' + str(Vsd) + ', assuming ' + str(Vsd / 10))
            Vsd /= 10

        self.Coss = Coss  # Vds = Vin
        self.Coss_Vds = Coss_Vds
        self.tRise = tRise or math.nan
        self.tFall = tFall or math.nan
        self.Qrr = math.nan if Qrr is None else Qrr  # GaN have Qrr = 0
        self.Vsd = Vsd  # body diode forward
        self.trr = trr

        fom = Rds_on * Qg * 1e3 * 1e9
        assert math.isnan(fom) or 10 < fom < 20000, ("fom out of range", fom, Rds_on, Qg)

        assert math.isnan(Qg) or .2e-9 < Qg < 2000e-9, (
            "qg range", Qg, Rds_on, fom)  # 2N7002DWH6327XTSA1, FF3MR20KM1HHPSA1
        assert math.isnan(
            self.Qrr) or 0 <= self.Qrr < 200e-6, self.Qrr  # GaN have 0 qrr, TK16A55D:26µC, SUP70042E:189uC

        rr = self.Qrr / self.trr
        assert math.isnan(rr) or 0.01 <= rr <= 40, ("qrr/trr ratio", self.Qrr / self.trr, self.Qrr, self.trr)
        # rr~=1.3: NVMFS6H818NLT1G, rr<1: TK110A10PL
        # rr = 30 : IXTK200N10P
        # MCB220N15Y-TP: 0.02

        assert math.isnan(self.tRise) or .5e-9 <= self.tRise < 1000e-9, self.tRise
        assert math.isnan(self.tFall) or .5e-9 < self.tFall < 1000e-9, self.tFall
        if isnum(Vsd):
            Vsd = abs(Vsd)

        assert not isnum(
            Vsd) or 0.2 < Vsd < 5, "Vsd %s out of range" % Vsd  # FBG10N30BC: 2.5V, FF33MR12W1M1HB11BPSA1: 4.2V

        assert math.isnan(Qg * Rds_on) or 2e-11 < Qg * Rds_on < 2e-08, (Qg, Rds_on, Qg * Rds_on)

        if isnum(Qg_th + Qgs):
            assert 0.2 < (Qg_th / Qgs) < 0.8, ((Qg_th / Qgs), Qg_th, Qgs)

        if isnum(Qsw) and isnum(Qgd) and isnum(Qgs2):
            # up: TK3R9E10PL, AUIRF7769L2TR
            assert 0.33 < Qgd / Qsw < 0.95, (Qgd / Qsw, Qgd, Qsw)

            err = rel_err(Qsw, Qgd + Qgs2)
            if abs(err) > 0.05:
                s = 'Qsw=(%.1fn) != (%.1fn + %.1fn)=Qgd+Qgs2 {err=%.2f}' % (Qsw * 1e9, Qgd * 1e9, Qgs2 * 1e9, err)
                if abs(err) > 0.36:
                    raise ValueError(s)
                else:
                    warnings.warn(s)

        self.Rg = Rg
        self.Id = Id
        # if not math.isnan(Rg):
        # assert 0.2 < Rg < 200, ("Rg out of range", Rg)

    @staticmethod
    def from_mpn(mpn, mfr) -> 'MosfetSpecs':
        import dslib.store
        from dslib.field import MpnMfr
        part = dslib.store.parts_db.load_obj(MpnMfr(mfr, mpn=mpn))
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
        return self.Qgs * Qgs2_Qgs_ratio_estimate  # TODO estimate

    @property
    def Qsw(self):
        if not math.isnan(self._Qsw):
            return self._Qsw
        return self.Qgd + self.Qgs2

    @property
    def Qg_sync(self):
        # sync fet
        return self.Qg - self.Qgd

    def Qg_odr(self):
        """
        Gate Charge Overdrive. Charge after miller plateau until Vgs
        :return:
        """
        return self.Qg - self.Qgd - self.Qgs

    def __str__(self):
        coss_vds = self.Coss_Vds if hasattr(self, 'Coss_Vds') else None
        return (f'MosfetSpecs({round_to_n_dec(self.Vds, 3)}V,{round_to_n_dec(self.Rds_on, 3)}Ω '
                f'Qg={round_to_n_dec(self.Qg, 3)} Qsw={round_to_n_dec(self.Qsw, 3)} '
                f'trf={round_to_n_dec(self.tRise, 3)}/{round_to_n_dec(self.tFall, 3)} '
                f'Qrr={round_to_n_dec(self.Qrr, 3)} Coss@{round_to_n_dec(coss_vds or "nan", 3)}={round_to_n_dec(self.Coss, 3)})')

    def keys(self):
        fl = ['Vds', 'Vsd', 'Rds_on', 'Qg', 'tRise', 'tFall', 'Qgs', 'Qgd', '_Qg_th', '_Qgs2', '_Qsw', 'Coss']
        return set(s.lstrip('_') for s in fl if hasattr(self, s) and not math.isnan(getattr(self, s)))

    @property
    def FoM(self):
        # "Rectification FoM"
        return self.Rds_on * self.Qg * 1e3 * 1e9  # [mΩ*nC]

    # @property
    # def FoMswitch(self):
    #    # "Switch FoM" (Qgd plays mayor role in switch losses)
    #    # https://epc-co.com/epc/Portals/0/epc/documents/papers/eGaN%20FET%20Electrical%20Characteristics.pdf
    #    return self.Rds_on * self.Qgd * 1e3 * 1e9  # [mΩ*nC]

    @property
    def FoMqrr(self):
        return self.Rds_on * self.Qrr * 1e3 * 1e9  # [mΩ*nC]

    @property
    def FoMqsw(self):
        return self.Rds_on * self.Qsw * 1e3 * 1e9  # [mΩ*nC]

    @property
    def FoMcoss(self):
        return self.Rds_on * self.Coss * 1e3 * 1e12  # [mΩ*pF]

    @property
    def QgdQgsRatio(self):
        """
        Self turn-on ratio.
        For LS this should be < 1.
        :return:
        """
        return self.Qgd / self.Qgs

    @property
    def Coss_V0(self):
        mf = self
        coss_vds = getattr(mf, 'Coss_Vds', math.nan)
        coss_v0 = math.nan

        # reject coss_v0 if it is too far away from half the break-down voltage
        if coss_vds and math.isfinite(coss_vds) and (abs((mf.Vds / 2) - coss_v0) / mf.Vds < 0.2):
            coss_v0 = abs(coss_vds)  # test voltage might be given negative for p-channel

        elif math.isnan(coss_v0):
            # Fallback: assume Coss specified at ~half Vds (common datasheet practice)
            vds = abs(mf.Vds or math.nan)
            if math.isfinite(vds) and vds > 1:
                coss_v0 = vds / 2
            else:
                coss_v0 = math.nan

        return coss_v0


class GateDrive:
    """

    Parameters for a gate drive circuit.
    Optionally takes miller plateau voltage V_pl (V_gp) which is used can be used as fallback
    if mosfet doesn't specify it.

    """

    def __init__(self, rg_total, rg_total_dis, Von=10, Von_GaN=math.nan, Voff=0, fallback_V_pl=math.nan, tDead=500e-9):
        self.rg_total = rg_total
        self.rg_total_dis = rg_total_dis
        self.Von = Von
        self.Von_GaN = Von_GaN
        self.Voff = Voff
        self.fallback_V_pl = fallback_V_pl
        self.tDead = tDead

    def __str__(self):
        return f'GateDrive(Rg_tot=%.1fΩ Von=%.1f Voff=%.1f Vpl_fallback=%.1f)' % (self.rg_total, self.Von, self.Voff,
                                                                                  self.fallback_V_pl)


class MosfetSlot():
    """
    Represents a mosfet slot
    """

    def __init__(self, mf: MosfetSpecs, rg_total, rg_total_dis=math.nan, parallel=1, L_csi=0):
        assert not L_csi
        self.mf = mf
        self.rg_total = rg_total
        self.rg_total_dis = rg_total_dis if not math.isnan(rg_total_dis) else rg_total
        self.parallel = parallel
