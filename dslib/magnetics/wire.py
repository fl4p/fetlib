import math
from enum import Enum


class MaterialResistivity(Enum):
    Copper = 1.68e-8  # Ω*m
    CopperAnnealed = 1.71e-8  # Ω*m


def awg2m(awg):
    return 0.127 * 92 ** ((36 - awg) / 39)


def wire_resistance(mat: MaterialResistivity, length:float, diameter:float, strands=1):
    return mat.value * length / ((diameter / 2) ** 2 * math.pi) / strands
