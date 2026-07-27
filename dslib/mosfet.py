import math
import warnings

from dslib import isnum, rel_err, round_to_n_dec

# Rds_on[mOhm] * Qg[nC]. See the assert in MosfetSpecs.__init__ for how these were chosen.
# Asserted in two places (once in SI units) -- keep them derived from here, not re-typed.
# FOM_MIN is 20, not 10, because 20 is what the code ACTUALLY enforced before these two
# asserts were unified: the SI-unit copy used 2e-11 C*Ohm, which is FoM 20, and both ran.
# Collapsing them onto the more permissive 10 would have been a silent loosening of the
# bound that matters most -- the LOWER one is what catches a 1000x-LOW Rds_on, since it
# maps a normal FoM of ~600 onto 0.6. One record sits in the gap (IQEH50NE2LM7UCGSC,
# FoM 13.5); it was already failing before, so 20 preserves behaviour rather than changing
# it. Unifying duplicated bounds must take the STRICTER value, or the merge is a quiet
# regression dressed as a cleanup.
FOM_MIN = 20.0
FOM_MAX = 2e5

Qgs2_Qgs_ratio_estimate = 0.55  # 0.3 ... 0.6


def attach_qrr_registries(specs: 'MosfetSpecs', mfr, mpn):
    """Fill `specs.qrr_cond` / `specs.qrr_points` from the curated registries, in place.

    dslib.store.load_parts() does this for specs unpickled from the parts DB. Specs built
    fresh from parsed datasheet fields (dslib.field.get_mosfet_specs — the path the whole
    main.py pipeline runs on) never went through load_parts, so they arrived with both
    attributes None and MosfetSpecs.Qrr_op could only ever raise LMFitError on them. Any
    operating-point Qrr consumer wired into that pipeline would have degraded to the flat
    datasheet value for 100% of parts while looking like it was doing something.

    Fill-if-absent, and each registry imported under its OWN try/except so a broken or
    renamed qrr_points_for cannot silently disable the qrr_cond attach as well.
    """
    if specs is None:
        return specs
    try:
        from dslib.qrr_conditions import qrr_conditions_for
    except ImportError:
        qrr_conditions_for = None
    if qrr_conditions_for is not None and not getattr(specs, 'qrr_cond', None):
        cond = qrr_conditions_for(mfr, mpn)
        if cond:
            specs.qrr_cond = cond
    try:
        from dslib.qrr_points import qrr_points_for
    except ImportError:
        qrr_points_for = None
    if qrr_points_for is not None and not getattr(specs, 'qrr_points', None):
        pts = qrr_points_for(mfr, mpn)
        if pts:
            specs.qrr_points = pts
    return specs


