import math

import pandas as pd
from matplotlib import pyplot as plt

from apps.mppts.libresolar import LibreSolar_MPPT_2420_HC
from dslib.magnetics.cores import MicrometalsToroid, MicrometalsT130, MicrometalsT184
from dslib.powerloss import CoilSpecs, dcdc_buck_coil
from dslib.spec_models import DcDcLoadParams

materials = [
    'GX',
    'MS',
    'SM',
    'OC', # 'OE',  # 'OE', #'OD',
    'MP', #'HF',  # 'FS',
]

shape = 130 #MicrometalsT130
#shape = MicrometalsT184
L0 = 55e-6
Io = .5 #0.5
fsw = 200e3
stacks = (
#    1,
    2,
)
uis = (
    60,
    #75,
     90,
    #125
)
points = []
idx = []

while Io < 33:

    point = dict()
    for mat in materials:
        for ui in uis: #(60,75,90,125):
            for stack in stacks:
                try:
                    core = MicrometalsToroid(mat, ui, shape).stack(stack)
                    coil = CoilSpecs(1e-3, L0=L0, core=core, wire_diameter=1e-3)
                    #coil =  MPPT_2420_HC().coil
                    #dcdc = DcDcSpecs(75, 30, fsw, io=Io, L=coil.Ldc(Io))
                    dcdc = DcDcLoadParams(66, 27, fsw, io=Io, L=coil.Ldc(Io))
                    loss = dcdc_buck_coil(dcdc, coil)
                    assert loss['P_core'] > 0
                    if len(points) == 0:
                        print(coil.core.mpn, coil.micrometals_analyzer(dcdc))
                    point[f'{coil.core.mpn} {round(coil.turns)}T'] = loss['P_core']
                except:
                    # point[core.mpn] = math.nan
                    continue
            #break

    if point:
        points.append(point)
        idx.append(Io)
    Io *= 1.1

df = pd.DataFrame(points, index=idx)
df = df[df.mean().sort_values().keys()]
df.plot()
plt.title(str(dcdc))
plt.legend(reverse=True)
plt.ylim((0, None))
plt.show()
print(df.mean().round(2))
