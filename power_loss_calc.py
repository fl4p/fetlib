import warnings

import matplotlib.pyplot as plt
import pandas as pd

import apps.mppts.libresolar
from apps.mppts import fugu
from dclib.powerloss import SwitchPowerLoss
from dslib import round_to_n_dec
from dslib.mosfet import GateDrive
from dslib.spec_models import DcDcLoadParams, DCMNotImplemented

if __name__ == '__main__':
    """
    TODO
    - losses appear to be too low
    - use LTspice, ngspice
    - consider self turn on?
    """

    # buck = MPPT_2420_HC()
    # buck = apps.mppts.libresolar.FuguWhite184()
    # buck = apps.mppts.libresolar.MPPT_Fheat2()

    buck = fugu.FuguSpiceTest1()

    gd = GateDrive(rg_total=buck.hs.rg_total,
                   rg_total_dis=buck.hs.rg_total_dis,
                   Von=11,
                   Von_GaN=5,
                   fallback_V_pl=4.5,
                   tDead=1e-9 * (8.6 * 33 + 13),  # ucc2333
                   )


    def compute_losses(pin, fsw=None):
        # dcdc = DcDcSpecs(vi=66, vo=27, pin=pin, f=fsw, Vgs=11, tDead=400e-9, L=buck.coil.L0)

        fsw = fsw or (buck.f_sw)
        # dcdc = DcDcLoadParams(vi=66, vo=27, pin=pin, f=fsw,tDead=400e-9, L=buck.coil.L0)
        # dcdc = DcDcLoadParams(vi=40, vo=27, pin=800, f=fsw,tDead=200e-9, L=buck.coil.L0)
        # dcdc = DcDcLoadParams(vi=60, vo=9.9, pin=pin, f=fsw, tDead=300e-9, L=buck.coil.L0)
        # dcdc = DcDcLoadParams(vi=75, vo=27, pin=pin, f=fsw, tDead=gd.tDead, L=buck.coil.L0)
        dcdc = DcDcLoadParams(vi=72, vo=27, pin=pin, f=fsw, tDead=gd.tDead, L=buck.coil.L0) # L arg is irrelevant here

        # dcdc = DcDcSpecs(vi=67, vo=27, io=13, f=fsw, Vgs=11, tDead=400e-9, L=buck.coil.L0)

        assert dcdc.Io < buck.Io_max

        return buck.powerloss(dcdc, gd)


    losses, dcdc = compute_losses(800)
    # losses, dcdc = compute_losses(60 * 0.48)

    print('Converter', buck.name)
    print('Rg_total=', buck.hs.rg_total, 'Ω')
    print('HS(cntr)=', str(buck.hs.parallel) + 'p', buck.hs.mf.part.mpn, buck.hs.mf)
    print('LS(sync)=', buck.ls.mf.part.mpn, buck.ls.mf, 'Qgs/Qgd=', round(buck.ls.mf.QgdQgsRatio, 1))
    print('Coil=', repr(buck.coil))
    print('     Analyzer', buck.coil.micrometals_analyzer(dcdc))
    print('OperatingPoint=', dcdc)

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
    print('Io = %.2f A, Ipp = %.2f A' % (dcdc.Io, dcdc.Iripple))
    print('Total Ploss = %.2f W (%4.2f%% of Pout %.1fW)' % (p_total_total, p_total_total / dcdc.Pout * 100, dcdc.Pout))
    print('Efficiency = %.2f%%' % ((1 - p_total_total / dcdc.Pout) * 100))

    coil_core_loss_ratio = losses.coil.P_core / (losses.coil.P_dcr + losses.coil.P_core)

    if coil_core_loss_ratio < 0.1:
        warnings.warn(
            'Coil: core loss is <10% of total coil loss, consider additional wire strands, bigger core and/or higher permeability to reduce copper loss')

    if coil_core_loss_ratio > 0.3:
        warnings.warn('Coil: core loss is >30% of total coil loss, consider a smaller core to prevent thermal issues')

    if losses.coil.P_acr / losses.coil.P_dcr > 0.05:
        warnings.warn('Coil: Pacr > 5% * Pdcr, consider litz wires.')

    eff_curve = []
    loss_curve = []
    parts_curve = []
    pin = 5
    while pin < 2000:
        try:
            losses, dcdc = compute_losses(pin)
            assert dcdc.is_ccm, "coil core loss only valid in ccm"
            p_total = sum(map(lambda g: sum(v for v in g.values() if not callable(v)), losses.values()))
            eff = 1 - p_total / pin
            eff_curve.append((pin, eff, dcdc.Iripple))
            loss_curve.append(dict(
                pin=pin,
                P_sw=losses.hs.P_sw,
                P_rdsH=losses.hs.P_cl,
                P_rdsL=losses.ls.P_cl,
                P_dt=losses.ls.P_dt,
                P_rr=losses.ls.P_rr,
                P_ldcr=losses.coil.P_dcr,
                P_lacr=losses.coil.P_acr,
                P_lcore=losses.coil.P_core,
                P_csr=losses.misc.get('P_csr', 0),
                P_cin=losses.cap.P_cin,
                P_cout=losses.cap.P_cout,
                P_coss=losses.hs.P_coss + losses.ls.P_coss,
            ))

            parts_curve.append(dict(
                pin=pin,
                P_fet=losses.hs.buck_hs() + losses.ls.buck_ls(),
                P_coil=(losses.coil.P_dcr + losses.coil.P_acr + losses.coil.P_core),
                P_caps=losses.cap.P_cin + losses.cap.P_cout,
                P_rest=sum(losses.misc.values()),
            ))
        except DCMNotImplemented as e:
            # print('err with pin', pin, e)
            # print(traceback.format_exc())
            pass
        pin *= 1.1

    loss_df = pd.DataFrame(parts_curve).set_index('pin')
    loss_df = loss_df[list(loss_df.iloc[-1, :].sort_values().keys())]
    loss_df.plot()
    # plt.grid()
    # plt.ylim((0.95, 1))
    # plt.xlim((0, eff_curve[-1][0]))
    plt.title('parts curve f=%shz' % round_to_n_dec(dcdc.f, 2))
    plt.show()

    pd.DataFrame(eff_curve).set_index(0)[1].plot()
    plt.grid()
    plt.ylim((0.95, 1))
    plt.xlim((0, eff_curve[-1][0]))
    plt.title('f=%shz' % round_to_n_dec(dcdc.f, 2))
    plt.show()

    pd.DataFrame(eff_curve).set_index(0)[2].plot()
    plt.grid()
    #plt.ylim((0.95, 1))
    plt.xlim((0, eff_curve[-1][0]))
    plt.title('Ipp f=%shz)' % round_to_n_dec(dcdc.f, 2))
    plt.show()

    loss_df = pd.DataFrame(loss_curve).set_index('pin')
    loss_df = loss_df[list(loss_df.iloc[-1, :].sort_values().keys())]
    plt.stackplot(loss_df.index.values, loss_df.T.values, labels=loss_df.columns)
    plt.legend(reverse=True)
    plt.xlabel('Pin')
    plt.ylabel('Ploss')
    plt.title(
        f'{buck.name} {round_to_n_dec(dcdc.Vi, 2)}/{round_to_n_dec(dcdc.Vo, 2)}V f={round_to_n_dec(buck.f_sw, 2)}Hz')
    # plt.grid()

    # y = np.vstack([y1, y2, y3])

    # loss_df.plot()
    plt.show()

    # pd.DataFrame(eff_curve).set_index(0)[2].plot()
    # plt.title('∆I')
    # plt.show()

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
