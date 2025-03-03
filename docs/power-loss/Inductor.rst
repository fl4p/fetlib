=============
Inductor Loss
=============

See `Considerations for Power Inductors Used for Buck Converters`_.

::

    Total Inductor Loss
    ├── Copper Loss
    │   ├── Wire Resistance (DCR)
    │   ├── Skin Effect (ACR)
    │   └── Proximity Effect
    └── Core Loss
        ├── Hysteresis Loss
        ├── Eddy Current Loss
        └── Net Loss

We neglect Proximity Effect, and Core Net Loss. We assume that Hysteresis and Eddy Current Loss are both modeled by the core loss density function from a core material's datasheet.


Total Inductor loss is:

.. math::
   P_{L} ≈ P_{L\_dcr} + P_{L\_acr}  + P_{L\_core}

:math:`P_{L\_dcr}` DC resistance loss; :math:`P_{L\_acr}` is the AC resistance loss due to skin effect and proximity effect;
:math:`P_{L\_core}` hysteresis and eddy current loss in the core material.


---------------
Winding Loss
---------------

.. math::
   P_{L\_dcr} = I_{L,rms}^2 \cdot R_dc

For the buck converter in CCM (continuous conduction mode, see `Selecting Inductors for Buck Converters`_) we calculate the mean-squared current of the triangular waveform:
and https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_converter_efficiency_app-e.pdf

.. math::
   I_{L,rms}^2 = I_DC^2 + \frac{\Delta I^2}{3}

Where :math:`I_DC` is the DC inductor current (output current of the converter), and :math:`\Delta I` is the ripple current (ac peak-peak).

AC Winding Loss:

Eddy currents inside the conductor cause a non-homogenous current density along the cross-section area of the conductor.
Close to the center eddy currents flow in opposite direction while near the conductor edge they superimpose in the same direction
as the main current, increasing total current density. This phenomena is called skin effect.

Two conductors very close to each other with currents flowing in the same direction are prone to proximity effect: current density decreases at the side
where both conductors are close to each other.

We assume that for toroid inductors with round wire conductors the ac resistance increase due to skin effect is much higher than the proximity effect (see below).

The skin depth is defined as the depth below the conductor surface where current density falls below 1/e.
We calculate the skin depth with:

.. math::
    {\displaystyle \delta ={\sqrt {(\frac {2 \rho }{2\pi f \cdot \mu })}}}

where :math:`\mu` is the resistivity (for copper ~1.7e-8 Ωm). Notice that skin depth increases with resistivity,
so the skin effect decreases in bad conductors.

We approximate the ac resistance of the round conductor with that of a hollow tube:

.. math::
    {\displaystyle R_AC\approx \frac{{\ell \rho }}{\pi (D-\delta )\delta }}

.. math::
    P_AC = \Delta I_RMS^2  \cdot R_AC

For the triangular current waveform:

.. math::
    P_AC = \frac{ \Delta I^2}{3} \cdot R_AC


TODO: equation for ac resistance loss
FPE: p 429

Circular conductor proximity effect power loss (TODO ref):

.. math::
    P_{pe} = \frac{{\pi \omega^2 \overline{\hat B}^2 l s d^4}}{128 \rho_c}

.. math::
    \overline{\hat B} = µ_0 \cdot N \hat I/l

where :math:`l`  is the eff. magnetic path length of the magnetic field through the winding and back trough the core.

Computation of proximity effect loss is not yet implemented (todo: calculate :math:`l` and :math:`\overline{\hat B}` for toroids).
It turns out to be rather complex to compute, Um et. al. refer to FEM, analytic and hybrid methods in `AC-Winding-Resistance Calculation of Toroidal Inductors with Solid-Round-Wire and Litz-Wire Winding Based on Complex Permeability Modeling`_ .

Their proposed method appears to have lowest error for multilayer windings comprising solid wires. In a loosely wound toroid inductor the skin effect dominates.
For the power loss optimization target it seems to be a good approach to choose thin litz wire so that the skin effect becomes negligible, e.g. AWG24 (d≈0.51mm) for 50 kHz.
Since proximity effect is proportional to :math:`d^4` we can assume that it plays a minor role when switching frequency is below ~200 kHz.
For an overview of wire Rac/Rdc ratios at common converter frequencies see `IRAUDPS1`_ (p. 30 Table 9) or `Transformer and Inductor Design Handbook` (p. 175, Table 4-13).

For accurate results measure the AC resistance at given frequency using an LCR meter.


https://www.e-magnetica.pl/doku.php/calculator/proximity_effect_from_dowell_curves
https://www.femm.info/wiki/HomePage
https://github.com/cenit/FEMM
FEMM core loss https://www.femm.info/wiki/ACLoss

* TRANSFORMER AND INDUCTOR DESIGN HANDBOOK p 174
* https://electronics.stackexchange.com/questions/586278/how-do-skin-effect-and-proximity-effect-behave-for-flat-conductor-power-inductor
* "Below 1 MHz, skin effect losses are generally insignificant and proximity effect losses will dominate."
* https://electronics.stackexchange.com/questions/594519/what-is-the-difference-between-esr-and-dcr?noredirect=1&lq=1
* TODO usually significant at f>500khz ? see F.E. Terman  Radio Engineers' Handbook
* https://www.edaboard.com/threads/skin-effect-for-a-rectangular-wave.183232/

---------------
Core Loss
---------------

Core loss in magnetic materials is complex to describe and manufacturers usually fit the Steinmetz relationship to measurement data.
To increase accuracy across a large frequency range and flux density range, they use a set of Steinmetz coefficients
or more advanced models (see Micrometals `A new core loss model`_).

