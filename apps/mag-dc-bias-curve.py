"""

Plot DC bias curve for magnetic materials as commonly shown in the material data sheet.

"""
from maglib import materials
from maglib.plot import plot_dc_bias_curve

plot_dc_bias_curve([
    materials.Micrometals_Sendust_60u,
    materials.KDM_SendustKS_60,
    materials.MagInc_KoolMu_60,

    materials.Micrometals_MS_T_125u,
    materials.KDM_SendustKS_125,
])

"""
coil = CoilSpecs(
    Rdc=0.0067,  # micro-mat
    L0=161e-6,  # micro-mat
    turns=24,
    wire_diameter=1.8e-3,
    core=KDM_KS184_125A,
)

dcdc = DcDcLoadParams(71, 27, 39000, io=24, L=coil.Ldc(24))
print(dcdc)
"""
