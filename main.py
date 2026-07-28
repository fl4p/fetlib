import argparse
import asyncio
import datetime
import logging
import math
import os.path
import random
import sys
import traceback
from typing import List, Dict, Literal, Tuple, Optional, Union

import pandas as pd

import dslib.manual_fields
from dclib.powerloss import (dcdc_buck_hs, dcdc_buck_ls, ls_commutation_didt,
                             qrr_rankable_at_operating_point, GateLoopInfeasible)
from dclib.coss_loss import coss_audit_json
from discover_parts import discover_mosfets
from dslib import write_csv, dotdict, round_to_n, isnum
from dslib.cache import disk_cache
from dslib.discovery import DiscoveredPart, Substrate
from dslib.fetch import fetch_datasheet
from dslib.field import Field, DatasheetFields, field_repr_salt, merge_keeping_absent_symbols
from dslib.mosfet import GateDrive
from dslib.pdf.fonts import fontforge_bin
from dslib.pdf.parse import (parse_datasheet, subsctract_needed_symbols, NoTabularData,
                             TooManyPages, chart_digitizer_salt)
from dslib.pdf.tabular import tabula_is_running
from dslib.spec_models import DcDcLoadParams
from dslib.store import Part
from dslib.util import run_parallel

# MAX_PARALLEL = 2

IDP_ID_RATIO = 10  # GaN pulse current is up to 10x higher than dc (EPC2052)

excludes = {
    'datasheets/infineon/BSC160N15NS5ATMA1.pdf',
    'datasheets/infineon/BSC019N08NS5ATMA1.pdf',
    'datasheets/infineon/IQE050N08NM5ATMA1.pdf',
    'datasheets/infineon/BSC050N10NS5ATMA1.pdf',
    'datasheets/infineon/BSZ123N08NS3GATMA1.pdf',
    'datasheets/infineon/IRF150DM115XTMA1.pdf',
    'datasheets/infineon/BSZ097N10NS5ATMA1.pdf',
    'datasheets/infineon/BSC070N10NS3GATMA1.pdf',

    'datasheets/infineon/IPI072N10N3G.pdf',
    'datasheets/infineon/IPP180N10N3GXKSA1.pdf',
    'datasheets/infineon/IPP048N12N3GXKSA1.pdf',
    'datasheets/infineon/BSC109N10NS3GATMA1.pdf',
    'datasheets/infineon/BSC047N08NS3GATMA1.pdf',
    'datasheets/infineon/BSC057N08NS3GATMA1.pdf',
    'datasheets/infineon/IST026N10NM5AUMA1.pdf',

    'datasheets/infineon/IPP028N08N3GXKSA1.pdf',
    'datasheets/infineon/IPP06CN10LG.pdf',

    'datasheets/diodes/DMTH15H017SPS-13.pdf',  # `cant find unicode for glyph name`

    'datasheets/littelfuse/IXTH10P60.pdf',  # P-mos todo
}
excludes.clear()

excludes.add('datasheets/diodes/DMTH15H017SPS-13.pdf')
excludes.add('datasheets/littelfuse/IXTH10P60.pdf')


def main_yaml():
    parser = argparse.ArgumentParser(description='')
    # Required. `python3 main.py` with no arguments used to reach main(), which built a
    # DcDcLoadParams.default() design — that entry point had already decayed to a stub that
    # computed the design and returned without running anything, and __main__ has called
    # main_yaml() for a while, so the no-arg form died with a TypeError inside open(None).
    # An argparse error naming the missing option beats that. README step 6 and CLAUDE.md
    # both documented the no-arg form and have been corrected.
    parser.add_argument('--config-file', required=True,
                        help='YAML project to run, e.g. apps/proj/buck.yaml')

    parser.add_argument('-j', default=8)  # parallel jobs
    parser.add_argument('-q')
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--no-ocr', action='store_true')
    parser.add_argument('--no-download', action='store_true')
    parser.add_argument('--tabular-harvest', action='store_true',
                        help='run Tabula even when text+v2 already satisfy need_symbols '
                             '(restores pre-2026-07 opportunistic harvesting of non-needed '
                             'fields into the DB; slower -- adds a Tabula pass per covered part)')
    parser.add_argument('--fetch-prices', action='store_true',
                        help='fetch distributor prices for the ranked candidates before CSV '
                             'generation: DigiKey API (creds from env or data/.digikey-api; '
                             'the FIRST run opens a browser for OAuth) + LCSC brand-catalog '
                             'harvest. Results persist in data/prices-lib.sqlite3 (~7d fresh). '
                             'Without this flag the price_usd column is still filled from '
                             'whatever that store already holds (stale records suppressed).')
    parser.add_argument('--qrr-op', action='store_true',
                        help='force syncFet.qrrOperatingPoint on for this run: book the LS '
                             "reverse-recovery loss on the Qrr predicted at THIS converter's "
                             'operating point (IF = valley current, di/dt from the HS '
                             'current-rise time) instead of the flat datasheet Qrr measured at '
                             "the vendor's own test point. Only parts with curated conditions "
                             '(dslib/qrr_conditions.py) or two-di/dt rows (dslib/qrr_points.py) '
                             'are rescaled -- 98%% of the current corpus has neither and keeps '
                             'the flat value, marked Qrr_src=datasheet-flat-nofit in the CSV. '
                             'Read that column before comparing rows.')

    cargs = parser.parse_args(sys.argv[1:])

    if cargs.no_cache:
        # In the MAIN process, before discovery: the worker-side call at
        # compile_part_datasheet only covers the parse phase, so without this,
        # --no-cache silently did NOT bypass the discovery-level disk caches
        # (discover_mosfets 1d, per-scraper 7d, LCSC raw rows 7d).
        from dslib.cache import disk_cache_disable
        disk_cache_disable(True)

    import yaml
    with open(cargs.config_file) as fh:
        conf = yaml.safe_load(fh)

    args = RunArgs(topology=conf['topology'],
                   substrates=conf['substrates'], packages=conf['packages'],
                   vdsRange=conf['vdsRange'],
                   dcdc=DcdcArgs(
                       controlFet=ControlFetArgs(**conf['controlFet']),
                       gateDrive=GateDrive(rg_total=float(conf['gateDrive']['rgTotal']),
                                           rg_total_dis=float(conf['gateDrive']['rgTotalOff']),
                                           Von=float(conf['gateDrive']['voltage']),
                                           Von_GaN=float(conf['gateDrive'].get('voltageGaN', 'nan')),
                                           Voff=0,
                                           fallback_V_pl=float(conf['gateDrive']['vplFallback']),
                                           tDead=float(conf['gateDrive']['deadTime'])),
                       syncFet=SyncFetArgs(**conf['syncFet']),
                       inductor=InductorArgs(**conf['inductor']),
                   ),
                   loads=[
                       DcdcLoadPoint(weight=p['pointWeight'], vIn=p['vIn'], vOut=p['vOut'], pIn=p['pIn'],
                                     f=float(p['f']))
                       for p in conf['loadPoints']
                   ],
                   q=cargs.q,
                   price_qty=int(conf.get('priceQty', 100)),
                )

    # CLI override for the YAML knob, so the two rankings can be A/B'd from one config.
    # One-way on purpose: --qrr-op can enable it, nothing here can turn a config's
    # `qrrOperatingPoint: true` back off silently.
    if cargs.qrr_op:
        args.dcdc.syncFet.qrrOperatingPoint = True

    run(args, cargs, os.path.basename(cargs.config_file).split('.yaml')[0])


