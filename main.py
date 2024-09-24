import argparse
import math
import asyncio
import math
import os.path
import pickle
import sys
import traceback
from typing import List, Dict, Literal, Tuple

import numpy as np
import pandas as pd

import dslib.manual_fields
from discover_parts import discover_mosfets
from dslib import round_to_n
from dslib.fetch import fetch_datasheet
from dslib.field import Field, DatasheetFields
from dslib.parts_discovery import DiscoveredPart
from dslib.pdf2txt.parse import parse_datasheet, is_gan, subsctract_needed_symbols
from dslib.powerloss import dcdc_buck_hs, dcdc_buck_ls
from dslib.spec_models import MosfetSpecs, DcDcSpecs
from dslib.store import Part, Mfr, Mpn


def main():
    parser = argparse.ArgumentParser(description='')

    # parser.add_argument('command', choices=(
    #    'discover', 'download', 'parse', 'power'), default='power')
    parser.add_argument('--dcdc-file')
    parser.add_argument('-q')
    parser.add_argument('-j',default=8) # parallel jobs
    args = parser.parse_args(sys.argv[1:])

    if not args.dcdc_file:
        # set DC-DC operating point:
        dcdc = DcDcSpecs(vi=62, vo=27, pin=800, f=40e3, Vgs=12, ripple_factor=0.3, tDead=500e-9)
        print('Using default DC-DC:', dcdc)
    else:
        raise NotImplemented()

    # discover available MOSFETS:
    parts = asyncio.run(discover_mosfets())
    print('Discovered', len(parts), 'parts from manufacturers:', ','.join(sorted(set(p.mfr for p in parts))))

    if args.q:
        words = list(map(lambda s: s.strip(), args.q.lower().strip(' "\'').split(' ')))

        def _match_part(p: DiscoveredPart):
            for w in words:
                if w not in p.mfr.lower() and w not in p.mpn.lower() and w not in str(p.mpn2).lower():
                    return False
            return True

        parts = list(filter(_match_part, parts))

        print('Filtered', len(parts), 'parts:', ','.join(p.mpn for p in parts[:20]), '..', args.q)

    # pre-select mosfets by voltage and current
    n_pre_select = len(parts)
    parts = [p for p in parts if (
            p.specs.Vds_max >= (dcdc.Vi * 1.1) and p.specs.Vds_max <= (dcdc.Vi * 4)
            and p.specs.ID_25 > dcdc.Io_max * 1.2)]

    print('Found       ', len(parts), 'out of', n_pre_select, 'parts are suitable for given DC-DC specs')

    # parts = parts[:100]

    # do all the magic: download datasheets, read them and compute power loss:
    parts = generate_parts_power_loss_csv(parts, dcdc=dcdc, n_jobs=int(args.j))

    # show parts missing Qsw, no switching loss estimation is possible:
    no_qsw = [p for p in parts if math.isnan(p.specs.Qsw)]
    print('Parts missing Qsw:', len(no_qsw))
    for p in no_qsw:
        print(p.discovered.get_ds_path())


def compile_part_datasheet(part: DiscoveredPart, need_symbols):
    mfr = part.mfr
    mpn = part.mpn
    ds_url = part.ds_url
    ds_path = part.get_ds_path()

    if not os.path.exists(ds_path):
        if not os.path.exists(ds_path):
            fetch_datasheet(ds_url, ds_path, mfr=mfr, mpn=mpn)

    ds = DatasheetFields(part=part)

    # place manual fields:
    man_fields = dslib.manual_fields.get_fields()
    ds.add_multiple(man_fields.get(mfr, {}).get(mpn, []))

    ff = dslib.manual_fields.fallback_specs(mfr, mpn)
    if ds or ff:
        need_symbols = subsctract_needed_symbols(need_symbols, set(ds.keys()) | set(ff.keys()), copy=True)

    # parse datasheet (tabula and pdf2txt):
    if os.path.isfile(ds_path):
        try:
            dsp = parse_datasheet(ds_path, mfr=mfr, mpn=mpn, need_symbols=need_symbols)
        except Exception as e:
            print(ds_path, e)
            return None, None
        ds.add_multiple(dsp.all_fields())

    # try nexar api:
    if 1:
        try:
            from dslib.nexar.api import get_part_specs_cached
            specs = {}  # get_part_specs_cached(mpn, mfr) or {}
        except Exception as e:
            print(mfr, mpn, 'get_part_specs_cached', e)
            specs = {}

        for sym, sn in dict(tRise='risetime', tFall='falltime').items():
            sv = specs.get(sn) and pd.to_timedelta(specs[sn]).nanoseconds
            if sv and sym not in ds:
                ds.add(Field(sym, min=math.nan, typ=sv, max=math.nan))

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


