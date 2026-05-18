import math
from collections import defaultdict

import dslib.store
from dslib.conditions import normalize_conditions

dss = dslib.store.datasheets_db.load()


h = defaultdict(lambda: [])

for k, ds in dss.items():

    vbr = ds.get_max_or_min_or_typ('Vds')

    if "Qoss" in ds.fields_lists:
        for f in ds.fields_lists["Qoss"]:
            vds = normalize_conditions(f.cond).get('Vds')
            if vds:
                if vds > vbr:
                    print(ds.part.mpn, 'vds>vbr', f)

                h[vbr].append(vds)
                break
        else:
            for f in ds.fields_lists["Qoss"]:
                print(ds.part.mpn, f, normalize_conditions(f.cond))


for vbr, v in sorted(h.items()):
    print(vbr, sorted(set(v)))