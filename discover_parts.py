import asyncio
import math
import os
from collections import defaultdict
from typing import List, Dict, Tuple

import dslib.discovery.ao
import dslib.discovery.digikey
import dslib.discovery.epc
import dslib.discovery.huayi
import dslib.discovery.infineon
import dslib.discovery.nxp
import dslib.discovery.onsemi
import dslib.discovery.st
import dslib.discovery.ti
import dslib.discovery.toshiba
import dslib.discovery.tw
import dslib.discovery.vishay
from dslib import mfr_tag
from dslib.discovery import DiscoveredPart, benchmark_mpns
from dslib.fetch import fetch_datasheet, close_browser, get_datasheet_url


def unique_parts(parts: List[DiscoveredPart]):
    def normal_mpn(mpn, mfr):
        if mfr_tag(mfr) == 'infineon':
            if mpn.endswith('AKMA1') or mpn.endswith('AKSA1') or mpn.endswith('XKSA1') or mpn.endswith('XKMA1'):
                mpn = mpn[:-5]

        return mpn

    by: Dict[Tuple[str, str], DiscoveredPart] = {}
    for part in parts:
        assert part.mpn and isinstance(part.mpn, str) and part.mpn.lower() != 'nan', part.mpn
        k = part.mfr, normal_mpn(part.mpn, part.mfr)
        if k in by:
            if part.specs and part.specs.source == ['digikey']:
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

    try:
        parts += await dslib.discovery.onsemi.onsemi_mosfets()
        parts += await dslib.discovery.ao.aosmd_medium_voltage_mosfets()
        parts += await dslib.discovery.toshiba.toshiba_mosfets()
        parts += await dslib.discovery.ti.ti_mosfets()
        parts += await dslib.discovery.infineon.infineon_mosfets()
        parts += await dslib.discovery.tw.taiwansemi_nfets()
        parts += await dslib.discovery.st.st_mosfets()
        parts += dslib.discovery.vishay.vishay_mosfets()
        parts += dslib.discovery.huayi.huayi_mosfets()
        parts += await dslib.discovery.nxp.nexperia_mosfets()
        parts += await dslib.discovery.epc.epc_gan()

        # TODO
        # EPC china partner https://www.upi-semi.com/upisemi/products/mosfet/middle-voltage-power-mosfet-40v200v/
        # qorvo SiC
        # rohm
        # MCC
        # comchip
        # diodes
        # goford
        # good-ark
        # torex semiconductor
        # panjit
        #

        from dslib.discovery.lcsc import discover_china_mosfets
        parts +=await discover_china_mosfets()
    except:
        await close_browser()
        raise

    parts += dslib.discovery.digikey.digikey('parts-lists/digikey/*.csv', no_obsolete=no_obsolete)

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
    # discover available MOSFETS:
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
    dcdc_params = DcDcLoadParams.default()
    #parts = dcdc_params.select_mosfets(parts, max_parallel=10)

    #parts = [p for p in parts if (p.specs.ID_25 >= 2 and p.specs.Rds_on_10v_max < 20e-3)]
        #        or (p.specs.Vds_max >= 200 and p.specs.Vds_max <= 800 and p.specs.ID_25 >= 10)
        #        or is_benchmark_part(p)
        # )]

    #parts = [p for p in parts if (
    #        (p.specs.Vds_max >= 60 and p.specs.Vds_max <= 200 and p.specs.ID_25 >= 20 and p.specs.Rds_on_10v_max < 10e-3)
    #        or (p.specs.Vds_max >= 200 and p.specs.Vds_max <= 800 and p.specs.ID_25 >= 10)
    #        or is_benchmark_part(p)
    #)]

    sel_by_mfr = defaultdict(list)
    for p in parts:
        sel_by_mfr[p.mfr].append(p)
    for mfr in by_mfr.keys():
        if len(sel_by_mfr[mfr]) > 0:
            print('%-22s with %5d/%5d' % (mfr, len(sel_by_mfr[mfr]), len(by_mfr[mfr])))

    print('selected mosfet parts:', len(parts), dcdc_params)

    #for p in parts:
    #    if ' ' in p.mpn or '/' in p.mpn or ', ' in p.mpn:
    #        op = os.path.join('datasheets', p.mfr, p.mpn + '.pdf')
    #        if os.path.exists(op):
    #            if os.path.exists(p.get_ds_path()):
    #                print('removed', op, '(new: ', p.get_ds_path())
    #                os.remove(op)
    #            else:
    #                print('rename', op, p.get_ds_path())
    #                os.rename(op, p.get_ds_path())

                # os.remove(op)

    download = [p for p in parts if not os.path.exists(p.get_ds_path()) and p.ds_url]

    def manual_dl_only(p:DiscoveredPart):
        if p.mfr == 'st':
            return True
        return False

    man = []
    for d in download:
        if manual_dl_only(d):
            man.append(d.ds_url or get_datasheet_url(d.mfr, d.mpn))

    if man:
        print('manual dl parts:', (man))
        print("""
async function downloadAll(urls) {
  for (const url of urls) {
    try {
      const res = await fetch(url);
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = url.split('/').pop().split('?')[0] || 'download';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(a.href);
      await new Promise(r => setTimeout(r, 300));
    } catch (e) {
      console.error('Failed:', url, e);
    }
  }
}
        
        """)

    from wakepy import keep
    with keep.running():
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
