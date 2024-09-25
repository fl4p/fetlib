from typing import Tuple

import pandas as pd

from dslib import write_csv
from dslib.field import DatasheetFields
from dslib.spec_models import MosfetSpecs
from dslib.store import ObjectDatabase, Mfr, Mpn

#from dslib.store import datasheets_db


datasheets_db = ObjectDatabase[Tuple[Mfr, Mpn], DatasheetFields]('out/datasheets-lib', lambda d: (d.part.mfr, d.part.mpn) if hasattr(d, 'part') else (d.mfr, d.mpn))



def main():
    dss = datasheets_db.load()

    rows = []

    for ds in dss.values():
        try:
            mf = ds.get_mosfet_specs()
        except Exception as e:
            ds.print()
            raise

        row = {
            **ds.get_row(),

            'Qgd/Qgs': mf.Qgd / mf.Qgs,

            'Qgs/Qsw': mf.Qgs / mf.Qsw,
            'Qgd/Qsw': mf.Qgd / mf.Qsw,

            'Qgs2/Qgs': mf.Qgs2 / mf.Qgs,
            'Qg_th/Qgs': mf.Qg_th / mf.Qgs,
        }
        rows.append(row)

    if len(rows):
        write_csv(pd.DataFrame(rows), 'fet-params.csv')


if __name__ == '__main__':
    main()