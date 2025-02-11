from dslib.magnetics import H2oe, µ0
from dslib.magnetics.cores import MagneticCoreSpecs
from dslib.powerloss import CoilSpecs
from dslib.spec_models import DcDcLoadParams

"""

Indcutor Power Loss

Core Loss
    - Hysteresis Loss
    - Eddy Current Loss
    - Anomalous Loss
Wire Loss
    - RDC loss
    - skin effect
    - proximity
    
https://www.mdpi.com/2072-666X/13/3/418
https://www.e-magnetica.pl/doku.php/proximity_effect

Ridley-Nace Core Loss Formula
https://ridleyengineering.com/images/phocadownload/7%20modeling%20ferrite%20core%20losses.pdf


TODO 
Considerations:

- DC Bias
    "Core Loss Modeling of Inductive Components"
    https://www.psma.com/sites/default/files/uploads/tech-forums-magnetics/presentations/2012-apec-134-core-loss-modeling-inductive-components-employed-power-electronic-systems.pdf
        - dc bias
        - relaxation effects
        - eddy currents in tape wound cores
    
- Non-sinusoidal excitation
    "Accurate Prediction of Ferrite Core Loss with Nonsinusoidal Waveforms Using Only Steinmetz Parameters"
    Venkatachalani et al  (https://sci-hub.se/10.1109/CIPE.2002.1196712)
    
    "A Dynamic Core Loss Model for Soft Ferromagnetic and Power Ferrite Materials in Transient Finite Element Analysis"
    https://www.researchgate.net/publication/224747211_A_Dynamic_Core_Loss_Model_for_Soft_Ferromagnetic_and_Power_Ferrite_Materials_in_Transient_Finite_Element_Analysis
    
    
    
Micrometals Model:
    "A New Core Loss Model For Iron Powder Material" by Christopher Oliver,
    https://ridleyengineering.com/images/phocadownload/new%20core%20loss%20model.pdf
    

https://www.mag-inc.com/Design/Design-Tools/Inductor-Design/Thank-You
"""


def Bpk_dc_mag(dc: DcDcLoadParams, coil: CoilSpecs):
    """
    Compute peak ac flux density using dc magnetization curve
    :param dc:
    :param coil:
    :return:
    """
    # method 1 https://www.mag-inc.com/design/design-guides/powder-core-loss-calculation
    mat = coil.core.mat

    tpl = (coil.turns / coil.core.l_e)

    H_ac_max = tpl * dc.Io_max
    H_ac_min = tpl * dc.Io_min

    # TODO Hdc?
    B_ac_max = mat.dc_magnetization(H_oe=H2oe(H_ac_max))
    B_ac_min = mat.dc_magnetization(H_oe=H2oe(abs(H_ac_min))) * (-1 if H_ac_min < 0 else 1)

    Bpk = (B_ac_max - B_ac_min) / 2

    return Bpk


def Bpk_dc_bias(dc: DcDcLoadParams, coil: CoilSpecs):
    """
    Compute peak ac flux density using dc bias.
    Assume that effective µ is constant around the dc bias (i.e. ΔI << Io)
    :param dc:
    :param coil:
    :return:
    """
    # method 2 https://www.mag-inc.com/design/design-guides/powder-core-loss-calculation
    tpl = (coil.turns / coil.core.l_e)
    ΔH = tpl * dc.Iripple
    Hdc = tpl * dc.Io
    Bpk = .5 * µ0 * coil.core.mat.permeability_dc_bias(Hdc) * ΔH
    return Bpk


def Bpk_sinusoidal(dc: DcDcLoadParams, coil: CoilSpecs):
    # https://ridleyengineering.com/images/phocadownload/new%20core%20loss%20model.pdf#page=3
    vrms = 0
    Bpk = vrms * 10 / (4.44 * coil.core.A_e * 100e2 * coil.turns * dc.f / 1e3)
    return Bpk


def core_hysteresis_loss(Bpk: float, core: MagneticCoreSpecs, f: float):
    core_loss_density_mW_cm3 = core.mat.core_loss_density(Bpk_tesla=Bpk, f_khz=f * 1e-3)
    P_core = core_loss_density_mW_cm3 * core.A_e * core.l_e * 1e-3 * 1e6  # coil.core.Vol * 1e6 * 1e-3
    return P_core, Bpk, core_loss_density_mW_cm3


def core_loss_from_dc_magnetization(dc: DcDcLoadParams, coil: CoilSpecs):
    """

    After mag-inc's 'Method 1 – Determine Bpk from DC Magnetization Curve. Bpk= f(H)'
    https://www.mag-inc.com/design/design-guides/powder-core-loss-calculation


    :param dc: DC-DC operating point
    :param coil:
    :return: Estimated core loss in W
    """
    # assert abs(rel_err(dc.L, coil.L0)) < 0.1

    Bpk = Bpk_dc_mag(dc, coil)

    return core_hysteresis_loss(Bpk, core=coil.core, f=dc.f)


def core_loss_from_dc_bias(dc: DcDcLoadParams, coil: CoilSpecs):
    """

    mag-inc's method 2, for small ΔH (small ripple current)

    :param dc:
    :param coil:
    :return:
    """

    Bpk = Bpk_dc_bias(dc, coil)

    return core_hysteresis_loss(Bpk, core=coil.core, f=dc.f)

