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
from dclib.powerloss import dcdc_buck_hs, dcdc_buck_ls
from discover_parts import discover_mosfets
from dslib import write_csv, dotdict
from dslib.cache import disk_cache
from dslib.discovery import DiscoveredPart, Substrate
from dslib.fetch import fetch_datasheet
from dslib.field import Field, DatasheetFields
from dslib.mosfet import GateDrive
from dslib.pdf.fonts import fontforge_bin
from dslib.pdf.parse import parse_datasheet, subsctract_needed_symbols, NoTabularData, TooManyPages
from dslib.pdf.tabular import tabula_is_running
from dslib.spec_models import DcDcLoadParams
from dslib.store import Part

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
    parser.add_argument('--config-file')

    parser.add_argument('-j', default=8)  # parallel jobs
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--no-ocr', action='store_true')
    parser.add_argument('--no-download', action='store_true')

    cargs = parser.parse_args(sys.argv[1:])

    import yaml
    with open(cargs.config_file) as fh:
        conf = yaml.safe_load(fh)

    args = RunArgs(topology=conf['topology'],
                   substrates=conf['substrates'], packages=conf['packages'],
                   vdsRange=conf['vdsRange'],
                   dcdc=DcdcArgs(
                       controlFet=ControlFetArgs(**conf['controlFet']),
                       gateDrive=GateDrive(rg_total=float(conf['gateDrive']['rgTotal']),
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
                   ])
    run(args, cargs, os.path.basename(cargs.config_file).split('.yaml')[0])


def main():
    parser = argparse.ArgumentParser(description='')

    # parser.add_argument('command', choices=(
    #    'discover', 'download', 'parse', 'power'), default='power')
    parser.add_argument('--dcdc-file')
    parser.add_argument('-q')
    parser.add_argument('-substrate')
    parser.add_argument('--swcd', action='store_true')

    parser.add_argument('--rg-total', default=4.7)  # total gate resistance
    parser.add_argument('--vpl-fallback', default=4.5)

    parser.add_argument('-j', default=8)  # parallel jobs
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--no-ocr', action='store_true')
    parser.add_argument('--no-download', action='store_true')

    parser.add_argument('--no-pre-select',
                        action='store_true')  # also read datasheets of parts that are out of spec, takes much longer
    parser.add_argument('--clean', action='store_true')
    args = parser.parse_args(sys.argv[1:])

    if args.clean:
        raise NotImplementedError()
        # git clean -xn

    if args.no_cache:
        from dslib.cache import disk_cache_disable
        disk_cache_disable(True)

    if not args.dcdc_file:
        # set DC-DC operating point:
        dcdc = DcDcLoadParams.default()
        print('Using default DC-DC:', dcdc)
    else:
        raise NotImplemented()


class ControlFetArgs():
    def __init__(self, maxParallel, stagedSwitching):
        self.maxParallel = maxParallel
        self.stagedSwitching = stagedSwitching


class SyncFetArgs():
    def __init__(self, maxParallel=1, reverseRecoveryFactor: float = 1.0):
        assert isinstance(maxParallel, int) and maxParallel >= 1 and maxParallel <= 20
        self.maxParallel = maxParallel
        assert reverseRecoveryFactor >= 0 and reverseRecoveryFactor <= 1
        self.reverseRecoveryFactor = reverseRecoveryFactor


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
                 ):
        assert topology == 'buck'
        self.topology = topology

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


def run(args: RunArgs, cargs, name):
    # discover available MOSFETS:
    parts = asyncio.run(discover_mosfets(no_obsolete=not args.includeObsolete))
    print('Discovered', len(parts), 'parts from manufacturers:', ', '.join(sorted(set(p.mfr for p in parts))))


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
    print(set(p.mpn for p in parts))
    print('Vds_max:   ',
          sorted(set(int(p.specs.Vds_max) for p in parts if p.specs.Vds_max and not math.isnan(p.specs.Vds_max))))
    print('Substrates:', (set(p.specs.__dict__.get('substrate') for p in parts)))

    # parts = parts[:100]

    from wakepy import keep
    with keep.running():
        # do all the magic: download datasheets, read them and compute power loss:
        dss = read_parts_datasheets(parts, dotdict(cargs.__dict__))

        dss = [ds for ds in dss if dcdc.vds_in_range(ds.get_max_or_min_or_typ('Vds'))]

        generate_HS_power_loss_csv(dss,
                                   args=args.dcdc,
                                   dcdc=dcdc,
                                   gd=args.dcdc.gateDrive,
                                   name=name
                                   )

        generate_LS_power_loss_csv(dss,
                                   args=args.dcdc,
                                   dcdc=dcdc,
                                   gd=args.dcdc.gateDrive,
                                   name=name
                                   )


