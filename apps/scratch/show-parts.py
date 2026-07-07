import math
from collections import defaultdict

import dslib.store
from dslib.conditions import normalize_conditions

parts = dslib.store.parts_db.load()

print('loaded', len(parts), 'parts')

for k, ds in parts.items():
   print(k, ds.specs)
