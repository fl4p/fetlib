import re

s = "Q gs,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan"
r = re.compile(r'(charge(\s+gate[\s-]to[\s-](source|drain)\s*)?(\s+at\s+V[ _]?th)?|Q[\s_]?[0-9a-z]{1,3}([\s_]?\([a-z]{2,5}\))?)(,([ -_]*|nan))*,-\s+(?P<typ>[0-9]+(\.[0-9]+)?)\s+-[,\s](?P<unit>[uμnp]C)(,|$)', re.IGNORECASE)

next(r.finditer(s), None)

