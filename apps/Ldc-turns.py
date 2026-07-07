"""

Plot DC-biased inductivity Ldc over number of turns for
given DC current Idc and for different materials.

This can help to optimize the relative permeability of the core.
As core materials with higher permeability tend to saturate earlier, they lose inductivity
more quickly with rising number of turns (which causes an increased H).

With this tool you find the intersections of the material curves.
For a given number of turns and DC current you can quickly see which material
performs best (i.e. has the highest permeability/inductivity).

"""

import pandas as pd
from matplotlib import pyplot as plt

from maglib import cores
from dclib.powerloss import CoilSpecs


cores_list = [
    cores.MicrometalsToroid('MS', 60, 184),
    cores.MicrometalsToroid('MS', 75, 184),
    cores.MicrometalsToroid('MS', 90, 184),
    cores.MicrometalsToroid('MS', 125, 184),
    cores.MicrometalsToroid('OE', 90, 184),
]

Idc = 20

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
