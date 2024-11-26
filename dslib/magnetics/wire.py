import math
from enum import Enum


class MaterialResistivity(Enum):
    Copper = 1.68e-8  # Ω*m
    CopperAnnealed = 1.71e-8  # Ω*m


def awg2m(awg):
    return 0.127 * 92 ** ((36 - awg) / 39)


def wire_resistance(mat: MaterialResistivity, length: float, diameter: float, strands=1):
    return mat.value * length / ((diameter / 2) ** 2 * math.pi) / strands


class Winding():
    def __init__(self, mat: MaterialResistivity, awg: int, turns, l, strands: int = 1):
        self.mat = mat
        self.awg = awg
        self.turns = turns
        self.l = l
        self.strands = strands

    @property
    def avg_wire_length(self):
        return self.l * self.turns

    @property
    def R(self):
        d = awg2m(self.awg)
        return wire_resistance(self.mat, self.avg_wire_length, d, self.strands)
