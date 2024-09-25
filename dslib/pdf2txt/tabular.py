import json
import logging
import os
import re
import threading
import time
from collections import deque
from typing import List

import backoff
import pandas as pd
import requests
from tqdm import tqdm

from dslib.cache import random_str, acquire_file_lock, disk_cache

_tab_web_lock = threading.Lock()


@disk_cache(ttl='99d', file_dependencies=[0], salt='v02', hash_func_code=True)
@backoff.on_exception(backoff.expo, TimeoutError, max_time=300, logger=None)
def tabula_browser(pdf_path, pad=2) -> List[pd.DataFrame]:
    with _tab_web_lock:
    #with acquire_file_lock(os.path.dirname(__file__) + '/tabula-web.lock', kill_holder=False, max_time=300):
        s = requests.Session()

        with open(pdf_path, 'rb') as f:
            res = s.post('http://127.0.0.1:8080/upload.json', files={'files[]': f}).json()

        assert len(res) == 1
        # [{"filename": "IRF150DM115XTMA1_cyn_char.pdf", "success": true,
        #  "file_id": "3fff9659cce6631bf6faaf41a8c83cc5005062d2", "upload_id": "29e01281-ad71-4a8a-8cb0-a16ef63bdecd"}]
        r = res[0]
        assert r['success']
        uid = r['upload_id']
        assert uid
        fid = r['file_id']
        assert fid

        with tqdm(total=100, desc='tabular web ' + r['filename']) as pbar:
            while True:
                res = s.get(f'http://127.0.0.1:8080/queue/{uid}/json?file_id={fid}&_={time.time()}').json()
                assert res
                if res['status'] == 'error':
                    raise ValueError(res['message'])
                if res['status'] == 'completed':  # or 'complete' in res['messages']:
                    break
                # print(pdf_path, 'waiting for tabula', res['pct_complete'], '%')
                pbar.update(res['pct_complete'] - pbar.n)
                time.sleep(1)

            #

        # tables = [
        #     [[30.0, 76.0, 245.0, 78.0], [30.0, 167.0, 250.0, 94.0], [30.0, 274.0, 251.0, 72.0]]  # page 1
        # ]

        @backoff.on_exception(backoff.expo, Exception, max_time=180, max_tries=30,
                              backoff_log_level=logging.DEBUG)  # logger=
        def get_tables(fid):
            res = s.get(f"http://127.0.0.1:8080/pdfs/{fid}/tables.json?_={time.time()}")
            if res.status_code != 200:
                raise ValueError(res.text)
            return res.json()

        try:
            tables = get_tables(fid)

            coords = []
            for p_num in range(1, len(tables) + 1):
                for tc in tables[p_num - 1]:
                    assert len(tc) == 4
                    # guess, original=stream, spreadsheet=lattic
                    coords.append(dict(page=p_num, extraction_method="original", selection_id=random_str(),
                                       x1=tc[0] - pad, x2=tc[0] + tc[2] + pad,
                                       y1=tc[1] - pad, y2=tc[1] + tc[3] + pad,
                                       width=tc[2] + 2 * pad, height=tc[3] + 2 * pad,
                                       )
                                  )
                    coords.append(dict(page=p_num, extraction_method="spreadsheet", selection_id=random_str(),
                                       x1=tc[0] - pad, x2=tc[0] + tc[2] + pad,
                                       y1=tc[1] - pad, y2=tc[1] + tc[3] + pad,
                                       width=tc[2] + 2 * pad, height=tc[3] + 2 * pad,
                                       )
                                  )
            chunk_n = 16
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
            }

            dat =[]
            chunks = deque([coords[i:i + chunk_n] for i in range(0, len(coords), chunk_n)])

            while chunks:
                chunk = chunks.popleft()

                res = s.post(f"http://127.0.0.1:8080/pdf/{fid}/data",
                         data=dict(coords=json.dumps(chunk)), headers=headers)
                if res.status_code != 200:
                    txt = re.sub('\s+', ' ', res.text)
                    txt = re.sub('<[^<]+?>', '', txt)
                    print(pdf_path, 'tabula web error posting', len(chunk),'coords', txt)

                    if len(chunk) > 1:
                        # subdivide
                        hl = int(len(chunk) / 2)
                        chunks.append(chunk[:hl])
                        chunks.append(chunk[hl:])

                    #raise RuntimeError('tabula web error with %s: %s' % (pdf_path, txt))
                else:
                    dat += res.json()

            #print(pdf_path, 'tabula web extracted', len(dat), 'tables from', len(coords), 'rects extracted')
        except Exception as e:
            print(pdf_path, 'tabula web error', e)
            raise
        finally:
            s.post(f"http://127.0.0.1:8080/pdf/{fid}", data=dict(_method='delete'))

        dfs = []
        for tab in dat:
            td = [[c['text'] for c in row] for row in tab['data']]
            df = pd.DataFrame(td)
            df.index.name = 'tabula_web_' + tab['extraction_method']
            dfs.append(df)


        # print(pdf_path, 'tabula browser extracted', len(dfs), 'tables with', sum(len(df) for df in dfs), 'rows')

        return dfs