class ControlFetArgs():
    def __init__(self, maxParallel, stagedSwitching):
        self.maxParallel = maxParallel
        self.stagedSwitching = stagedSwitching


class SyncFetArgs():
    def __init__(self, maxParallel=1, reverseRecoveryFactor: float = 1.0,
                 qrrOperatingPoint: bool = False):
        assert isinstance(maxParallel, int) and maxParallel >= 1 and maxParallel <= 20
        self.maxParallel = maxParallel
        assert reverseRecoveryFactor >= 0 and reverseRecoveryFactor <= 1
        self.reverseRecoveryFactor = reverseRecoveryFactor
        # See main()'s --qrr-op help. Off by default: the flat datasheet Qrr is what every
        # stored CSV in out/ was ranked with, and the operating-point charge is a different
        # quantity (typically several times larger at a real converter's di/dt), not a
        # correction that can be switched on silently under existing results.
        assert isinstance(qrrOperatingPoint, bool), qrrOperatingPoint
        self.qrrOperatingPoint = qrrOperatingPoint


class InductorArgs():

    def __init__(self, rippleFactor):
        assert rippleFactor > 0 and rippleFactor <= 1
        self.rippleFactor = rippleFactor


class DcdcArgs():

    def __init__(self, controlFet: ControlFetArgs, gateDrive: GateDrive, syncFet: SyncFetArgs, inductor: InductorArgs):
        self.controlFet = controlFet
        self.gateDrive = gateDrive
        self.syncFet = syncFet
        self.inductor = inductor


class DcdcLoadPoint():
    def __init__(self, weight, vIn, vOut, pIn, f):
        self.weight = weight
        self.vIn = vIn
        self.vOut = vOut
        self.pIn = pIn
        self.f = f


class RunArgs():
    def __init__(self, topology: Literal['buck'],
                 substrates: Union[List[Substrate], str],
                 packages: Optional[Literal['TO-220']],
                 vdsRange: Tuple[float, float],
                 dcdc: DcdcArgs,
                 loads: List[DcdcLoadPoint],
                 includeObsolete: bool = False,
                 q: Optional[str] = None,
                 price_qty: int = 100,
                 ):
        assert topology == 'buck'
        self.topology = topology
        # qty basis for the price_usd CSV column (YAML: priceQty). One fixed basis per
        # run keeps rows comparable across parallel counts.
        self.price_qty = int(price_qty)

        if isinstance(substrates, str):
            substrates = set(map(lambda s: s.strip(), substrates.split(',')))
        else:
            substrates = set(substrates)
        assert not (substrates - {'GaN', 'Si', 'SiC'})
        self.substrates = substrates

        packages = set(map(lambda s: s.strip(), packages.split(',')) if isinstance(packages, str) else packages or [])
        assert not (packages - {'TO-220'})
        self.packages = set(packages)

        self.vdsRange = vdsRange
        self.dcdc = dcdc
        self.loads = loads
        self.includeObsolete = includeObsolete
        self.q = q


async def _discover_and_close_browser(no_obsolete):
    # Each asyncio.run phase must own its browser: get_browser_page keys contexts by
    # event-loop id and asserts no context of a DEAD loop lingers (dslib/fetch.py:152),
    # so leaving the browser open here would crash the next asyncio.run phase (e.g. the
    # --fetch-prices LCSC harvest).
    from dslib.fetch import close_browser
    try:
        return await discover_mosfets(no_obsolete=no_obsolete)
    finally:
        await close_browser()


def run(args: RunArgs, cargs, name):

    parts = asyncio.run(_discover_and_close_browser(no_obsolete=not args.includeObsolete))
    print('Discovered', len(parts), 'parts from manufacturers:', ', '.join(sorted(set(p.mfr for p in parts))))
    # print('all parts:', ','.join(sorted(set(p.mpn for p in parts))))


    if args.substrates:
        parts = [p for p in parts if
                 not hasattr(p.specs, 'substrate') or not p.specs.substrate or p.specs.substrate in args.substrates]

    if args.packages:
        def _match_package(part, packages):
            if not part.package:
                return True
            for pk in packages:
                p = part.package.upper()
                if pk == 'TO-220' and 'TO220' in p or 'TO-220' in p or 'T220' in p:
                    return True
            return False

        parts = [p for p in parts if _match_package(p, args.packages)]

    if args.vdsRange:
        assert args.vdsRange[0] < args.vdsRange[1]
        assert len(args.vdsRange) == 2
        parts = [p for p in parts if
                 p.specs.Vds_max > 1 and p.specs.Vds_max >= args.vdsRange[0] and p.specs.Vds_max <= args.vdsRange[1]]

    if args.q:
        words = list(map(lambda s: s.strip(), args.q.lower().strip(' "\'').split(' ')))

        def _match_part(p: DiscoveredPart):
            for w in words:
                if (w not in p.mfr.lower() and w not in p.mpn.lower() and w not in str(p.mpn2).lower()
                        and w not in str(p.package).lower() and w not in str(p.specs.source).lower()):
                    return False
            return True

        parts = list(filter(_match_part, parts))

    print('Filtered', len(parts), 'parts:', ','.join(p.mpn for p in parts[:20]), '..', args.q)

    # pre-select mosfets by voltage and current
    n_pre_select = len(parts)
    # if not args.no_pre_select:

    assert len(args.loads) == 1
    assert args.loads[0].weight == 1
    l = args.loads[0]
    dcdc = DcDcLoadParams(l.vIn, l.vOut, l.f, tDead=args.dcdc.gateDrive.tDead, pin=l.pIn,
                          ripple_factor=args.dcdc.inductor.rippleFactor)

    parts = dcdc.select_mosfets(parts,
                                max_parallel=IDP_ID_RATIO if args.dcdc.controlFet.stagedSwitching else args.dcdc.controlFet.maxParallel)

    print('Found       ', len(parts), 'out of', n_pre_select, 'parts are suitable for given DC-DC specs')
    if cargs.fetch_prices:
        # ranked candidates only: a few hundred parts, right before CSV generation.
        # Runs its own asyncio phase (LCSC harvest) -- the discovery browser was closed
        # above, so this opens and closes its own.
        from dslib.prices import fetch_prices_for_parts
        fetch_prices_for_parts([(p.mfr, p.mpn) for p in parts])
    print(', '.join(sorted(set(p.mpn for p in parts))))
    print('Vds_max:   ',
          sorted(set(int(p.specs.Vds_max) for p in parts if p.specs.Vds_max and not math.isnan(p.specs.Vds_max))))
    print('Substrates:', (set(p.specs.__dict__.get('substrate') for p in parts)))

    # parts = parts[:100]

    from wakepy import keep
    with keep.running():
        # do all the magic: download datasheets, read them and compute power loss:
        dss = read_parts_datasheets(parts, dotdict(cargs.__dict__))

        dslib.store.parts_db.add([Part(discovered=ds.part, specs=mf) for ds in dss
                                  if (mf := get_fet_specs(ds, args.dcdc.gateDrive))])
        # merge= is load-bearing: without it this is a whole-record replacement (add's
        # overwrite defaults to True), so a run parsing fewer symbols than the stored
        # record DELETES the difference. That is what cost 1348 records 65,631 fields on
        # 2026-07-27. Fresh values still win; only the deletion is refused.
        dslib.store.datasheets_db.add(dss, merge=merge_keeping_absent_symbols)

        if not args.vdsRange:
            dss = [ds for ds in dss if dcdc.vds_in_range(ds.get_max_or_min_or_typ('Vds'))]
        else:
            dss = [ds for ds in dss if ds.get_max_or_min_or_typ('Vds') >= args.vdsRange[0]]

        generate_HS_power_loss_csv(dss,
                                   args=args.dcdc,
                                   dcdc=dcdc,
                                   gd=args.dcdc.gateDrive,
                                   name=name,
                                   price_qty=args.price_qty,
                                   )

        generate_LS_power_loss_csv(dss,
                                   args=args.dcdc,
                                   dcdc=dcdc,
                                   gd=args.dcdc.gateDrive,
                                   name=name,
                                   price_qty=args.price_qty,
                                   )


