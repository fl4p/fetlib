import re



pattern = r'(?P<conds_mTm>=name)?^([^\n]*\n){0,2}[- 	_.,;:#*"\'()\[\]a-z0-9]{,30}(capacitance|C[ _]?[a-z]{1,3}) *[- 	_.,;:#*"\'()\[\]a-z0-9]* *\n((?P<conds_ml>(?P<cond_sym>([a-z]{1,2}([/a-z0-9]*|[_ ][a-z]{1,3})(\([a-z0-9]{1,6}\))?)) *[=≈] *(((?P<cond_val>(-?[0-9]+(\.[0-9]+)?)) *(?P<cond_unit>((([uμnm]s|㎱|㎲|㎳)|[uμnp]F|[m]?Vv?|[uμnp]?C|[muμn]?A|[mkM]?(Ω|Ω|O|Q|Ohm|W)|[k]?(S)|(°C|℃)/W|(°[CF]|K|℃|℉)|[Mk]?Hz)[/a-z0-9]{0,4}){0,2})?|([a-z]{1,2}([/a-z0-9]*|[_ ][a-z]{1,3})(\([a-z0-9]{1,6}\))?)) *[-+*/]? *)+( +to +(?P<cond_val_to>(-?[0-9]+(\.[0-9]+)?)) *(?P<cond_unit2>([uμnm]s|㎱|㎲|㎳)|[uμnp]F|[m]?Vv?|[uμnp]?C|[muμn]?A|[mkM]?(Ω|Ω|O|Q|Ohm|W)|[k]?(S)|(°C|℃)/W|(°[CF]|K|℃|℉)|[Mk]?Hz)?)? *[;,\n ]*)+[- 	_.,;:#*"\'()\[\]a-z0-9]*\n)?(?P<min>[-~=._]+|nan|[0-9]+(\.[0-9]+)?)\n(?P<typ>[0-9]+(\.[0-9]+)?)\n(?P<max>[-~=._]+|nan|[0-9]+(\.[0-9]+)?)\n(\n|$)'
inp =  'Ciss\nCoss\nCrss\nVGS=0V , f=1MHz\nCiss=Cgs+Cgd\nCoss=Cds+Cgd\nCrss=Cgd\nVDS=520V\nVDS=325V\nVDS=130V\nFigure  10  Typical Theshold Voltage vs Junction Temperature\nFigure  11  Typical Breakdown Voltage vs Junction Temperature'
rg = re.compile(pattern, re.IGNORECASE)
rg.findall(inp)

input="""Ciss
Coss
Crss
VGS=0V , f=1MHz
Ciss=Cgs+Cgd
Coss=Cds+Cgd
Crss=Cgd
VDS=520V
VDS=325V
VDS=130V
Figure  10  Typical Theshold Voltage vs Junction Temperature
Figure  11  Typical Breakdown Voltage vs Junction Temperature
"""

#import regex
r = regex.compile('(?P<cond_mtmu>=name)?^([^\n]*\n){0,2}[- 	_.,;:#*"\'()\[\]a-z0-9]{,30}(((diode )?forward )?voltage|V[ _]?[a-z]{1,8}) *[- 	_.,;:#*"\'()\[\]a-z0-9]* *\n'
               '(?P<c>?>((?P<cond_sym>([a-z]{1,2}([/a-z0-9]*|[_ ][a-z]{1,3})(\([a-z0-9]{1,6}\))?)) *= *(((?P<cond_val>(-?[0-9]+(\.[0-9]+)?)) *(?P<cond_unit>((([uμnm]s|㎱|㎲|㎳)|[uμnp]F|[m]?Vv?|[uμnp]?C|[muμn]?A|[mkM]?(Ω|Ω|O|Q|Ohm|W)|(°[CF]|K))[/a-z0-9]{0,4}){0,2})?|([a-z]{1,2}([/a-z0-9]*|[_ ][a-z]{1,3})(\([a-z0-9]{1,6}\))?)) *[-+*/]? *)+( +to +(?P<cond_val_to>(-?[0-9]+(\.[0-9]+)?)) *(?P<cond_unit2>([uμnm]s|㎱|㎲|㎳)|[uμnp]F|[m]?Vv?|[uμnp]?C|[muμn]?A|[mkM]?(Ω|Ω|O|Q|Ohm|W)|(°[CF]|K))?)? *[;,\n ]*)+[- 	_.,;:#*"\'()\[\]a-z0-9]*\n([- 	_.,;:#*"\'()\[\]a-z0-9]+\n){0,3})?'
               '(?P<min>[-=._]+|nan|-?[0-9]+(\.[0-9]+)?)\n(?P<typ>[-=._]+|nan|-?[0-9]+(\.[0-9]+)?)\n(?P<max>[-=._]+|nan|-?[0-9]+(\.[0-9]+)?)\n(?P<unit>[m]?Vv?)(\n|$)', regex.IGNORECASE)

s =  'Figure 9. Diode Forward Voltage vs. Current\nVGS = 0V\nTJ= -55°C\nTJ= 25°C\nTJ= 85°C\nTJ= 125°C\nTJ= 150°C\nTJ= 175°C\n10\n100\n1000\n10000'



print('running...')
m = r.findall(s)
print(m)