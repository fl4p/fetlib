import math


µ0 = 4 * math.pi * 1e-7

oe = 1000 / (4 * math.pi)


def oe2Apm(H_oe):
    return H_oe * oe


def H2oe(H):
    return H / oe