def compile_part_datasheet(part: DiscoveredPart, need_symbols, no_cache, no_ocr, no_download=False,
                           tabular_harvest=False):
    mfr = part.mfr
    mpn = part.mpn
    ds_url = part.ds_url
    ds_path = part.get_ds_path()

    if no_cache:
        # call this here again on all workers
        from dslib.cache import disk_cache_disable
        disk_cache_disable(True)

    ds = DatasheetFields(part=part)

    # place manual fields:
    man_fields = dslib.manual_fields.get_fields()
    ds.add_multiple(man_fields.get(mfr, {}).get(mpn, []), ['ref'])

    ff = dslib.manual_fields.fallback_specs(mfr, mpn)
    # todo filter invalid fields
    if ds or ff:
        need_symbols = subsctract_needed_symbols(need_symbols, set(ds.keys()) | set(ff.keys()), copy=True)

    if not no_cache:

        lp = dslib.store.parts_db.load_obj(part)
        # todo filter invalid fields
        if lp:
            lp_keys = lp.specs.keys()
            if lp_keys:
                need_symbols = subsctract_needed_symbols(need_symbols, lp_keys, copy=True)

        try:
            ld = dslib.store.datasheets_db.load_obj(part)
        except:
            ld = None
        ld_keys = ld.keys() if ld else None
        if ld_keys:
            need_symbols = subsctract_needed_symbols(need_symbols, ld_keys, copy=True)

    if not os.path.exists(ds_path) and not no_download:
        asyncio.run(fetch_datasheet(ds_url, ds_path, mfr=mfr, mpn=mpn))

    # parse datasheet (tabula and pdf2txt):
    if ds_path in excludes:
        ds.errors.append('excluded')
    elif os.path.isfile(ds_path):
        try:
            dsp = parse_datasheet(ds_path, mfr=mfr, mpn=mpn, need_symbols=need_symbols, no_ocr=no_ocr,
                                  tabular_harvest=tabular_harvest)
            ds.timestamp = dsp.timestamp
            ds.date_from_meta = dsp.date_from_meta
            ds.date_from_text = dsp.date_from_text
            ds.add_multiple(dsp.all_fields())
        except (KeyError, AttributeError, NameError):  # Type, Timeout, TimeoutError,
            logging.error('Could not parse datasheet %s', ds_path)
            raise
        except Exception as e:
            if not isinstance(e, (NoTabularData, TooManyPages,)):
                print(traceback.format_exc())
            print(ds_path, 'parse error', type(e).__name__, e)
            ds.errors.append(f'{type(e).__name__} {e}')
    else:
        ds.errors.append('file not found %s' % ds_path)

    try:
        # add discovered basic specs
        ds.add_multiple(part.specs.fields())
    except:
        print(mfr, mpn, part, part.specs)
        raise

    # fallback specs for GaN etc (EPC tRise and tFall)
    fs = dslib.manual_fields.fallback_specs(mfr, mpn)
    for sym, typ in fs.items():
        ds.add(Field(sym, min=math.nan, typ=typ, max=math.nan))

    # print(mfr, mpn)
    return ds


def gate_drive_vgs(ds: DatasheetFields, gd: GateDrive) -> float:
    """The gate voltage this design actually drives `ds` at.

    GaN parts use `Von_GaN` when the config supplies one — they are driven at 5-6 V, not the
    10 V a silicon part sees, and Rds_on/Qg differ materially at that point. Falls back to
    `Von` when `Von_GaN` is NaN (i.e. not configured), because inventing a GaN-specific
    voltage would be worse than using the one the user did state.
    """
    if getattr(ds.part.specs, 'isGaN', False) and not math.isnan(gd.Von_GaN):
        return float(gd.Von_GaN)
    return float(gd.Von)


def get_reference_fet_specs(ds: DatasheetFields):
    """Specs at the DATASHEET REFERENCE gate voltage, for generic parts-DB and utility use.

    Exists because `get_fet_specs` requires a GateDrive, and the generic builders
    (apps/process_parts.py, apps/refresh_part_specs.py) have no design to speak for. Making
    them invent a GateDrive would be worse than naming what they actually want: the vendor's
    characterisation point, not any particular converter's.

    DO NOT rank on this. The distinction is not cosmetic — specs selected at a design's real
    Vgs are design-specific, and `parts_db` is keyed on (mfr, mpn) with no Vgs recorded, so
    persisting design specs under that key lets a 5 V run silently overwrite the reference
    Rds_on/Qg every later consumer reads. Reference specs are the only kind safe to store
    there. main.run still persists design specs at :325 — that is the open half of this
    split, and it is why the boundary is named rather than implicit.
    """
    try:
        return ds.get_mosfet_specs()        # Vgs=None -> dslib.field._DATASHEET_REF_VGS
    except Exception as e:
        ds.errors.append('specs error: ' + str(e))
        return None


