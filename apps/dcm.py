"""
DC bias current decreases core permeability and increases ripple current.
This app performs a grid search on Vin, Vout and Iout to find operating points
where converter with L0 operates in CCM, whereas reduced L due to dc-bias would actually
and increased ripple current will actually put the converter in DCM.


"""
from apps.mppts.libresolar import FuguHeat184
from dslib import round_to_n_dec

coils = [
    # MPPT_2420_HC().coil,
    FuguHeat184().coil,
]
f = 40e3


def ripple_current(vi, vo, f, L):
    iripple = vo / (f * L) * (1 - vo / vi)
    return iripple


import decimal


def drange(x, y, jump):
    while x < y:
        yield float(x)
        x += decimal.Decimal(jump)


for vin in range(15, 100):
    for vout in range(12, 60):
        if vin - vout < 1:
            continue

        for iout in drange(1, 30, 1):
            for coil in coils:
                ir0 = ripple_current(vin, vout, f, L=coil.L0 )#* 0.95
                irB = ripple_current(vin, vout, f, L=coil.Ldc(iout))
                if ir0 / 2 < iout and not (irB / 2 < iout):
                    print(vin, vout, iout, 'L0 CCM, but Ldc=', round_to_n_dec(coil.Ldc(iout), 3),
                          'DCM!', 'Ldc/L0=', round_to_n_dec(coil.Ldc(iout) / coil.L0 * 100, 2), '%',
                          round_to_n_dec(irB / ir0 * 100, 3), '%'
                          )