class MosfetSpecs:

    def __init__(self, Vds_max, Rds_on, Qg, tRise, tFall, Qrr, trr=None, Qgd=None, Qgs=None, Qgs2=None, Qg_th=None,
                 Qsw=None,
                 Vpl=None, Vsd=None,
                 Coss=math.nan, Coss_Vds=None,
                 Rg=math.nan, Id=math.nan, part=None, coss_curve=None,
                 Id_gc=math.nan, gfs_min=math.nan, gfs_typ=math.nan, Id_gfs=math.nan,
                 Vgs_th=math.nan, Id_vsd=math.nan):
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
        # Optional datasheet Coss(V)/Crss(V) curve: [(Vds_V, Coss_pF, Crss_pF), ...] or None.
        # Attached by load_parts() from dslib.coss_curves (by MPN). Consumers use it for a
        # curve-faithful output cap; None -> they warn and fall back to the scalar Coss.
        self.coss_curve = coss_curve
        # Optional datasheet Ciss(V) curve: [(Vds_V, Ciss_pF), ...] or None.
        # Attached by load_parts() from dslib.coss_curves CISS_CURVES (by MPN). Together
        # with the Crss column of coss_curve it yields a datasheet Cgs(V) = Ciss - Crss;
        # None -> consumers keep their gate-charge-partition Cgs basis (Qgs/Vpl).
        self.ciss_curve = None
        # Optional datasheet reverse-recovery TEST CONDITIONS: dict(IF, didt, VR, Tj) or None.
        # Attached by load_parts() from dslib.qrr_conditions (by MPN). Qrr/trr below are
        # scalars measured AT this operating point; a consumer that needs to re-scale them
        # (Qrr ~ sqrt(di/dt)) or fit a charge-control diode model needs it. See fl4p/fetlib#37.
        self.qrr_cond = None
        # Optional MULTI-di/dt reverse-recovery rows: [dict(IF, didt, VR, Tj, Qrr, trr), ...]
        # or None. Attached by load_parts() from the generated dslib.qrr_points (by MPN).
        # Parts carrying two same-IF rows get a per-part (tau, TM, q0) fit in Qrr_op —
        # the part's own di/dt data replaces the global QRR_QOSS_FRACTION assumption.
        self.qrr_points = None
        # Optional human-verified saturation-channel Vth_eff(T)+K(T) fit.
        # Attached by load_parts() from dslib.channel_temp_specs; it deliberately
        # does not replace or modify the independent Rds(on,Tj) behavior.
        self.channel_temp = None
        self.tRise = tRise or math.nan
        self.tFall = tFall or math.nan
        self.Qrr = math.nan if Qrr is None else Qrr  # GaN have Qrr = 0
        self.Vsd = Vsd  # body diode forward
        self.trr = trr

        # FoM = Rds_on[mOhm] * Qg[nC]. Bounds are a scale sanity check, not a quality metric.
        #
        # The ceiling was 20000, which is a low/mid-voltage assumption: FoM grows steeply with
        # Vds, so 600-800 V parts legitimately land far above it. Measured over 5593 DB records
        # (p50=627, p90=5250, p99=18050, p99.9=63700) 46 records exceed 20000, and above the
        # real parts there is a clean gap: IXFN27N80 at 1.2e5 and BSP179 at 1.1e5, then nothing
        # until XR65R110T at 6.4e5 -- which is genuinely wrong, storing 14 Ohm where its own
        # MPN and PDF say 0.11/0.14 Ohm (a dropped decimal, not a unit error). 2e5 sits in that
        # gap: every real part passes and the one bad record still fails.
        #
        # Two things this comment previously got wrong, both found in review:
        #   - It claimed STF40N60M2/STFW40N60M2 also fail here. They do not. Their Rds_on field
        #     is corrupt (88 Ohm) but Rds_on_10v=0.088 Ohm takes precedence in get_mosfet_specs,
        #     so the constructor never sees the bad value. Checking a raw field is not the same
        #     as checking what the constructor is actually handed.
        #   - IXFN27N80's true row is 0.30 Ohm; the DB selected the adjacent 25N80 0.35 Ohm row,
        #     so its real FoM is ~1.05e5. The headroom argument survives, the number was off.
        #
        # At 20000 this rejected 43 records -- every one of them a part whose Rds_on had just
        # been CORRECTED from a 1000x-low value. The guard was inverted for exactly the class it
        # should catch: the corrupt 0.16 mOhm reading of IXTX46N50L gave FoM=41.6 and sailed
        # through, while the true 160 mOhm gives 41600 and was rejected.
        #
        # The LOWER bound is what catches the 1000x-low class (it maps a normal FoM of ~600 onto
        # 0.6) -- see FOM_MIN, which is 20 because that is what the pair of asserts enforced
        # before they were unified. Raising the ceiling costs upper-bound detection only for
        # parts whose true FoM already exceeds 200. Note a failure here DELETES the part and
        # purges its cache (main.py:410), so an empirical upper gap of this kind is better
        # served report-only (dslib/validate.py) than as a deleting assert; the 2e5 value is
        # supported, the delete-on-failure policy around it is not.
        fom = Rds_on * Qg * 1e3 * 1e9
        assert math.isnan(fom) or FOM_MIN < fom < FOM_MAX, ("fom out of range", fom, Rds_on, Qg)

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

        # The SAME check as the `fom` assert above, in SI units: Qg[C]*Rds_on[Ohm] is the FoM
        # divided by 1e12. It was drifting independently (lower bound 2e-11 == FoM 20, vs 10
        # above), so both now derive from one pair of constants. Do not re-tighten one alone.
        assert math.isnan(Qg * Rds_on) or FOM_MIN < (Qg * Rds_on) * 1e12 < FOM_MAX, (
            Qg, Rds_on, Qg * Rds_on)

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

        # Gate/channel anchor specs (see dslib/gate_specs.py). Id_gc is the gate-charge
        # TABLE's test current — the current Qgs/Qg_th/Qgd and Vplateau were measured at —
        # NOT the ID_25 continuous rating stored in `Id` (1.4-4x apart on parts checked).
        # gfs (usually a MIN spec, at Id_gfs) and Vgs_th (TYP) back the channel-derivation
        # cross-checks. NaN when the datasheet/curation doesn't supply them.
        # NO range asserts here: these are AUXILIARY anchors, and an assert in this
        # ctor drops the part's ENTIRE spec object at DB-rebuild time (field.py wraps
        # get_mosfet_specs in except->None) over a field whose consumers already refuse
        # on bad values (loss models.derive_channel). field.py range-sanitizes to NaN
        # with a warning instead.
        self.Id_gc = Id_gc if Id_gc is not None else math.nan
        self.gfs_min = gfs_min if gfs_min is not None else math.nan
        self.gfs_typ = gfs_typ if gfs_typ is not None else math.nan
        self.Id_gfs = Id_gfs if Id_gfs is not None else math.nan
        self.Vgs_th = Vgs_th if Vgs_th is not None else math.nan
        self.Id_vsd = Id_vsd if Id_vsd is not None else math.nan

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

    def Qrr_op(self, IF, didt, Tj=25.0, detail=False):
        """Predicted reverse-recovery charge [C] at an OPERATING point (IF [A],
        didt [A/s], Tj [degC]) — fl4p/fetlib#37. The flat `self.Qrr` is only valid at
        the datasheet test condition; this extrapolates it with the Lauritzen-Ma
        charge-control fit (dslib/qrr_model.py: exact at the calibration point,
        linear-ish in IF, sub-linear in di/dt, tau(Tj) via an ASSUMED exponent —
        results at Tj != the datasheet Tj are model guesses, flagged via
        detail=True -> dict(..., tj_extrapolated=True)).

        Parts with multi-di/dt datasheet rows (dslib/qrr_points.py, attached as
        `qrr_points`) get a per-part two-point (tau, TM, q0) fit — their own di/dt
        data pins the capacitive share of the Qrr integral instead of the global
        QRR_QOSS_FRACTION assumption. Contamination-dominated pairs that admit no
        two-point fit fall back EXPLICITLY to the single-point path (detail=True
        carries method='2pt'/'1pt' and the fallback reason).

        GaN (Qrr == 0) returns 0.0. Raises qrr_model.LMFitError when the part has no
        curated test conditions (dslib/qrr_conditions.py) or an LM-inconsistent
        datasheet pair — fail loud rather than invent an operating point.
        """
        from dslib import qrr_model
        if self.Qrr == 0:
            return dict(Qrr=0.0, trr=0.0, irrm=0.0, td=0.0, tau=0.0, TM=0.0,
                        tj_extrapolated=False, fit=None,
                        method='zero') if detail else 0.0
        if not hasattr(self, "_lm_fit_cache"):
            self._lm_fit_cache = {}
        # getattr: an instance unpickled from a parts-lib written before the field
        # existed bypasses __init__ and would AttributeError instead of LMFitError.
        points = getattr(self, "qrr_points", None)
        fallback_reason = None
        if points:
            try:
                p = qrr_model.qrr_op_2pt(points, IF, didt, Tj=Tj,
                                         _fit_cache=self._lm_fit_cache)
                return p if detail else p["Qrr"]
            except qrr_model.LMFitError as e:
                fallback_reason = str(e)  # e.g. Qrr ~flat with di/dt: 1pt only
        p = qrr_model.qrr_op(self.Qrr, self.trr, getattr(self, "qrr_cond", None),
                             IF, didt, Tj=Tj, _fit_cache=self._lm_fit_cache)
        p["method"] = "1pt"
        if fallback_reason:
            p["fallback_from_2pt"] = fallback_reason
        return p if detail else p["Qrr"]

    def FoMqrr_op(self, IF, didt, Tj=25.0):
        """FoMqrr [mΩ*nC] evaluated at an operating point instead of the datasheet
        test condition (fl4p/fetlib#37 item 3) — ranking by this de-biases parts whose
        datasheet Qrr was simply measured at a gentler di/dt or lower IF."""
        return self.Rds_on * self.Qrr_op(IF, didt, Tj) * 1e3 * 1e9  # [mΩ*nC]

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
