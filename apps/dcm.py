"""

This app performs a grid search on Vin, Vout and Iout to find operating points
where converter with initial inductivity L0 operates in CCM, whereas reduced L due
to dc-bias would actually run in DCM.

This can help you with implementing the PWM signal for sensor-less diode emulation for synchronous
converters. Start with `L_drop_estimate = 1` and lower it until you get zero misestimations.

Choosing L_drop_estimate ..
- ..too high will cause the sync rectifier to switch too long -> reverse current -> lowered conversion eff.
- .. too low will cause an overestimation of ripple current and the sync rectifier switches too long -> increased body diode loss in the sync rectifier -> lowered conversion eff.


Notes:
DC bias current decreases core permeability, reducing L and increases ripple current.
This can put the converter in DCM with higher loads.

"""
from apps.mppts.libresolar import MPPT_Fheat2
from dslib import round_to_n_dec

L_drop_estimate = 0.99

coils = [
    # MPPT_2420_HC().coil,
    MPPT_Fheat2().coil,
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


n_me = 0

for vin in range(15, 100):
    for vout in range(12, 60):
        if vin - vout < 1:
            continue

        for iout in drange(1, 30, 1):
            for coil in coils:
                ir0 = ripple_current(vin, vout, f, L=coil.L0 * L_drop_estimate)
                irB = ripple_current(vin, vout, f, L=coil.Ldc(iout))

                if ir0 / 2 < iout and not (irB / 2 < iout):
                    n_me += 1
                    print(vin, vout, iout, 'L0 CCM, but Ldc=', round_to_n_dec(coil.Ldc(iout), 3),
                          'DCM!', 'Ldc/L0=', round_to_n_dec(coil.Ldc(iout) / coil.L0 * 100, 2), '%',
                          round_to_n_dec(irB / ir0 * 100, 3), '%'
                          )

print('L_drop_estimate = %s' % L_drop_estimate)
print('Number of misestimations: %i' % n_me)
