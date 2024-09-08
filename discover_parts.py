import os
from typing import List

from dslib.fetch import fetch_datasheet
from dslib.parts_discovery import infineon_mosfets, ti_mosfets, DiscoveredPart
from dslib.pdf2txt.parse import parse_datasheet

parts: List[DiscoveredPart] = []

parts += ti_mosfets()

parts += infineon_mosfets(
    Vds_min=60,
    Rds_on_max=20e-3,
)

parts = [p for p in parts if p.specs.Vds_max >= 60]

download = [p for p in parts if not os.path.exists(p.get_ds_path())]

i = 0
for part in download:
    i += 1
    print('download', i, '/', len(download))
    fetch_datasheet(part.ds_url, part.get_ds_path(), mfr=part.mfr, mpn=part.mpn)

for part in parts:
    parse_datasheet(part.get_ds_path())
