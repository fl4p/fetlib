"""

These regular expression find specification/test result values within a text from a PDF.
Since values are inside tables, and tables might contain testing condition parameters,
it is not always straightforward.

For now, there is one regex for each manufacturer and each value to be extracted, so it doesn't
scale very good. Might want to use more lenient regex.

    https://regex101.com/r/Mi15wn/1


"""

QRR = {

    'infineon': r"(Q\s?rr|reverse\srecovery\scharge[\s()0-9]+Q|Qrr\s+Reverse\s+Recovery\s+Charge)\s+(?P<min>[-0-9.]+\s+)?(?P<typ>[-0-9.]+)\s+(?P<max>[-0-9.]+)\s*nC"

    , 'ti': r"""Qrr
Reverse Recovery Charge
VDS=\s*(?P<vds>[0-9.]+)\s*V,\s*IF\s*=\s*(?P<if>[0-9.]+)\s*A,
di/dt\s*=\s*(?P<didt>[0-9.]+)\s*A/μs
(?P<typ>[0-9.]+)
nC"""

    , 'ao': r"Qrr\s+(?P<typ>[0-9.]+)\s+nC"

    , 'onsemi': (
        r"(IF =\s*(?P<if>[0-9.]+)\s*A, di/dt =\s*(?P<didt>[0-9.]+)\s*A/[uµ]s\s[\s\S]{4,20})?"
        r"(Qrr\s+Reverse[-\s]Recovery Charge|Reverse[−\s]Recover[edy]{1,2}\s+Charge\s+QRR)\s+"
        r"(ISD = (?P<if2>[0-9.]+)\s*A, dISD/dt = (?P<didt2>[0-9.]+)\s*A/µs\s+)?"
        r"(?P<min>[-0-9.]+\s+)?(?P<typ>[-0-9.]+)\s+(?P<max>[-0-9.]+\s+)?nC")

    , 'nxp': (r"Qrr?\s+recovered\s+charge\s+"
              r"(IS = (?P<if>[0-9.]+) A; dIS/dt = (?P<didt>[-0-9.]+) A/µs;\s+"
              r"VGS = (?P<vgs>[0-9.]+) V;\s+VDS = (?P<vds>[0-9.]+) V"
              r"(;\s+Tj = (?P<tj>[-0-9.]+) °C;?)?[\s\S]{,20}\s+)?"
              r"(?P<min>[-0-9.]+\s+)(?P<typ>[-0-9.]+\s+)(?P<max>[-0-9.]+\s+)nC")

    , 'st': r"Qrr\s+Reverse\s+recovery\s+charge\s+(?P<min>[-0-9.]+\s+)(?P<typ>[-0-9.]+\s+)(?P<max>[-0-9.]+\s+)?nC"

    , 'toshiba': r"""trr
Qrr
Test Condition
[^\n]*
[^\n]*(\n[^\n]*)?
[^\n]*IDR = (?P<if>[0-9.]+) A,\s+VGS = (?P<vgs>[0-9.]+) V,?\s+-dIDR/dt = (?P<didt>[0-9.]+) A/µs\s*
Min
(?P<idr_min>[-0-9.]+\n)?(?P<idrp_min>[-0-9.]+)
(?P<vdsf_min>[-0-9.]+)
(?P<trr_min>[0-9.]+)
(?P<min>[0-9.]+)
Typ.
(?P<idr_typ>[-0-9.]+\n)?(?P<idrp_typ>[-0-9.]+)
(?P<vdsf_typ>[-0-9.]+)
(?P<trr_typ>[0-9.]+)
(?P<typ>[0-9.]+)
Max
(?P<idr_max>[-0-9.]+\n)?(?P<idrp_max>[-0-9.]+)
(?P<vdsf_max>[-0-9.]+)
(?P<trr_max>[0-9.]+)
(?P<max>[0-9.]+)
Unit
A
V
ns
nC
"""
    , 'diodes': r"""I[FS] = (?P<if>[0-9.]+)A, di/dt = (?P<didt>[0-9.]+)A/μs\s*
(Body Diode\s+)?Reverse Recovery Charge\s*
QRR\s*
(?P<min>[-0-9.]+\s*)
(?P<typ>[-0-9.]+\s*)
(?P<max>[-0-9.]+\s*)
nC"""
    , 'vishay': r""".*I[FSM]{1,2}\s*=\s*(?P<if>[0-9.]+)\s*A,?\s+di/dt\s*=\s*(?P<didt>[0-9.]+)\s*A/μs,?[\s\S]{,60}
(Body Diode\s+)?Reverse Recovery Charge\s*
QRR\s*
(?P<min>[-0-9.]+\s*)
(?P<typ>[-0-9.]+\s*)
(?P<max>[-0-9.]+\s*)
(?P<unit>[nμ]C)""",

    'epc': r"""QRR
Source-Drain Recovery Charge
(?P<typ>[-0-9.]+\s*)""",

    'mcc': r"""Qrr
(?P<typ>[-0-9.]+\s*)
(nC|IF=\s*(?P<if>[0-9.]+)\s*A,di/dt=\s*(?P<didt>[0-9.]+)\s*A/μs)""",
}

# Time