def compute_part_powerloss(ds: DatasheetFields, dcdc: DcDcSpecs) -> Tuple[Part, Dict[str, float]]:
    if isinstance(ds, tuple):
        raise ValueError(ds)
    else:
        part = ds.part
    mfr = part.mfr
    mpn = part.mpn

    ds.add_multiple(ds.part.specs.fields())

    # parse specification for DC-DC loss model
    try:
        fet_specs = ds.get_mosfet_specs()
    except Exception as e:
        print(mfr, mpn, 'error creating mosfet specs', e, type(e))
        print(traceback.format_exc())
        print(part, part.specs.__dict__)
        print('\n'.join(map(str, ds.items())))
        parse_datasheet.invalidate(ds.ds_path, mfr=mfr, mpn=mpn)
        parse_datasheet.invalidate(ds.ds_path, mfr=mfr)
        parse_datasheet.invalidate(ds.ds_path)

        # raise
        return None, None

    # compute power loss
    if 1:
        loss_spec = dcdc_buck_hs(dcdc, fet_specs, rg_total=6, fallback_V_pl=4.5)
        ploss = loss_spec.__dict__.copy()
        del ploss['P_dt']
        ploss['P_hs'] = loss_spec.buck_hs()
        ploss['P_2hs'] = loss_spec.parallel(2).buck_hs()

        loss_spec = dcdc_buck_ls(dcdc, fet_specs)
        ploss['P_rr'] = loss_spec.P_rr
        ploss['P_on_ls'] = loss_spec.P_on
        ploss['P_dt_ls'] = loss_spec.P_dt
        ploss['P_ls'] = loss_spec.buck_ls()
        ploss['P_2ls'] = loss_spec.parallel(2).buck_ls()
    # except Exception as e:
    #    print(mfr, mpn, 'dcdc_buck_hs', e)
    #    ploss = {}

    row = dict(
        mfr=mfr,
        mpn=mpn,
        housing=part.package,

        Vds_max=ds.get_max('Vds', True),
        Rds_max=ds.get_max('Rds_on_10v', True) * 1000,
        Id=ds.get_typ_or_max_or_min('ID_25', True),

        Qg_max=ds.get_max('Qg') * 1e9,
        Qgs=ds.get_typ_or_max_or_min('Qgs'),
        Qgd=ds.get_typ_or_max_or_min('Qgd'),
        Qsw=fet_specs and (fet_specs.Qsw * 1e9),

        # C_oss_pF=ds.get('Coss') and ds.get('Coss').max_or_typ_or_min,

        Qrr_typ=ds.get_typ('Qrr'),
        Qrr_max=ds.get_max('Qrr'),

        tRise_ns=round(fet_specs.tRise * 1e9, 1),
        tFall_ns=round(fet_specs.tFall * 1e9, 1),

        Vth=part.specs.Vgs_th_max,
        Vpl=fet_specs and fet_specs.V_pl,

        FoM=fet_specs.Rds_on * 1000 * (fet_specs.Qg * 1e9),
        FoMrr=fet_specs.Rds_on * 1000 * (fet_specs.Qrr * 1e9),
        FoMsw=fet_specs.Rds_on * 1000 * (fet_specs.Qsw * 1e9),

        **ploss,
    )

    return Part(specs=fet_specs, discovered=part), row


