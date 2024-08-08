import os

from dslib.powerloss import dcdc_buck_hs, CoilSpecs, dcdc_buck_coil, dcdc_buck_ls
from dslib.spec_models import DcDcSpecs, MosfetSpecs

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

    dcdc = DcDcSpecs(vi=70, vo=32, pin=800, f=40e3, Vgs=12, tDead=400e-9)

    fet_ho = MosfetSpecs.from_mpn('AON6284A', mfr='ao')
    fet_lo = MosfetSpecs.from_mpn('AONS66811', mfr='ao')


    p_hs = dcdc_buck_hs(
        dcdc,
        fet_ho,
        # MosfetSpecs(Rds_on=1e-3, Qg=1e-9, tRise=.5e-9, tFall=.5e-9, Qrr=1e-9)
        # MosfetSpecs(Rds_on=6.8e-3, Qg=39e-9, tRise=39e-9, tFall=46e-9, Qrr=43e-9),  # TK6R8A08QM
        #MosfetSpecs(Rds_on=2.3e-3, Qg=120e-9, tRise=11e-9, tFall=10e-9, Qrr=525e-9),#CSD19506KCS

        # MosfetSpecs.mpn(mpn='TK6R8A08QM', mfr='toshiba')
    )

    p_hs = p_hs.parallel(2)

    coil = CoilSpecs(Rdc=5e-3)
    p_coil = dcdc_buck_coil(dcdc, coil)

    p_ls = dcdc_buck_ls(dcdc,
                        #MosfetSpecs(Rds_on=2.3e-3, Qg=120e-9, tRise=11e-9, tFall=10e-9, Qrr=525e-9),
                        fet_lo
                        )


    print(dcdc)
    print('HS(cntr)=', fet_ho)
    print('LS(sync)=', fet_lo)

    p_groups = dict(hs=p_hs, ls=p_ls, coil=p_coil)

    for n, p in p_groups.items():
        p_total = sum(p.values())
        print(f'P_{n}:')
        for k, v in p.items():
            print('%10s = %.2f W (%2.0f%%)' % (k, v, v / p_total * 100))
        print('Total P_%s = %.2f W (%4.2f%%)' % (n, p_total, p_total / dcdc.Pout * 100))
        print('')

    p_total = sum(sum(p.values()) for p in p_groups.values())
    print('')
    print('Total P = %.2f W (%4.2f%%)' % (p_total,  p_total / dcdc.Pout * 100))


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