Generally we compute total core loss by multiplying core loss density by effective magnetic area and path length of the core:

.. math::
   P_{L\_core} = PL(B_pk, f) \cdot A_e \cdot l_e


:math:`PL(B_pk, f)` is the loss density model specific to the core material and usually specified by the manufacturer in the datasheet of the material.


Notice that core loss density depends on the ac part of the flux density only (hysteresis loss & eddy current loss), which directly depends on the ripple current.
Higher DC bias current can still increase core loss due to core saturation and lowered permeability.

Micrometals Core Loss model:


.. math::
   PL(B_pk, f) = \frac{f}{\frac{a}{B_pk^3} + \frac{b}{B_pk^{2.3}} + \frac{c}{B_pk^{1.65}} } + d \cdot B_pk^2 \cdot f^2

with material constants :math:`a, b, c, d`. The expression :math:`d \cdot B_pk^2 \cdot f^2` models the eddy current loss.


Peak flux density (`Power core loss calculation`_):

.. math::
   B_pk = \frac{\Delta B}{2} = \frac{B_ACmax - B_ACmin}{2}

In magnetic powder cores flux density is not linear to magnetizing field, as permeability falls with increasing magnetization.
There are multiple ways to obtain the ac peak flux densities :math:`B_ACmax` and :math:`B_ACmin`.

Here we show the way using the BH-Curve from the material datasheet, also referred as Initial Magnetization Curve.

The Micrometals BH-Curve model is as follows:

.. math::
   B(H) = \frac{µ_i}{\frac{1}{H+aH^b} + \frac{1}{c+H^d} + \frac{1}{e}}

where magnectic flux density :math:`B` expressed in gauss, H in oersted and :math:`a,b,c,d,e` material specific constants from the data sheet.

The magnetic field strength inside an inductor:

.. math::
   H = \frac{N}{l_e} \cdot I_L

with number of turns :math:`N`, magnetic path length :math:`l_e`, inductor current :math:`I_L`

.. math::
   H_ACmax = \frac{N}{l_e} \cdot (I_DC + \Delta I/2)

.. math::
    H_ACmin = \frac{N}{l_e} \cdot (I_DC - \Delta I/2)

with DC current (converter output current) :math:`I_DC` and ripple current :math:`\Delta I`.


Finally, we compute the ac peak flux density

.. math::
   B_pk = \frac{B(H_ACmax) - B(H_ACmin)}{2}

which we use a input for the core loss density model. Notice that manufacturers tend to use *Unrationalized CGS* system,
so converting the magnetic field to oersted and the flux density to gauss might be necessary. (see `Fundamental of Power Electronics`_ p.413)


------------
Design Notes
------------

* Staking N cores while keeping inductivity value L0 and ID constant (i.e. reduce turns, add strands):
    * distribute flux across cores (N x A_e), lower flux density (but *not* generally 1/N!)
    * reduce core saturation
    * increased dc bias permeability causes less ripple current
    * does not significantly change core loss across load range
    * reduce winding R_dc (keeping ID constant)
    * wire loss is reduced more than linear, because ripple current is reduced as well

* Increasing µi while keeping L0 and ID constant:
    * increase core saturation
    * decreased dc bias permeability causes more ripple current
    * increase core loss
    * reduce winding R_dc
    * might have total reduced loss (despite higher ripple current)
    * similar $ price
    * shape converter efficiency curve: higher µi can increase high-load efficiency, but adds a constant loss
    * consider decision based on multiple (weighted) operating points


* Winding
    * Consider skin effect and multiple wire strands
    * For 50 kHz use AWG24 or higher (smaller diameter)

* Links
    * https://www.micrometals.com/design-and-applications/core-design-considerations/#inductor-design-basics
    * https://www.mag-inc.com/design/design-guides/inductor-cores-material-and-shape-choices


------------
Design Tools
------------



Cores, Windings:
https://micrometals.com/design-and-applications/software-guide/#DC-Inductor

FEMM

==========
Literature
==========


* "TRANSFORMER AND INDUCTOR DESIGN HANDBOOK" (McLyman)
    * chp4: skin effect, proximity effect (pg 173)
    * core loss: page 70
* "Fundamental of Power Electronics" (Robert Erikson)
* "Soft Ferrites, Properties and Applications" by E. C. Snelling, pages 344-345
* "Ferrites for Inductors and Transformers" by Snelling and Giles
* https://www.e-magnetica.pl/doku.php/start
* https://sci-hub.se/10.1109/28.936396 "Calculation of Losses in Ferro- and Ferrimagnetic Materials Based on the Modified Steinmetz Equation"

.. _Considerations for Power Inductors Used for Buck Converters: https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_pwr_ind_app-e.pdf
.. _A new core loss model: https://elnamagnetics.com/wp-content/uploads/library/Micrometals/A_New_Core_Loss_Model_for_Iron_Powder_Material.pdf
.. _Power core loss calculation: https://www.mag-inc.com/design/design-guides/powder-core-loss-calculation
.. _Fundamental of Power Electronics: https://elprivod.nmu.org.ua/files/converters/Robert_Erikson_fundamentals-of-power-electronics-3n_2020.pdf
.. _Selecting Inductors for Buck Converters: https://www.ti.com/lit/an/snva038b/snva038b.pdf
.. _AC-Winding-Resistance Calculation of Toroidal Inductors with Solid-Round-Wire and Litz-Wire Winding Based on Complex Permeability Modeling: https://www.mdpi.com/2075-1702/12/4/228
.. _IRAUDPS1: https://www.infineon.com/dgdl/Infineon-Evaluation_board_IRAUDPS1-ReferenceDesign-v00_02-EN.pdf?fileId=5546d462533600a40153569af6412c01
