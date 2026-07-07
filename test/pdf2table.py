import camelot

from dslib.cache import disk_cache


@disk_cache(ttl='1d')
def read_tables():
    tables = camelot.read_pdf('../datasheets/toshiba/TK35A08N1.pdf', pages='all',
                              flavor="stream")
    return tables

tables = read_tables()

import pandas as pd
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)

#df = pd.concat([t.df for t in tables],axis=0,ignore_index=True)

for table in tables:
    print(table.df)
#print(df)