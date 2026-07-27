import math

from maglib import H2oe, µ0
from maglib.cores import MagneticCoreSpecs
from dclib.powerloss import CoilSpecs
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
    """Peak AC flux density from the applied volt-seconds.

    Oliver / Ridley, "A New Core Loss Model For Iron Powder Material", p.3:

        Bpk = Vrms x 10^1 / (4.44 x Area x N x f)

    "Bpk is the peak AC flux density in tesla, Vrms measured voltage in volts,
    Area is the cross-section area of the core in cm2, N is the number of turns
    and f is the frequency in kHz." The scaling below is that equation
    verbatim: ``A_e`` is stored in m2 (x1e4 -> cm2) and ``dc.f`` in Hz
    (/1e3 -> kHz), so the result is tesla, matching what ``core_loss_density``
    expects for ``Bpk_tesla``.

    ``vrms`` was hardcoded to 0, so this returned Bpk = 0 for EVERY operating
    point. Zero flux gives zero core loss, which is the one answer that makes
    any inductor look perfect -- the failure is invisible precisely where a
    core is worst. Nothing calls this today, so it was latent rather than live.

    Vrms is the RMS of the voltage across the INDUCTOR, which in a CCM buck is
    a square wave: (Vi - Vo) for D of the period and -Vo for the remainder, so

        Vrms^2 = D*(Vi - Vo)^2 + (1 - D)*Vo^2

    which for the ideal D = Vo/Vi reduces to Vrms = sqrt(Vo*(Vi - Vo)).

    CAVEAT, and it is not small. The 4.44 is 2*pi/sqrt(2), the form factor of a
    SINE -- the paper uses this equation for its sinusoidally-driven measuring
    setup (Figure 5), not for a switching converter. Feeding it a square wave's
    RMS is therefore an approximation, and the error depends on duty cycle.
    Against the exact volt-second result, Bpk = Vo*(1 - D)/(2*f*N*A_e):

        ratio = (2/4.44) / sqrt(D*(1 - D))

        D = 0.5        0.90   (10% low)
        D = 0.4, 0.6   0.92
        D = 0.2, 0.8   1.13
        D = 0.1, 0.9   1.50   (50% high)

    So it is reasonable near 50% duty and poor at the extremes. Prefer
    ``Bpk_dc_mag`` or ``Bpk_dc_bias`` for a converter operating point; this
    exists to drive the Oliver model on the terms that model was fitted on.
    """
    # https://ridleyengineering.com/images/phocadownload/new%20core%20loss%20model.pdf#page=3
    D = dc.D_buck
    vrms = math.sqrt(D * (dc.Vi - dc.Vo) ** 2 + (1 - D) * dc.Vo ** 2)
    Bpk = vrms * 10 / (4.44 * coil.core.A_e * 100e2 * coil.turns * dc.f / 1e3)
    return Bpk


def core_hysteresis_loss(Bpk: float, core: MagneticCoreSpecs, f: float):
    # TODO this probably includes eddy current loss
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

