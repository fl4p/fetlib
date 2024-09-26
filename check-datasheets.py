import asyncio
import os.path

from discover_parts import discover_mosfets
from dslib.fetch import fetch_datasheet
from dslib.spec_models import DcDcSpecs


async def check_datasheets():
    dcdc = DcDcSpecs(vi=62, vo=27, pin=800, f=40e3, Vgs=12, ripple_factor=0.3, tDead=500e-9)

    parts = asyncio.run(discover_mosfets())
    parts = dcdc.select_mosfets(parts)
    parts = sorted(parts, key=lambda p:(p.mfr,p.mpn))

    missing = []
    for part in parts:
        if not os.path.isfile(part.get_ds_path()):
            print('Missing', part.get_ds_path(), 'URL=', part.ds_url)
            missing.append(part)

    print(len(missing), 'are missing')

    for part in missing:
        #if part.ds_url and part.ds_url.strip(' -'):
        await fetch_datasheet(part.ds_url, part.get_ds_path(), mfr=part.mfr, mpn=part.mpn)

    # download
    # probe: check num pages, if name in content


asyncio.run(check_datasheets())