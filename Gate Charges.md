The amount of charge of the gate to reach the miller-plateau is often

|          | Qg_th  | Qgs2   | Qgodr | specification in DS      |   |
|----------|--------|--------|-------|--------------------------|---|
| infineon | Qgs1   | Qgs2   | Qgodr | Qg_th or (Qgs1 and Qgs2) |   |
| NXP      | Qgs1   | Qgs2   |       |                          |   |
| onsemi   |        |        |       |                          |   |
| ti       | Qg(th) |        |       | Qg(th)                   |   |
| toshiba  | Qgs1.1 | Qgs1.2 | Qgs2  | Qgs1                     |   |

# Gate charge waveform definitions

## Infineon

* AUIRF540ZXKMA1
* IRF6644TRPBF

![img.png](docs/gate-charge-waveform-infineon-auir.png)

* BSS169IXTSA1

![img.png](docs/gate-charge-curve-infineon-bss.png)

## NXP

* BUK7E4R0
* Specifies: Qg, Qgs, Qgd
* Qgs1 = Qgs * (Vth/Vpl)

![img.png](docs/gate-charge-curve-nxp.png)

* PSMN5R5-100YSFX.pdf
* QGS(th): pre-threshold gate- source charge
* QGS(th-pl): post-threshold gate- source charge

## Onsemi

![img.png](docs/gate-charge-curve-onsemi-FDB.png)
FDB024N08BL7.pdf

## Toshiba

https://toshiba.semicon-storage.com/info/application_note_en_20180726_AKX00068.pdf?did=59460

* Toshiba's Qgs1 is = Qgs

![img.png](docs/gate-drive-waveform-toshiba.png)

# Predict Qgs2

Analyse products with complete data first:

* (Qgs2/Qgs)
* compare (Vth/Vpl) with (Qgs2/Qgs)