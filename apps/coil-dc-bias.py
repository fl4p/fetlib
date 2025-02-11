import dslib.magnetics.materials
from dslib.magnetics.cores import KDM_KS184_125A
from dslib.magnetics.plot import plot_dc_bias_curve

from dslib.magnetics.materials import MagInc_KoolMu_60, Micrometals_Sendust_60u, Micrometals_MS_T_125u
from dslib.powerloss import CoilSpecs
from dslib.spec_models import DcDcLoadParams

plot_dc_bias_curve(MagInc_KoolMu_60)
#plot_dc_bias_curve(Micrometals_Sendust_60u)
plot_dc_bias_curve(Micrometals_MS_T_125u)
plot_dc_bias_curve(dslib.magnetics.materials.KDM_SendustKS_125)

coil = CoilSpecs(
    Rdc=0.0067,# micro-mat
    L0=161e-6, #micro-mat
    turns=24,
    wire_diameter=1.8e-3,
    core=KDM_KS184_125A,
)

dcdc = DcDcLoadParams(71, 27, 39000, io=24, L=coil.Ldc(24))
print(dcdc)