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
        raise NotImplementedError()
        #return self.resistivity_20 * temperature


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


def copper_resistivity_tempco(resistivity20, temp, tc=0.00393):
    return resistivity20 + (temp - 20) * tc


def dc_resistance(resistivity, length: float, diameter: float):
    # Snelling Soft Ferrites p340
    return resistivity * length / (math.pi * (diameter / 2) ** 2)


def skin_depth(resistivity: float, f: float, mu_r=1.0):
    # https://en.wikipedia.org/wiki/Skin_effect
    # mu_r is usually 1 (copper)
    return (2 * resistivity / (2 * math.pi * f * µ0 * mu_r)) ** .5


def ac_resistance(resistivity: float, length: float, diameter: float, f: float):
    """

    Returns the total (Rdc+Rac) resistance considering skin depth.
    See ac_resistance_factor() for details

    :param resistivity:
    :param length:
    :param diameter:
    :param f:
    :return:
    """

    sd = skin_depth(resistivity, f)
    assert sd / diameter < 0.25
    return resistivity * length / (math.pi * (diameter - sd) * sd), sd


def ac_resistance_factor(resistivity, diameter: float, f):
    """
    Compute Rac/Rdc ratio considering the skin effect only (no proximity effect)
    The conductor is considered a hollow cylinder.

    :param resistivity: Conductor resistivity
    :param diameter: Wire diameter in mm
    :param f: frequency in Hz
    :return:
    """
    sd = skin_depth(resistivity, f)
    assert sd / diameter < 0.3
    return diameter ** 2 / (4 * sd * (diameter - sd)), sd


def acr_factor_micrometals(resistivity, diameter: float, f, strands, turns, id, od):
    """

    Fac/dc = Fskin + Fprox

    :param resistivity:
    :param diameter:
    :param f:
    :param strands:
    :param turns:
    :param id:
    :param od:
    :return: tuple (Fskin, Fprox)
    """
    # https://s3.amazonaws.com/micrometals-production/filer_public/7c/72/7c728863-9c0e-40b3-ba86-a3f94d5ad1c1/acresistance_rev0_110123.pdf

    sd = skin_depth(resistivity, f)
    zeta = diameter / sd

    Ga = zeta ** 6 + 6.1 * zeta ** 5 + 32 * zeta ** 4 + 13 * zeta ** 3 + 90 * zeta ** 2 + 110 * zeta
    F_hf_s = (1 + Ga / 36864) ** -.5

    # f_skin = 1 + zeta ** 4 / 768 * F_hf_s
    # here we remove the +1 as we want the F per definition in soft ferrites Rac=Rdc(1+F)
    f_skin = zeta ** 4 / 768 * F_hf_s

    assert id < od
    b_eq = math.pi / 2 * (id + od)
    # for  E, PQ and EQ:
    # w_h = 2*D (from data sheet)
    # b_eq = 2*w_h

    G_t = zeta ** 6 + 2.7 * zeta ** 5 - 1.3 * zeta ** 4 - 17 * zeta ** 3 + 85 * zeta ** 2 - 43 * zeta
    F_hf_p = (1 + G_t / 1024) ** -.5

    f_prox = (math.pi * strands * turns) ** 2 * diameter ** 2 * zeta ** 4 / (192 * b_eq ** 2) * F_hf_p

    return f_skin, f_prox


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

    # def Rac(self, f: float):
    #    d = awg2d(self.awg)
    #    # r, sd = ac_resistance(float(self.mat.value), self.avg_wire_length, d, f)
    #    acr_factor_micrometals(float(self.mat.value), d, f, self.strands, self.turns, id, od)
    # return r / self.strands

    def Rac_sepe(self, f: float, core_id: float, core_od: float):
        d = awg2d(self.awg)
        F_se, F_pe = acr_factor_micrometals(float(self.mat.value), d, f, self.strands, self.turns, core_id, core_od)
        return self.Rdc * (1 + F_se + F_pe)
