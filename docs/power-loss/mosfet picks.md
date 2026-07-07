## IPB017N10N5LF

* Ideal for hot-swap and e-fuse applications (higher Vpl means higher gate discharge current)
* Vgs(th): 2.5/3.3/4.1
* Rg: 44/66Ω
* Qgs: 4.4nC , Qgd: 141nC
* Included in Poweresim

### PowerEsim: Vin=70, Vout=27, Iout=30, 15.5uH

* HS
    * Irms = 19A, Ipk=38A
    * Pd(CL+SW) = 0.77 + 2.4 = 3.154 W
* LS
    * Pd(CL+SW) = 1.3 + 37 m = 1.329 W

### This Model
With Rgext = 4.7Ω and Vpl = 7.1V, we compute a Ig_on = 0.83A, Ig_off = 1.5A .
With Qsw = 143nC, we get tr=170ns, tf=95ns and P_on=6.17W, P_off=4.59W (40khz).
Total switching loss = 10.8W. (vs 2.4W in PowerEsim...)

Conduction Loss: P_cl = 0.72 W (Rds=2.3m, I=18.7)