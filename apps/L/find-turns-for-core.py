import pandas as pd
from matplotlib import pyplot as plt

from dslib.spec_models import DcDcLoadParams
from maglib import cores

#core = cores.MicrometalsToroid('MS', 75, cores.MicrometalsT184)
core = cores.MicrometalsToroid('MS', 125, cores.MicrometalsT184)


def ripple_current(vi, vo, f, L):
    iripple = vo / (f * L) * (1 - vo / vi)
    return iripple


vin = 72
vout = 27
f_sw = 39e3
iout = 30

points = []

for t in range(1, 100):
    from dclib.powerloss import dcdc_buck_coil, CoilSpecs

    # wire_diameter
    # wire_strands,

    coil = CoilSpecs(Rdc=3e-3, turns=t, wire_diameter=2e-3, wire_strands=2, core=core)
    Ldc = coil.Ldc(iout, no_raise=True)
    if ripple_current(vin, vout, f_sw, Ldc) > 2 * iout:
        continue
    load = DcDcLoadParams(vin, vout, f=f_sw, tDead=200e-9, io=iout, L=Ldc)
    p_coil = dcdc_buck_coil(load, coil)

    points.append(dict(turns=t, L0=coil.L0, Ldc=Ldc, **p_coil))


df = pd.DataFrame(points).set_index('turns')

(df.Ldc*1e6).plot()
plt.title('Ldc(µH)')
plt.figure()


(df.Ldc/df.L0*100).plot()
plt.title('Ldc/L0 (%)')
plt.figure()

df.P_core.plot()
plt.title('P_core')
plt.ylabel('W')
plt.show()