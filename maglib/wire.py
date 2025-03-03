import math
from enum import Enum

µ0 = 4 * math.pi * 1e-7

"""
TODO
Strands Formular: d_b = (d_a**2 * n_a/n_b)**.5 # d_b = diameter, n_b = num strands

"""


class ConductorMaterial():
    def __init__(self, name, resistivity_20, temp_coefficient_20):
        self.name = name
        self.resistivity_20 = resistivity_20
        self.temp_coefficient_20 = temp_coefficient_20

    def resistivity_T(self, temperature):
        return self.resistivity_20 * temperature


CopperPure = ConductorMaterial('Copper', 1.68e-8, 3.93e-3)


class MaterialResistivity(Enum):
    Copper = 1.68e-8  # Ω*m
    """
    "Ideal" Pure Copper.
    """

    CopperAnnealed = 1.71e-8
    """
    Annealed Copper
    V180, IEC 60317-51 (typ conductivity: 58.5 MS/m)
    W210, Grade 2
    DIN EN 60317-13
    Distributors: schneitec_shop
    """

    CopperCW024A = 2.2e-8
    """
       CopperCW024A:
       - names: CW024A, 2.0090, C12200, Cu-DHP, C106
       - "craft wire", water pipes, gas pipes
       - "used wherever there are no high demands on electrical conductivity"
       - https://kupfer.de/wp-content/uploads/2019/11/Cu-DHP.pdf
   """


def awg2d(awg):
    return 0.127 * 92 ** ((36 - awg) / 39) * 1e-3


def d2awg(d):
    return 36 - 39 * (math.log10(d * 1e3 / 0.127) / math.log10(92))


def dc_resistance(resistivity, length: float, diameter: float):
    return resistivity * length / (math.pi * (diameter / 2) ** 2)


def skin_depth(resistivity: float, f: float, mu_r=1.0):
    # https://en.wikipedia.org/wiki/Skin_effect
    return (2 * resistivity / (2 * math.pi * f * µ0 * mu_r)) ** .5


def ac_resistance(resistivity: float, length: float, diameter: float, f: float):
    # this assumes the conductor is a hollow cylinder
    # TODO reference
    sd = skin_depth(resistivity, f)
    assert sd / diameter < 0.25
    return resistivity * length / (math.pi * (diameter - sd) * sd), sd


def ac_resistance_factor(resistivity, diameter: float, f):
    # Rac/Rdc
    sd = skin_depth(resistivity, f)
    sd = min(sd, diameter / 2)
    return diameter ** 2 / (4 * sd * (diameter - sd)), sd


class Winding():
    def __init__(self, mat: MaterialResistivity, awg: int, turns, l, strands: int = 1):
        self.mat = mat
        self.awg = awg
        self.turns = turns
        self.l = l
        self.strands = strands

    @property
    def avg_wire_length(self) -> float:
        return self.l * self.turns

    @property
    def Rdc(self):
        d = awg2d(self.awg)
        return dc_resistance(float(self.mat.value), self.avg_wire_length, d) / self.strands

    def Rac(self, f: float):
        d = awg2d(self.awg)
        r, sd = ac_resistance(float(self.mat.value), self.avg_wire_length, d, f)
        return r / self.strands
