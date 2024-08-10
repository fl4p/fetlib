# Extensive parametric search of MOSFETs for DC-DC converters

![](spreadsheet.png)

Finding the right switches for your DCDC-Converter might be not as straight forward as it looks on first sight.
Especially the reverse recovery loss appears to be often overlooked.
Both switching operate in rather different conditions. This program tries to help you with the selection.

What it does:

- Read search results from part suppliers
- Download parts datasheets in PDF
- Extract specification values from the PDF files
- Store gathered parts specifications in a database or CSV file
- Compute power Loss estimation for a given DC-DC converter

# How to use

1. acquire a parts list from digikey. go
   to [digikey.com](https://www.digikey.de/en/products/filter/transistors/fets-mosfets/single-fets-mosfets/278)
2. narrow down the search filters so your have 500 or less results.
3. download the CSV files (click *Download Table* / *First 500 Results*)

4. Open `main.py` and adjust the path to the downloaded csv file:

```
read_digikey_results(csv_path='digikey-results/80V 26A 10mOhm 250nC.csv')
```

5. Adjust the DCDC operating point:

```
dcdc = DcDcSpecs(vi=62, vo=27, pin=800, f=40e3, Vgs=12, ripple_factor=0.3, tDead=500e-9)
```

```
vi              input voltage
vo              output voltage
pin             is the input power, alternatively you can set io or ii.
f               switching frequency
Vgs             gate drive voltage for both HS and LS
ripple_factor   is the difference between the min and max coil current (assming CCM)
tDead           gate driver dead-time
```

6. Run `python3 main.py` and it will download all datasheets (if not already found), extract values and compose a CSV
   file
   with loss estimations for the given DC-DC converter.

```
P_hs    total loss in HS switch
P_2hs   total HS loss with 2 parallel switches

            loss_spec = dcdc_buck_ls(dcdc, fet_specs)
P_rr        reverse recovery loss when used as LS (sync fet)
P_on_ls     LS conduction loss
P_dt_ls     LS dead time loss
P_ls        total loss in LS switch
P_2ls       total LS loss with 2 parallel switches
```

# Acquiring part specifications

The program collects part specification values from different sources:

- Values from search results (Rds_on, Qg, Vds)
- Manual fields from `dslib/manual_fields.py`
- Nexar API
- PDF Datasheet
    - Text regex
    - Tabula
        - Table header aware iteration
        - Row regex iteration

Values for Rds_on and Qgd are usually shown in the search results (Digikey, LCSC).
Nexar API doesn't show the Qrr, and (tRise+tFall) only for some parts (especially values for newer chips are missing
here).
So I found the only way to extract Qrr from the Datasheet.
We use 2 techniques:

1. Convert the PDF to txt and find the values with regular expressions. this can be tedious work, as table structure is
   not homogenous across manufacturers and some manufacturers use different formats across product series and release
   date. each extracted field usually requires its own regex since tables include testing conditions or design notes.
2. use tabula (or another pdf2table program) to read the tables from the PDF. there is a python binding available that
   produces pandas DataFrames. find values by iterating the rows.

## Datasheet download

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

## Troubleshooting

- Tabula on macos: I had some issues getting java running on Mac M2, use zulu JDK

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

HS:

* Low Q_sw.
* Fast rise and fall time

LS:

* Low Q_rr
* Low Qgd/Qgs ratio
* High Vth

## Notes about Qrr

Qrr is usually defined by design and values from the data-sheet are not subject to production test.
Qrr depends on temperature, reverse voltage V_R, forward current I_F and forward current transient dif/dt.
Most datasheets only specify a single value under some given conditions.
DS of IQD016N08NM5 includes one for dif/dt=100A/us and dif/dt=1000A/us

Most part suppliers dont have a parametric search for Qrr. Also filtering and sorting by FoM and custom FoM is not
possible.

### Special Qrr Datasheets

* 'PSMN4R2-80YSEX': Qrr timing plot
* UM1575 User manual spice models

# Acquiring Parts Lists from Suppliers (Search Results)

