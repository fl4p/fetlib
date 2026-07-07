import math

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

from maglib.cores import MicrometalsT184
from maglib.wire import acr_factor_micrometals, MaterialResistivity

diameters = np.array(range(400, 2000, 200)) * 1e-6

f = 40e3
core_shape = MicrometalsT184

points = []

def bundle_d(d, n):
    return (4 * (n * (math.pi * d ** 2 / 4)) / math.pi) ** .5

for diameter in diameters:
    strands = 3

    bundle = (4 * (strands * (math.pi * diameter ** 2 / 4)) / math.pi) ** .5

    points.append(dict(zip(('s', 'p'), acr_factor_micrometals(
        MaterialResistivity.CopperAnnealed.value, diameter, f,
        strands=strands,
        turns=20,
        id=core_shape.ID, od=core_shape.OD
    ))))

    pd.DataFrame(points, index=diameters * 1e3).plot()
    plt.show()
