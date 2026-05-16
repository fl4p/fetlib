import argparse
import asyncio
import traceback

from discover_parts import discover_mosfets
from dslib.field import DatasheetFields
from dslib.store import Part, parts_db
from main import compile_part_datasheet, get_fet_specs

need_symbols = {
    'tRise', 'tFall',  # HS
    'Qgd',  # HS
    ('Qgs', 'Qg_th', 'Qgs2'),  # HS, need one of those.
    'Vsd',  # LS
    # if we would only specify Qgs, the OCR pipeline would brute-force rasterization
    # until it wrongly finds Qgs (which actually was Qgs1)
    # 'Qrr'  # LS # kl leave this, many DS dont have this
}


def _process_one_part(part: Part, no_cache=False, no_ocr=False, no_download=False):
    try:
        ds: DatasheetFields = compile_part_datasheet(
            part, need_symbols, no_cache=no_cache,
            no_ocr=no_ocr, no_download=no_download)
        part.specs = get_fet_specs(ds)
        return part, None
    except Exception as e:
        err = (f'  error compiling {part.mfr} {part.mpn}: '
               f'{type(e).__name__}: {e}\n{traceback.format_exc()}')
        return None, err


def run(jobs: int = 1):
    parts = asyncio.run(discover_mosfets(no_obsolete=False))

    if jobs > 1:
        from main import run_parallel
        for p in parts:
            print(p.mfr, p.mpn)
        job_dict = {
            (p.mfr, p.mpn): (_process_one_part, p)
            for p in parts
        }
        results = run_parallel(job_dict, jobs, 'multiprocessing', verbose=0)
        updated = []
        for (mfr, mpn), (new_part, err) in results.items():
            if err:
                print(err)
                return None
            updated.append(new_part)
        parts_db.add(updated, overwrite=True)
    else:
        for part in parts:
            print(part.mfr, part.mpn)
            _, err = _process_one_part(part)
            if err:
                print(err)
                return None
        parts_db.add(parts, overwrite=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-j', '--jobs', type=int, default=1,
                        help='number of parts to process in parallel '
                             '(1 = serial; >1 uses run_parallel from main.py)')
    args = parser.parse_args()

    from wakepy import keep
    with keep.running():
        run(jobs=args.jobs)
