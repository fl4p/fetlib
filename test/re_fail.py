import re

s = "Q gs,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan"
r = re.compile(r'(charge(\s+gate[\s-]to[\s-](source|drain)\s*)?(\s+at\s+V[ _]?th)?|Q[\s_]?[0-9a-z]{1,3}([\s_]?\([a-z]{2,5}\))?)(,([ -_]*|nan))*,-\s+(?P<typ>[0-9]+(\.[0-9]+)?)\s+-[,\s](?P<unit>[uμnp]C)(,|$)', re.IGNORECASE)

next(r.finditer(s), None)



# catasthrophic backtracking
# 'Figure 9. Diode Forward Voltage vs. Current\nVGS = 0V\nTJ = -55oC\nTJ = 25oC\nTJ = 85oC\nTJ = 125oC\nTJ = 175oC\nTJ = 150oC\n1\n10\n100\n1000'


"""
'(?P<cond_mtmu>=name)?^([^\n]*\n){0,2}[- 	_.,;:#*"\'()\[\]a-z0-9]{,30}(time|[tf][_ ]?[rf]?) *[- 	_.,;:#*"\'()\[\]a-z0-9]* *\n(?=(\n|.)+(([uμnm]s|㎱|㎲|㎳))(\n|$))(((?P<conds_ml>(?P<cond_sym>([a-z]{1,2}([/a-z0-9]*|[_ ][a-z]{1,3})(\([a-z0-9]{1,6}\))?)) *[=≈] *(((?P<cond_val>(-?[0-9]+(\.[0-9]+)?)) *(?P<cond_unit>((([uμnm]s|㎱|㎲|㎳)|[uμnp]F|[m]?Vv?|[uμnp]?C|[muμn]?A|[mkM]?(Ω|Ω|O|Q|Ohm|W)|[k]?(S)|(°C|℃)/W|(°[CF]|K|℃|℉))[/a-z0-9]{0,4}){0,2})?|([a-z]{1,2}([/a-z0-9]*|[_ ][a-z]{1,3})(\([a-z0-9]{1,6}\))?)) *[-+*/]? *)+( +to +(?P<cond_val_to>(-?[0-9]+(\.[0-9]+)?)) *(?P<cond_unit2>([uμnm]s|㎱|㎲|㎳)|[uμnp]F|[m]?Vv?|[uμnp]?C|[muμn]?A|[mkM]?(Ω|Ω|O|Q|Ohm|W)|[k]?(S)|(°C|℃)/W|(°[CF]|K|℃|℉))?)? *[;,\n ]*)+)[- 	_.,;:#*"\'()\[\]a-z0-9]*\n([- 	_.,;:#*"\'()\[\]a-z0-9]+\n){0,3})?(?P<min>[-=._]+|nan|[0-9]+(\.[0-9]+)?)\n(?P<typ>[-=._]+|nan|[0-9]+(\.[0-9]+)?)\n(?P<max>[-=._]+|nan|[0-9]+(\.[0-9]+)?)\n(?P<unit>([uμnm]s|㎱|㎲|㎳))(\n|$)'
'tr\nVGS = 10 V, VDS = 0.5 VDSS, ID = 60 A\n42\nns\ntd(off)\nRG = 4 Ω (External)\n85\nns\ntf\n26\nns\nQg(on)'
tr
VGS = 10 V, VDS = 0.5 VDSS, ID = 60 A
42
ns

"""