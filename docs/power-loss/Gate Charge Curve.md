# Vishay AN608A (Feb-2016)

**Power MOSFET Basics: Understanding Gate Charge and Using it to Assess Switching Performance**
https://www.vishay.com/docs/73217/an608a.pdf

![img.png](img/img.png)
![img_1.png](img/img_1.png)

"It is often stated in the literature that VTH + IDS/gfs can be
substituted for Vgp. While technically correct, the users
should be aware that transconductance is not constant but
varies with load. The datasheet value for VTH is specified at
a low value of IDS, at which the Vgp tends to be higher than
the calculated value. Using the value of Vgp from the gate
charge curves is recommended for accurate results."

"It is difficult to use a value of Cgd for the fall time period of
Vds (tvf = t3). Therefore if the datasheet value of gate charge
QGD is used and divided by the voltage swing seen on the
drain connection VDS then this effectively gives a value for
Cgd based on the datasheet transient."

![img_2.png](img/img_2.png)

## Infineon MOSFET Power Losses Calculation Using the DataSheet Parameters - 2006

https://application-notes.digchip.com/070/70-41484.pdf

![img_16.png](img/img_16.png)
![img_17.png](img/img_17.png)

"It is supposed that if the drain-source voltage is in the
range uDS∈[UDD/2,UDD], then the gate-drain capacitance takes value of CGD1= CGD(UDD). On the other
hand, if the drain-source voltage is in the range uDS∈[0V,UDD/2], then the gate-drain capacitance
takes value of CGD2= CGD(RDSon·Ion)."

![img_18.png](img/img_18.png)

## Other / TODO

Making Use of Gate Charge Information in MOSFET and
IGBT Data
Sheets https://ww1.microchip.com/downloads/aemDocuments/documents/sic/ApplicationNotes/ApplicationNotes/APT0103.pdf

https://www.ti.com/lit/an/slyt664/slyt664.pdf
"MOSFET power losses and how they affect power-supply efficiency"

* assumes a constant gate drive current. not applicable / high error with CV + R gate drive and high Vpl.
* ![img_3.png](img/img_3.png) ![img_4.png](img/img_4.png)
* ![img_5.png](img/img_5.png)
* ![img_6.png](img/img_6.png)
* ![img_7.png](img/img_7.png)
* ![img_8.png](img/img_8.png)
* ![img_9.png](img/img_9.png)
* ![img_10.png](img/img_10.png)

https://epc-co.com/epc/Portals/0/epc/documents/application-notes/AN030%20Hard%20Switching%20Losses%20Calculation.pdf
Hard Switching Losses Calculations
![img_11.png](img/img_11.png)
![img_12.png](img/img_12.png)
![img_13.png](img/img_13.png)
![img_14.png](img/img_14.png)

https://www.ti.com/lit/an/slpa009a/slpa009a.pdf

https://assets.nexperia.com/documents/white-paper/White_paper_SiC_MOSFETs_HR.pdf

rohm
https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/power_loss_appli-e.pdf

| Consideration | Description                                            |
|---------------|--------------------------------------------------------|
| Ig - Vpl      | With a CV gate drive, the gate current is not constant |
| Icr/Ivr       |                                                        |
|               |                                                        |
|               |                                                        |

| AN                 | Ig(t)              | LCSI | Tj                 | self turn-on | overlap loss | comments                                       |
|--------------------|--------------------|------|--------------------|--------------|--------------|------------------------------------------------|
| EPC AN030  2024    | ✅                  | no   | ✅                  | no           | ✅            |                                                |
| Nexperia WP  2024  |                    |      |                    |              |              |                                                |
| SLVAEQ9–July 2020  | ✅                  | no   | yes, not specified |              |              |                                                |
| Vishay AN608A 2016 | ✅                  | ✅    | no                 | no           |              |                                                |
| TI AA 1Q 2016      | yes, not specified | no   | no                 | ✅            |              | BD Conduction loss, freq charts, HS/LS         |
| TI SLPA009A 2011   | (no) for Qgd>>Qgs2 | ✅    | no                 | no           | no           | need adjustments for modern fets with Qgd<Qgs2 |
| Infineon AN 2006   |                    |      | ✅                  |              |              | CGD(UDD)                                       |
| rohm               |                    |      |                    |              |              |                                                |

# TODO

* https://www.onsemi.com/pub/collateral/and9083-d.pdf
* https://www.tij.co.jp/jp/lit/an/slvaeq9/slvaeq9.pdf

## Google searches

* `mosfet switching loss gate charge curve qgs qgd`