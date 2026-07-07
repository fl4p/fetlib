
import matplotlib.pyplot as plt
import numpy as np

v = 10 ** (np.array(range(-10, 21))/10)

fns = dict(fn1 = lambda v: 319*(50/v)**.5,
fn2 = lambda v: 7000/(1+v/0.1)**.5)

for l, fn in fns.items():
    c = np.array(list(map(fn, v)))
    plt.plot(v, c, label=l)

plt.semilogx()
plt.semilogy()
plt.grid()
plt.legend()
plt.show()