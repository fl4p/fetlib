import math
from typing import Union

import maglib.materials as materials
from dslib import round_to_n, rel_err
from maglib.materials import MagInc_KoolMu_60, KDM_SendustKS_60, MagneticCoreMaterialSpecs

µ0 = 4 * math.pi * 1e-7


class ToroidShape():
    def __init__(self, name, l_e, A_e, Vol, od=math.nan, id=math.nan, ht=math.nan,
                 id_coated=math.nan):
        """

        :param name:
        :param l_e:
        :param A_e:
        :param Vol:
        :param od:
        :param id: BARE core nominal inner diameter
        :param ht:
        :param id_coated: coated-core MINIMUM inner diameter, i.e. the bore a
            winding actually has to pass through. Datasheets publish both; the
            coating costs 0.8-1.3 mm of bore, which is a whole strand on a
            small core. See ``winding_bore_coated()``.
        """

        # assert math.isnan(od), "not implemented"
        # assert math.isnan(id), "not implemented"
        # assert math.isnan(ht), "not implemented"

        self.name = name
        self.l_e = l_e
        self.A_e = A_e
        self.Vol = Vol
        self.ID = id
        self.OD=od
        self.HT=ht
        self.ID_coated = id_coated

        assert 0.9 < (self.A_e * self.l_e / self.Vol) < 1.1, (self.A_e * self.l_e, self.Vol)

    def values(self):
        return dict(l_e=self.l_e, A_e=self.A_e, Vol=self.Vol)

    def stack(self, n):
        return ToroidShape(f'{n}s({self.name})', l_e=self.l_e, A_e=self.A_e*n, Vol=self.Vol*n, od=self.OD, id=self.ID,
                           ht=self.HT*n, id_coated=self.ID_coated
                           )


