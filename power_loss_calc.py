import os








if __name__ == '__main__':
    dcdc = DcDcSpecs(vi=62, vo=27, pin=800, f=40e3, Vgs=12)
    p = buck_hs(
        dcdc,
        # MosfetSpecs(Rds_on=1e-3, Qg=1e-9, tRise=.5e-9, tFall=.5e-9, Qrr=1e-9)
        # MosfetSpecs(Rds_on=6.8e-3, Qg=39e-9, tRise=39e-9, tFall=46e-9, Qrr=43e-9),  # TK6R8A08QM
        MosfetSpecs(Rds_on=2.3e-3, Qg=120e-9, tRise=11e-9, tFall=10e-9, Qrr=525e-9),#CSD19506KCS

        # MosfetSpecs.mpn(mpn='TK6R8A08QM', mfr='toshiba')
    )

    """
    Picks
    SUM60020E vishay
    """
    print(dcdc)
    p_total = sum(p.values())
    for k, v in p.items():
        print('%10s = %.2f W (%2.0f%%)' % (k, v, v / p_total * 100))

    print('')
    print('Total P_mosfet = %.2f W (%4.2f%%)' % (p_total, p_total / dcdc.Pout * 100))
