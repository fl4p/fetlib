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

:math:`P_{L\_dcr}` DC resistance loss; :math:`P_{L\_acr}` is the AC resistance loss due to skin effect;
:math:`P_{L\_core}` hysteresis and eddy current loss in the core material.


---------------
Winding Loss
---------------

.. math::
   P_{L\_dcr} = I_{L,rms}^2 \cdot R_dc

For the buck converter in CCM (continuous conduction mode, see `Selecting Inductors for Buck Converters`_):

.. math::
   I_{L,rms}^2 = I_DC^2 + \frac{\Delta I^2}{12}

AC Winding Loss:

Circual conductor proximity effect power loss:

.. math::
    P_{pe} = \frac{{\pi \omega^2 \overline{\hat B}^2 l s d^4}}{128 \rho_c}

.. math::
    \overline{\hat B} = µ_0 \cdot N \hatI/l

where l  is the eff. magnetic path length of the magnetic field through the winding and back trough the core.

* TRANSFORMER AND INDUCTOR DESIGN HANDBOOK p 174
* https://electronics.stackexchange.com/questions/586278/how-do-skin-effect-and-proximity-effect-behave-for-flat-conductor-power-inductor
"Below 1 MHz, skin effect losses are generally insignificant and proximity effect losses will dominate."
https://electronics.stackexchange.com/questions/594519/what-is-the-difference-between-esr-and-dcr?noredirect=1&lq=1

* TODO usually significant at f>500khz ? see F.E. Terman  Radio Engineers' Handbook
https://www.edaboard.com/threads/skin-effect-for-a-rectangular-wave.183232/

---------------
Core Loss
---------------

Core loss in magnetic materials is complex to describe and manufacturers usually fit the Steinmetz relationship to measurement data.
To increase accuracy across a large frequency range and flux density range, they use a set of Steinmetz coefficients
or more advanced models (see Micrometals `A new core loss model`_).


.. math::
   P_{L\_core} = PL(B_pk, f) \cdot A_e \cdot l_e


:math:`PL(B_pk, f)` is the loss density model specific to the core material and usually specified by the manufacturer in the datasheet of the material.


Notice that core loss density depends on the ac part of the flux density only (hysteresis loss), which directly depends on the ripple current.
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

Here we show the way using the BH-Curve from the material datasheet, also referred as Initial Magnetization Curve or DC-Magnetization Curve.

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



.. _Considerations for Power Inductors Used for Buck Converters: https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/buck_pwr_ind_app-e.pdf
.. _A new core loss model: https://elnamagnetics.com/wp-content/uploads/library/Micrometals/A_New_Core_Loss_Model_for_Iron_Powder_Material.pdf
.. _Power core loss calculation: https://www.mag-inc.com/design/design-guides/powder-core-loss-calculation
.. _Fundamental of Power Electronics: https://elprivod.nmu.org.ua/files/converters/Robert_Erikson_fundamentals-of-power-electronics-3n_2020.pdf
.. _Selecting Inductors for Buck Converters: https://www.ti.com/lit/an/snva038b/snva038b.pdf


==========
Literature
==========


"TRANSFORMER AND INDUCTOR DESIGN HANDBOOK" (McLyman)
* chp4: skin effect, proximity effect (pg 173)
* core loss: page 70
"Fundamental of Power Electronics" (Robert Erikson)
"Soft Ferrites, Properties and Applications" by E. C. Snelling, pages 344-345"
" "Ferrites for Inductors and Transformers" by Snelling and Giles"