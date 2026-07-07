![img.png](img.png)

# maglib

This library tries to help you with designing dc power inductors for switching converters, e.g. buck and boost
converters.

It contains a small selection of sendust and sendust-like powder core materials from Magnetics Inc, Micrometals and KDM.

* power loss
* dc bias

## Overview of functions

Wire:

* skin depth
* wire dc resistance
* wire ac resistance
    * skin effect
    * proximity effect
* average winding length
* TODO: multi-strand wire packing (bundle diameter etc) (snelling Soft Ferrites p338)

Power loss:

* core dc bias
* Bpk: peak ac flux density (or peak ac magnetic field)
    * two methods
* core hysteresis loss


# Wire Resistances

From snelling Soft Ferrites (p341):

R_ac = R_ac + R_se = R_dc * (1+F)

R_se is the increase in resistance due to skin effect.
F = R_ac/R_dc - 1

# How to design an inductor

Use
Micrometals [Inductor Design Tool](https://www.micrometals.com/design-and-applications/design-tools/inductor-designer/)
to find a suitable core shape, core material and winding for your design.

[KDM's Crossreference](https://semic.cz/!old/files/pdf_www/Ljf_KDM.pdf) can help you finding similar material from other
manufacturers.

With the Micrometals too you can compare multiple designs.
Analyze the design further these requirements:

* cost
* space/weight
* power loss
* ripple current
* wire diameter and strands
* core material permeability
* core material composition (e.g. optimized dc bias/saturation, core loss)

Once you picked a core shape and material, you can see if it is already here in this library. You can use the function
`micrometals_material()` to access nearly all Micrometals materials (it imports model properties from a CSV).

See `examples/`.

# Todo

- implement grid search or similar to have a design tool like the micrometals one

# More Resources

* Design Tools, Considerations
    * [Micrometals Design Tools](https://www.micrometals.com/design-and-applications/design-tools/)
    * Material Selection Guide by
      Application https://micrometals.com/design-and-applications/material-selection-application/
    * https://micrometals.com/design-and-applications/core-design-considerations/#inductor-design-basics
* [Encyclopedia Magnetica](https://www.e-magnetica.pl/doku.php/start)
* Books
    * E. C. Snelling, Soft Ferrites - Properties and Applications. Mendham: PSMA, 2010.
    * TRANSFORMER AND INDUCTOR DESIGN HANDBOOK Third Edition, Revised and Expanded, COLONEL WM. T. MCLYMAN
    * Inductors and Transformers for Power Electronics. Boca Raton, FL, USA: CRC Press, 2005.
    * [FUNDAMENTALS OF POWER ELECTRONICS ROBERT W. ERICKSON y DRAGAN MAKSIMOVIC](https://elprivod.nmu.org.ua/files/converters/Robert_Erikson_fundamentals-of-power-electronics-3n_2020.pdf)





