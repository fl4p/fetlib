
# Power Loss Model

The power loss model for a DC-DC buck is based on this rOHM article. We assume CCM mode, coil current never touches
zero.
Note that loss from LS reverse recovery `P_rr` is dissipated in HS. In other words, bad behaviour of LS heats up the HS.
The generated CSV file includes the estimated losses caused by a transistor when placed in the HS or LS slot.
Note that this power is not necessarily dissipated in the same switch.

# DCDC

In a buck converter, the high-side switch is desirably fast (low Q_d, r_g) and has low Rds_on.
The LS sync fet operates in a rather different way, parasitic turn-on can become a problem here.
Because we make use of the body diode, reverse recovery charge can cause high current peaks increasing losses in the HS
switch and input capacitor.
this [eetimes article](https://www.eetimes.com/how-fet-selection-can-optimize-synchronous-buck-converter-efficiency/)
gives a good overview.
https://github.com/fl4p/Fugu2/blob/main/doc/Mosfets.md

Most part suppliers have a parametric search function that is just good enough.
We can usually filter and sort by `Vdss`, `Id`, `Qg`, `Rds_on`.
For some specific applications we might want to filter more parameters that we can only find in the datasheet, such
as `Qrr`.

# Ranking mosfets

synchronous DC-DC converter

* Conduction loss (Rds_on)
* Switching losses (tRise+tFall)
* Reverse recovery losses (Qrr)
* Gate drive losses

According to
the [Rohm AN](https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/power_loss_appli-e.pdf),
high-side (control fet) switching losses are ~= C * (tRise + tFall) with C=0.5 * V_in * I_o * f_sw.

To rank MOSFETS, we can come up with a FoM like
Rds_on * Qrr * (tRise+tFall)

To reduce gate drive current and loss:
Rds_on * Qgd * Qrr * (tRise+tFall)

# Mosfet FOM

FOM (Figure of Merit) is a common performance indicator to rank MOSFET power loss for DC-DC converter applications.
Our aim is to reduce total mosfet loss:

```
P_mosfet = Pon + Psw + Prr + Pgd
Pon = A * Rds           # A ~ Io * Vo/Vi
Psw = B * (tRise+tFall) # B ~ Vin * Io * f
Prr = C * Qrr           # C = Vin * f
Pgd = D * Qg            # D ~ Vgs^2 * f

P_mosfet = A * (Rds) + B * (tRise+tFall) + C * (Qrr) + D * (Qg)
```

It tries to indicate a score about how efficient the MOSFET is in a switching app (the lower the better).

```
FOM = Rds_on * Qg
```

Yoo et al propose a new FOM [[2007, link](https://sci-hub.se/10.1109/EDSSC.2007.4450305)]:

```
FOM_new = (Il²) * Rds_on  +  (4 * fs * Vgg) * Qg`
```

* `Il`: average load current
* `fs`: switching frequency
* `Vgg`: gate driver supply voltage

However, with modern high-current gate drivers, low `Qg` becomes less important.
High-efficiency converter use fast switching times and `Qrr` becomes more
important [src](https://efficiencywins.nexperia.com/efficient-products/qrr-overlooked-and-underappreciated-in-efficiency-battle)

Note that GaN-switches have a `Qrr` of zero.

To find the best chip for a specific app, we can define our own custom scores, such as:

* `Rds_on * Qg / Vds`
* `sqrt(Rds_on * Qg * Qrr)`
* `Rds_on * Qrr`
* `Rds_on * Qrr * Qg * (t_rise+t_fall)`

In a half-bridge topology for synchronous DC-DC converters the HS and LS switch work in quite different
conditions. Current through the LS usually flows from Source to Drain in the direction of the body diode. It acts as a
synchronous rectifier aka. ideal diode



### Special Qrr Datasheets

* 'PSMN4R2-80YSEX': Qrr timing plot
* UM1575 User manual spice models
* PSMP050N10NS2_T0_00601: Vplateau
* IPA050N10NM5S : Vplateau
## Qg_th
- csd19506
- BSB056N10NN3: typo, Gate to drain charge confusion



# Coss power loss
* Use ocr (sample 'BUK7E4R0-80E,127.pdf', 'IPB019N08N3GATMA1' ) `ocrmypdf` can recover the text, but doesn't recognize
  symbols
  correctly.
* Mouser, API?
* Extract more fields
    * Qgd/Qgs (self turn on)
    * Vsd (body diode forward voltage)
    * r_g

# Resources

* https://www.discoveree.io/
* https://octopart.com/ (Ciss, rise&fall times, )
* https://epc-co.com/epc/design-support/part-cross-reference-search
  * a very useful tool that comes with power loss calculations. i found some values to be off, e.g. IPA050N10NM5S Rds_on_max@10V is 5, in the app its 5.6.

https://www.discoveree.io/collateral/continental/PCIM2020_DiscoverEE_PowerLossModeling_AudioVisual.mp4
https://www.discoveree.io/collateral/PCIM_Europe_2020/PCIM2020_DiscoverEE_PowerLossModeling_Slides.pdf
https://pcimasia-expo.cn.messefrankfurt.com/content/dam/messefrankfurt-redaktion/pcim_asia/download/pac2020/speakers-ppt/1/Shishir%20Rai.pdf
https://ww1.microchip.com/downloads/en/Appnotes/01471A.pdf
https://www.st.com/resource/en/application_note/dm00380483-calculation-of-turnoff-power-losses-generated-by-a-ultrafast-diode-stmicroelectronics.pdf
https://www.vishay.com/docs/73217/an608a.pdf

# names

fetlib
mosfetlib
fetfinder
findfet
mosdb