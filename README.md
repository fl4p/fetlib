# Extensive parametric search of MOSFETs for DC-DC converters

.. and how to acquire and programmatically read PDF datasheets.

Most part suppliers have a parametric search function that is just good enough.
We can usually filter and sort by `Vdss`, `Id`, `Qg`, `Rds_on`.
For some specific applications we might want to filter more parameters that we can only find in the datasheet, such
as `Qrr`.

# Noteworthy Tools

* https://octopart.com/ (Ciss, rise&fall times, )

# Switching Losses in a synchronous DC-DC converter

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

Values for Rds_on and Qgd are usually shown in the search results (Digikey, LCSC).
Nexar API doesn't show the Qrr, and (tRise+tFall) only for some parts (especially values for newer chips are missing
here).
So I found the only way to extract Qrr from the Datasheet.
There are at least these 2 ways:

1. Convert the PDF to txt and find the values with regular expressions. this can be tedious work, as table structure is
   not homogenous across manufacturers and some manufacturers use different formats across product series and release
   date. each extracted field usually requires its own regex since tables include testing conditions or design notes.
2. use tabula (or another pdf2table program) to read the tables from the PDF. there is a python binding available that
   produces pandas DataFrames. (I had some issues getting java running on Mac M2, use zulu JDK)

# FOM

FOM (Figure of Merit) is a common performance indicator to rank MOSFET power loss for DC-DC converter applications.
Our aim is to reduce total mosfet loss:
P_mosfet = Pon + Psw + Prr + Pgd
Pon = A * Rds               # A ~ Io * Vo/Vi
Psw = B * (tRise+tFall)     # B ~ Vin * Io * f
Prr = C * Qrr               # C = Vin * f
Pgd = D * Qg                # D ~ Vgs^2 * f
P_mosfet = A * (Rds) + B * (tRise+tFall) + C * ()
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

Most part suppliers

In a half-bridge topology for synchronous DC-DC converters the HS and LS switch work in quite different
conditions.

Current through the LS usually flows from Source to Drain in the direction of the body diode. It acts as a
synchronous rectifier aka. ideal diode

The HS current is usually

When the DC-DC converter is in boost operation, currents are reverse. HS is now a synchronous rectifier.

HS:

* Low Qrr
* Fast rise-time

LS:

* Low
* Examples:
*
*

Most part suppliers dont have a parametric search for Qrr. Also filtering and sorting by FoM and custom FoM is not
possible.

# FoM

# Potential Sources

- Digikey
- LCSC
- Mouser / API

# Digikey

- N-Ch, 80V, Idc>25A, Qg<250nC, RdsON<
  10mOhm [453 results](https://www.digikey.de/de/products/filter/transistoren/fets-mosfets/einzelne-fets-mosfets/278?s=N4IgjCBcoGwAwyqAxlAZgQwDYGcCmANCAPZQDaIAzAOwAcAnIyALpEAOALlCAMocBOASwB2AcxABfIgCYEtJCE7cAqsMEcA8mgCyeDDgCu-PCCIHuANVMgAtiO6041mxgAe3MHCdSQ06TGkFJUgQAGFiAzYsPAATVXUtXX0jEzNuYVDnN25pAFZvCQkgA)
    - [80V 26A 10mOhm 250nC.csv](digikey-results/80V%2026A%2010mOhm%20250nC.csv)

## Datasheet Acquisition

Downloads for some datasheet are protected by anti-robot mechanism.
To avoid this, we use pyppeteer (Python port of puppeteer) with Chromium to simulate human user interaction.
This will handle JS challenges, redirects and if the link points to a PDF-Preview page, we look for a download button
and
click it.

Chromiums PDF must be disabled, because we cannot access it through pupeteer.
`chromiumUserDataPath/Default/Preferences`:

```
"plugins": {"always_open_pdf_externally": true},
```

## Reading Values from the Datasheets

- some DS (IPB019N08N3GATMA1) have garbage text. `ocrmypdf` can recover the text, but doesn't recognize symbols
  correctly.

## Notes about Qrr

Qrr is usually defined by design and values from the data-sheet are not subject to production test.
Qrr depends on temperature, reverse voltage V_R, forward current I_F and forward current transient dif/dt.
Most datasheets only specify a single value under some given conditions.
DS of IQD016N08NM5 includes one for dif/dt=100A/us and dif/dt=1000A/us
Infineon diF/dt=100 A/μs

### Special Qrr Datasheets

* 'PSMN4R2-80YSEX': Qrr timing plot
* UM1575 User manual spice models

## OCR needed

* 'BUK7E4R0-80E,127'

# Acquiring Parts Lists (Search Results)

* Digikey: use the filters to reduce number of results to 500 or less. then export csv
* LCSC: use Browser Developer Tools to copy HTML DOM of each results page.

# PDF Processing Tools

* tabula (pdf table extraction), open source
* 