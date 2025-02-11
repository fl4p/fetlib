"""

Plot DC-biased inductivity Ldc over number of turns for
given DC current Idc and for different materials.

This can help to optimize the relative permeability of the core.
As higher perm. Cores tend to saturate earlier, they loose inductivity
more quickly with rising number of turns (which causes an increased H.



"""

import pandas as pd
from matplotlib import pyplot as plt

from dslib.magnetics import cores
from dslib.powerloss import CoilSpecs


cores_list = [
    cores.MicrometalsToroid('MS', 60, 184),
    cores.MicrometalsToroid('MS', 75, 184),
    cores.MicrometalsToroid('MS', 90, 184),
    cores.MicrometalsToroid('MS', 125, 184),
    cores.MicrometalsToroid('OE', 90, 184),
]

Idc = 30

turns = 10
res = dict()
while turns < 30:
    res[turns] = {'%2s' % (c.mpn): CoilSpecs(1e-3, turns=turns, core=c).Ldc(Idc, no_raise=True) for c in cores_list}
    turns *= 1.1

pd.DataFrame(res).T.plot()
plt.xlabel('#turns')
plt.ylabel('Ldc')
plt.title('Idc=%.1fA' % (Idc))
plt.grid()
plt.show()