def get_fet_specs(ds: DatasheetFields, gd: GateDrive):
    """`gd` is REQUIRED on purpose.

    This used to call ds.get_mosfet_specs() with no arguments, taking that method's 10 V
    default — so Rds_on and Qg were selected at 10 V for every design regardless of the
    configured gateDrive.voltage, and GaN parts were read at a gate voltage they are never
    driven at. Making the gate drive a required parameter means a future call site cannot
    reintroduce that silently; it has to fail loudly instead.
    """
    part = ds.part
    mfr = part.mfr
    mpn = part.mpn
    # parse specification for DC-DC loss model
    try:
        fet_specs = ds.get_mosfet_specs(Vgs=gate_drive_vgs(ds, gd))
        ds.get_row()
        return fet_specs
    except Exception as e:
        print(ds.ds_path, 'error creating mosfet specs', e, type(e))
        print(traceback.format_exc())
        print(part, part.specs.__dict__)
        ds.print(show_cond=True, show_sources=True)
        parse_datasheet.invalidate(ds.ds_path, mfr=mfr, mpn=mpn)
        parse_datasheet.invalidate(ds.ds_path, mfr=mfr)
        parse_datasheet.invalidate(ds.ds_path)
        parse_datasheet.invalidate(ds.ds_path, need_symbols=set(), no_ocr=True)
        parse_datasheet.invalidate(ds.ds_path, need_symbols=set(), no_ocr=False)
        from dslib.pdf.sheet import read_sheet
        read_sheet.invalidate(ds.ds_path)
        dslib.store.parts_db.del_obj(part, ignore_missing=True)

        ds.errors.append('specs error: ' + str(e))
        return None


# field_repr_salt is composed in because the cached value is a list of DatasheetFields, i.e.
# PICKLED Field objects. `hash_func_code` defaults to False and the salt was ('13', excludes),
# so NOTHING in this key covered the code that decides what a Field stores -- and this
# function's result is written straight back to the DB with overwrite=True (main.py:326).
#
# That is not hypothetical. After Rds_on_10v gained an explicit unit, a cache entry written
# before the change was served here and re-persisted its pre-change Fields, silently undoing
# the migration for 1404 records: 4212 fields went back to unitless, where the reader now
# refuses them. A stale cache is recoverable; a stale cache that WRITES ITSELF INTO THE
# DATABASE is not, so the key has to move whenever Field representation moves.
#
# chart_digitizer_salt is here for exactly the same reason, one level out: bumping only
# parse_datasheet's key re-parses nothing, because THIS cache short-circuits it. The
# stale DatasheetFields would be served from here and written back to the DB with
# overwrite=True — the corrected Vpl would never be computed, and the run would look
# like a successful no-op. A key that gates a DB write must move whenever anything it
# could have derived differently moves.
@disk_cache(ttl='999d', salt=('13', excludes, field_repr_salt(), chart_digitizer_salt()))
def read_parts_datasheets(parts: List[DiscoveredPart], args):
    need_symbols = {
        'tRise', 'tFall',  # HS
        'Qgd',  # HS
        ('Qgs', 'Qg_th', 'Qgs2'),  # HS, need one of those.
        'Vsd',  # LS
        # if we would only specify Qgs, the OCR pipeline would brute-force rasterization
        # until it wrongly finds Qgs (which actually was Qgs1)
        # 'Qrr'  # LS # kl leave this, many DS dont have this
    }

    if not os.path.isdir('datasheets'):
        try:
            import subprocess
            subprocess.run(['git', 'clone', 'https://github.com/open-pe/fet-datasheets', 'datasheets'])
        except Exception as e:
            print('git clone error:', e)

    if not tabula_is_running():
        raise RuntimeError('tabula is not running')

    if not fontforge_bin():
        raise RuntimeError('fontforge not found')

        # from ocrmypdf.subprocess import check_external_program
        # check_external_program()
    """
    TODO
    
    check for:
    
    tesseract
    poppler (img2image)
    
     File "/home/fab/fetlib/venv/lib/python3.9/site-packages/pluggy/_callers.py", line 139, in _multicall
    raise exception.with_traceback(exception.__traceback__)
    File "/home/fab/fetlib/venv/lib/python3.9/site-packages/pluggy/_callers.py", line 103, in _multicall
    res = hook_impl.function(*args)
    File "/home/fab/fetlib/venv/lib/python3.9/site-packages/ocrmypdf/builtin_plugins/ghostscript.py", line 53, in check_options
    check_external_program(
    File "/home/fab/fetlib/venv/lib/python3.9/site-packages/ocrmypdf/subprocess/__init__.py", line 341, in check_external_program
    raise MissingDependencyError(program)
    ocrmypdf.exceptions.MissingDependencyError: gs
    
    """

    import pickle

    if os.path.isfile('fet-datasheets.pkl_'):
        with(open('fet-datasheets.pkl', 'rb')) as f:
            dss: List[DatasheetFields] = pickle.load(f)
    else:
        parts_shuffled = list(parts)
        random.shuffle(parts_shuffled)
        jobs = {(p.mfr, p.mpn): (compile_part_datasheet, p, need_symbols, args.no_cache, args.no_ocr,
                                 args.no_download, args.get('tabular_harvest', False))
                for p in
                parts_shuffled}
        results = run_parallel(jobs, int(args.j), 'multiprocessing', verbose=0)
        dss: List[DatasheetFields] = list(results.values())

    dss = [d for d in dss if d != (None, None)]

    for ds in dss:
        ds.add_multiple(ds.part.specs.fields())


    return dss


