import math

import dslib.magnetics.materials as materials
from dslib import round_to_n
from dslib.magnetics.materials import MagInc_KoolMu_60, KDM_SendustKS_60, MagneticCoreMaterialSpecs
from dslib.spec_models import rel_err

µ0 = 4 * math.pi * 1e-7


class ToroidShape():
    def __init__(self, l_e, A_e, Vol):
        self.l_e = l_e
        self.A_e = A_e
        self.Vol = Vol
        assert 0.9 < (self.A_e * self.l_e / self.Vol) < 1.1, (self.A_e * self.l_e, self.Vol)


class MagneticCoreSpecs:
    def __init__(self, mpn, mat: MagneticCoreMaterialSpecs, A_L, l_e, A_e, Vol):
        """

        :param mpn:
        :param mat:
        :param l_e: effective magnetic path length in m
        :param A_e: eff. magnetic cross-sectional Area in m2
        :param Vol:  core volume in m3
        """
        self.mat = mat
        self.mpn = mpn
        self.A_L = A_L
        self.l_e = l_e
        self.A_e = A_e  # in m2
        self.Vol = Vol

        assert 0.9 < (self.A_e * self.l_e / self.Vol) < 1.1, (self.A_e * self.l_e, self.Vol)
        assert abs(rel_err(µ0 * mat.mu_r * A_e / l_e, self.A_L)) < 0.04, (µ0 * mat.mu_r * A_e / l_e, self.A_L)

    def stack(self, n):
        return MagneticCoreSpecs(
            f'2s({self.mpn})', self.mat,
            A_L=self.A_L * n,
            l_e=self.l_e,
            A_e=self.A_e * n,
            Vol=self.Vol * n,
        )

    def __str__(self):
        return (f'Core<{self.mpn}, Al={round_to_n(self.A_L * 1e9, 3)}nH, '
                f'le={round_to_n(self.l_e * 1e2, 2)}cm, '
                f'Ae={round_to_n(self.A_e * 1e4, 2)}cm2 '
                f'Ve={round_to_n(self.Vol * 1e6, 2)}cm3>')


# https://www.mag-inc.com/Media/Magnetics/File-Library/Product%20Literature/Powder%20Core%20Literature/Magnetics-Powder-Core-Catalog-2024.pdf#page=168

MagInc_106_KoolMu60 = MagneticCoreSpecs('0077894A7', MagInc_KoolMu_60,
                                        A_L=75e-9,  # nH/N2
                                        l_e=63.5e-3,  # mm
                                        A_e=65.4e-6,  # mm2
                                        Vol=4150e-9,  # mm3 eff. Volume
                                        )

# https://www.kdm-mag.com/products/details-toroidal-1375.html
# https://semic.cz/!old/files/pdf_www/Ljf_KS130-060A_KD.pdf
KDM_KS130_060A = MagneticCoreSpecs('KDM_KS130_060A', KDM_SendustKS_60,
                                   A_L=61e-9,  # nH/N2
                                   l_e=8.125e-2,  # cm
                                   A_e=0.672e-4,  # cm2
                                   Vol=5.480e-6,
                                   )
MicrometalsT130 = ToroidShape(l_e=8.15e-2, A_e=0.698e-4, Vol=5.69e-6)
MicrometalsT184 = ToroidShape(l_e=10.743e-2, A_e=1.99e-4, Vol=21.4e-6)

# https://datasheets.micrometals.com/MS-132060-2-DataSheet.pdf
Micrometals_MS_130_060 = MagneticCoreSpecs('MS-132060-2',
                                           materials.Micrometals_Sendust_60u,
                                           **MicrometalsT130.__dict__,
                                           A_L=65e-9,  # nH/N2
                                           )

# https://datasheets.micrometals.com/MS-184060-2-DataSheet.pdf
Micrometals_MS_184_060 = MagneticCoreSpecs('MS-184060-2',
                                           materials.Micrometals_Sendust_60u,
                                           **MicrometalsT184.__dict__,
                                           A_L=135e-9,  # nH/N2 (checksum)
                                           )

# https://datasheets.micrometals.com/MS-184090-2-DataSheet.pdf
Micrometals_MS_184_090 = MagneticCoreSpecs('MS-184090-2',
                                           materials.Micrometals_MS_T_090u,
                                           **MicrometalsT184.__dict__,
                                           A_L=202e-9,  # nH/N2 (checksum)
                                           )

# https://datasheets.micrometals.com/MS-184125-2-DataSheet.pdf
Micrometals_MS_184_125 = MagneticCoreSpecs('MS-184125-2',
                                           materials.Micrometals_MS_T_125u,
                                           **MicrometalsT184.__dict__,
                                           A_L=281e-9,  # nH/N2
                                           )

# https://datasheets.micrometals.com/OE-184060-2-DataSheet.pdf
Micrometals_OE_184_060 = MagneticCoreSpecs('OE-184060-2',
                                           materials.Micrometals_OE_60u,
                                           **MicrometalsT184.__dict__,
                                           A_L=135e-9,  # nH/N2
                                           )

# https://datasheets.micrometals.com/OE-226060-2-DataSheet.pdf
Micrometals_OE_226_060 = MagneticCoreSpecs('OE-226060-2', materials.Micrometals_OE_60u,
                                           A_L=138e-9,  # nH/N2
                                           l_e=12.506e-2,  # cm
                                           A_e=2.29e-4,  # cm2
                                           Vol=28.6e-6,
                                           )
