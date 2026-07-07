

Write a function normalize_conditions() which normalizes the `cond` property of the class `Field`.
Cond is dict containing the field-conditions extracted from the datasheet for a parameter.
For example, Qoss is usually given at a specific Vds. Let's Qoss has been measured at Vds 50V, then
cond={"Vds":50.0}.
Some fields in datasheet_db contain non normalized symbols, such as 'V ds' or 'VDS', 'VDD'.
Sometimes the dict keys are numeric and the values need to be parsed to extract the condition values, for example:
`{0: 'Output charge1)', 1: 'Qoss', 2: '-', 3: '136', 4: '181', 5: 'nC', 6: 'VDS=75 V, VGS=0 V'}`

Explore data in datasheet_db and write the normalize_conditions based on what you find.
Look into these fields and their conditions:
* Qoss: Vds, Vgs
* Qrr: di/dt, I, Vds

For Qoss also accept Vds values in the like 'V =75 V'.