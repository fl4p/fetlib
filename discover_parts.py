import asyncio
import math
import os
from collections import defaultdict
from typing import List, Dict, Tuple

from dslib import parts_discovery
from dslib.fetch import fetch_datasheet
from dslib.parts_discovery import DiscoveredPart, benchmark_mpns


def unique_parts(parts: List[DiscoveredPart]):
    by: Dict[Tuple[str, str], DiscoveredPart] = {}
    for part in parts:
        k = part.mfr, part.mpn
        if k in by:
            if part.specs.source == 'digikey':
                continue # digikey data is often wrong
            by[k].package = by[k].package or part.package
            try:
                by[k].specs.update(part.specs)
            except:
                print('error updating specs for', k)
                print(by[k].specs.fields(), 'from ', by[k].specs.source)
                print('- and -')
                print(part.specs.fields(), 'from ', part.specs.source)
                raise
        else:
            by[k] = part
    return list(by.values())


async def discover_mosfets(no_obsolete=False):
    parts: List[DiscoveredPart] = []

    parts += await parts_discovery.onsemi_mosfets()
    parts += await parts_discovery.aosmd_medium_voltage_mosfets()
    parts += await parts_discovery.toshiba_mosfets()
    parts += await parts_discovery.ti_mosfets()
    parts += await parts_discovery.infineon_mosfets()
    parts += await parts_discovery.taiwansemi_nfets()
    parts += await parts_discovery.st_mosfets()
    parts += await parts_discovery.vishay_mosfets()
    parts += parts_discovery.huayi_mosfets()

    parts += parts_discovery.digikey('parts-lists/digikey/*.csv', no_obsolete=no_obsolete)

    parts = unique_parts(parts)

    return parts


def move_low_voltage_datasheets(parts):
    parts = [p for p in parts if p.specs.Vds_max < 80 or p.specs.Vds_max > 200]
    for p in parts:
        if os.path.exists(p.get_ds_path()):
            print('rename', p.get_ds_path())
            d = os.path.dirname('lv-' + p.get_ds_path())
            os.path.exists(d) or os.makedirs(d, exist_ok=True)
            os.rename(p.get_ds_path(), 'lv-' + p.get_ds_path())


def is_benchmark_part(part: DiscoveredPart):
    return (part.mfr, part.mpn) in benchmark_mpns() or (part.mfr, part.mpn2) in benchmark_mpns()


async def main():
    parts = await discover_mosfets()

    # move_low_voltage_datasheets(parts)
    # exit(0)

    print('discovered mosfet parts:', len(parts))
    print('MFR:', set(p.mfr for p in parts))
    print('Vds_max:', sorted(set(int(p.specs.Vds_max) for p in parts if not math.isnan(p.specs.Vds_max))))
    by_mfr = defaultdict(list)
    for p in parts:
        by_mfr[p.mfr].append(p)

    from dslib.spec_models import DcDcLoadParams
    parts = DcDcLoadParams.default().select_mosfets(parts)

    #parts = [p for p in parts if (
    #        (p.specs.Vds_max >= 60 and p.specs.Vds_max <= 200 and p.specs.ID_25 >= 20 and p.specs.Rds_on_10v_max < 10e3)
    #        or (p.specs.Vds_max >= 200 and p.specs.Vds_max <= 800 and p.specs.ID_25 >= 10)
    #        or is_benchmark_part(p)
    #)]

    sel_by_mfr = defaultdict(list)
    for p in parts:
        sel_by_mfr[p.mfr].append(p)
    for mfr in by_mfr.keys():
        if len(sel_by_mfr[mfr]) > 0:
            print('%-22s with %5d/%5d' % (mfr, len(sel_by_mfr[mfr]), len(by_mfr[mfr])))

    print('selected mosfet parts:', len(parts))

    download = [p for p in parts if not os.path.exists(p.get_ds_path()) and p.ds_url]

    i = 0
    for part in download:
        i += 1
        print('download', i, '/', len(download))

        # if os.path.exists('other-' + part.get_ds_path()):
        #    os.rename('other-' + part.get_ds_path(), part.get_ds_path())
        #    continue

        await fetch_datasheet(part.ds_url, part.get_ds_path(), mfr=part.mfr, mpn=part.mpn)


if __name__ == '__main__':
    asyncio.run(main())