def generate_HS_power_loss_csv(dss: List[DatasheetFields], args: DcdcArgs, dcdc: DcDcLoadParams, gd: GateDrive,
                               name, price_qty: int = 100):
    assert dss, "No parts to generate"
    print('generating power loss estimates for ', len(dss), 'parts')

    from dslib.prices import PriceLookup
    price_lookup = PriceLookup(qty=price_qty)

    result_rows = []  # csv
    unranked_rows = []

    print(set(ds.part.mpn for ds in dss))
    print('computing power loss for %s parts...' % len(dss))

    parts_loss = []
    parts = []

    for ds in dss:
        fet_specs = get_fet_specs(ds, args.gateDrive)
        if fet_specs is None:
            continue

        parts.append(Part(specs=fet_specs, discovered=ds.part))

        if not dcdc.Id_in_range(fet_specs.Id,
                                IDP_ID_RATIO if args.controlFet.stagedSwitching else args.controlFet.maxParallel):
            continue

        try:
            loss_spec = dcdc_buck_hs(dcdc, fet_specs,
                                     gd=gd,  # Lcsi=3e-9, ls_Qoss=200e-9,  # TO220: ~4, SMD~2
                                     isGaN=ds.part.specs.isGaN
                                     )
        except GateLoopInfeasible as e:
            # No gate-loop solution at this drive -> no switching-loss number exists for
            # this part. Drop it from the ranking rather than aborting the run over one
            # datasheet (it used to raise AssertionError straight out of main), and rather
            # than falling back to gd.fallback_V_pl, which would rank the part on an
            # invented plateau voltage precisely where we know the parsed one is unusable.
            unranked_rows.append(dict(
                mpn=ds.part.mfr[:3] + ' ' + ds.part.mpn,
                housing=ds.part.package,
                Vds_max=ds.get_max_or_min_or_typ('Vds', False),
                Id=fet_specs.Id,
                Vpl=fet_specs.V_pl,
                Vgs=gate_drive_vgs(ds, gd),
                reason=e.msg,
                errors=', '.join(ds.all_errors()),
            ))
            ds.errors.append('gate loop: ' + e.msg)
            continue

        parts_loss.append((ds, fet_specs, loss_spec))

        ploss = loss_spec.__dict__.copy()
        del ploss['P_dt'], ploss['P_rr']
        ploss.pop('_cond', None)

        # Single reader, returns mΩ. This replaces `Rds_on` -> `Rds_on_10v` fallback plus
        # `if rds_on_max < 0.1: *= 1000`, a magnitude GUESS that was the undocumented
        # Ω->mΩ conversion for the Rds_on_10v branch. It was anti-monotone: parts with
        # Rds_on_10v >= 100 mΩ never met the <0.1 test and stayed 1000x low.
        #
        # SCOPE, corrected: this local feeds ONLY the CSV's Rds_max column below. It does
        # NOT affect the ranking. fet_specs and loss_spec are both computed further up, from
        # get_mosfet_specs(), and P_tot -- the sort key -- comes from those. So the ranking
        # fix lives in get_mosfet_specs, not here; an earlier version of this comment
        # claimed the guess produced ~0 P_on and sorted parts to the top, which overstated
        # these two assignments. Measured: 1475/6040 records move in Rds_max, mostly the
        # intentional Rds_on_10v-first precedence (commonly 0.6-0.8x, because a vendor
        # max-at-10V differs from a parsed table max at 4.5/6/8V), plus 10 corrupt
        # cross-dimension records that correctly become NaN.
        #
        # Precedence also now matches dslib/field.py (Rds_on_10v first), which previously
        # disagreed with this file.
        rds_on_max = ds.select_rds_on_milliohm(stat='max')

        pr = price_lookup.get(ds.part.mfr, ds.part.mpn)
        stocks = price_lookup.stocks(ds.part.mfr, ds.part.mpn)

        for i in range(1, args.controlFet.maxParallel + 1):
            ls = loss_spec.parallel(i)
            result_rows.append(dict(
                mpn=ds.part.mfr[:3] + ' ' + (ds.part.mpn if i == 1 else f'{i}p {ds.part.mpn}'),
                housing=ds.part.package,

                Vds_max=ds.get_max_or_min_or_typ('Vds', False),
                Rds_max=rds_on_max / i,
                Id=fet_specs.Id * i,
                Qsw=fet_specs and (fet_specs.Qsw * 1e9),
                errors=', '.join(ds.all_errors()),

                # unit price at the fixed price_qty basis x device count (NOT the ladder
                # re-read at qty*i) so rows stay comparable across parallel counts.
                # None -> empty CSV cell; 0 is never a no-price fallback.
                price_usd=pr.price * i if pr else None,
                price_src=f'{pr.distributor}@{pr.qty}' if pr else '',
                price_date=pr.fetched_at.strftime('%Y-%m-%d') if pr else '',
                # informational (never gates a price); empty = no fresh stock report
                stock_dk=stocks.get('digikey'),
                stock_lcsc=stocks.get('lcsc'),

                date=ds.date_from_text.strftime('%Y-%m') if ds.date_from_text else '',
                dateC=ds.date_from_meta.strftime('%Y-%m') if ds.date_from_meta else '',

                # TODO tr,tf

                P_cl=ls.P_cl,
                P_sw=ls.P_sw,
                P_gd=ls.P_gd,
                P_coss=ls.P_coss,
                P_coss_scope=ls.get_cond('P_coss').get('accounting_scope'),
                # curve_model_state, not model_state: the latter is the TRANSITION label
                # ('hard-switch-default' for every production row, unavailable included)
                # while curve_model_state is what discriminates datasheet-curve vs
                # scalar-guess vs unavailable — the distinction this column exists for.
                P_coss_state=ls.get_cond('P_coss').get('curve_model_state'),
                P_coss_evidence=ls.get_cond('P_coss').get('evidence_quality'),
                P_coss_validation=ls.get_cond('P_coss').get('validation_status'),
                P_coss_audit=coss_audit_json(ls.get_cond('P_coss')),
                P_tot=ls.buck_hs(),
            ))

            if math.isnan(ls.buck_hs()):
                break

    dslib.store.parts_db.add(parts, overwrite=True)

    if args.controlFet.stagedSwitching:
        # staged switching. one switcher device and one or more parallel conductors
        # the switcher is fast, low Qsw, higher Rds(on), Id(pulsed) sufficiently high
        # the conductor is slower, low Rds(on). needs a separate gate drive signal during turn-off

        # rank best switchers and conductors. NaN-safe by construction: an
        # unavailable/FAILed-Coss part carries P_coss=NaN by contract, and a NaN sort
        # key makes sorted() order undefined — a NaN part could land first, best_psw
        # went NaN, and the 6x prune silently died (NaN comparisons are always False).
        # Refused parts get an unranked_rows entry instead of vanishing.
        def _staged_key(gate, p):
            return p if gate > 0 and math.isfinite(p) else 9e9

        low_sw = sorted(parts_loss, key=lambda pml: _staged_key(
            pml[2].P_sw, pml[2].P_sw + pml[2].P_coss))[:5000]
        low_cl = sorted(parts_loss, key=lambda pml: _staged_key(
            pml[2].P_cl, pml[2].P_cl + pml[2].P_coss))[:5000]

        low_cl_ranked = []
        for ds2, fet_specs2, ls2 in low_cl:
            if math.isfinite(ls2.P_cl + ls2.P_gd + ls2.P_coss):
                low_cl_ranked.append((ds2, fet_specs2, ls2))
            else:
                unranked_rows.append(dict(
                    mpn=ds2.part.mfr[:3] + ' ' + ds2.part.mpn,
                    housing=ds2.part.package,
                    Vds_max=ds2.get_max_or_min_or_typ('Vds', False),
                    Id=fet_specs2.Id,
                    reason='staged conductor: %s NaN' % '+'.join(
                        n for n, v in (('P_cl', ls2.P_cl), ('P_gd', ls2.P_gd),
                                       ('P_coss', ls2.P_coss)) if math.isnan(v)),
                    errors=', '.join(ds2.all_errors()),
                ))
        low_cl = low_cl_ranked

        sc_best = {}
        best = 9e9
        best_psw = min((l.P_sw + l.P_gd + l.P_coss for _, _, l in low_sw
                        if math.isfinite(l.P_sw + l.P_gd + l.P_coss)),
                       default=math.nan)

        for ds, fet_specs, ls in low_sw:
            p_sw = ls.P_sw + ls.P_gd + ls.P_coss
            if not math.isfinite(p_sw):
                unranked_rows.append(dict(
                    mpn=ds.part.mfr[:3] + ' ' + ds.part.mpn,
                    housing=ds.part.package,
                    Vds_max=ds.get_max_or_min_or_typ('Vds', False),
                    Id=fet_specs.Id,
                    reason='staged switcher: %s NaN' % '+'.join(
                        n for n, v in (('P_sw', ls.P_sw), ('P_gd', ls.P_gd),
                                       ('P_coss', ls.P_coss)) if math.isnan(v)),
                    errors=', '.join(ds.all_errors()),
                ))
                continue
            if p_sw > best_psw * 6:
                continue

            # here we need the pulsed drain current, which we assume is 4x higher than Id_DC
            # always verify datasheet 'Maximum Safe Operating Area' diagram
            idp = ds.get_max_or_min_or_typ('Idp')
            if math.isnan(idp):
                if not dcdc.Id_in_range(fet_specs.Id, IDP_ID_RATIO):
                    continue
            else:
                if idp < dcdc.Io_max * 1.2:
                    continue

            for ds2, fet_specs2, ls2 in low_cl:
                if not dcdc.Id_in_range(fet_specs2.Id, args.controlFet.maxParallel):
                    continue

                for i in range(1, args.controlFet.maxParallel + 1):
                    ls3 = ls2.parallel(i)

                    p = p_sw + ls3.P_cl + ls3.P_gd + ls3.P_coss

                    k = (ds.part.mfr, ds.part.mpn)
                    if p < sc_best.get(k, 9e9):
                        sc_best[k] = p

                    if p < best:
                        best = p
                    if p < best * 2.0 and p < sc_best[k] * 1.5 and p < ls.parallel(2).buck_hs() and p < ls3.parallel(
                            2).buck_hs():

                        #rds_on_max = ds2.get_max('Rds_on_10v', False)
                        #if math.isnan(rds_on_max):
                        # rds_on_max = ds2.get_max('Rds_on', False)

                        # a staged row names TWO devices: sum only when BOTH are priced,
                        # a one-sided sum would silently understate the pair
                        pr1 = price_lookup.get(ds.part.mfr, ds.part.mpn)
                        pr2 = price_lookup.get(ds2.part.mfr, ds2.part.mpn)
                        pair_priced = pr1 is not None and pr2 is not None

                        result_rows.append(dict(
                            mpn=f'{ds.part.mpn} || {str(i) + "p " if i > 1 else ""}{ds2.part.mpn}',
                            housing=ds.part.package + ' & ' + ds2.part.package,

                            Vds_max=f"{fet_specs.Vds}, {fet_specs2.Vds}",
                            Rds_max=fet_specs2.Rds_on * 1000 / i,
                            Id=idp if not math.isnan(idp) else fet_specs.Id,  # TODO min ?
                            Qsw=fet_specs and (fet_specs.Qsw * 1e9),

                            price_usd=pr1.price + pr2.price * i if pair_priced else None,
                            price_src=f'{pr1.distributor}+{pr2.distributor}@{pr1.qty}' if pair_priced else '',
                            price_date=min(pr1.fetched_at, pr2.fetched_at).strftime('%Y-%m-%d') if pair_priced else '',
                            # a staged row names TWO devices: one stock number would
                            # be ambiguous, so the columns stay empty here
                            stock_dk=None,
                            stock_lcsc=None,
                            # A staged-switching row describes TWO devices, and its Rds_max
                            # comes from ds2 (above), so reporting only ds's errors drops a
                            # violation on the very part whose resistance this row states.
                            # Attributed by mpn because the row names both.
                            errors=', '.join(
                                ['%s: %s' % (ds.part.mpn, e) for e in ds.all_errors()] +
                                ['%s: %s' % (ds2.part.mpn, e) for e in ds2.all_errors()]),

                            date='',  # ds.date_from_text.strftime('%Y-%m') if ds.date_from_text else '',
                            dateC='',  # ds.date_from_meta.strftime('%Y-%m') if ds.date_from_meta else '',

                            P_cl=ls3.P_cl,
                            P_sw=ls.P_sw,
                            P_gd=ls.P_gd + ls3.P_gd,
                            P_coss=ls.P_coss + ls3.P_coss,
                            P_coss_scope='%s + %s' % (
                                ls.get_cond('P_coss').get('accounting_scope'),
                                ls3.get_cond('P_coss').get('accounting_scope')),
                            P_coss_state='%s + %s' % (
                                ls.get_cond('P_coss').get('curve_model_state'),
                                ls3.get_cond('P_coss').get('curve_model_state')),
                            P_coss_evidence='%s + %s' % (
                                ls.get_cond('P_coss').get('evidence_quality'),
                                ls3.get_cond('P_coss').get('evidence_quality')),
                            P_coss_validation='%s + %s' % (
                                ls.get_cond('P_coss').get('validation_status'),
                                ls3.get_cond('P_coss').get('validation_status')),
                            P_coss_audit=coss_audit_json(dict(
                                switcher=ls.get_cond('P_coss'),
                                conductor=ls3.get_cond('P_coss'))),
                            P_tot=p,
                        ))

                        print('framed switching %s + %s (%.2f W)' % (ds.part.mpn, ds2.part.mpn, p))

    df = pd.DataFrame(result_rows)

    if len(dss) >= 1:
        os.path.exists('out') or os.makedirs('out', exist_ok=True)
        dat = f'{datetime.datetime.now():%Y-%m-%d}'
        # out_fn = f'out/{dcdc.fn_str("buck")}v2-{dat}-inp{len(parts)}'
        # if args.substrate:
        #    out_fn += f'-{args.substrate}'
        # if args.q:
        #    out_fn += f'-q{args.q}'
        out_fn = f'out/{name}/{dat}-{dcdc.fn_str("buck")}-HS-inp{len(dss)}'
        out_fn += '.csv'
        write_csv(df, out_fn, power_value_digits=3, sort_by=['P_tot'])
        print('\n>>>', out_fn)
        print('>>>', price_lookup.stats())

        # Same contract as the LS path: a ranking shorter than its input list is a result,
        # not a detail, so the excluded parts get a sibling CSV with the reason and a
        # console summary. "Not ranked" must never have to be inferred from an absence.
        if unranked_rows:
            un_fn = out_fn.replace('-HS-inp', '-HS-unranked-inp')
            write_csv(pd.DataFrame(unranked_rows), un_fn, sort_by=['mpn'])
            print('>>> %d parts EXCLUDED from the HS ranking (per-row reason: gate-loop '
                  'infeasible, or a NaN loss component in the staged pass):'
                  % len(unranked_rows))
            for r in unranked_rows[:10]:
                print('      %-28s %s' % (r['mpn'], r['reason']))
            if len(unranked_rows) > 10:
                print('      ... and %d more, see the CSV' % (len(unranked_rows) - 10))
            print('>>>', un_fn)
    else:
        print('skip csv write because only few parts')

    show_summary(dss)

    # show parts missing Qsw, no switching loss estimation is possible:
    no_qsw = [pml[0] for pml in parts_loss if math.isnan(pml[1].Qsw)]
    print('Parts missing Qsw:', len(no_qsw))
    for p in no_qsw:
        print(p.part.mfr, p.part.mpn)

    # report
    # - total datasheets with at least 1 field
    # - total fields with at least one value
    # - total values
    # - total power values


