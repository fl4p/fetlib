import asyncio
import os

import backoff

from dslib import dotdict
from dslib.cache import disk_cache


def transfer_disk_cache(old, new, inputs):

    for inp in inputs:
        old_key = old.cache_key(*inp.args, **inp.kwargs)
        if os.path.exists(old_key):
            new_key = new.cache_key(*inp.args, **inp.kwargs)
            os.rename(old_key, new_key)
            # print('')


def transfer():
    from dslib.pdf.tabular import tabula_browser

    from discover_parts import discover_mosfets
    parts = asyncio.run(discover_mosfets(no_obsolete=True))

    inputs = [dotdict(args=part.get_ds_path(), kwargs={}) for part in parts]

    transfer_disk_cache(
        old=tabula_browser,
        new =disk_cache(ttl='999d', file_dependencies=[0], salt='v03')(tabula_browser),
        inputs
    )

    # 'datasheets/littelfuse/IXTK170P10P.pdf.gs.pdf'

    #old = disk_cache(ttl='999d', file_dependencies=[0], salt='v02', hash_func_code=True)(
    #    backoff.on_exception(backoff.expo, TimeoutError, max_time=300, logger=None)(tabula_browser))

    new = disk_cache(ttl='999d', file_dependencies=[0], salt='v03')(tabula_browser)


