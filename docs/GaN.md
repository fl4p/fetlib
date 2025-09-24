
https://e2e.ti.com/support/power-management-group/power-management/f/power-management-forum/408481/is-there-an-inherent-body-diode-in-gan-power-fets-if-so-what-is-the-v-i-curve-for-that

![img_1.png](img_1.png)


datasheet says no body diode:
https://assets.nexperia.com/documents/data-sheet/GAN3R2-100CBE.pdf
"Qr
 is not specified separately from Qoss for e-mode GaN FETs, since Qr
 = Qoss + QD, and QD = 0. (QD is charge associated with
diffusion of minority carriers. Since there is no body diode, no minority carriers in excess of Qoss have to be transferred for e-mode
GaN FETs.)"


dead-time optimal:
https://www.ti.com/lit/an/snoaa36/snoaa36.pdf?ts=1748896465535


ref designs
https://www.ti.com/tool/PMP20978
