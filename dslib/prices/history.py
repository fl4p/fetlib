"""Append-only price history (docs/Parts Prices.md's date index, realized).

`prices_db` stays a latest-snapshot store (whole-record overwrite); this side table
records every CHANGE so ladders can be tracked over time. One row per
(record, offer, ladder break), plus a single row for negative-status records ("on this
date DigiKey had no such part") with NULL break_qty/unit_price.

Change detection: a snapshot is appended only when its content hash differs from the
last recorded one for the same (mfr, mpn, distributor, currency) key. The hash covers
status, currency and the offers' (sku, packaging, moq, ladder) -- deliberately NOT
`stock`, which jitters on every fetch and would turn "history of prices" into "log of
every harvest". Stock is still stored on the rows that DO get appended, so it is
sampled at price-change points only.

Failure isolation: recording history must never lose fetched price data -- callers
write prices_db FIRST, then call record_history(). An exception here is a code/schema
bug and stays loud.
"""

import datetime
import hashlib
import json
import os
import sqlite3
from typing import List, Optional

from dslib.prices import PartOffers

_PATH = os.path.realpath(os.path.dirname(__file__) + '/../../data/prices-history.sqlite3')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY,
    mfr         TEXT NOT NULL,
    mpn         TEXT NOT NULL,
    distributor TEXT NOT NULL,
    currency    TEXT NOT NULL,
    status      TEXT NOT NULL,
    sku         TEXT,
    packaging   TEXT,
    break_qty   INTEGER,            -- NULL on negative-status rows
    unit_price  REAL,               -- NULL on negative-status rows; never 0
    moq         INTEGER,
    stock       INTEGER,            -- sampled only when the price content changed
    fetched_at  TEXT NOT NULL,      -- ORIGIN timestamp of the data (ISO, UTC)
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ph_part ON price_history(mfr, mpn, distributor, currency);
CREATE TABLE IF NOT EXISTS price_history_last (
    k       TEXT PRIMARY KEY,       -- json [mfr, mpn, distributor, currency]
    hash    TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""

_conn_cache = {}


def _conn(path=None) -> sqlite3.Connection:
    path = path or _PATH
    cx = _conn_cache.get(path)
    if cx is None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cx = sqlite3.connect(path)
        cx.execute('PRAGMA journal_mode=WAL')
        cx.executescript(_SCHEMA)
        _conn_cache[path] = cx
    return cx


def _content_hash(rec: PartOffers) -> str:
    payload = dict(
        status=rec.status, currency=rec.currency,
        offers=sorted((o.sku, o.packaging, o.moq, o.ladder) for o in rec.offers),
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def record_history(records: List[PartOffers], path=None) -> int:
    """Append every record whose price content changed since its last recorded snapshot.
    Returns the number of records appended (not rows). Idempotent for unchanged data --
    re-running a harvest over cached envelopes appends nothing."""
    cx = _conn(path)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    appended = 0
    with cx:  # one transaction: the 'last' pointer and its rows can't diverge
        for rec in records:
            k = json.dumps(list(rec.key))
            h = _content_hash(rec)
            row = cx.execute('SELECT hash FROM price_history_last WHERE k = ?',
                             (k,)).fetchone()
            if row is not None and row[0] == h:
                continue
            base = (rec.mfr, rec.mpn, rec.distributor, rec.currency, rec.status)
            fetched_at = rec.fetched_at.isoformat()
            if rec.offers:
                cx.executemany(
                    'INSERT INTO price_history(mfr, mpn, distributor, currency, status,'
                    ' sku, packaging, break_qty, unit_price, moq, stock, fetched_at,'
                    ' recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    [base + (o.sku, o.packaging, bq, up, o.moq, o.stock, fetched_at, now)
                     for o in rec.offers for bq, up in o.ladder])
            else:
                # negative status IS a datapoint: the part vanished from the catalog
                cx.execute(
                    'INSERT INTO price_history(mfr, mpn, distributor, currency, status,'
                    ' sku, packaging, break_qty, unit_price, moq, stock, fetched_at,'
                    ' recorded_at) VALUES(?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,?,?)',
                    base + (fetched_at, now))
            cx.execute('INSERT OR REPLACE INTO price_history_last(k, hash, fetched_at)'
                       ' VALUES(?,?,?)', (k, h, fetched_at))
            appended += 1
    return appended


def read_history(mfr: str, mpn: str, distributor: Optional[str] = None,
                 currency: str = 'USD', path=None) -> List[tuple]:
    """(fetched_at, distributor, status, sku, break_qty, unit_price, moq, stock) rows,
    oldest first."""
    cx = _conn(path)
    sql = ('SELECT fetched_at, distributor, status, sku, break_qty, unit_price, moq,'
           ' stock FROM price_history WHERE mfr = ? AND mpn = ? AND currency = ?')
    params = [mfr, mpn, currency]
    if distributor:
        sql += ' AND distributor = ?'
        params.append(distributor)
    return cx.execute(sql + ' ORDER BY fetched_at, distributor, sku, break_qty',
                      params).fetchall()


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print('usage: python -m dslib.prices.history <mfr> <mpn> [distributor]')
        sys.exit(2)
    rows = read_history(sys.argv[1], sys.argv[2],
                        sys.argv[3] if len(sys.argv) > 3 else None)
    if not rows:
        print('no history for', sys.argv[1], sys.argv[2])
    for r in rows:
        print('%s  %-8s %-18s %-10s qty>=%-6s %-8s moq=%-6s stock=%s'
              % (r[0][:10], r[1], r[3] or '-', r[2], r[4] or '-', r[5] or '-',
                 r[6] or '-', r[7] if r[7] is not None else '-'))
