import math

import matplotlib.pyplot as plt
import pandas as pd

import dslib.magnetics.cores
from dslib import dotdict, round_to_n
from dslib.field import Field
from dslib.pdf2txt.parse import parse_datasheet
from dslib.powerloss import dcdc_buck_hs, CoilSpecs, dcdc_buck_coil, dcdc_buck_ls, SwitchPowerLoss
from dslib.spec_models import DcDcSpecs

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
                     #core=dslib.magnetics.cores.Micrometals_OE_184_060,
                     #core=dslib.magnetics.cores.Micrometals_OE_226_060,

                     )

    ds_ho = parse_datasheet('datasheets/toshiba/TK6R8A08QM.pdf', mfr='toshiba')
    ds_ho.add(Field('Rds_on_10v', math.nan, 5.3e-3, 6.8e-3))

    # ds_ho = parse_datasheet('datasheets/ti/CSD19501KCS.pdf')
    # ds_ho.add(Field('Rds_on_10v', math.nan, 5.5e-3, 6.5e-3))

    ds_lo = parse_datasheet('datasheets/onsemi/FDP027N08B.pdf', mfr='onsemi')
    ds_lo.add(Field('Rds_on_10v', math.nan, 2.21e-3, 2.7e-3))

    fet_ho = ds_ho.get_mosfet_specs()
    fet_lo = ds_lo.get_mosfet_specs()

    rg_total = 22

    # fet_ho = MosfetSpecs.from_mpn('TK6R8A08QM', mfr='toshiba')
    # fet_lo = MosfetSpecs.from_mpn('FDP027N08B', mfr='onsemi')

    hs_p = 2


    def compute_losses(pin):

        # dcdc = DcDcSpecs(vi=66, vo=27, pin=800, f=40e3, Vgs=11, tDead=400e-9, L=50e-6)
        dcdc = DcDcSpecs(vi=66, vo=27, pin=pin, f=40e3, Vgs=11, tDead=400e-9, L=coil.L)

        p_hs = dcdc_buck_hs(
            dcdc,
            fet_ho,
            rg_total=rg_total,
            fallback_V_pl=5.4,

            Lcsi=2e-9,
            ls_Qoss=250e-9, # TODO csd19503
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
            P_bflow=1e-3 * dcdc.Io ** 2,  # backflow switch
            P_rpcb=.7e-3 * dcdc.Io ** 2,
        )

        return dotdict(hs=p_hs, ls=p_ls, coil=p_coil, misc=p_misc), dcdc


    losses, dcdc = compute_losses(900)

    print(dcdc)
    print('Rg_total=', rg_total)
    print('HS(cntr)=', str(hs_p) + 'p', fet_ho.part.mpn, fet_ho)
    print('LS(sync)=', fet_lo.part.mpn, fet_lo)
    print('Coil=', repr(coil))

    p_total_total = sum(sum(p.values()) for p in losses.values())

    for n, p in losses.items():
        p_group = sum(p.values())
        print(f'P_{n:5}', '  =  %.2f W       (%4.1f%%)' % (p_group, p_group / p_total_total * 100))
        for k, v in sorted(p.items(), key=lambda t: -t[1]):
            if v != 0:
                if isinstance(p, SwitchPowerLoss) or hasattr(p, 'get_cond'):
                    cond_str = ', '.join(f'{k}={round_to_n(v, 3)}' for k, v in p.get_cond(k).items())
                else:
                    cond_str = ''
                print('%10s = %.2f W (%2.0f%%)  (%4.1f%%) %30s' % (k, v, v / p_group * 100, v / p_total_total * 100,
                                                                   cond_str))
        # print()
        print('')

    print('')
    print('Total P = %.2f W (%4.2f%%)' % (p_total_total, p_total_total / dcdc.Pout * 100))
    print('Efficiency = %.1f%%' % ((1 - p_total_total / dcdc.Pout) * 100))

    eff_curve = []
    loss_curve = []
    pin = 5
    while pin < 1200:
        try:
            losses, dcdc = compute_losses(pin)
            p_total = sum(map(lambda g: sum(g.values()), losses.values()))
            eff = 1 - p_total / pin
            eff_curve.append((pin, eff))
            loss_curve.append(dict(
                pin=pin,
                P_sw=losses.hs.P_sw,
                P_rds=losses.hs.P_on + losses.ls.P_on,
                P_dt=losses.ls.P_dt,
                P_rr=losses.ls.P_rr,
                P_ldcr=losses.coil.P_dcr,
                P_lcore=losses.coil.P_core,
                P_csr=losses.misc.P_csr,
            ))
        except AssertionError as e:
            #print('err with pin', pin, e)
            pass
        pin *= 1.1

    pd.DataFrame(eff_curve).set_index(0)[1].plot()
    plt.grid()
    plt.ylim((0.95,1))
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
