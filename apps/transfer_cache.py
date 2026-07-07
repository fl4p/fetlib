import asyncio
import os

import backoff

from dslib import dotdict
from dslib.cache import disk_cache


def transfer_disk_cache(old, new, inputs):
    for inp in inputs:
        old_key = old.cache_key(*inp.args, **inp.kwargs)
        old_path = old.store.get_path(old_key)
        #old(*inp.args, **inp.kwargs)
        if os.path.exists(old_path):
            print('cache hit', inp)
            new_key = new.cache_key(*inp.args, **inp.kwargs)
            new_path = new.store.get_path(new_key)
            if new_path != old_path and not os.path.exists(new_path):
                print('mv', repr(old_path), repr(new_path))
                os.rename(old_path, new_path)
            # print('')


def transfer():
    from dslib.pdf.tabular import tabula_browser

    from discover_parts import discover_mosfets
    parts = asyncio.run(discover_mosfets(no_obsolete=True))

    inputs = []
    for part in parts:
        if os.path.exists(part.get_ds_path()):
            inputs.append(dotdict(args=[part.get_ds_path()], kwargs={}))

    transfer_disk_cache(
        old=tabula_browser,
        new =disk_cache(ttl='999d', file_dependencies=[0], salt='v03')(tabula_browser),
        inputs=inputs
    )

    # 'datasheets/littelfuse/IXTK170P10P.pdf.gs.pdf'

    #old = disk_cache(ttl='999d', file_dependencies=[0], salt='v02', hash_func_code=True)(
    #    backoff.on_exception(backoff.expo, TimeoutError, max_time=300, logger=None)(tabula_browser))

    new = disk_cache(ttl='999d', file_dependencies=[0], salt='v03')(tabula_browser)



transfer()