def compile_part_datasheet(part: DiscoveredPart, need_symbols, no_cache, no_ocr, no_download=False):
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
    if ds or ff:
        need_symbols = subsctract_needed_symbols(need_symbols, set(ds.keys()) | set(ff.keys()), copy=True)

    if not no_cache:

        lp = dslib.store.parts_db.load_obj(part)
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
            dsp = parse_datasheet(ds_path, mfr=mfr, mpn=mpn, need_symbols=need_symbols, no_ocr=no_ocr)
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


def get_fet_specs(ds: DatasheetFields):
    part = ds.part
    mfr = part.mfr
    mpn = part.mpn
    # parse specification for DC-DC loss model
    try:
        fet_specs = ds.get_mosfet_specs()
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


def compute_part_powerloss(ds: DatasheetFields, dcdc: DcDcLoadParams, args) -> Tuple[Optional[Part], Dict[str, any]]:
    if isinstance(ds, tuple):
        raise ValueError(ds)
    else:
        part = ds.part

    fet_specs = get_fet_specs(ds)

    if fet_specs is None:
        # raise
        return None, dict(mfr=part.mfr,
                          mpn=part.mpn,
                          housing=part.package,
                          errors=', '.join(ds.errors))

    # compute power loss
    if 1:
        gd = GateDrive(float(args.rg_total), Von=10, Voff=0, fallback_V_pl=float(args.vpl_fallback))
        loss_spec = dcdc_buck_hs(dcdc, fet_specs,
                                 gd=gd,
                                 # Lcsi=3e-9, ls_Qoss=200e-9,  # TO220: ~4, SMD~2
                                 use_datasheet_timings=False
                                 )
        ploss = loss_spec.__dict__.copy()
        del ploss['P_dt']
        ploss.pop('_cond', None)
        ploss['P_hs'] = loss_spec.buck_hs()
        ploss['P_2hs'] = loss_spec.parallel(2).buck_hs()
        ploss['tr'] = round(loss_spec.get_cond('P_sw')['tr'] * 1e9, 1)  # possibly nan!
        ploss['tf'] = round(loss_spec.get_cond('P_sw')['tf'] * 1e9, 1)
        # ploss['P_coss'] = loss_spec.P_coss

        loss_spec = dcdc_buck_ls(dcdc, fet_specs, gd=gd)
        ploss['PcossLS'] = loss_spec.P_coss
        ploss['Prr'] = loss_spec.P_rr
        ploss['PonLS'] = loss_spec.P_cl
        ploss['PdtLS'] = loss_spec.P_dt
        ploss['P_LS'] = loss_spec.buck_ls()
        ploss['P_2ls'] = loss_spec.parallel(2).buck_ls()

    # except Exception as e:
    #    print(mfr, mpn, 'dcdc_buck_hs', e)
    #    ploss = {}

    row = dict(
        **ds.get_row(),

        Vth=part.specs.Vgs_th_max,
        Vpl=fet_specs and fet_specs.V_pl,

        FoMrect=fet_specs.FoM,
        FoMrr=fet_specs.FoMqrr,
        FoMsw=fet_specs.FoMqsw,
        FoMoss=fet_specs.FoMcoss,
        QgdQgs=fet_specs.QgdQgsRatio,
        QgdQgs2=fet_specs.Qgd / fet_specs.Qgs2,

        **ploss,
    )

    return Part(specs=fet_specs, discovered=part), row


