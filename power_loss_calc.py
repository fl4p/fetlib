import math
import warnings

import matplotlib.pyplot as plt
import pandas as pd

import dslib.magnetics.cores
from dslib import dotdict, round_to_n_dec
from dslib.field import Field, MpnMfr
from dslib.pdf2txt.parse import parse_datasheet
from dslib.powerloss import dcdc_buck_hs, CoilSpecs, dcdc_buck_coil, dcdc_buck_ls, SwitchPowerLoss
from dslib.spec_models import DcDcSpecs, MosfetSpecs
from dslib.store import parts_db

if __name__ == '__main__':
    """
    TODO
    - losses appear to be too low
    - use LTspice, ngspice
    - consider self turn on?
    """

    """
    Picks
    SUM60020E vishay
    TK6R8A08QM toshiba (switch) Q_sw=13nC
    CSD19506KCS ti (sync)    
    IPP052N08N5AKSA1 infineon (switch) Q_sw=16nC
    CSD19503KCS (switch)
    """

    coil = CoilSpecs(Rdc=6.2e-3,
                     L=46e-6,
                     # turns=19.5,
                     core=dslib.magnetics.cores.KDM_KS130_060A.stack(2),
                     # core=dslib.magnetics.cores.Micrometals_OE_184_060,
                     # core=dslib.magnetics.cores.Micrometals_OE_226_060,

                     )

    ds_ho = parse_datasheet('datasheets/toshiba/TK6R8A08QM.pdf', mfr='toshiba')
    ds_ho.add(Field('Rds_on_10v', math.nan, 5.3e-3, 6.8e-3))
    # fet_ho = ds_ho.get_mosfet_specs()

    # ds_ho = parse_datasheet('datasheets/ti/CSD19501KCS.pdf')
    # ds_ho.add(Field('Rds_on_10v', math.nan, 5.5e-3, 6.5e-3))

    # ds_lo = parse_datasheet('datasheets/onsemi/FDP027N08B.pdf', mfr='onsemi')
    # ds_lo.add(Field('Rds_on_10v', math.nan, 2.21e-3, 2.7e-3))
    # fet_lo = ds_lo.get_mosfet_specs()

    fet_lo: MosfetSpecs = parts_db.load_obj(MpnMfr('infineon', 'IPB017N10N5LFATMA1')).specs
    #fet_ho: MosfetSpecs = parts_db.load_obj(MpnMfr('infineon', 'IPB017N10N5LFATMA1')).specs

    fet_ho: MosfetSpecs = parse_datasheet('datasheets/vishay/SiRA04DP.pdf').get_mosfet_specs()
    fet_ho._Vpl = 2.6

    rg_total = 350 # 4.7

    # fet_ho = MosfetSpecs.from_mpn('TK6R8A08QM', mfr='toshiba')
    # fet_lo = MosfetSpecs.from_mpn('FDP027N08B', mfr='onsemi')

    hs_p = 1


    def compute_losses(pin):

        # dcdc = DcDcSpecs(vi=66, vo=27, pin=800, f=40e3, Vgs=11, tDead=400e-9, L=50e-6)
        # dcdc = DcDcSpecs(vi=66, vo=27, pin=pin, f=40e3, Vgs=11, tDead=400e-9, L=coil.L)
        #dcdc = DcDcSpecs(vi=70, vo=27, io=30, f=40e3, Vgs=11, tDead=100e-9, L=coil.L)
        dcdc = DcDcSpecs(vi=12, vo=5, io=15, f=40e3, Vgs=5, tDead=100e-9, L=coil.L)

        p_hs = dcdc_buck_hs(
            dcdc,
            fet_ho,
            rg_total=rg_total,
            fallback_V_pl=5.4,

            # Lcsi=4e-9,            ls_Qoss=500e-9,  # TODO csd19503 # TODO Qload_HS = Qoss_LS + Qrr_LS ?
            # MosfetSpecs(Rds_on=1e-3, Qg=1e-9, tRise=.5e-9, tFall=.5e-9, Qrr=1e-9)
            # MosfetSpecs(Rds_on=6.8e-3, Qg=39e-9, tRise=39e-9, tFall=46e-9, Qrr=43e-9),  # TK6R8A08QM
            # MosfetSpecs(Rds_on=2.3e-3, Qg=120e-9, tRise=11e-9, tFall=10e-9, Qrr=525e-9),#CSD19506KCS

            # MosfetSpecs.mpn(mpn='TK6R8A08QM', mfr='toshiba')
        )

        p_hs = p_hs.parallel(hs_p)

        p_coil = dcdc_buck_coil(dcdc, coil)

        p_ls = dcdc_buck_ls(dcdc,
                            # MosfetSpecs(Rds_on=2.3e-3, Qg=120e-9, tRise=11e-9, tFall=10e-9, Qrr=525e-9),
                            fet_lo
                            )

        p_misc = dotdict(
            P_mcu=0.7,  # ESP32
            P_csr=1e-3 * dcdc.Io ** 2,  # current sense resistor (burden)
            P_bflow=.75e-3 * dcdc.Io ** 2,  # backflow switch
            P_rpcb=1e-3 * dcdc.Io ** 2,
            P_fuse=1.5e-3 * dcdc.Io ** 2,  # littelfuse 40A blade (1.33mOhm cold)
        )

        return dotdict(hs=p_hs, ls=p_ls, coil=p_coil, misc=p_misc), dcdc


    losses, dcdc = compute_losses(900)

    print(dcdc)
    print('Rg_total=', rg_total)
    print('HS(cntr)=', str(hs_p) + 'p', fet_ho.part.mpn, fet_ho)
    print('LS(sync)=', fet_lo.part.mpn, fet_lo, 'Qgs/Qgd=', round(fet_lo.QgdQgsRatio, 1))
    print('Coil=', repr(coil))

    p_total_total = sum(sum(v for v in p.values() if not callable(v)) for p in losses.values())

    for n, p in losses.items():
        p_group = sum(v for v in p.values() if not callable(v))
        print(f'P_{n:5}', '  =  %.2f W       (%4.1f%%)' % (p_group, p_group / p_total_total * 100))
        for k, v in sorted(((k, v) for (k, v) in p.items() if not callable(v)), key=lambda t: -t[1]):
            if v != 0:
                if isinstance(p, SwitchPowerLoss) or hasattr(p, 'get_cond'):
                    cond_str = ', '.join(
                        f'{k}={round_to_n_dec(v, 3) if isinstance(v, (int, float,)) else v}' for k, v in
                        p.get_cond(k).items())
                else:
                    cond_str = ''
                print('%10s = %.2f W (%2.0f%%)  (%4.1f%%) %30s' % (k, v, v / p_group * 100, v / p_total_total * 100,
                                                                   cond_str))
        # print()
        print('')

    print('')
    print('Total P = %.2f W (%4.2f%%)' % (p_total_total, p_total_total / dcdc.Pout * 100))
    print('Efficiency = %.1f%%' % ((1 - p_total_total / dcdc.Pout) * 100))

    coil_core_loss_ratio = losses.coil.P_core / (losses.coil.P_dcr + losses.coil.P_core)

    if coil_core_loss_ratio < 0.1:
        warnings.warn(
            'Coil: core loss is <10% of total coil loss, consider additional wire strands, bigger core and/or higher permeability to reduce copper loss')

    if coil_core_loss_ratio > 0.3:
        warnings.warn('Coil: core loss is >30% of total coil loss, consider a smaller core to prevent thermal issues')

    eff_curve = []
    loss_curve = []
    pin = 5
    while pin < 1200:
        try:
            losses, dcdc = compute_losses(pin)
            p_total = sum(map(lambda g: sum(v for v in g.values() if not callable(v)), losses.values()))
            eff = 1 - p_total / pin
            eff_curve.append((pin, eff))
            loss_curve.append(dict(
                pin=pin,
                P_sw=losses.hs.P_sw,
                P_rds=losses.hs.P_cl + losses.ls.P_cl,
                P_dt=losses.ls.P_dt,
                P_rr=losses.ls.P_rr,
                P_ldcr=losses.coil.P_dcr,
                P_lcore=losses.coil.P_core,
                P_csr=losses.misc.P_csr,
            ))
        except AssertionError as e:
            # print('err with pin', pin, e)
            pass
        pin *= 1.1

    pd.DataFrame(eff_curve).set_index(0)[1].plot()
    plt.grid()
    plt.ylim((0.95, 1))
    plt.show()
    pd.DataFrame(loss_curve).set_index('pin').plot()
    plt.show()