def generate_LS_power_loss_csv(dss: List[DatasheetFields], args: DcdcArgs, dcdc: DcDcLoadParams, gd: GateDrive, name,
                               price_qty: int = 100):
    assert dss, "No parts to generate"

    from dslib.prices import PriceLookup
    price_lookup = PriceLookup(qty=price_qty)

    result_rows = []
    unranked_rows = []

    for ds in dss:
        fet_specs = get_fet_specs(ds, args.gateDrive)
        if fet_specs is None:
            continue

        if not dcdc.Id_in_range(fet_specs.Id, args.syncFet.maxParallel):
            continue

        if fet_specs.QgdQgsRatio > 1:
            # mosfet might self turn-on
            continue

        # Self-pairing: this CSV ranks LS candidates with
        # no named HS partner, so the commutation di/dt is the one the part's own turn-on
        # would impose. A design that knows its actual HS should pass that part's di/dt.
        qrr_op = bool(args.syncFet.qrrOperatingPoint)
        qrr_didt = (ls_commutation_didt(dcdc, fet_specs, gd, isGaN=ds.part.specs.isGaN)
                    if qrr_op else None)
        loss_spec = dcdc_buck_ls(dcdc, fet_specs, gd=gd, isGaN=ds.part.specs.isGaN,
                                 qrr_didt=qrr_didt,
                                 # syncFet.reverseRecoveryFactor was parsed from every
                                 # project YAML and read by nothing since it was added.
                                 # Every shipped config sets 1, so wiring it changes no
                                 # existing result — but a config that sets 0.5 now gets
                                 # the half it asked for instead of being ignored.
                                 qrr_factor=args.syncFet.reverseRecoveryFactor)

        # When the ranking is supposed to be AT the operating point, a part whose charge
        # could not be evaluated there has no place in it. Ranked alongside the others it
        # keeps the vendor's gentle test-point Qrr while every fitted part pays the real
        # (p50 ~6x) commutation charge, so it is not merely uncertain — it is
        # systematically flattered. Measured before this exclusion: 8 of the top 10 LS
        # parts at the fugu3 point were exactly these, i.e. missing data read as a GOOD
        # part, which is the opposite of what a ranking should do with it.
        #
        # Keyed on the CONFIG FLAG, not on `qrr_didt is not None`. ls_commutation_didt
        # also returns None when the flag IS on but the HS gate charges are missing, and
        # dcdc_buck_ls then labels the row `datasheet-flat` — identical to a flag-off row.
        # Using the di/dt as the proxy let 75 such parts through unlabelled, 9 of them
        # into the ranking, on the un-rescaled vendor charge.
        qrr_src = loss_spec.get_cond('P_rr')['Qrr_src']
        if not qrr_rankable_at_operating_point(qrr_op, qrr_src):
            # Dropped from the RANKING, not from the output: they go to a sibling CSV with
            # the reason, so "not ranked" never has to be inferred from a part's absence.
            reason = loss_spec.get_cond('P_rr').get('qrr_nofit')
            if not reason:
                # No LM failure to quote — this is the no-operating-point case, whose
                # cause lives upstream of dcdc_buck_ls and would otherwise read as an
                # unexplained exclusion.
                reason = ('no commutation di/dt: the HS gate charges (Qgs2/Qg_th/Vpl) '
                          'needed for the current-rise time are missing'
                          if qrr_didt is None else 'not evaluated at the operating '
                          'point (Qrr_src=%s)' % qrr_src)
            qrr_ds = fet_specs.Qrr
            trr_ds = fet_specs.trr
            unranked_rows.append(dict(
                mpn=ds.part.mfr[:3] + ' ' + ds.part.mpn,
                housing=ds.part.package,
                Vds_max=ds.get_max_or_min_or_typ('Vds', False),
                Id=fet_specs.Id,
                # NaN, not None, is how MosfetSpecs stores "absent" for Qrr — testing
                # `is not None` never fires and would put a NaN in the cell either way.
                Qrr=(qrr_ds * 1e9) if isnum(qrr_ds) else None,
                trr=(trr_ds * 1e9) if isnum(trr_ds) else None,
                didt_rr=None if qrr_didt is None else round_to_n(qrr_didt / 1e6, 3),
                Qrr_src=qrr_src,
                reason=reason,
                errors=', '.join(ds.all_errors()),
            ))
            continue

        # Single reader, returns mΩ. This replaces `Rds_on` -> `Rds_on_10v` fallback plus
        # `if rds_on_max < 0.1: *= 1000`, a magnitude GUESS that was the undocumented
        # Ω->mΩ conversion for the Rds_on_10v branch. It was anti-monotone: parts with
        # Rds_on_10v >= 100 mΩ never met the <0.1 test and stayed 1000x low.
        #
        # SCOPE, corrected: this local feeds ONLY the CSV's Rds_max column below. It does
        # NOT affect the ranking. fet_specs and loss_spec are both computed further up, from
        # get_mosfet_specs(), and P_tot -- the sort key -- comes from those. So the ranking
        # fix lives in get_mosfet_specs, not here; an earlier version of this comment
        # claimed the guess produced ~0 P_on and sorted parts to the top, which overstated
        # these two assignments. Measured: 1475/6040 records move in Rds_max, mostly the
        # intentional Rds_on_10v-first precedence (commonly 0.6-0.8x, because a vendor
        # max-at-10V differs from a parsed table max at 4.5/6/8V), plus 10 corrupt
        # cross-dimension records that correctly become NaN.
        #
        # Precedence also now matches dslib/field.py (Rds_on_10v first), which previously
        # disagreed with this file.
        rds_on_max = ds.select_rds_on_milliohm(stat='max')

        pr = price_lookup.get(ds.part.mfr, ds.part.mpn)
        stocks = price_lookup.stocks(ds.part.mfr, ds.part.mpn)

        for i in range(1, args.syncFet.maxParallel + 1):
            ls = loss_spec.parallel(i)
            result_rows.append(dict(
                mpn=ds.part.mfr[:3] + ' ' + (ds.part.mpn if i == 1 else f'{i}p {ds.part.mpn}'),
                housing=ds.part.package,

                Vds_max=ds.get_max_or_min_or_typ('Vds', False),
                Rds_max=rds_on_max / i,
                Id=fet_specs.Id * i,

                # fixed price_qty basis x device count; None -> empty cell, never 0
                price_usd=pr.price * i if pr else None,
                price_src=f'{pr.distributor}@{pr.qty}' if pr else '',
                price_date=pr.fetched_at.strftime('%Y-%m-%d') if pr else '',
                # informational (never gates a price); empty = no fresh stock report
                stock_dk=stocks.get('digikey'),
                stock_lcsc=stocks.get('lcsc'),

                # sync fet specific:
                Qrr=fet_specs and (fet_specs.Qrr * 1e9) * i,
                # The charge P_rr was actually booked on, and where it came from. These
                # two travel together on purpose: a Qrr_eff column alone cannot tell a
                # reader whether a row is an operating-point prediction or the flat
                # datasheet number that survived a failed fit.
                Qrr_eff=round_to_n(loss_spec.get_cond('P_rr')['Qrr'] * 1e9, 4) * i,
                Qrr_src=loss_spec.get_cond('P_rr')['Qrr_src'],
                Qrr_q0_nC=(loss_spec.get_cond('P_rr').get('Qrr_q0') * 1e9 * i
                           if loss_spec.get_cond('P_rr').get('Qrr_q0') is not None
                           else None),
                Qrr_q0_basis=loss_spec.get_cond('P_rr').get('Qrr_q0_basis'),
                Qrr_double_booking=loss_spec.get_cond('P_rr').get(
                    'Qrr_double_booking'),
                Qrr_double_booking_evidence=loss_spec.get_cond('P_rr').get(
                    'Qrr_double_booking_evidence'),
                Qrr_qoss_vr_nC=(
                    loss_spec.get_cond('P_rr').get('Qrr_qoss_vr') * 1e9 * i
                    if loss_spec.get_cond('P_rr').get('Qrr_qoss_vr') is not None
                    else None),
                Qrr_qoss_model_state=loss_spec.get_cond('P_rr').get(
                    'Qrr_qoss_model_state'),
                Qrr_qoss_evidence=loss_spec.get_cond('P_rr').get(
                    'Qrr_qoss_evidence'),
                Qrr_qoss_provenance=loss_spec.get_cond('P_rr').get(
                    'Qrr_qoss_provenance'),
                Qrr_qoss_extrapolation_flags=loss_spec.get_cond('P_rr').get(
                    'Qrr_qoss_extrapolation_flags'),
                didt_rr=None if qrr_didt is None else round_to_n(qrr_didt / 1e6, 3),
                Vsd=fet_specs and (fet_specs.Vsd),
                QgdQgs=fet_specs and fet_specs.QgdQgsRatio,

                errors=', '.join(ds.all_errors()),

                date=ds.date_from_text.strftime('%Y-%m') if ds.date_from_text else '',
                dateC=ds.date_from_meta.strftime('%Y-%m') if ds.date_from_meta else '',

                P_cl=ls.P_cl,
                P_rr=ls.P_rr,
                P_gd=ls.P_gd,
                P_coss=ls.P_coss,
                P_coss_scope=ls.get_cond('P_coss').get('accounting_scope'),
                P_coss_state=ls.get_cond('P_coss').get('curve_model_state'),
                P_coss_evidence=ls.get_cond('P_coss').get('evidence_quality'),
                P_coss_validation=ls.get_cond('P_coss').get('validation_status'),
                P_coss_audit=coss_audit_json(ls.get_cond('P_coss')),
                P_tot=ls.buck_ls(),
            ))

            if math.isnan(ls.buck_ls()):
                break

    df = pd.DataFrame(result_rows)

    if len(dss) >= 1:
        os.path.exists('out') or os.makedirs('out', exist_ok=True)
        dat = f'{datetime.datetime.now():%Y-%m-%d}'
        out_fn = f'out/{name}/{dat}-{dcdc.fn_str("buck")}-LS-inp{len(dss)}'
        out_fn += '.csv'
        write_csv(df, out_fn, power_value_digits=3, sort_by=['P_tot'])
        print('\n>>>', out_fn)
        print('>>>', price_lookup.stats())

        # A shorter ranking than the input list is a result, not a detail. Report the
        # count and WHY at the same volume as the CSV path itself, so nobody reads a
        # 2800-row ranking of a 3900-part corpus as covering the corpus.
        if unranked_rows:
            un_fn = out_fn.replace('-LS-inp', '-LS-unranked-inp')
            write_csv(pd.DataFrame(unranked_rows), un_fn, sort_by=['mpn'])
            print('>>> %d parts EXCLUDED from the ranking: no reverse-recovery fit at the '
                  'operating point (syncFet.qrrOperatingPoint is on). Top reasons:'
                  % len(unranked_rows))
            from collections import Counter
            reasons = Counter(r['reason'].split(' --')[0][:64] for r in unranked_rows)
            for why, n in reasons.most_common(5):
                print('      %5d  %s' % (n, why))
            print('>>>', un_fn)
    else:
        print('skip csv write because only few parts')

    # show_summary(dss)


def show_summary(dss: List[DatasheetFields]):
    print('total num parts :    ', len(dss))
    dss = [d for d in dss if d != (None, None)]
    print('total num parsed DS: ', len(dss))
    print('total num fields:    ', sum(len(ds) for ds in dss))
    print('total num values:    ', sum(len(f) for ds in dss for f in ds.fields_lists.values()))


if __name__ == '__main__':
    try:
        main_yaml()
    except KeyboardInterrupt:
        print('interrupted')
