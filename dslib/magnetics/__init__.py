import math

from dslib.magnetics.cores import KDM_KS130_060A
from dslib.magnetics.materials import KDM_SendustKS_60, MagInc_KoolMu_60, Micrometals_Sendust_60u
#from dslib.powerloss import MagneticCoreMaterialSpecs, dcdc_buck_coil, CoilSpecs

µ0 = 4 * math.pi * 1e-7

oe = 1000 / (4 * math.pi)


def oe2Apm(H_oe):
    return H_oe * oe


def Apm2oe(H):
    return H / oe


def _main():
    materials = [Micrometals_Sendust_60u, MagInc_KoolMu_60, KDM_SendustKS_60]
    from dslib.magnetics.plot import core_loss_density_curves
    core_loss_density_curves(materials, f_khz=40)
    from dslib.magnetics.plot import dc_bias_curves
    dc_bias_curves(materials)
    from dslib.magnetics.plot import dc_magnetization_curves
    dc_magnetization_curves(materials)
    return

    # mag-inc example https://www.mag-inc.com/design/design-guides/powder-core-loss-calculation

    p0 = KDM_SendustKS_60.core_loss_density(B_tesla=300e-4, f_khz=50)
    print(p0)

    L = 47e-6

    from dslib.spec_models import DcDcSpecs
    dcdc = DcDcSpecs(vi=66, vo=27, pin=800, f=40e3, Vgs=11, tDead=400e-9, L=L)

    core = KDM_KS130_060A.stack(2)

    p_coil = dcdc_buck_coil(dcdc, CoilSpecs(L, Rdc=4e-3, turns=19.5, core=core))
    print(p_coil)


if __name__ == '__main__':
    _main()
