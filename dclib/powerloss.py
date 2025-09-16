"""

Literature

https://epc-co.com/epc/Portals/0/epc/documents/application-notes/AN030%20Hard%20Switching%20Losses%20Calculation.pdf

https://www.ti.com/lit/an/slyt664/slyt664.pdf
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
from typing import Tuple

import numpy as np

from dslib import round_to_n, dotdict, round_to_n_dec, rel_err
from dslib.mosfet import Qgs2_Qgs_ratio_estimate, MosfetSpecs, GateDrive
from dslib.spec_models import DcDcLoadParams
from maglib.cores import MagneticCoreSpecs
from maglib.wire import d2awg, MaterialResistivity, acr_factor_micrometals, skin_depth

µ0 = 4 * math.pi * 1e-7


class SwitchPowerLoss():
    def __init__(self, P_cl, P_gd, P_sw=math.nan, P_coss=math.nan, P_rr=math.nan, P_dt=math.nan, cond=None):
        """
        :param P_on: conduction loss
        :param P_gd: gate drive loss
        :param P_sw:  switching loss
        :param P_coss: output capacitance loss
        :param P_rr:  reverse recovery loss
        :param P_dt:  dead-time loss during body diode conduction
        """
        self.P_cl = P_cl
        self.P_sw = P_sw
        self.P_coss = P_coss
        self.P_rr = P_rr
        self.P_gd = P_gd
        self.P_dt = P_dt

        self._cond = cond

    def get_cond(self, tag):
        if not self._cond:
            return {}
        cond = {}
        t = '_' + tag.split('_')[-1]
        for k, v in self._cond.items():
            if k.endswith(t):
                cond.update(v)
        return cond

    def values(self):
        d = self.__dict__.copy()
        d.pop('_cond', None)
        return d.values()

    def items(self):
        d = self.__dict__.copy()
        d.pop('_cond', None)
        return d.items()

    def parallel(self, n=2):
        """
        Compute total power loss for n parallel switches.

        For P_sw we assume that the fastest switch takes all the losses

        :return:
        """
        return SwitchPowerLoss(
            P_cl=self.P_cl / n * 0.9,  # HS: one switch takes most of the dynamic load, the rest stay cooler
            P_sw=self.P_sw,
            P_coss=self.P_coss * n,
            P_rr=n * self.P_rr,
            P_gd=n * self.P_gd,
            P_dt=self.P_dt,  # Vsd body diode voltage drop
            cond=self._cond,
            # P_coss=n * self.P_coss,
        )

    def buck_hs(self):
        """
        The attributed (not dissipated) power loss when used as high-side (control) switch in buck topology.
        :return:
        """
        p = self.P_sw + self.P_cl + self.P_gd + self.P_coss
        return p

    def buck_ls(self):
        # attributed (not dissipated)
        # P_rr and P_coss is induced but not self-dissipated!
        p = self.P_rr + self.P_cl + self.P_gd + self.P_dt + self.P_coss
        # Qoss is recovered, not lost!
        return p

    def sum(self):
        return sum(v for v in self.values() if not math.isnan(v))

    def __iter__(self):
        return iter(self.values())


def mosfet_switching_trf(dc: DcDcLoadParams, mf: MosfetSpecs):
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


def Rds_on(mf: MosfetSpecs, Id, Tj):
    # TODO https://application-notes.digchip.com/070/70-41484.pdf (pg5)
    # Rds_on(Tj) = Rds_on(Tj=25°C) * (1+alpha/100)**(Tj-25°C)

    # TODO Rds_on(Id) model
    # mostly constant?

    if math.isnan(Tj):
        # this is a rough approximation from looking at various datasheets from different mfn
        return mf.Rds_on * 1.35

    assert Tj == 25
    return mf.Rds_on


def dcdc_buck_hs(dc: DcDcLoadParams, mf: MosfetSpecs, gd: GateDrive, Tj=math.nan,
                 ls_Qoss=0, Lcsi=0,
                 use_datasheet_timings=False):
    # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/power_loss_appli-e.pdf
    # https://www.richtek.com/Design%20Support/Technical%20Document/AN009#Ripple%20Factor

    assert mf.Qg is not None, 'Qg must be set ' + mf.__repr__()
    assert mf.Qrr is not None, 'Qrr must be set ' + mf.__repr__()
    assert math.isnan(dc.Iripple) or dc.Iripple > 0

    if gd.rg_total < mf.Rg:
        warnings.warn('Rg_total %.1f < MF internal Rg %.1f' % (gd.rg_total, mf.Rg))

    i_rms2 = dc.D_buck * dc.Io_mean_squared_on

    # TODO https://application-notes.digchip.com/070/70-41484.pdf

    if Lcsi > 0:
        assert ls_Qoss > 0
        tr, tf, t_cond = mosfet_hs_sw_timings_lcsi(dc, mf, gd=gd,
                                                   ls_Qoss=ls_Qoss,
                                                   Lcsi=Lcsi,
                                                   )
    else:
        tr, tf = mosfet_hs_sw_timings_hs2(mf, gd)
        t_cond = {}

    if use_datasheet_timings:
        tr = max(tr, mf.tRise)
        tf = max(tf, mf.tFall)

    Psw_on = 0.5 * dc.Vi * dc.Io_min * dc.f * tr
    Psw_off = 0.5 * dc.Vi * dc.Io_max * dc.f * tf

    # P_sw=mosfet_switching_trf(dc, mf),

    rds = Rds_on(mf, dc.Io, Tj)

    # for Coss the HS contribution is the energy stored in Coss
    # which is wasted in its own channel during turn-on
    # mf.Coss is Coss at ~V_bus. Coss is ~1/sqrt(V)
    # https://elprivod.nmu.org.ua/files/converters/Robert_Erikson_fundamentals-of-power-electronics-3n_2020.pdf#page=138

    # TODO compute Coss at given dc.Vi, for 80V fets, this is given at 40V, Coss is ~1/sqrt(V)
    # TODO consider dc.Vi for Coss loss
    # instead of: 2 / 3 * mf.Coss * dc.Vi ** 2 * dc.f
    # use:        2 / 3 * mf.Coss * dc.Vi ** (3/2) * mf.Coss_V0 ** .5 * dc.f,

    return SwitchPowerLoss(
        P_cl=i_rms2 * rds,  # conduction loss
        P_sw=(Psw_on + Psw_off),
        P_dt=0,  # body diode never conducts
        P_rr=0,  # body diode never conducts
        P_gd=(gd.Von - gd.Voff) * dc.f * 2 * mf.Qg,
        P_coss=2 / 3 * mf.Coss * dc.Vi ** 2 * dc.f,  # 2/3 comes from integration of Coss(V)
        cond=dict(
            P_sw=dict(
                **t_cond,
                tr=round_to_n(tr, 2), tf=round_to_n(tf, 2),
                P_on=Psw_on,
                P_off=Psw_off),
            P_cl=dict(
                Rds=rds, I=i_rms2 ** .5,
            ),
            P_gd=dict(Qg=mf.Qg),
            P_coss=dict(Coss=mf.Coss),
        ),
    )


def dcdc_buck_ls(dc: DcDcLoadParams, mf: MosfetSpecs, gd: GateDrive, Tj=math.nan, Qrr_temp_rise=1.2):
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
        vsd = abs(mf.Vsd)

    Qrr_eff = mf.Qrr * Qrr_temp_rise  # Qrr temp rise 63 + ((75-25) * 0.25) ~1.2
    # TODO Qrr di/dit, Id, (IPT025N15NM6ATMA1)
    # TODO https://application-notes.digchip.com/070/70-41484.pdf
    # TODO Qrr(didt) https://www.mouser.com/datasheet/2/268/mscos08164_1-2275581.pdf#page=7

    rds = Rds_on(mf, dc.Io, Tj)  # temp rise Tj=100°C

    if mf.QgdQgsRatio > 1:
        warnings.warn('%s: Qgd/Qgs %.1f > 1! LS might suffer from self turn-on' % (mf.part, mf.QgdQgsRatio))

    # charge in Coss is recovered during discharge
    # the only loss is the during turn-off through the charge "resistor"
    # P_coss = V_bus * Qoss - Eoss
    # Eoss = 2 / 3 * Coss * V_bus ** 2 * dc.f
    #

    qoss = 2 * mf.Coss * dc.Vi
    return SwitchPowerLoss(
        P_cl=(1 - dc.D_buck) * dc.Io_mean_squared_on * rds,
        P_dt=vsd * dc.Io * (dc.tDead * 2) * dc.f,  # TODO https://www.ti.com/lit/an/slyt664/slyt664.pdf
        P_rr=dc.Vi * dc.f * Qrr_eff,  # this is dissipated in HS
        P_gd=(gd.Von - gd.Voff) * dc.f * 2 * mf.Qg,
        P_sw=0,  # negligible TODO diode?
        P_coss=4 / 3 * mf.Coss * dc.Vi ** 2 * dc.f,  # charge is recovered, but charging over a resistance path
        cond=dict(
            R_on=dict(Rds=rds),
            P_dt=dict(Vsd=vsd, tDead=dc.tDead),
            P_rr=dict(Qrr=Qrr_eff),
            P_gd=(dict(Qg=mf.Qg)),
            P_coss=dict(Coss=mf.Coss, Qoss=qoss),
        )
    )


P2 = Tuple[float, float]


class CoilSpecs():
    def __init__(self, Rdc, L0=None, turns=None, wire_diameter=None, wire_awg=None, wire_strands=None,
                 core: MagneticCoreSpecs = None):
        """

        :param L0: inductivity in H
        :param Rdc: ESR in Ω
        :param turns: number of turns
        """
        # TODO skin effect

        if turns is None:
            assert L0 > 0
            turns = round_to_n((L0 / core.A_L) ** .5, 3)

        l = turns ** 2 * core.A_L
        if L0 is None:
            L0 = round_to_n(l, 3)

        self.Rdc = Rdc
        self.turns = turns

        if wire_awg:
            assert wire_diameter is None
            from maglib.wire import awg2d
            wire_diameter = awg2d(wire_awg)

        self.wire_diameter = wire_diameter

        self.wire_strands = wire_strands

        self.core: MagneticCoreSpecs = core
        self.L0 = L0

        assert abs(rel_err(L0, l)) < 0.05, (L0, l)

    def Ldc(self, dc_bias_current, no_raise=False):
        tpl = (self.turns / self.core.l_e)
        Hdc = tpl * dc_bias_current
        Ldc = self.L0 * self.core.mat.permeability_dc_bias(Hdc, no_raise=no_raise) / self.core.mat.mu_r
        return Ldc

    def __repr__(self):
        return f'CoilSpecs(Rdc={round_to_n_dec(self.Rdc, 3)}, L={round_to_n_dec(self.L0, 3)}, T={self.turns}, core={(self.core)})'

    @property
    def awg(self):
        return round(d2awg(self.wire_diameter), 1)

    @property
    def bundle_diameter(self):
        # https://calculator.academy/bundle-diameter-calculator/
        return (4 * (self.wire_strands * (math.pi * self.wire_diameter ** 2 / 4)) / math.pi) ** .5

    def micrometals_analyzer(self, dc: DcDcLoadParams):
        strands = self.wire_strands or 1
        awg = self.awg
        mpn = self.core.mpn
        stack = 1
        if mpn.startswith('2s('):
            stack = 2
            mpn = mpn[3:-1]
        args = dict(
            name="",
            inductor_type="D",  # D=DC inductor
            l=50,  # ??
            iavg=round(dc.Io, 2),
            vin_rms_min=dc.Vi - dc.Vo,  # VLon = Vin - Vout (buck)
            vin_rms_max=dc.Vo,  # VLoff = Vout (buck)
            f_switching=int(round(dc.f)),
            ambient_temp=40,
            max_temp_rise=50,
            temp_rise=1,
            min_l=40,
            part_type="A",
            winding="F",
            num_cores=stack,
            wire_strands=strands,
            full_ratio=0.90,
            min_awg=30,
            pct_win_fill_max_e=100,
            energy_cost=0.2,
            continuous_use=0.5,
            conductor_material="Cu",
            n=self.turns,
            strandsxawg=f'{strands}xAWG%23{awg}',
            partnumber=mpn,
            awg=awg,
        )
        import urllib.parse
        u = "https://www.micrometals.com/design-and-applications/design-tools/inductor-analyzer/?"
        u += urllib.parse.urlencode(args)
        return u


def dcdc_buck_coil(dc: DcDcLoadParams, coil: CoilSpecs):
    """

    * Wire Loss
        * dcr wire loss
        * skin effect TODO
    * Core Loss
        * hysteresis loss (core volume) x (area of B-H hysteresis loop) ~ peak ac flux density ΔB
            ΔB = 2Bpk = B_acmax - B_acmin (https://www.mag-inc.com/design/design-guides/powder-core-loss-calculation)
        * eddy current loss (i2r losses inside core material) ~ f^2

    Well designed coils have a 80/20% distribution of Wire and Core Loss


    ref https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_converter_efficiency_app-e.pdf

    ref https://elprivod.nmu.org.ua/files/converters/Robert_Erikson_fundamentals-of-power-electronics-3n_2020.pdf#page=433
    ref https://ieeexplore.ieee.org/document/1196712
        * data sheet data from manufactureres is for sinusodial excitation
        * DC bias affects loss https://sci-hub.se/10.1109/41.649940
                                https://sci-hub.se/10.1109/APEC.1996.500481


    https://www.psma.com/sites/default/files/uploads/tech-forums-magnetics/presentations/2012-apec-134-core-loss-modeling-inductive-components-employed-power-electronic-systems.pdf

    :param dc:
    :param coil:
    :return:
    """

    assert math.isnan(dc.Iripple) or dc.Iripple > 0
    # assert abs(rel_err(dc.L, coil.L0)) < 0.05

    # require ripple current since core loss computation needs it anyways
    assert math.isfinite(dc.Iripple), "no ripple current"

    if math.isfinite(dc.Iripple):
        assert dc.Iripple < 2 * dc.Io, 'CCM required, DCM not supported TODO'
        I_ms = (dc.Io ** 2 + (dc.Iripple ** 2 / 12))  # https://www.ti.com/lit/an/slvaeq9/slvaeq9.pdf#page=5
    else:
        I_ms = dc.Io ** 2

    P_dcr = I_ms * coil.Rdc

    # acf, sd = ac_resistance_factor(MaterialResistivity.CopperAnnealed.value, coil.wire_diameter, dc.f)
    # rac = (acf - 1) * coil.Rdc

    F_se, F_pe = acr_factor_micrometals(MaterialResistivity.CopperAnnealed.value, coil.wire_diameter, dc.f,
                                        coil.wire_strands, coil.turns,
                                        id=coil.core.shape.ID, od=coil.core.shape.OD,
                                        )
    rac = (1 + F_se + F_pe) * coil.Rdc
    sd = skin_depth(MaterialResistivity.CopperAnnealed.value, dc.f)

    # notice that this is independent from duty cycle
    # https://www.mouser.com/pdfDocs/Coilcraft_inductorlosses.pdf
    P_acr = dc.Il_ac_rms2 * rac

    # https://www.quora.com/What-is-the-formula-for-calculating-peak-value-of-flux-density-of-an-inductor
    # TODO DC bias https://www.ti.com/lit/an/snva038b/snva038b.pdf?ts=1730558298197
    # B_pk = (dc.Vi - dc.Vo) * dc.ton_buck / (coil.turns * coil.core.A_e)  # peak flux density in Tesla
    # B_pk2 = coil.L * dc.Io_max / (coil.turns * coil.core.A_e)  # peak flux density in Tesla

    # https://www.eevblog.com/forum/projects/toroidal-core-for-high-power-buck-converter/msg3085987/#msg3085987
    """
    Bmax = (ueff*uo*N*Ipk)/ lc
    ueff = effective permeability
    uo = free space permeability
    N = turns
    Ipk = peak current
    lc = mean core length
    """

    # method 2
    """
    H_dc = tpl * dc.Io
    Hpp = tpl * dc.Iripple
    Bpk2 = .5 * µ0 * coil.core.mat.permeability_dc_bias(H=H_dc) * Hpp

    Bpk22 = .5 * µ0 * coil.core.mat.permeability_dc_bias(H=H_dc) * Hpp

    ur = coil.core.mat.permeability_dc_bias(H=H_dc)

    Lbias = coil.L * ur / coil.core.mat.mu_r
    Iripple_bias = dc.Iripple / (ur / coil.core.mat.mu_r)  # TODO fix model
    # ^ TODO fix mode

    # TODO confirm Iripple_bias with measurement
    Hpk_ac = coil.turns * Iripple_bias / (coil.core.l_e)  # Eq13.14 Fundamentals of Power Electronics. 2nd, p497
    # ^ hysteresis loss is modeled with p2p ac ripple

    Bpk_ac = ur * µ0 * Hpk_ac  # peak ac flux density [T]
    B_pk = ur * µ0 * Hpk_ac
    """
    from maglib.powerloss import core_loss_from_dc_bias

    # P_core1, Bpk1, cld1 = core_loss_from_dc_magnetization(dc, coil)  # method 1
    P_core1, Bpk1, cld1 = 0, 0, 0
    P_core2, Bpk2, cld2 = core_loss_from_dc_bias(dc, coil)  # method 2

    # TODO the mac-inc methods do not consider core saturation
    # L drops with rising dc bias current, which will increase ripple current and Bpk and hysteresis loss

    return dotdict(
        P_dcr=P_dcr,
        P_acr=P_acr,
        P_core=max(P_core1, P_core2),
        get_cond=lambda k: dict(
            P_dcr=dict(Rdc=coil.Rdc),
            P_acr=dict(Rac=rac, δ=sd, Fskin=F_se, Fprox=F_pe),
            P_core=dict(
                ΔI=dc.Iripple,
                Bpk=max(Bpk1, Bpk2),  # peak ac flux density
                CLD=round_to_n_dec(max(cld1, cld2), 3) + 'mW/cm3',  # core loss density
                mthd=2 if cld2 > cld1 else 1,
            ),
        ).get(k)
    )


def dcdc_buck_cout(dc: DcDcLoadParams, Z_cin: float, Z_cout: float):
    i_ac_rms2 = dc.Il_ac_rms2

    i_cin_rms = dc.Io * ((dc.Vi - dc.Vo) * dc.Vo) ** .5 / dc.Vi

    # cout & cin:
    # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_converter_efficiency_app-e.pdf#page=4

    return dotdict(
        P_cin=i_cin_rms ** 2 * Z_cin,
        P_cout=i_ac_rms2 * Z_cout,
        get_cond=lambda k: dict(
            P_cin=dict(Z=round_to_n_dec(Z_cin, 2), Irms=i_cin_rms),
            P_cout=dict(Z=round_to_n_dec(Z_cout, 2), Irms=i_ac_rms2 ** .5),
        )[k],
    )


def mosfet_hs_sw_timings_hs(hs: MosfetSpecs, gd: GateDrive):
    # https://www.ti.com/lit/an/slpa009a/slpa009a.pdf#page=3  3.1.1
    assert math.isnan(hs.Qsw) or 0 < hs.Qsw < 1000e-9
    rg_total = np.nanmax([hs.Rg, gd.rg_total])
    vpl = gd.fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl
    # TODO igon1 + igon2
    assert vpl < gd.Von, "Vpl >= VGS"
    ig_on = (gd.Voff - vpl) / rg_total
    ig_off = (vpl - gd.Voff) / rg_total
    tr = hs.Qsw / ig_on
    tf = hs.Qsw / ig_off
    return tr, tf


def mosfet_hs_sw_timings_hs2(hs: MosfetSpecs, gd: GateDrive):
    # https://www.tij.co.jp/jp/lit/an/slvaeq9/slvaeq9.pdf#page=4
    # SLVAEQ9–July 2020
    # An Accurate Approach for Calculating the Eff. of a Synch. Buck Converter Using the MOSFET Plateau Voltage
    # equation (6) appears to be wrong.

    assert math.isnan(hs.Qsw) or 0 < hs.Qsw < 1000e-9
    rg_total = np.nanmax([hs.Rg, gd.rg_total])

    vpl = gd.fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl
    vgs_th = vpl * (hs.Qg_th / hs.Qgs)
    v_ir = .5 * (vpl + vgs_th)  # average voltage charging Qgs2
    tr = (hs.Qgs2 / (gd.Von - v_ir) + hs.Qgd / (gd.Von - vpl)) * rg_total  # (5)
    tf = (hs.Qgs2 / (v_ir - gd.Voff) + hs.Qgd / (vpl - gd.Voff)) * rg_total  # (6) *corrected
    return tr, tf


def mosfet_hs_sw_timings_hs_vishay(hs: MosfetSpecs, gd: GateDrive):
    # https://www.vishay.com/docs/73217/an608a.pdf
    # Cgd(Vds)
    # needs Ciss(at dc.Vi)

    assert math.isnan(hs.Qsw) or 0 < hs.Qsw < 1000e-9
    rg_total = np.nanmax([hs.Rg, gd.rg_total])
    vpl = gd.fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl
    vgs_th = vpl * (hs.Qg_th / hs.Qgs)
    v_ir = .5 * (vpl + vgs_th)  # average voltage charging Qgs2
    tr = (hs.Qgs2 / (gd.Von - v_ir) + hs.Qgd / (gd.Von - vpl)) * rg_total  # (5)
    tf = (hs.Qgs2 / (v_ir - gd.Voff) + hs.Qgd / (vpl - gd.Voff)) * rg_total  # (6) *corrected
    return tr, tf


def mosfet_hs_sw_timings_lcsi(dc: DcDcLoadParams, hs: MosfetSpecs, ls_Qoss, gd: GateDrive, Lcsi: float,
                              fallback_V_pl=math.nan):
    # loss with L_csi considerations
    # https://www.ti.com/lit/an/slpa009a/slpa009a.pdf
    Qgs2 = hs.Qgs2
    rg_total = np.nanmax([hs.Rg, gd.rg_total])
    vpl = fallback_V_pl if math.isnan(hs.V_pl) else hs.V_pl

    # pw on
    ig1_on = (gd.Von - vpl) / (rg_total + (Lcsi * dc.Io_min / Qgs2))
    a = (Lcsi * ls_Qoss / hs.Qgd ** 2) if Lcsi else 0
    b = rg_total
    c = -(gd.Von - vpl)
    ig2_on = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    tr = (Qgs2 / ig1_on + hs.Qgd / ig2_on)

    # pw off
    ig1_off = (vpl - gd.Voff) / (rg_total + Lcsi * dc.Io_max / Qgs2)
    c = - (vpl - gd.Voff)
    ig2_off = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    tf = (Qgs2 / ig1_off + hs.Qgd / ig2_off)

    return tr, tf, dict(Lcsi=Lcsi, Qoss_ls=ls_Qoss, Qsw=Qgs2 + hs.Qgd, Vpl=vpl)


def capacitor_out():
    # https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_converter_efficiency_app-e.pdf
    raise NotImplemented("see dcdc_buck_cout()")


def tests():
    dcdc = DcDcLoadParams(24, 12, 40_000, 500e-9, 10, iripple=1e-9)
    gd = GateDrive(1e-6, 12, fallback_V_pl=4)
    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9, Qsw=2e-9,
                     Qgs=2e-9, Qgs2=2e-9 * Qgs2_Qgs_ratio_estimate, Coss=0)

    loss = dcdc_buck_hs(dcdc, mf, gd=gd, Rds_temp_rise=1)
    assert loss.P_cl == (10 ** 2) * 10e-3 * .5
    assert loss.P_sw == 24 * 10 * 40e3 * 40e-9
    assert loss.P_gd == (12 * 40e3 * 2 * 100e-9)
    assert math.isnan(loss.P_dt) or loss.P_dt == 0
    assert loss.buck_hs() == loss.P_cl + loss.P_sw + loss.P_gd + loss.P_coss

    loss = dcdc_buck_ls(dcdc, mf, gd, rds_temp_rise=1, Qrr_temp_rise=1)
    assert loss.P_cl == (10 ** 2) * 10e-3 * .5
    assert loss.P_dt == 1 * 10 * (500e-9 * 2) * 40e3
    assert loss.P_rr == 24 * 40e3 * 120e-9
    assert loss.P_gd == (12 * 40e3 * 2 * 100e-9)
    assert math.isnan(loss.P_sw) or loss.P_sw == 0
    assert loss.buck_ls() == loss.P_rr + loss.P_cl + loss.P_gd + loss.P_dt

    dcdc = DcDcLoadParams(vi=62, vo=27, pin=800, f=40e3, ripple_factor=0.3, tDead=500e-9)
    mf = MosfetSpecs.from_mpn('DMT10H9M9SCT', 'diodes')
    l = mosfet_hs_sw_timings_hs(mf, GateDrive(6, 12, fallback_V_pl=4.5))
    pr = 0.5 * dcdc.Vi * dcdc.Io_min * dcdc.f * l[0]
    pf = 0.5 * dcdc.Vi * dcdc.Io_max * dcdc.f * l[1]
    assert abs(pr - 0.3) < 0.1
    assert abs(pf - 0.7) < 0.1

    l2 = mosfet_hs_sw_timings_hs2(mf, GateDrive(6, 12, fallback_V_pl=4.5))
    assert l2

    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9,
                     Qgd=80e-9,
                     Qgs=2e-9,
                     Qgs2=1e-9,
                     Coss=0)
    l1 = mosfet_hs_sw_timings_hs(mf, GateDrive(5, fallback_V_pl=4))

    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9,
                     Qgd=80e-9,
                     Qgs=4e-9,  # timings are independent of Qgs
                     Qgs2=1e-9,
                     Coss=0)
    l2 = mosfet_hs_sw_timings_hs(mf, GateDrive(5, fallback_V_pl=4))

    assert l1 == l2

    mf = MosfetSpecs(100, 10e-3, 100e-9, 40e-9, 40e-9, 120e-9, 10e-9,
                     Qgd=80e-9,
                     Qgs=2e-9,
                     Qgs2=1e-9,
                     Coss=0)
    assert mf.Qg_th == 1e-9

    tr, tf = mosfet_hs_sw_timings_hs2(mf, GateDrive(5, 10, fallback_V_pl=4))
    tr_ref = (mf.Qgs2 / (10 - .5 * (4 + 2)) + mf.Qgd / (10 - 4)) * 5
    assert abs(rel_err(tr, tr_ref)) < 1e-5
    assert tf == (mf.Qgs2 / (.5 * (4 + 2)) + mf.Qgd / (4)) * 5

    tr1, tf1 = mosfet_hs_sw_timings_hs(mf, GateDrive(5, fallback_V_pl=4))
    assert abs(rel_err(tr, tr1)) < 1e-2
    assert abs(rel_err(tf, tf1)) < 1e-2


def tests_lcsi():
    dcdc = DcDcLoadParams(70, 35, 40_000, 10, 500e-9, 33, ripple_factor=0.01)
    hs = MosfetSpecs.from_mpn('CSD19503KCS', mfr='ti')
    # ls = MosfetSpecs.from_mpn('CSD19503KCS', mfr='ti')
    hs.Qg_th = 6.1e-9
    hs.Qgs = 9.8e-9
    hs.Qoss = 71e-9
    hs.Qgd = 5.4e-9
    hs._Vpl = 4.2
    hs._Qgs2 = math.nan

    """
        hs.Qg_th = 24
    hs.Qgs = 37
    hs.Qoss = 335
    hs.Qgd =17
    """

    tr, tf = mosfet_hs_sw_timings_hs(hs, gd=GateDrive(6))
    assert abs(tr) < abs(tf)
    assert 0.6 < (tr / tf) < 0.9

    ls = hs
    tr_lcsi0, tf_lcsi0, _ = mosfet_hs_sw_timings_lcsi(dcdc, hs, ls, gd=GateDrive(6), Lcsi=.01e-9)
    assert abs(tr - tr_lcsi0) / tr < 0.05
    assert abs(tf - tf_lcsi0) / tf < 0.05

    tr_lcsi2, tf_lcsi2, _ = mosfet_hs_sw_timings_lcsi(dcdc, hs, ls, gd=GateDrive(6), Lcsi=2e-9)
    assert tr_lcsi2 < tf_lcsi2
    assert tr_lcsi2 > tr_lcsi0
    assert tf_lcsi2 > tf_lcsi0


def plot_vpl_curve():
    dcdc = DcDcLoadParams(70, 35, 40_000, 10, 500e-9, 33, ripple_factor=0.01)
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

    # Pon, Poff = mosfet_hs_sw_timings_hs(dcdc, hs, rg_total=6)


if __name__ == '__main__':
    tests()
    tests_lcsi()
