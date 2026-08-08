import json

import argparse
import asyncio
import copy
import math
import os
import sys
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
from dslib.cache import disk_cache
from dslib.discovery import DiscoveredPart, benchmark_mpns
from dslib.fetch import fetch_datasheet, close_browser, get_datasheet_url
from dslib.prices import PACKAGING_SUFFIXES, family_mpn


def _valid_mpn(mpn):
    return bool(mpn) and isinstance(mpn, str) and mpn.lower() != 'nan'


def normal_mpn(mpn, mfr):
    """Ordering-code-insensitive spelling of one MPN.

    Strips only codes DOCUMENTED as packing codes for that manufacturer
    (Infineon AKSA1/XKMA1/XTSA1/... -- family_mpn's regex, which supersedes the
    four suffixes this used to hardcode). Generic continuations are left alone:
    IRFB4110G is not IRFB4110. Cross-vendor carrier suffixes are handled by
    _group_keys, which additionally requires the bare base to exist.

    Case/whitespace are normalized too -- 'BSC070N10NS3 G' and 'BSC070N10NS3G'
    are the same part. The returned value is a KEY, not a display MPN.
    """
    return family_mpn(mfr_tag(mfr), mpn)


def _group_keys(parts: List[DiscoveredPart]) -> Dict[int, Tuple[str, str]]:
    """Map id(part) -> consolidation key, joining ordering siblings.

    Three links, all of which must hold the SAME die:
      1. normal_mpn      -- documented packing codes (IPP039N10N5{,AKSA1,XKSA1})
      2. mpn2            -- the manufacturer's own "this is the same part" pointer
                            (Infineon lists IRFB4110 with mpn2=IRFB4110PBF)
      3. prefix scan     -- a reviewed packaging suffix ON TOP of a base that is
                            ITSELF present in the corpus. Never invents a base:
                            two rows must exist for anything to merge.

    Grouping here only proposes a merge; unique_parts still has to get it past
    MosfetBasicSpecs.update's agreement asserts, and refuses the merge if not.
    """
    parent: Dict[Tuple[str, str], Tuple[str, str]] = {}

    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            # shorter key wins as root, so the family root is the base MPN
            lo, hi = sorted((ra, rb), key=lambda k: (len(k[1]), k[1]))
            parent[hi] = lo

    own: Dict[int, Tuple[str, str]] = {}
    for part in parts:
        tag = mfr_tag(part.mfr)
        k = (tag, normal_mpn(part.mpn, part.mfr))
        own[id(part)] = k
        find(k)
        mpn2 = getattr(part, 'mpn2', None)
        if _valid_mpn(mpn2):
            union(k, (tag, normal_mpn(mpn2, part.mfr)))

    # (3) reviewed packaging suffix over a base that is itself in the corpus
    present = set(parent)
    for tag, mpn in sorted(present):
        for suffix in sorted(PACKAGING_SUFFIXES, key=len, reverse=True):
            base = mpn[:-len(suffix)]
            # >=4 keeps a short MPN from being eaten by its own tail
            if len(base) >= 4 and mpn.endswith(suffix) and (tag, base) in present:
                union((tag, mpn), (tag, base))
                break

    return {i: find(k) for i, k in own.items()}


def unique_parts(parts: List[DiscoveredPart]):
    valid = []
    for part in parts:
        if _valid_mpn(part.mpn):
            valid.append(part)
        else:
            print('SKIP part with invalid mpn:', part.mfr, repr(part.mpn),
                  part.specs and part.specs.source)
    parts = valid
    keys = _group_keys(parts)

    by: Dict[Tuple[str, str], DiscoveredPart] = {}
    # group root -> every key the group ended up occupying, in insertion order. A
    # refused merge spills to a new key, and the NEXT sibling has to be offered
    # every spill before minting one of its own: IPP70N10S3L12AKSA1 and ...AKSA2
    # agree with each other and disagree only with their (stale) base record, so
    # trying just the first key left them as two rows.
    spills: Dict[Tuple[str, str], list] = {}
    for part in parts:
        root = keys[id(part)]
        if root not in spills:
            spills[root] = [root]
            by[root] = part
            continue
        if part.specs and part.specs.source == ['digikey']:
            continue # digikey data is often wrong
        # Trial-merge on a COPY. MosfetBasicSpecs.update asserts that the two
        # sources agree (Vds exactly, Rds_on/ID within 45%, Qg within 1%) and
        # mutates as it goes, so a failing merge would otherwise leave the
        # survivor half-updated -- and it used to abort the whole run.
        # Ordering siblings do sometimes carry different scraped values (the
        # CoolMOS 25C/150C V(BR)DSS rows; Qg_typ read off a different table
        # column). Refusing the merge keeps BOTH rows in the ranking, which is
        # visible and inspectable; picking a winner here would publish one
        # spelling's numbers under the other's name.
        reasons = []
        for k in spills[root]:
            trial = copy.deepcopy(by[k].specs)
            try:
                trial.update(part.specs)
            except Exception as e:
                reasons.append('%s (%s)' % (by[k].mpn, e))
            else:
                by[k].specs = trial
                by[k].package = by[k].package or part.package
                break
        else:
            print('KEEPING duplicate %s separate, specs disagree with %s'
                  % (part.mpn, ', '.join(reasons)))
            k = _unmerged_key(root, part, by)
            spills[root].append(k)
            by[k] = part
    return list(by.values())


