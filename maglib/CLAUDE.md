# maglib — inductor (powder core) design & loss

Largely independent of the FET pipeline; pulled in via `dclib.powerloss` for AC-resistance and core-loss factors (`MagneticCoreSpecs`, `acr_factor_micrometals`, `skin_depth`, `d2awg`, `MaterialResistivity`). Materials are loaded from `maglib/materials/micrometals.csv`.