* Digikey: use the filters to reduce number of results to 500 or less. then export csv
    * N-Ch, 80V, Idc>25A, Qg<250nC, RdsON<
      10mOhm [453 results](https://www.digikey.de/de/products/filter/transistoren/fets-mosfets/einzelne-fets-mosfets/278?s=N4IgjCBcoGwAwyqAxlAZgQwDYGcCmANCAPZQDaIAzAOwAcAnIyALpEAOALlCAMocBOASwB2AcxABfIgCYEtJCE7cAqsMEcA8mgCyeDDgCu-PCCIHuANVMgAtiO6041mxgAe3MHCdSQ06TGkFJUgQAGFiAzYsPAATVXUtXX0jEzNuYVDnN25pAFZvCQkgA) [80V 26A 10mOhm 250nC.csv](digikey-results/80V%2026A%2010mOhm%20250nC.csv)
    * [100V](https://www.digikey.de/en/products/filter/transistoren/fets-mosfets/einzelne-fets-mosfets/278?s=N4IgjCBcoGwAwyqAxlAZgQwDYGcCmANCAPZQDaIAzAOwAcAnIyALpEAOALlCAMocBOASwB2AcxABfIvFpIQqSJlyES5EACY4YMAFY4IImBja4lAyGoAWWnTNFqO%2BnB3VzdWpR13wx7a%2BmWRoHmuvS0YN5GlLqyRJb0MInelpZ6cP4gMIEwOurmWUaOITDRtPqGxrSWeRWa6jU%2BXuoQFU06blmaiHEJiRkFOS2NlJSW5npg8eUgljnqKR206iXFXpaROaPtFTSz5kuW1HD0%2BQkIDVFOsRYwYdRDiQfXRtSUK0R6KWAN99TUWW4wE5jG4EpRaNsQHpPFZiq86OZrOojkMwB40uMwHBnCd7NZ-pCrDYIfsgTpdG58bcQui4Nd7qk3jTPJpmbkxnFKMd6JDZiNrDSIuEaTBmriZvRwZQGuF6PDEalsd0oVp4kMHE4dBzwLRRdKafFhXE-oFvLLXsleokFWlIQN4vlsnp8m9lkMUjpbj8wVUabLpmjHmbsaZxYG5c8nMjCVTlTAqjAEfYPGBqD8tdUMp91EtEXNDoDNZCgXAc5DoS4MkDU9bDPRU7C6w27WdnXX0jpi04-mHJUt6bcbOKkUdvLZU2OS6LxqqPCE%2B5RhzYrNqgeouZF6PMmUQytjLAGt9ZLVkbPPT%2BqG9OPlYwr2svX5153uAwqLtRNrNc9KLaxYp%2BWs69rq0TzowJJxPmkaMAkYHpNqDhTMqRIeOKmiTAg5jNOs9Dathi5ZrOeGTAeDTWHSSYWF%2BbYgOaCz2FeyRzDRzRZFyWG6F4Dwweo4rmuCM6TLmRDND2yqsRGlI2EU0gMtSHymDEHHAtq1RLOuHEeM0WF1IubjLCyOmlvRGhitUOlAqkUn-BkI6lhZPLusuaZuFq3Z5rkXg6dKkqOkEkL1OoehofMmbeZUOkuF5IlBQ4GT-Hcqk6GUyw6Si4nIloGT1HMDTria3j5Q4Qx0UMRXRRoNCIVhBF0jVUbTPMCD6iJB4lAFB5Klh2SYbuQJWIV2RYt1WJyt18wUq1bwuN101oSkNh4QtwkaLMpaNWt2mtU01zzPGLWre14mHPAhWer4WHnWil2JKyInJfyl10L5924bhpJyjuGjwLk7rJQkeXGIE2r2oDyIMFhorUE4kPIo%2BIklND2VZHou1ZKYPyDp6kO-YD5EBYkuh4a8F0iST11k28QJYWmLiFVYKM014Llk8zxOis4NPxqmNN0FqvMQrtfwQmhwvwDTi3E5KwQiXuX3%2BuxsvnBk4R8rtNgIGVGvXjMy4zbLqt5QwWgBcbRhYQwnqFU4ER4fWaLDslryNVu2LW9Ek0aJKjxYYwTu%2BzyMMiX78NUPudVEFyxwCZHWiTEMXKBg0XJBcNselMnpgeNqG7ouYXLrDHYfWOb0gQti%2BTl%2BK8bktMNfaPkRzJT8IbePa0xHPACHfHA3fQ%2BqmgyRYaYvrcjA0G4VQ0e4xygqm6oJN8oLhCrNBlPsa%2Br%2B4G-Pfsnz9GcAq7vAkz7Cj1xOKYcZytDkJOIEGTAvUfklOKVxnkQ9Zcm-uj-OY9Ymn-pZBouEMz-zcnfZKRoQAJFmFWEMQUQgIOVFiOkRdUGMAQo4dSSDbaRC0AwMMzg-goOIX8JBHNnjNVDlieM69DAIFoNArERwmD2FyFYYsWIXDXAGAdEwEJVzaHjiEbQqQhGTBBPYUcoFDB%2BEVuAEiCixHrCrEo3h2QRiiOPKiXQrpRHhDTrrE0KC0QeEiKRLa4BLFVlIrI6xpYDqpBsBpXcvdDhhkCKEREy54whECLkCxdRUSpF0HGTRq5Uh-GLIcBmL9PD%2BPCC%2BaGuoXoWGWPKQwegXDTFlIcZ4XhRiREKVZBiUUAxak1jOGEw54y8WLJ6CEDxNG8ITNDREowljIQyV9IwilVJWhlJIz2RgsQ81qBuYoyJS60SxLMVcWQDx8WGauJYtCaTNAjsYqwB94BSJmFYOoL8CwBCCCDFIj1WAgE4NwPgQgxCSGkEvaA8h0DYHwEQUgkAKCFwQOKXIPJvyqneh8XiL4AWvHGLxRsFgwRbihUFD8lTyyVO-FqZ%2BHx0VjhTDCj0Rxpjor-ASPZHkDKuWBEMKKPJl63AJdzLMkp9ZQm9pS725ZvbfklCzXW0zJzAl4Swuu2QIKZBYXaFhcYWHVybnOJ5dJxSITUqcLc8L7B1IBNIHMiC4iKlcZkHMCjRR501R4ZUqQvC9X1ZMC48YDzPFtUYowVRqYVCqPMYobrbJLHuOmFSbgqZ6u%2BOSSiQa0SRFThDNxKQg7gFTqq2ZuEP6xvJNSwwywqhVnTTRb4NcUFZueOm8W0hcLQwaCUKGHcSzcu%2BILMMZYaH1oLbqCuabm2rijmwzI8AAEhETukXtccAyJwiAO74FxE7up1XzZUtde5DrRJ2F%2Bupe2BjHF%2BSN4BSiQsMFu9taI-47v3c8UoK0lh0j1TZHkKCRiBJtMZXtnhlE3vlu41Nm7PDrAfVqfo2Rt3pMTCZW2twqyjHxb2w4lrbZHBAxBsMoHHXwdRG8Ok17u1IeMPZHdGHIhU1nlhkwHTuTtscMiXtFpx0Wnba8A8ZHRhUdGOEl47bbjkiwqWeYAV2OsZElxvKXHOM5T4zlPC7G-xlGjeJdj9w2P1EonUOGMmtUhHuDyC4Kmi3gHU6idTKD1MaJeGp-qhmUzKajtpqOq5nZL0MFZyzidyyoJlppxOzxnZ3Wc%2Bx0zpZdMHlKTcNMDobMHgqqmYLYYrAICrBFv9qZoS6c%2BNpz4xYHDOADCl-mNmobJaNQhfEb6ay8RlJoNZynRT5f%2BFHUrXJ4uC2UxaKL1HtPUcAtUfZhw1xqdeIumzXXXNdfC9nSIthcjKfRJZ9EUX0R9cYLpr%2Bln6x7Bswt8L9Zs39w0w4H6Y4x6ewSvWMMe5fSGEOygvcMa0TYnjRd7kNItBaH0rqJht3uHPcg2ULEzx3uOpSQkmKZRRg6XE3hHMzg8og4qvUMo3XMjCrHOkPcgOcSI405D84yPu7djKiDvxf2-lsa8GEfHB4yrOFIkT0w5PpVauyqTz2XRviFU1vY%2BnE8eNA0aprJz9PP1s8mDT4wLFNbcY0ELxnAu4z3FyMhKcaFGH7K6I9tj8ZpNs5sGL6SSubCSeV7tRh7TVf0IlHQEdBvLzdkZylmnKXZfFUkw4Kxmh7ecftzTqovc2NusZ26zjVQAc8d95J33ruUh8aqItkXYfg9Hwj4qD3qQ%2BOSiLpoaWbcYJJuT4ZHjjLGeMvEmMhwHEsrxUCAwPPBC0JjJjZsoEhUxW147BX9IOtNn-DL-8XaLCC8iW4afbv8cFXck5uw%2BIfuNBiN%2Bwc74nb5hMN4t1JhSevzmVakw6HM-dRlS-C%2BD0WhjpMMTPPmwm%2BmEwv%2B2qQskWaoobKlyXU4lb-cviMbgKD%2BPyObyg-5CdCFHrkkY1aIsw7oio4ylUki2UABOOoBhwH%2BfOhU0QjkNUZIeE8BQ8v%2BcoMBcoyB-U9%2B64OQNU64hu64BBcBUcH%2BUc4BUcu0IwccNUicJBqo%2Bk1WVBLmtBpYN%2BLIyBLIzBXEtBTQvBJk64bUH%2BB4MKghTeNUIhaEdG%2BulU0acB0ayB0aVBio-%2BT%2Bf00kqhn0EhmBbgCAjSkMtw8uiQcoDwaY4QhUxhK0ywg41wCseElhw4Km7m1hjAgMY8Y4yI8wbhjAyMY8aMY8CqEQEQgM%2BK4kiY2I2U5IH2l0wiZUURdO8RtSSwaSqcnokRv8Z0v8w4wBZ0myaEv0Dc90zQveGgBR%2BRQUOYl0FR5RPBRRXgAUnkX0FRWocRiKZ0384kFq0%2BXEQ%2BpRHsjUXEhRfR2g7R2g%2BR0QzhXEzOUxeEUxnR0QrO-4CxcREBl0bw6ez4T290bwY02xRweUqK%2BRSy-QZhc%2B90gQ-a5xBG5x5El0C0DRC0M6jmZ0Shdx0Sbx5Caqt8DxwsmI%2B4sx%2BSRscyuSei0COYcyaE4Qzgps3C2UUJL44JCAeE8JMJCA4k8JWYjmqJohUJcmuJkJH26JH2yMDAIB6aW4gMko2q30ieFhieaMieaEtwowZUzJfmyw0sDJOQXJGqNJiQgEdAkBmUWgZaZhCihcAKNM2Ik6VEDsosSJ9MehAUncKOncRwUpiYeUap5yTqjUap4kap8p3MGpVhncIq0ydIxMo0Wpo0H4vc1hUpPIbcYpZU9wNAY4BEZJvwppqY6e3pQsqYVevwKRaYdIypyeWpGevs5qu0oCzecZAUoCKuXsUSdsUS2USZaEoCYJ2ZGZqQocvE%2BZ1sa0Lsa01croXemQFZWsywTKWqJhFs0KZo8wzsjZYQRsvEy6PQiQ4e9Z8afZpsBqyJ0oWxGgWkMaswHCpsPkhU45050KFs1BjU6INEBwrwRsnga%2BK56Jm5cJm5CqnpO5%2BhssbUWsbUcJIhZ58OFsdqy5dqV5sqY5Syd5YyN56yJ5LCN5gBX5CJYeQpkeRsKQf6OYQFhI2CpGJ5fws5%2BSd5dARsP4cJeg3KZY8EFsSFyE66-QxIwF5cnxY5SFthJYWiaqs%2BkJFqWsFqiF38aFHsNFJu%2BF0QyoXIgSkIzFBB%2BcoO2MscUuyQKmFMYcUudoVgYiHFHCmcHCGQbFlEbFhubFMaclYwVyNykAvAAgIg4gUgr4EMLyCgSgHyqg3yGg5g0wilmlCucgul7yKgXyFAqCAABAAGosDsBcAqUACqwgggHAAA8mgAALJ4AYA4AACu-AeAjypk04LyylIAAAwsQMFWwFgHgAACYeVeW%2BUBVBWhXhVEDBXcDCCxXmAAC2GAAAHtwEFPoBIJpYgC8oICldwAALSvkuXcDmAcAACebA4VKlQVqANVQAA)
* LCSC: use Browser Developer Tools to copy HTML DOM of each results page.

# TODO

* Use ocr (sample 'BUK7E4R0-80E,127.pdf', 'IPB019N08N3GATMA1' ) `ocrmypdf` can recover the text, but doesn't recognize
  symbols
  correctly.
* Mouser, API?
* Extract more fields
  * Qgd/Qgs (self turn on)
  * Vsd (body diode forward voltage)
  * r_g

# Resources

* https://octopart.com/ (Ciss, rise&fall times, )
* https://epc-co.com/epc/design-support/part-cross-reference-search

# names

fetlib
mosfetlib
fetfinder
findfet