@disk_cache(ttl='999d', salt=('13', excludes))
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
        jobs = {(p.mfr, p.mpn): (compile_part_datasheet, p, need_symbols, args.no_cache, args.no_ocr, args.no_download)
                for p in
                parts_shuffled}
        results = run_parallel(jobs, int(args.j), 'multiprocessing', verbose=0)
        dss: List[DatasheetFields] = list(results.values())

    dss = [d for d in dss if d != (None, None)]

    for ds in dss:
        ds.add_multiple(ds.part.specs.fields())

    return dss


def generate_parts_power_loss_csv(parts: List[DiscoveredPart], dcdc: DcDcLoadParams, args):
    assert parts, "No parts to generate"

    print('generating power loss estimates for ', len(parts), 'parts')

    result_rows = []  # csv
    result_parts: List[Part] = []  # db storage
    # all_mpn = set()

    dss = read_parts_datasheets(parts, args)

    if len(dss) == 1:
        # print(repr(dss[0]))
        dss[0].print(show_cond=True)
        print('mosfet specs:')
        print(dss[0].get_mosfet_specs())

        # with open('fet-datasheets.pkl', 'wb') as f:
        #    pickle.dump(dss, f)

    print(set(ds.part.mpn for ds in dss))
    print('computing power loss for %s parts...' % len(dss))
    for ds in dss:
        if isinstance(ds, tuple) and ds == (None, None):
            continue
        if not dcdc.vds_in_range(ds.get_max_or_min_or_typ('Vds')):
            print(ds.part, 'vds not in range', ds.get_typ_or_max_or_min('Vds'))
            continue
        part, row = compute_part_powerloss(ds, dcdc, args=args)
        if part is not None:
            result_parts.append(part)
        if row is not None:
            result_rows.append(row)

    # print('no P_sw')
    # for row in result_rows:
    #    if math.isnan(row.get('P_sw') or math.nan):
    ##        #no_psw.append((mfr, mpn))
    #        #print(os.path.join('datasheets', row['mfr'], row['mpn'] + '.pdf'))

    df = pd.DataFrame(result_rows)

    if len(dss) >= 1:
        os.path.exists('out') or os.makedirs('out', exist_ok=True)
        dat = f'{datetime.datetime.now():%Y-%m-%d}'
        out_fn = f'out/{dcdc.fn_str("buck")}-{dat}-inp{len(parts)}.csv'
        write_csv(df, out_fn)
        print('written', out_fn)
    else:
        print('skip csv write because only few parts')

    dslib.store.parts_db.add(result_parts, overwrite=True)
    dslib.store.datasheets_db.add(dss, overwrite=True)

    print('')
    print('')
    print('stored', len(result_parts), 'parts')
    show_summary(dss)

    # report
    # - total datasheets with at least 1 field
    # - total fields with at least one value
    # - total values
    # - total power values

    return result_parts