def generate_parts_power_loss_csv(parts: List[DiscoveredPart], dcdc: DcDcSpecs,n_jobs=8):
    assert parts, "No parts to generate"

    result_rows = []  # csv
    result_parts: List[Part] = []  # db storage
    all_mpn = set()

    need_symbols = {
        'tRise', 'tFall',  # HS
        'Qgd', # HS
        ('Qgs', 'Qg_th', 'Qgs2'), # HS, need one of those.
        'Vsd', # LS
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

    import pickle

    if os.path.isfile('fet-datasheets2_.pkl'):
        with(open('fet-datasheets.pkl', 'rb')) as f:
            dss: List[DatasheetFields] = pickle.load(f)
            dss = [d for d in dss if d != (None, None)]
    else:
        jobs = {(p.mfr, p.mpn): (compile_part_datasheet, p, need_symbols) for p in parts}
        results = run_parallel(jobs, n_jobs, 'multiprocessing')
        dss: List[DatasheetFields] = list(results.values())

    if len(dss) == 1:
        print(repr(dss[0]))
        print(dss[0].get_mosfet_specs())

        #with open('fet-datasheets.pkl', 'wb') as f:
        #    pickle.dump(dss, f)

    print('computing power loss...')
    for ds in dss:
        if isinstance(ds, tuple) and ds == (None, None):
            continue
        part, row = compute_part_powerloss(ds, dcdc)
        if part is not None:
            result_rows.append(row)
            result_parts.append(part)

    # print('no P_sw')
    # for row in result_rows:
    #    if math.isnan(row.get('P_sw') or math.nan):
    ##        #no_psw.append((mfr, mpn))
    #        #print(os.path.join('datasheets', row['mfr'], row['mpn'] + '.pdf'))

    df = pd.DataFrame(result_rows)

    df.sort_values(by=['Vds_max', 'mfr', 'mpn'], inplace=True, kind='mergesort')

    for col in df.columns:
        if col.startswith('P_') or col.startswith('FoM'):
            df.loc[:, col] = df.loc[:, col].map(lambda v: round_to_n(v, 2) if isinstance(v, float) else v)

    os.path.exists('out') or os.makedirs('out', exist_ok=True)
    out_fn = f'out/fets-loss-{dcdc.fn_str("buck")}.csv'
    df.to_csv(out_fn, index=False, float_format=lambda f: round_to_n(f, 4))
    print('written', out_fn)

    dslib.store.add_parts(result_parts, overwrite=True)

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


def run_parallel(jobs, max_concurrency=256,
                 backend: Literal['threading', 'multiprocessing'] = 'multiprocessing',
                 verbose=100, **kwargs):
    from joblib import Parallel, delayed
    with tqdm_joblib(tqdm(desc="Run Progress:", total=len(jobs))) as progress_bar:
        results = Parallel(n_jobs=min(num_cores() + 1, max_concurrency, len(jobs)), verbose=verbose, backend=backend, **kwargs)(
            delayed(fn)() if callable(fn) else delayed(fn[0])(*fn[1:]) for fn in jobs.values())
    return dict(zip(jobs.keys(), results))


def show_summary(dss: List[DatasheetFields]):
    print('totel num parts :    ', len(dss))
    dss = [d for d in dss if d != (None, None)]
    print('total num parsed DS: ', len(dss))
    print('total num fields:    ', sum(len(ds) for ds in dss))
    print('total num values:    ', sum(len(f) for ds in dss for f in ds.fields_lists.values()))


if __name__ == '__main__':
    if os.path.isfile('fet-datasheets.pkl'):
        with(open('fet-datasheets.pkl', 'rb')) as f:
            dss: List[DatasheetFields] = pickle.load(f)

        dss = [d for d in dss if d != (None, None)]
        show_summary(dss)

        # exit(0)
    # parse_pdf_tests()
    main()
