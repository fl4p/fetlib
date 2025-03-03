

## Power Loss Tree

```
- Switch
  - Conduction (cntrl & sync)
  - Switching (cntrl)
  - Coss (cntrl & sync or cntrl only? TODO)
  - Reverse Recovery (sync)
  - Gate Drive (ctrl & sync)
- Inductor
  - Coil
    - Rdc1
    - Rac (Eddy currents)
      - Proximity Effect
      - Skin Effect
  - Core
    - Hyteresis 
    - Eddy Currents
  - Stray flux
- Capacitor
  - Input Capacitor
  - Output Capacitor
- Resistive Losses
  - Fuse
  - Current Sense Resistor (Shunt)
  - Terminals
  - PCB
- Housekeeping
  - MCU
  - Power supply
  
```