import re

s = "Q gs,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan"
r = re.compile(r'(charge(\s+gate[\s-]to[\s-](source|drain)\s*)?(\s+at\s+V[ _]?th)?|Q[\s_]?[0-9a-z]{1,3}([\s_]?\([a-z]{2,5}\))?)(,([ -_]*|nan))*,-\s+(?P<typ>[0-9]+(\.[0-9]+)?)\s+-[,\s](?P<unit>[uμnp]C)(,|$)', re.IGNORECASE)

next(r.finditer(s), None)



# catasthrophic backtracking
# 'Figure 9. Diode Forward Voltage vs. Current\nVGS = 0V\nTJ = -55oC\nTJ = 25oC\nTJ = 85oC\nTJ = 125oC\nTJ = 175oC\nTJ = 150oC\n1\n10\n100\n1000'
