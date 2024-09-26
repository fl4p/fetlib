"""

These regular expression find specification/test result values within a text from a PDF.
Since values are inside tables, and tables might contain testing condition parameters,
it is not always straightforward.

For now, there is one regex for each manufacturer and each value to be extracted, so it doesn't
scale very good. Might want to use more lenient regex.

    https://regex101.com/r/Mi15wn/1


"""
import re

from dslib import mfr_tag
from dslib.cache import mem_cache

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


def field_value_regex_variations(head, unit, signed=False):
    """

    :param head:
    :param unit:
    :return:
    """

    test_cond_broad = r'[-+\s=≈/a-z0-9äöü.,;:μΩ°(){}"\'<>]+'  # parameter lab testing conditions (temperature, I, U, didit,...)

    field = r'[0-9]+(\.[0-9]+)?'
    if signed:
        field = r'-?' + field
    nan = r'[-\s_]*|nan|\.'
    field_nan = nan + r'|' + field

    return [
        re.compile(  # min? typ max?,unit
            head + rf'(?P<minN_typ_maxN_unit>.)?,(?P<min>({field_nan})),(?P<typ>({field})),(?P<max>({field_nan})),I?(?P<unit>' + unit + r')(,|$|\s)',
            re.IGNORECASE),

        # "Gate charge at threshold,Qaitth),-,2.7 -,nC,Vop=50 V,,p=10 A, Ves=0 to 10 V"
        re.compile(  # head,gibber?,nan?,typ -,unit ...,
            head + r',([-_()a-z0-9]+,)?((' + field_nan + '),){0,4}(?P<typ>(' + field + r'))(\s*-+|\s+(?P<max>(' + field + r'))),(?P<unit>' + unit + r')(,|$|\s)',
            re.IGNORECASE),

        # 'Body diode reverse recovery charge Qn,.,nan,2,nan,108,220,nan,nan,nc'
        re.compile(  # broad,minN,typ,maxN,unit
            rf'{head}({test_cond_broad},)?(?P<min>{field_nan}),(?P<typ>{field}),(?P<max>{field_nan}),(nan,)*(?P<unit>{unit})(,|$)',
            re.IGNORECASE),

        re.compile(  # same as before but max required instead of typ TODO merge?
            #  "Qgs VGS= 10 V,VDS = 0.5 VDSS,ID = 25 A,,39 nC,,Min. Max.,Min. Max."
            rf'(?P<cond_minN_typN_max>.)?{head}({test_cond_broad},)?((?P<min>{field_nan}),)?(?P<typ>{field_nan}),(?P<max>{field})[,\s]I?(?P<unit>{unit})(,|$)',
            re.IGNORECASE),

        # re.compile(  # head,nan?,nan,max,unit
        #    rf'{head},(({nan}),)?({nan}),(?P<max>{field}),(?P<unit>' + unit + r')(,|$)',
        #    re.IGNORECASE),

        # typ surrounded by nan/- or max  and no unit
        re.compile(head + rf'[-\s]*,(-|nan|),(-,)?(?P<typ>{field}),(?P<max>{field_nan}),nan',
                   re.IGNORECASE),

        # 'Gate charge total,Qg,nan,nan,-,26,35,nan'
        # 'Body diode reverse recovery charge Qi ;,-,nan,115,230,nan,nan,nc'
        re.compile(  # broad,nan?,-,nan?,typ,max,nan*,unit?
            head + rf'({test_cond_broad})?,(nan,){{0,4}}-,((nan|),)?(?P<typ>{field}),(?P<max>{field})(,nan){{1,4}}(,(?P<unit>{unit}))?(,|$)',
            re.IGNORECASE),

        re.compile(
            head + r'[-\s]{,2}\s*,?\s*(?P<min>' + field_nan + r')\s*,?\s*(?P<typ>' + field_nan + r')\s*,?\s*(?P<max>' + field_nan + r')\s*,?\s*(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        re.compile(
            head + r'([\s=/a-z0-9.,μ]+)?(?P<min>' + field_nan + r'),(?P<typ>' + field_nan + r'),(?P<max>' + field_nan + r'),(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        # QgsGate charge gate to source,17,nC,nan,nan,nan,nan,nan
        re.compile(
            head + r'([\s/a-z0-9."]+)?,(?P<typ>' + field + r'),(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        # "tf fall time,nan,nan,- 49.5 - ns"
        re.compile(
            head + rf'(,({nan}))*,[-_]+\s+(?P<typ>{field})\s+[-_]+([,\s](?P<unit>{unit})|,nan)(,|$)',
            re.IGNORECASE),

        # "Coss Output Capacitance,---,319,---,VDS = 50V,nan"
        # "Reverse Recovery Charge Qrr nCIF = 80A, VGS = 0V--,297,--,nan"
        # ("Gate-drain charge Qga,-,nan,9.1,-,nan,nan", "Qgd", (na, 9.1, na)),

        re.compile(
            head + rf'({test_cond_broad})?,?-+,((nan|),)?(?P<typ>{field}),-+(,|$)',
            re.IGNORECASE),

        # 'nan,Coss,nan,7.0,nan'
        # 'Qgd,Gate-to-Drain Charge,23,nan,nan
        re.compile(head + rf'(,nan){{0,1}},(?P<typ>{field})(,nan){{0,3}}$', re.IGNORECASE),

        # 'COSS(ER),Effective Output Capacitance, Energy Related (Note 1),VDS = 0 to 50 V, VGS = 0 V,nan,1300,nan,nan', 'C'
        re.compile(head + rf'({test_cond_broad})?,nan,(?P<typ>{field}),nan,nan$', re.IGNORECASE),

        # 'Gate plateau voltage,Vplateau,nan,nan,4.7,nan,
        # Coss,Output Capacitance,460,nan,pF VDS = 25V,nan,nan
        re.compile(head + rf'(,nan){{0,3}},(?P<typ>{field}),nan(,(?P<unit>{unit})(|\s({test_cond_broad})))?(,|$)',
                   re.IGNORECASE),

        # 'Vsp,Diode Forward Voltage,-_- -_-,1.3,Vv,Ty=25°C, 15 =22A, Ves =0V @,nan', 'V'
        re.compile(head + rf',({field_nan})[\s,]({field_nan}),(?P<max>{field}),(?P<unit>{unit})(,|$|\s)',
                   re.IGNORECASE),

        # ^broad,-,-,<max>$
        # re.compile(head + rf'({test_cond_broad})?,(nan|-),(nan|-),(?P<max>{field})$', re.IGNORECASE),
        # ^board[ ,]-,<typ?>,<max>,nan?$
        # Forward Diode Voltage,VSD,VGS = 0 V,TJ = 25°C,,0.92,1.2,
        re.compile(
            head + rf'({test_cond_broad})?(,nan|[,\s]-|,),(?P<typ>{field_nan}),(?P<max>{field})(,({nan})){{0,3}}(,(?P<unit>{unit}))?$',
            re.IGNORECASE),

        # Qg,Total gate charge,Vop = 40 V, Ip = 26A, - 103 - Q
        # Qgs,Gate-source charge,Vics - 10 Vv (see Figure 14: - 35 - nc Q
        re.compile(
            head + rf'({test_cond_broad})?[,\s]-\s+(?P<typ>{field})\s+-(\s+(?P<unit>{unit}))?(\s+[a-z]{{0,2}})?$',
            re.IGNORECASE),

        # ^,-,<typ> <max> <unit>$ (space)
        # Charge,-,62 93 nC See
        # "nan,tf,Fall time,nan,-,44 - ns"
        re.compile(
            head + rf',(({nan}),)*-+,(?P<typ>{field})\s{{1,3}}(?P<max>({field})|-)\s{{1,3}}(?P<unit>{unit})(\s|,|$)',
            re.IGNORECASE),

        # "ISD = 80 A, VGS = 0 V ISD = 40 A, VGS = 0 V",,,1.25 1.2,V,,,,, V
        re.compile(
            head + rf'({test_cond_broad})?,({field_nan}),(?P<typ>{field})\s+(?P<max>{field}),(?P<unit>{unit})(\s|,|$)',
            re.IGNORECASE),

        #    'Rise time t Vp= p40 V,R= L4,Ip=10A,= 15,30,nan,nan'
        re.compile(
            head + rf'({test_cond_broad})?,[-=]\s+(?P<typ>{field}),(?P<max>{field})(,nan)*(,(?P<unit>{unit}))?(,|$)',
            re.IGNORECASE),

        # ',Avalanche Rated,nan,Qg Gate Charge Total (10 V),76,nC'
        # "QgGate charge total (10 V),VDS = 40 V, ID = 100 A,76,nC,nan,nan"
        re.compile(
            head + rf'(({test_cond_broad})[^0-9]{{2,}})?,(?P<typ>{field}),(?P<unit>{unit})(,nan)*$',
            re.IGNORECASE),

        # tr,nan,nan,Reverse Recovery Time,-. 64 96 ns,[Ty = 25°C, lr = 96A, Vpp = 38V
        re.compile(
            head + rf'({test_cond_broad})?,[-_.]+\s+(?P<typ>{field})\s+(?P<max>{field})\s+(?P<unit>{unit})(,|$)',
            re.IGNORECASE),


        # "VSDDiode forward voltage,ISD = 100 A, VGS = 0 V,0.91.1,V,nan,nan"
        # VSD,Source-to-Drain DiodeVoltage,ISD = 80 A,VGS = 0 VISD = 40 A,VGS = 0 V,,,1.251.2,V,
        re.compile(
            head + rf'(({test_cond_broad})[^0-9]{{2,}})?,(?P<typ>[0-9]\.[0-9]{{1,2}})(?P<max>[0-9]\.[0-9]),(?P<unit>{unit})(,({nan}))*$',
            re.IGNORECASE),

        # 'Qg,Total Gate Charge,---,285,428,ID = 100A'
        re.compile( #'Qg,Total Gate Charge,---,200,300,,,VDS = 38V,
            # Output capacitance ON- and LINFET,C oss,ON+LIN,,,-,2100,2730,
            rf'(?P<broad_typ_max_nanN_unitN>=name)?{head},?({test_cond_broad},)?(?P<typ>{field}),(?P<max>{field})(,({nan}))?,?(?P<unit>' + unit + r')?(,|$)',
            re.IGNORECASE),


        # TODO move this down
        # 'QgGate charge total (10 V),VDS = 40 V,ID = 100 A,76,nC,,'
        #
        re.compile(  # typ only with (scrambled) testing conditions
            rf'(?P<broad_typ_nanN_unitN>=name)?{head},?({test_cond_broad},)?(?P<typ>{field})(,({nan}))?(,(?P<unit>{unit}))?(,|$)',
            re.IGNORECASE),

        re.compile(  # typ surrounded by nan/-, unit
            head + r'(?P<nans_minN_typ_maxN_unit>=name)?,((-*|nan),){0,4}(?P<typ>(' + field + r')),((-*|nan),){0,4}(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        # tr,Rise Time,nan,22,nan,nan
        re.compile(rf'{head},({nan}),(?P<typ>{field})(,({nan})){{1,2}}$',
                   re.IGNORECASE),
    ]


# Time
def get_dimensional_regular_expressions():
    # regex matched on csv row
    # noinspection RegExpEmptyAlternationBranch
    dim_regs = dict(
        t=[
              re.compile(r'(time|t\s?[rf]),([ =/a-z,]+,)?(?P<typ>[-0-9]+(\.[0-9]+)?),(?P<unit>[uμnm]s)(,|$)',
                         re.IGNORECASE),
              re.compile(
                  r'[, ](?P<min>nan|-+||[-0-9]+(\.[0-9]+)?),(?P<typ>nan|-*|[-0-9.]+)[, ](?P<max>nan|-+||[-0-9.]+),(nan,)?(?P<unit>[uμnm]s)(,|$)',
                  re.IGNORECASE),
              re.compile(r'(time|t\s?[rf]),([\s=/a-z0-9.,]+,)?(?P<typ>[-0-9]+(\.[0-9]+)?),(?P<unit>[uμnm]s)(,|$)',
                         re.IGNORECASE),

              re.compile(r'(time|t\s?[rf]),(-|nan|),(?P<typ>[-0-9]+(\.[0-9]+)?),(-|nan|),nan',
                         re.IGNORECASE),

              re.compile(
                  r'(time|t[_\s]?[rf])\s*,?\s*(?P<min>nan|-*|[-0-9.]+)\s*,?\s*(?P<typ>nan|-*|[-0-9.]+)\s*,?\s*(?P<max>nan|-*|[-0-9.]+)\s*,?\s*(?P<unit>[uμnm]s)(,|$)',
                  re.IGNORECASE),

          ] + field_value_regex_variations(r'(time|[tf][_\s]?[rf]?)', r'[uμnm]s'),  # f for OCR confusing t
        # Q=
        Q=[

              re.compile(
                  r'(V|charge|Q[ _]?[a-z]{1,3}),(?P<min>(nan|-*|[0-9]+(\.[0-9]+)?)),(?P<typ>([0-9]+(\.[0-9]+)?)),(?P<max>(nan|-*|[0-9]+(\.[0-9]+)?)),(?P<unit>[uμnp]C)(,|$)',
                  re.IGNORECASE),

              re.compile(
                  r'(charge|Q[\s_]?[a-z]{1,3}),((-|nan|),){0,4}(?P<typ>[-0-9]+(\.[0-9]+)?),((-|nan|),){0,2}(?P<unit>[uμnp]C)(,|$)',
                  re.IGNORECASE),

              # re.compile(
              #    r'(charge|Q[ _]?[a-z]{1,3}),([\s=/a-z0-9.,μ]+,)?(?P<typ>[0-9]+(\.[0-9]+)?),(?P<unit>[uμnp]C)(,|$)',
              #    re.IGNORECASE),

              re.compile(r'(charge|Q[\s_]?[a-z]{1,3})[-\s]*,(-|nan|),(?P<typ>[-0-9]+(\.[0-9]+)?),(-|nan|),nan',
                         re.IGNORECASE),

              re.compile(
                  r'(charge|Q[\s_]?[a-z]{1,3})[-\s]{,2}\s*,?\s*(?P<min>nan|-*|[0-9.]+)\s*,?\s*(?P<typ>nan|-*|[0-9.]+)\s*,?\s*(?P<max>nan|-*|[0-9.]+)\s*,?\s*(?P<unit>[uμn]C)(,|$)',
                  re.IGNORECASE),

              re.compile(
                  r'(charge|Q[\s_]?[a-z]{1,3})([\s=/a-z0-9.,μ]+)?(?P<min>-*|nan|[0-9]+(\.[0-9]+)?),(?P<typ>-*|nan|[0-9]+(\.[0-9]+)?),(?P<max>-*|nan|[0-9]+(\.[0-9]+)?),(?P<unit>[uμnp]C)(,|$)',
                  re.IGNORECASE),

              # datasheets/vishay/SIR622DP-T1-RE3.pdf Qrr no value match Body diode reverse recovery charge Qrr -,350,680,nan,nC
          ] + field_value_regex_variations(
            r'(charge(\s+gate[\s-]to[\s-](source|drain)\s*)?(\s+at\s+V[ _]?th)?|charge\s+at\s+threshold|charge|Q[\s_]?[0-9a-z]{1,3}([\s_]?\([a-z]{2,5}\))?)',
            r'[uμnp]?C'),

        C=field_value_regex_variations(r'(capacitance|C[\s_]?[a-z]{1,3})', r'[uμnp]F'),
        V=field_value_regex_variations(r'(voltage|V[\s_]?[a-z]{1,8})', r'[m]?Vv?', signed=True)
    )
    return dim_regs


@mem_cache(ttl='1min')
def get_field_detect_regex(mfr):
    mfr = mfr_tag(mfr, raise_unknown=False)

    qgs = r'Q[ _]?gs'
    qgs1 = ''
    if mfr == 'toshiba':
        # toshiba:      Qgs1* = Qg_th + Qgs2 charge from 0 to miller plateau start (Qgs)
        #               Qgs2* = charger after miller plateau (not relevant and usually not specified)
        # IRF6644TRPBF: Qgs1* = Qg_th    (0|Qgs1|TH|Qgs2|Qgd)
        #               Qgs2* = Qgs
        # others:       Qgs1* = charge from Qg_th to miller plateau start (0 Qgs_th|TH|Qgs1|)
        qgs += '1?'
    else:
        qgs += '([^1]|$)'  # dont match Qgs1
        qgs1 = r'|^Q[ _]?gs[ _]?1$'

    # regex matched on cell contents
    fields_detect = dict(
        tRise=(re.compile(r'(rise\s+time|^t\s?r($|\sVGS))', re.IGNORECASE), ('reverse', 'recover')),
        tFall=(re.compile(r'(fall\s+time|^t\s?f($|\sVGS))', re.IGNORECASE), ('reverse', 'recover')),
        Qrr=re.compile(
            r'^((?!Peak)).*(reverse[−\s+]recover[edy]{1,2}[−\s+]charge|^Q\s*_?(f\s*r|r\s*[rm]?)($|\s+recover))',
            re.IGNORECASE),  # QRM
        Coss=re.compile(r'(output\s+capacitance|^C[ _]?oss([ _]?eff\.?\s*\(?ER\)?)?($|\sVGS))', re.IGNORECASE),

        Qgs2=re.compile(r'(Gate[\s-]+Charge.+Plateau|^Q[ _]?gs2$|^Q[ _]?gs?\(th[-_]?pl\))', re.IGNORECASE),
        Qg_th=(re.compile(
            rf'(gate[\s-]+charge\s+at\s+V[ _]?th|gate[\s-]+charge\s+at\s+thres(hold)?|^Q[ _]?gs?\s*\(?th\)?([^-_]|$){qgs1})',
            re.IGNORECASE),
               ('post-threshold',)),
        Qgd=re.compile(r'(gate[\s-]+(to[\s-]+)?drain[\s-]+(\(?"*miller"*\)?[\s-]+)?charge|^Q[ _]?gd)', re.IGNORECASE),
        Qgs=(re.compile(
            rf'(gate[\s-]+(to[\s-]+)?source[\s-]+(gate[\s-]+)?charge|Gate[\s-]+Charge[\s-]+Gate[\s-]+to[\s-]+Source|^{qgs})',
            re.IGNORECASE), ('Qgd',)),
        Qsw=re.compile(r'(gate[\s-]+switch[\s-]+charge|switching[\s-]+charge|^Q[ _]?sw$)', re.IGNORECASE),
        Qg=re.compile(  # this should be after all other gate charges
            rf'(total[\s-]+gate[\s-]+charge|gate[\s-]+charge[\s-]+total|^Q[ _]?g([\s_]?\(?(tota?l?|on)\)?)?$)',
            re.IGNORECASE),

        Vpl=re.compile(r'(gate\s+plate\s*au\s+voltage|V[ _]?(plateau|pl|gp)$)', re.IGNORECASE),

        Vsd=re.compile(
            r'(diode[\s-]+forward[\s-]+voltage|V[ _]?(\s*\([0-9]\)\s*)?sd(\s*\([0-9]\)\s*)?(\s+source[\s-]+drain[\s-]+voltage|\s*forward on voltage)?($|\sIF)|V[ _]?DS_?FW?D?)',
            re.IGNORECASE),
        # plate au
        # Qrr=re.compile(r'(reverse[−\s+]recover[edy]{1,2}[−\s+]charge|^Q[ _]?rr?($|\srecover))',
        #               re.IGNORECASE),

    )
    return fields_detect


dim_regs = get_dimensional_regular_expressions()
