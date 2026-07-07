"""
Backend for the human-ref-input.html labeling tool.

Serves:
  GET  /                       human-ref-input.html
  GET  /api/parts              list of [{mfr,mpn,labeled}] in random order
  GET  /api/part?mfr=&mpn=     part details (ds_path + fields + existing label)
  GET  /datasheets/<...>.pdf   raw PDF (range-supported via SimpleHTTPRequestHandler)
  POST /api/submit             save labeled values to data/human_ref/<mfr>__<mpn>.json

Run from the repo root:
    python apps/human_ref_input_server.py [--port 8765] [--host 127.0.0.1]
"""
import argparse
import http.server
import json
import math
import os
import random
import socketserver
import sys
import urllib.parse
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import dslib.store
from dslib.conditions import normalize_conditions
from dslib.field import Field, conditions_to_str

LABEL_DIR = os.path.join(ROOT, 'data', 'human_ref')
HTML_FILE = os.path.join(ROOT, 'human-ref-input.html')


def _safe_filename(s: str) -> str:
    return ''.join(c if c.isalnum() or c in '-._' else '_' for c in s)


def label_path(mfr: str, mpn: str) -> str:
    return os.path.join(LABEL_DIR, f'{_safe_filename(mfr)}__{_safe_filename(mpn)}.json')


def _nan_to_none(x):
    if isinstance(x, float) and math.isnan(x):
        return None
    return x


def _field_summary(f: Field) -> dict:
    cond_norm = normalize_conditions(f.cond, symbol=f.symbol)
    return dict(
        symbol=f.symbol,
        min=_nan_to_none(f.min),
        typ=_nan_to_none(f.typ),
        max=_nan_to_none(f.max),
        unit=f.unit,
        cond=conditions_to_str(cond_norm) if cond_norm else conditions_to_str(f.cond),
        cond_norm=cond_norm,
    )


def part_payload(ds) -> dict:
    fields_filled = []
    for sym, f in ds.fields_filled.items():
        fields_filled.append(_field_summary(f))

    fields_lists = {}
    for sym, fl in ds.fields_lists.items():
        fields_lists[sym] = [_field_summary(f) for f in fl]

    ds_path = ds.ds_path  # repo-relative
    return dict(
        mfr=ds.part.mfr,
        mpn=ds.part.mpn,
        ds_path=ds_path,
        ds_exists=os.path.exists(os.path.join(ROOT, ds_path)),
        fields=fields_filled,
        fields_lists=fields_lists,
    )


def load_existing_label(mfr: str, mpn: str) -> Optional[dict]:
    p = label_path(mfr, mpn)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def make_handler(db):
    # build a list of parts whose PDF exists; shuffled once at startup
    parts = []
    for key, ds in db.items():
        ds_path = ds.ds_path
        if os.path.exists(os.path.join(ROOT, ds_path)):
            parts.append((ds.part.mfr, ds.part.mpn))
    random.shuffle(parts)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=ROOT, **kw)

        def log_message(self, fmt, *args):
            sys.stderr.write(f'[{self.address_string()}] {fmt % args}\n')

        def _send_json(self, obj, status=200):
            payload = json.dumps(obj, default=str).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path in ('/', '/index.html'):
                if not os.path.exists(HTML_FILE):
                    self.send_error(404, 'human-ref-input.html missing at repo root')
                    return
                with open(HTML_FILE, 'rb') as f:
                    body = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
                return

            if path == '/api/parts':
                rows = [
                    dict(mfr=m, mpn=p, labeled=os.path.exists(label_path(m, p)))
                    for m, p in parts
                ]
                self._send_json(dict(parts=rows))
                return

            if path == '/api/part':
                qs = urllib.parse.parse_qs(parsed.query)
                mfr = (qs.get('mfr') or [''])[0]
                mpn = (qs.get('mpn') or [''])[0]
                ds = db.get((mfr, mpn))
                if ds is None:
                    self._send_json(dict(error=f'unknown part {mfr}/{mpn}'), 404)
                    return
                payload = part_payload(ds)
                payload['label'] = load_existing_label(mfr, mpn)
                self._send_json(payload)
                return

            # PDF files & anything else under datasheets/
            if path.startswith('/datasheets/'):
                return super().do_GET()

            self.send_error(404, 'not found')

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != '/api/submit':
                self.send_error(404, 'not found')
                return
            length = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                self._send_json(dict(error=f'bad json: {e}'), 400)
                return

            mfr = payload.get('mfr')
            mpn = payload.get('mpn')
            if not mfr or not mpn:
                self._send_json(dict(error='mfr and mpn required'), 400)
                return

            os.makedirs(LABEL_DIR, exist_ok=True)
            out_path = label_path(mfr, mpn)
            with open(out_path, 'w') as f:
                json.dump(payload, f, indent=2, default=str)
            self._send_json(dict(ok=True, saved=os.path.relpath(out_path, ROOT)))

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8765)
    args = ap.parse_args(argv)

    os.chdir(ROOT)
    os.makedirs(LABEL_DIR, exist_ok=True)

    print('loading datasheets db...', file=sys.stderr)
    db = dslib.store.datasheets_db.load()
    print(f'  {len(db)} parts in db', file=sys.stderr)

    handler = make_handler(db)

    class ReusableTCP(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    with ReusableTCP((args.host, args.port), handler) as httpd:
        url = f'http://{args.host}:{args.port}/'
        print(f'serving on {url}', file=sys.stderr)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('shutting down', file=sys.stderr)


if __name__ == '__main__':
    main()
