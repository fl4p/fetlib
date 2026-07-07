import math
from collections import defaultdict

import dslib.store
from dslib.conditions import normalize_conditions

dss = dslib.store.datasheets_db.load()

print('loaded', len(dss), 'datasheets')

db_parts = dslib.store.parts_db.load()

print('loaded', len(db_parts), 'parts')

for k, ds in dss.items():
   if k in db_parts:
      try:
         db_parts[k].specs = ds.get_mosfet_specs()
      except Exception as e:
         print(k, e)
         continue
   else:
      print(k, 'part is missing')

dslib.store.parts_db.add(list(db_parts.values()))