def generate_HS_power_loss_csv(dss: List[DatasheetFields], args: DcdcArgs, dcdc: DcDcLoadParams, gd: GateDrive,
                               name):
    assert dss, "No parts to generate"
    print('generating power loss estimates for ', len(dss), 'parts')

    result_rows = []  # csv

    print(set(ds.part.mpn for ds in dss))
    print('computing power loss for %s parts...' % len(dss))

    parts_loss = []

    for ds in dss:
        fet_specs = get_fet_specs(ds)
        if fet_specs is None:
            continue

        if not dcdc.Id_in_range(fet_specs.Id,
                                IDP_ID_RATIO if args.controlFet.stagedSwitching else args.controlFet.maxParallel):
            continue

        loss_spec = dcdc_buck_hs(dcdc, fet_specs,
                                 gd=gd,  # Lcsi=3e-9, ls_Qoss=200e-9,  # TO220: ~4, SMD~2
                                 isGaN=ds.part.specs.isGaN
                                 )

        parts_loss.append((ds, fet_specs, loss_spec))

        ploss = loss_spec.__dict__.copy()
        del ploss['P_dt'], ploss['P_rr']
        ploss.pop('_cond', None)

        rds_on_max = ds.get_max('Rds_on', False)
        if math.isnan(rds_on_max):
            rds_on_max = ds.get_max('Rds_on_10v', False)
        if rds_on_max < 0.1:
            rds_on_max *= 1000

        for i in range(1, args.controlFet.maxParallel + 1):
            ls = loss_spec.parallel(i)
            result_rows.append(dict(
                mpn=ds.part.mfr[:3] + ' ' + (ds.part.mpn if i == 1 else f'{i}p {ds.part.mpn}'),
                housing=ds.part.package,

                Vds_max=ds.get_max_or_min_or_typ('Vds', False),
                Rds_max=rds_on_max / i,
                Id=fet_specs.Id * i,
                Qsw=fet_specs and (fet_specs.Qsw * 1e9),
                errors=', '.join(ds.errors),

                date=ds.date_from_text.strftime('%Y-%m') if ds.date_from_text else '',
                dateC=ds.date_from_meta.strftime('%Y-%m') if ds.date_from_meta else '',

                P_cl=ls.P_cl,
                P_sw=ls.P_sw,
                P_gd=ls.P_gd,
                P_coss=ls.P_coss,
                P_tot=ls.buck_hs(),
            ))

            if math.isnan(ls.buck_hs()):
                break

    if args.controlFet.stagedSwitching:
        # staged switching. one switcher device and one or more parallel conductors
        # the switcher is fast, low Qsw, higher Rds(on), Id(pulsed) sufficiently high
        # the conductor is slower, low Rds(on). needs a separate gate drive signal during turn-off

        # rank best switchers and conductors
        low_sw = sorted(parts_loss, key=lambda pml: (pml[2].P_sw + pml[2].P_coss) if pml[2].P_sw > 0 else 9e9)[:5000]
        low_cl = sorted(parts_loss, key=lambda pml: (pml[2].P_cl + pml[2].P_coss) if pml[2].P_cl > 0 else 9e9)[:5000]

        sc_best = {}
        best = 9e9
        best_psw = low_sw[0][2].P_sw + low_sw[0][2].P_gd + low_sw[0][2].P_coss

        for ds, fet_specs, ls in low_sw:
            p_sw = ls.P_sw + ls.P_gd + ls.P_coss
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

                        result_rows.append(dict(
                            mpn=f'{ds.part.mpn} || {str(i) + "p " if i > 1 else ""}{ds2.part.mpn}',
                            housing=ds.part.package + ' & ' + ds2.part.package,

                            Vds_max=f"{fet_specs.Vds}, {fet_specs2.Vds}",
                            Rds_max=fet_specs2.Rds_on * 1000 / i,
                            Id=idp if not math.isnan(idp) else fet_specs.Id,  # TODO min ?
                            Qsw=fet_specs and (fet_specs.Qsw * 1e9),
                            errors=', '.join(ds.errors),

                            date='',  # ds.date_from_text.strftime('%Y-%m') if ds.date_from_text else '',
                            dateC='',  # ds.date_from_meta.strftime('%Y-%m') if ds.date_from_meta else '',

                            P_cl=ls3.P_cl,
                            P_sw=ls.P_sw,
                            P_gd=ls.P_gd + ls3.P_gd,
                            P_coss=ls.P_coss + ls3.P_coss,
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
        out_fn = f'out/{name}-{dat}-{dcdc.fn_str("buck")}-HS-inp{len(dss)}'
        out_fn += '.csv'
        write_csv(df, out_fn, power_value_digits=3, sort_by=['P_tot'])
        print('written', out_fn)
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


def generate_LS_power_loss_csv(dss: List[DatasheetFields], args: DcdcArgs, dcdc: DcDcLoadParams, gd: GateDrive, name):
    assert dss, "No parts to generate"

    result_rows = []

    for ds in dss:
        fet_specs = get_fet_specs(ds)
        if fet_specs is None:
            continue

        if not dcdc.Id_in_range(fet_specs.Id, args.syncFet.maxParallel):
            continue

        if fet_specs.QgdQgsRatio > 1:
            # mosfet might self turn-on
            continue

        loss_spec = dcdc_buck_ls(dcdc, fet_specs, gd=gd, isGaN=ds.part.specs.isGaN)

        rds_on_max = ds.get_max('Rds_on', False)
        if math.isnan(rds_on_max):
            rds_on_max = ds.get_max('Rds_on_10v', False)
        if rds_on_max < 0.1:
            rds_on_max *= 1000

        for i in range(1, args.syncFet.maxParallel + 1):
            ls = loss_spec.parallel(i)
            result_rows.append(dict(
                mpn=ds.part.mfr[:3] + ' ' + (ds.part.mpn if i == 1 else f'{i}p {ds.part.mpn}'),
                housing=ds.part.package,

                Vds_max=ds.get_max_or_min_or_typ('Vds', False),
                Rds_max=rds_on_max / i,
                Id=fet_specs.Id * i,
                Qsw=fet_specs and (fet_specs.Qsw * 1e9),
                errors=', '.join(ds.errors),

                date=ds.date_from_text.strftime('%Y-%m') if ds.date_from_text else '',
                dateC=ds.date_from_meta.strftime('%Y-%m') if ds.date_from_meta else '',

                P_cl=ls.P_cl,
                P_rr=ls.P_rr,
                P_gd=ls.P_gd,
                P_coss=ls.P_coss,
                P_tot=ls.buck_ls(),
            ))

            if math.isnan(ls.buck_ls()):
                break

    df = pd.DataFrame(result_rows)

    if len(dss) >= 1:
        os.path.exists('out') or os.makedirs('out', exist_ok=True)
        dat = f'{datetime.datetime.now():%Y-%m-%d}'
        out_fn = f'out/{name}-{dat}-{dcdc.fn_str("buck")}-LS-inp{len(dss)}'
        out_fn += '.csv'
        write_csv(df, out_fn, power_value_digits=3, sort_by=['P_tot'])
        print('written', out_fn)
    else:
        print('skip csv write because only few parts')

    # show_summary(dss)


def num_cores():
    try:
        # noinspection PyUnresolvedReferences
        return len(os.sched_getaffinity(0))
    except:
        # see https://stackoverflow.com/questions/1006289/how-to-find-out-the-number-of-cpus-using-python
        import multiprocessing
        return multiprocessing.cpu_count()


import contextlib
import joblib
from tqdm import tqdm


@contextlib.contextmanager
def tqdm_joblib(tqdm_object):
    """Context manager to patch joblib to report into tqdm progress bar given as argument"""

    class TqdmBatchCompletionCallback(joblib.parallel.BatchCompletionCallBack):
        def __call__(self, *args, **kwargs):
            tqdm_object.update(n=self.batch_size)
            return super().__call__(*args, **kwargs)

    old_batch_callback = joblib.parallel.BatchCompletionCallBack
    joblib.parallel.BatchCompletionCallBack = TqdmBatchCompletionCallback
    try:
        yield tqdm_object
    finally:
        joblib.parallel.BatchCompletionCallBack = old_batch_callback
        tqdm_object.close()


def run_serial(jobs):
    res = {}
    for k, fn in jobs.items():
        # print(k, '...')
        res[k] = fn() if callable(fn) else fn[0](*fn[1:])
    return res


def run_parallel(jobs, max_concurrency=256,
                 backend: Literal['threading', 'multiprocessing'] = 'multiprocessing',
                 verbose=100, **kwargs):
    if max_concurrency == 1:
        return run_serial(jobs)

    from joblib import Parallel, delayed
    with tqdm_joblib(tqdm(desc="Run Progress:", total=len(jobs))) as progress_bar:
        results = Parallel(n_jobs=min(num_cores() + 1, max_concurrency, len(jobs)), verbose=verbose, backend=backend,
                           **kwargs)(
            delayed(fn)() if callable(fn) else delayed(fn[0])(*fn[1:]) for fn in jobs.values())
    return dict(zip(jobs.keys(), results))


def show_summary(dss: List[DatasheetFields]):
    print('totel num parts :    ', len(dss))
    dss = [d for d in dss if d != (None, None)]
    print('total num parsed DS: ', len(dss))
    print('total num fields:    ', sum(len(ds) for ds in dss))
    print('total num values:    ', sum(len(f) for ds in dss for f in ds.fields_lists.values()))


if __name__ == '__main__':
    # if os.path.isfile('fet-datasheets.pkl'):
    #    with(open('fet-datasheets.pkl', 'rb')) as f:
    #        dss: List[DatasheetFields] = pickle.load(f)
    #
    #    dss = [d for d in dss if d != (None, None)]
    #    show_summary(dss)

    # exit(0)
    # parse_pdf_tests()
    # main()
    main_yaml()
