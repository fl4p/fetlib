import asyncio
import os
from typing import List

from dslib import parts_discovery
from dslib.fetch import fetch_datasheet
from dslib.parts_discovery import DiscoveredPart
from dslib.pdf2txt.parse import parse_datasheet


async def discover_mosfets():
    parts: List[DiscoveredPart] = []

    parts += await parts_discovery.onsemi_mosfets()
    parts += await parts_discovery.toshiba_mosfets()
    parts += await parts_discovery.ti_mosfets()
    parts += await parts_discovery.infineon_mosfets()

    return parts

def move_low_voltage_datasheets(parts):
    parts = [p for p in parts if p.specs.Vds_max < 80 or p.specs.Vds_max > 200]
    for p in parts:
        if os.path.exists(p.get_ds_path()):
            print('rename', p.get_ds_path())
            d = os.path.dirname('lv-' + p.get_ds_path())
            os.path.exists(d) or os.makedirs(d, exist_ok=True)
            os.rename(p.get_ds_path(), 'lv-' + p.get_ds_path())

if __name__ == '__main__':

    parts = asyncio.run(discover_mosfets())

    move_low_voltage_datasheets(parts)
    #exit(0)

    parts = [p for p in parts if p.specs.Vds_max >= 80 and p.specs.Vds_max <= 200] # 48V battery

    download = [p for p in parts if not os.path.exists(p.get_ds_path())]

    i = 0
    for part in download:
        i += 1
        print('download', i, '/', len(download))
        fetch_datasheet(part.ds_url, part.get_ds_path(), mfr=part.mfr, mpn=part.mpn)

    for part in parts:
        if os.path.exists(part.get_ds_path()):
            print(part.get_ds_path())
            parse_datasheet(part.get_ds_path())
