
* https://www.regular-expressions.info/catastrophic.html
* https://www.regexbuddy.com/debug.html

Atomic groups are available since python 3.13 (?>...) https://github.com/python/cpython/commit/345b390ed69f36681dbc41187bc8f49cd9135b54

Re alternatives:
https://pypi.org/project/regex/

emulate:
https://stackoverflow.com/questions/13577372/do-python-regular-expressions-have-an-equivalent-to-rubys-atomic-grouping




# Catastrophic Backtracking Samples

```
            print(r,'on', repr(s),'..')
'(?P<cond_mtmu>=name)?^([^\\n]*\\n){0,2}[- \t_.,;:#*"\'()\\[\\]a-z0-9]{,30}(((diode )?forward )?voltage|V[ _]?[a-z]{1,8}) *[- \t_.,;:#*"\'()\\[\\]a-z0-9]* *\\n(((?P<cond_sym>([a-z]{1,2}([/a-z0-9]*|[_ ][a-z]{1,3})(\\([a-z0-9]{1,6}\\))?)) *= *(((?P<cond_val>(-?[0-9]+(\\.[0-9]+)?)) *(?P<cond_unit>((([uμnm]s|㎱|㎲|㎳)|[uμnp]F|[m]?Vv?|[uμnp]?C|[muμn]?A|[mkM]?(Ω|Ω|O|Q|Ohm|W)|(°[CF]|K))[/a-z0-9]{0,4}){0,2})?|([a-z]{1,2}([/a-z0-9]*|[_ ][a-z]{1,3})(\\([a-z0-9]{1,6}\\))?)) *[-+*/]? *)+( +to +(?P<cond_val_to>(-?[0-9]+(\\.[0-9]+)?)) *(?P<cond_unit2>([uμnm]s|㎱|㎲|㎳)|[uμnp]F|[m]?Vv?|[uμnp]?C|[muμn]?A|[mkM]?(Ω|Ω|O|Q|Ohm|W)|(°[CF]|K))?)? *[;,\\n ]*)+[- \t_.,;:#*"\'()\\[\\]a-z0-9]*\\n([- \t_.,;:#*"\'()\\[\\]a-z0-9]+\\n){0,3})?(?P<min>[-=._]+|nan|-?[0-9]+(\\.[0-9]+)?)\\n(?P<typ>[-=._]+|nan|-?[0-9]+(\\.[0-9]+)?)\\n(?P<max>[-=._]+|nan|-?[0-9]+(\\.[0-9]+)?)\\n(?P<unit>[m]?Vv?)(\\n|$)' 

'Figure 9. Diode Forward Voltage vs. Current\nVGS = 0V\nTJ= -55°C\nTJ= 25°C\nTJ= 85°C\nTJ= 125°C\nTJ= 150°C\nTJ= 175°C\n10\n100\n1000\n10000'
Figure 9. Diode Forward Voltage vs. Current
VGS = 0V
TJ= -55°C
TJ= 25°C
TJ= 85°C
TJ= 125°C
TJ= 150°C
TJ= 175°C
10
100
1000
10000 ..

```