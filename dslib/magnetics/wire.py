import math
import random
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


Copper = ConductorMaterial('Copper', 1.68e-8, 3.93e-3)


class MaterialResistivity(Enum):
    Copper = 1.68e-8  # Ω*m

    """
    W210, Grade 2
    DIN EN 60317-13
    Distributors: schneitec_shop
    """
    CopperAnnealed = 1.71e-8  # V180, IEC 60317-51 (typ 58.5 MS/m)

    """
    CopperCW024A:
    - names: CW024A, 2.0090, C12200, Cu-DHP, C106
    - "craft wire", water pipes, gas pipes
    - "used wherever there are no high demands on electrical conductivity 
    - https://kupfer.de/wp-content/uploads/2019/11/Cu-DHP.pdf
    """
    CopperCW024A = 2.2e-8  #


def awg2d(awg):
    return 0.127 * 92 ** ((36 - awg) / 39) * 1e-3

def d2awg(d):
    return 36 - 39 * (math.log10(d * 1e3 / 0.127) / math.log10(92))


def dc_resistance(resistivity, length: float, diameter: float):
    return resistivity * length / (math.pi * (diameter / 2) ** 2)


def skin_depth(resistivity, f, mu_r=1):
    # https://en.wikipedia.org/wiki/Skin_effect
    return (2 * resistivity / (2 * math.pi * f * µ0 * mu_r)) ** .5


def ac_resistance(resistivity, length: float, diameter: float, f):
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
    def avg_wire_length(self):
        return self.l * self.turns

    @property
    def R(self):
        d = awg2m(self.awg)
        return wire_resistance(self.mat, self.avg_wire_length, d, self.strands)


def tests():
    from dslib import rel_err

    assert abs(rel_err(skin_depth( 1.72e-8, f=50), 9.335e-3)) < 1e-4
    assert abs(rel_err(skin_depth(1.72e-8, f=50, mu_r=2), 6.601e-3)) <  1e-4

    res = MaterialResistivity.Copper.value
    d = awg2d(14)


    rdc = dc_resistance(res, 1, d)
    assert abs(rel_err(rdc, 8.1e-3)) < 0.01

    rac = ac_resistance(res, 1, d, 50e3)
    assert abs(rel_err(rac, 13.7e-3)) < 0.01

    acf, sd = ac_resistance_factor(res, d, 50e3)
    assert abs(rel_err(rac, acf * rdc)) < 0.01

    for i in range(1000):
        x = random.random() * 10
        assert abs(rel_err(awg2d(d2awg(x)) ,x)) < 1e-9
        assert abs(rel_err(d2awg(awg2d(x)), x)) < 1e-9