def _unmerged_key(group_key, part, by):
    """A free key for a part whose merge into every key of its group was refused."""
    base = (group_key[0], normal_mpn(part.mpn, part.mfr))
    if base not in by:
        return base
    for n in range(2, 1000):
        k = (base[0], '%s#%d' % (base[1], n))
        if k not in by:
            return k
    raise RuntimeError('too many unmergeable spellings of %r' % (base,))


@disk_cache(ttl='1d', hash_func_code=True)
async def discover_mosfets(no_obsolete=False):
    # Whole-corpus cache on top of the per-scraper caches: a hit skips every scraper
    # await, the browser launch AND the unique_parts merge (repeat runs go from minutes
    # to ~a second). 1d ttl because the corpus drifts slowly. CAVEATS (all bounded by
    # the 1d ttl): hash_func_code covers only THIS function's source, not the scrapers
    # it calls or the parts-lists/*.csv inputs -- a scraper fix or a freshly exported
    # digikey CSV is not picked up until the ttl expires. Run once with --no-cache
    # (disables ALL disk caches, main_yaml calls disk_cache_disable before discovery)
    # or delete this function's cache tree to ingest immediately.
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


def parse_args():
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--config-file')
    return parser.parse_args(sys.argv[1:])


def load_config(config_file):
    if not config_file:
        return None
    import yaml
    with open(config_file) as fh:
        return yaml.safe_load(fh)


def filter_parts_by_config(parts, conf):
    substrates = conf.get('substrates')
    if substrates:
        substrates = set(map(lambda s: s.strip(), substrates.split(','))) if isinstance(substrates, str) \
            else set(substrates)
        parts = [p for p in parts if
                 not hasattr(p.specs, 'substrate') or not p.specs.substrate or p.specs.substrate in substrates]

    packages = conf.get('packages')
    if packages:
        packages = set(map(lambda s: s.strip(), packages.split(','))) if isinstance(packages, str) \
            else set(packages)

        def _match_package(part, packages):
            if not part.package:
                return True
            for pk in packages:
                p = part.package.upper()
                if pk == 'TO-220' and 'TO220' in p or 'TO-220' in p or 'T220' in p:
                    return True
            return False

        parts = [p for p in parts if _match_package(p, packages)]

    vds_range = conf.get('vdsRange')
    if vds_range:
        assert len(vds_range) == 2 and vds_range[0] < vds_range[1]
        parts = [p for p in parts if
                 p.specs.Vds_max > 1 and p.specs.Vds_max >= vds_range[0] and p.specs.Vds_max <= vds_range[1]]

    return parts


def dcdc_load_params_from_config(conf):
    from dslib.spec_models import DcDcLoadParams

    load_points = conf['loadPoints']
    assert len(load_points) == 1
    l = load_points[0]
    assert l['pointWeight'] == 1

    return DcDcLoadParams(l['vIn'], l['vOut'], float(l['f']),
                          tDead=float(conf['gateDrive']['deadTime']),
                          pin=l['pIn'],
                          ripple_factor=conf['inductor']['rippleFactor'])


async def main():
    try:
        await _main()
    finally:
        await close_browser()


async def _main():
    cargs = parse_args()
    conf = load_config(cargs.config_file)

    # discover available MOSFETS:
    parts = await discover_mosfets(no_obsolete=not (conf.get('includeObsolete', False) if conf else False))

    if conf:
        parts = filter_parts_by_config(parts, conf)

    # move_low_voltage_datasheets(parts)
    # exit(0)

    print('discovered mosfet parts:', len(parts))
    print('MFR:', set(p.mfr for p in parts))
    print('Vds_max:', sorted(set(int(p.specs.Vds_max) for p in parts if not math.isnan(p.specs.Vds_max))))
    by_mfr = defaultdict(list)
    for p in parts:
        by_mfr[p.mfr].append(p)

    if conf:
        dcdc_params = dcdc_load_params_from_config(conf)
    else:
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

downloadAll(""" + json.dumps(man) +  """)        
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