class MagneticCoreSpecs:
    def __init__(self, mpn, mat: MagneticCoreMaterialSpecs, shape: ToroidShape = None, l_e=None, A_e=None, Vol=None,
                 A_L=None):
        """

        :param mpn:
        :param mat:
        :param l_e: effective magnetic path length in m
        :param A_e: eff. magnetic cross-sectional Area in m2
        :param Vol:  core volume in m3
        """

        if shape is None:
            assert l_e is not None
            assert A_e is not None
            assert Vol is not None
        else:
            l_e = shape.l_e
            A_e = shape.A_e
            Vol = shape.Vol

        self.shape = shape

        if A_L is None:
            A_L = µ0 * mat.mu_r * A_e / l_e

        self.mat = mat
        self.mpn = mpn
        self.A_L = A_L
        self.l_e = l_e  # magnetic path length
        self.A_e = A_e  # in m2
        self.Vol = Vol

        assert 0.9 < (self.A_e * self.l_e / self.Vol) < 1.1, (self.A_e * self.l_e, self.Vol)
        assert abs(rel_err(µ0 * mat.mu_r * A_e / l_e, self.A_L)) < 0.04, (µ0 * mat.mu_r * A_e / l_e, self.A_L)

    def winding_bore(self):
        """(ID, OD) in m, for the winding models. Raises if not known.

        Proximity loss needs the mean turn length, b_eq = pi/2*(ID + OD), so a
        core given only l_e/A_e/Vol cannot be wound by
        ``acr_factor_micrometals``. Callers reached that through
        ``core.shape.ID`` and got ``AttributeError: 'NoneType' object has no
        attribute 'ID'`` from inside the loss calculation -- true, loud, and
        useless: it names neither the core nor what is missing, and every
        shape-less core in this module hits it, which is most of them.

        Refusing here rather than substituting a guessed bore is deliberate.
        A plausible OD/ID would flow straight into b_eq and produce a
        confident, wrong proximity loss; the honest failure is to say the
        geometry is absent and let the caller supply a ToroidShape.
        """
        if self.shape is None or not math.isfinite(getattr(self.shape, 'ID', math.nan)) \
                or not math.isfinite(getattr(self.shape, 'OD', math.nan)):
            raise ValueError(
                '%s: winding geometry unknown -- this core was defined without '
                'a ToroidShape carrying OD/ID, so proximity loss (b_eq = '
                'pi/2*(ID+OD)) cannot be computed. Give it shape=<ToroidShape> '
                'with the datasheet OD/ID rather than guessing them.' % self.mpn)
        return self.shape.ID, self.shape.OD

    def winding_bore_coated(self):
        """(ID_coated_min, OD) in m — the bore a winding must actually fit through.

        ``winding_bore()`` returns the BARE-core nominal ID, which no wire ever
        sees: powder cores ship parylene/epoxy coated, and the datasheets quote
        a separate coated-core MINIMUM ID that is 0.8-1.3 mm smaller. That is a
        real strand on a small core -- on a T250 the bare bore admits 108
        passes of 1.909 mm wire at 0.4 fill and the coated bore only 101, which
        moves the optimum from 15 turns x 7 strands to 14 x 7.

        This RAISES when the coated ID is unknown rather than falling back to
        the bare ID. The fallback would be optimistic in exactly the direction
        that matters -- it would silently claim a strand that does not fit --
        and a strand-count model that quietly rounds in its own favour is worse
        than one that refuses, because nothing downstream can tell the
        difference between "measured" and "assumed".
        """
        id_bare, od = self.winding_bore()          # reuse its shape/OD checks
        if not math.isfinite(getattr(self.shape, 'ID_coated', math.nan)):
            raise ValueError(
                '%s: coated-core minimum ID unknown -- the ToroidShape carries '
                'only the bare ID (%.2f mm). Winding fit must not be computed '
                'from the bare bore; the coating takes ~0.8-1.3 mm of it. Add '
                'id_coated=<datasheet "Coated Core (min)" ID> to the shape.'
                % (self.mpn, id_bare * 1e3))
        return self.shape.ID_coated, od

    def stack(self, n):
        assert n > 0
        if n == 1:
            return self
        if self.shape:
            shape = self.shape.stack(n)
            return MagneticCoreSpecs(
                f'{n}s({self.mpn})', self.mat,
                shape=shape,
            )
        else:
            return MagneticCoreSpecs(
                f'{n}s({self.mpn})', self.mat,
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

# Toroid shapes from the Micrometals Alloy Powder Cores catalogue (2021),
# "Physical Dimensions" / "Magnetic Dimensions" block per size:
#   https://s3.amazonaws.com/micrometals-production/filer_public/2f/ed/
#     2fedd6eb-44d0-4834-a442-8222486f0b77/micrometals_alloy-en-2021.pdf
# od/id/ht are the BARE CORE NOMINAL values, id_coated the COATED CORE (min) ID.
# Every one of these was cross-checked against the per-part datasheet at
# https://datasheets.micrometals.com/<PN>-DataSheet.pdf, and structurally
# against A_e ~ (OD-ID)/2*Ht and l_e ~ pi*(OD+ID)/2.
#
# Why the list is long: winding fit is limited by BORE AREA, not core volume,
# so a sweep restricted to the two sizes this module used to define (130/184)
# cannot see the answer -- one size up beats stacking, because stacking
# multiplies A_L but adds exactly zero bore. `winding_bore()` correctly refused
# the shape-less cores, which made the omission silent rather than wrong.
MicrometalsT130 = ToroidShape('130', l_e=8.15e-2, A_e=0.672e-4, Vol=5.48e-6, od=33.02e-3, id=19.94e-3, ht=10.67e-3,
                              id_coated=19.30e-3)
# ^ Vol was 5.69e-6 here, which is T132's volume, not T130's. A_e*l_e = 5.48e-6
#   disagreed with it by 3.8% -- inside the 0.9..1.1 consistency assert below,
#   so it never fired. The catalogue and KDM_KS130_060A both say 5.48.
MicrometalsT132 = ToroidShape('132', l_e=8.15e-2, A_e=0.698e-4, Vol=5.69e-6, od=33.02e-3, id=19.94e-3, ht=11.18e-3,
                              id_coated=19.30e-3)
MicrometalsT157 = ToroidShape('157', l_e=9.85e-2, A_e=1.07e-4, Vol=10.50e-6, od=39.88e-3, id=24.13e-3, ht=14.48e-3,
                              id_coated=23.32e-3)
MicrometalsT184 = ToroidShape('184', l_e=10.743e-2, A_e=1.99e-4, Vol=21.4e-6, od=46.74e-3, id=24.13e-3, ht=18.03e-3,
                              id_coated=23.32e-3)
MicrometalsT185 = ToroidShape('185', l_e=11.62e-2, A_e=1.34e-4, Vol=15.60e-6, od=46.74e-3, id=28.70e-3, ht=15.24e-3,
                              id_coated=27.89e-3)
MicrometalsT200 = ToroidShape('200', l_e=12.733e-2, A_e=1.25e-4, Vol=15.90e-6, od=50.80e-3, id=31.75e-3, ht=13.46e-3,
                              id_coated=30.94e-3)
MicrometalsT225 = ToroidShape('225', l_e=14.296e-2, A_e=1.44e-4, Vol=20.70e-6, od=57.15e-3, id=35.56e-3, ht=13.97e-3,
                              id_coated=34.75e-3)
MicrometalsT226 = ToroidShape('226', l_e=12.506e-2, A_e=2.29e-4, Vol=28.60e-6, od=57.15e-3, id=26.39e-3, ht=15.24e-3,
                              id_coated=25.58e-3)
MicrometalsT250 = ToroidShape('250', l_e=14.314e-2, A_e=3.89e-4, Vol=55.80e-6, od=63.50e-3, id=31.37e-3, ht=25.00e-3,
                              id_coated=30.48e-3)
MicrometalsT292 = ToroidShape('292', l_e=18.40e-2, A_e=4.94e-4, Vol=90.90e-6, od=74.10e-3, id=45.30e-3, ht=35.00e-3,
                              id_coated=44.10e-3)
MicrometalsT300 = ToroidShape('300', l_e=19.612e-2, A_e=1.77e-4, Vol=34.80e-6, od=77.80e-3, id=49.23e-3, ht=12.70e-3,
                              id_coated=47.96e-3)
MicrometalsT301 = ToroidShape('301', l_e=19.612e-2, A_e=2.22e-4, Vol=43.50e-6, od=77.80e-3, id=49.23e-3, ht=15.88e-3,
                              id_coated=47.96e-3)
# https://datasheets.micrometals.com/MS-184125-2-DataSheet.pdf

# https://www.semic.cz/media/pdf/Ljf_T184-S-125A_KD.pdf
KDM_KS184 = ToroidShape('KS184', l_e=10.74e-2, A_e=1.99e-4, Vol=21.30e-6, od=46.7e-3, id=24.11e-3, ht=18.0e-3)

# https://www.kdm-mag.com/products/details-toroidal-1375.html
# https://semic.cz/!old/files/pdf_www/Ljf_KS130-060A_KD.pdf
KDM_KS130_060A = MagneticCoreSpecs('KDM_KS130_060A', KDM_SendustKS_60,
                                   A_L=61e-9,  # nH/N2
                                   l_e=8.125e-2,  # cm
                                   A_e=0.672e-4,  # cm2
                                   Vol=5.480e-6,
                                   )

KDM_KS184_125A = MagneticCoreSpecs('KDM_KS184_125A', materials.KDM_SendustKS_125,
                                   A_L=281e-9,  # nH/N2
                                   shape=KDM_KS184,  # supplies l_e/A_e/Vol + bore (KDM datasheet)
                                   )

# https://datasheets.micrometals.com/MS-130060-2-DataSheet.pdf
Micrometals_MS_130_060 = MagneticCoreSpecs('MS-130060-2',
                                           materials.Micrometals_Sendust_60u,
                                           shape=MicrometalsT130,
                                           #**MicrometalsT130.values(),
                                           A_L=61e-9,  # nH/N2
                                           )

# `shape=` rather than `**shape.values()`: values() returns only l_e/A_e/Vol
# and DROPS the bore dimensions, leaving shape=None on a core whose OD/ID are
# known. The winding models need them -- proximity loss scales with the mean
# turn length b_eq = pi/2*(ID+OD) -- so stripping them made these cores
# unusable in dcdc_buck_coil for no reason. Same numbers, plus the geometry.
# https://datasheets.micrometals.com/MS-184060-2-DataSheet.pdf
Micrometals_MS_184_060 = MagneticCoreSpecs('MS-184060-2',
                                           materials.Micrometals_Sendust_60u,
                                           shape=MicrometalsT184,
                                           A_L=135e-9,  # nH/N2 (checksum)
                                           )

# https://datasheets.micrometals.com/MS-184090-2-DataSheet.pdf
Micrometals_MS_184_090 = MagneticCoreSpecs('MS-184090-2',
                                           materials.Micrometals_MS_T_090u,
                                           shape=MicrometalsT184,
                                           A_L=202e-9,  # nH/N2 (checksum)
                                           )

# https://datasheets.micrometals.com/MS-184125-2-DataSheet.pdf
Micrometals_MS_184_125 = MagneticCoreSpecs('MS-184125-2',
                                           materials.Micrometals_MS_T_125u,
                                           shape=MicrometalsT184,
                                           A_L=281e-9,  # nH/N2
                                           )

# https://datasheets.micrometals.com/OE-184060-2-DataSheet.pdf
Micrometals_OE_184_060 = MagneticCoreSpecs('OE-184060-2',
                                           materials.Micrometals_OE_60u,
                                           shape=MicrometalsT184,
                                           A_L=135e-9,  # nH/N2
                                           )

# https://datasheets.micrometals.com/OE-226060-2-DataSheet.pdf
Micrometals_OE_226_060 = MagneticCoreSpecs('OE-226060-2', materials.Micrometals_OE_60u,
                                           A_L=138e-9,  # nH/N2
                                           l_e=12.506e-2,  # cm
                                           A_e=2.29e-4,  # cm2
                                           Vol=28.6e-6,
                                           )

MicrometalsToroidShapes = {
    130: MicrometalsT130,
    132: MicrometalsT132,
    157: MicrometalsT157,
    184: MicrometalsT184,
    185: MicrometalsT185,
    200: MicrometalsT200,
    225: MicrometalsT225,
    226: MicrometalsT226,
    250: MicrometalsT250,
    292: MicrometalsT292,
    300: MicrometalsT300,
    301: MicrometalsT301,
}


def MicrometalsToroid(mat: materials.MicroMetalsMatLiteral, ui, shape: Union[ToroidShape, int]):
    if isinstance(shape, int):
        shape = MicrometalsToroidShapes[shape]
    mpn = mat + '-' + shape.name + '%03d' % ui
    return MagneticCoreSpecs(mpn, materials.micrometals_material(mat, 'T', ui), shape=shape)