"""
Cross Testing with LTSpice

DcDcSpecs(70.0V/32.0V=0.46 Io=25.0A Po=800.0W, dt=500ns)
           | LTSpice                  | this model
            Rdrv    P_HS      P_LS      P_hs    P_ls
AONS66811    6      1.97      1.37      1.96    1.75 (P_dt = 0.80 W maybe too high, maybe half?)
AON6284A     6      4.04      2.23      1.42    3.18

AON6284A  H  6      2.68
AONS66811 L  6                1.39

AON6284A   H 6      2.08
RB228NS150 L D                10

AONS66811  H  6     1.47             <- vs 1.97 with sync fet. HS causes LS to self-turn on over Cgd
RB228NS150 L D                10

 
        
"""

'''
Gate Resistors
https://www.infineon.com/dgdl/Infineon-EiceDRIVER-Gate_resistor_for_power_devices-ApplicationNotes-v01_00-EN.pdf?fileId=5546d462518ffd8501523ee694b74f18
To quickly find a balance point between stability and efficiency, the gate resistance value between nominal value
specified in the datasheet and twice of this nominal value can be considered as a point to start from. This is only in
the case if there is no time to check through all related issues which are explained in the above chapters. To be
sure the gate resistor really fits into the specified application, individual test must be applied based on the real
system.

Drivers:
2EDB7259K 250V, +5/-9A, programmable dead-time, galvanic isolation
2EDL8124G 120V +4/-6A, shoot-through protection
'''
