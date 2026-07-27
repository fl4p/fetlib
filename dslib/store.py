"""Persistent object stores for parts and parsed datasheets.

TWO BACKENDS live here. `_SqliteBackend` is the one to use; `_PickleBackend` is the
historical whole-file pickle, kept so an unmigrated checkout still runs and so
`FETLIB_STORE=pickle` is a working rollback. Which one an ObjectDatabase resolves to is
decided by what exists on disk -- see `_resolve_backend`.

WHY THE VALUES ARE PICKLE BLOBS AND MUST STAY THAT WAY. It is tempting to "clean up" the
blob column into JSON. Do not, without reading this first:

  * A to_dict/from_dict pair would have to live in dslib/field.py, and that file's CONTENT
    HASH *is* `field_repr_salt()` (field.py:_FIELD_REPR_SOURCES), which salts
    read_parts_datasheets in main.py. Editing it invalidates ~17 GB of parse cache and
    forces a full re-parse of ~6k datasheets through Tabula/OCR -- days of wall time, for
    no correctness gain.
  * 59% of all min/typ/max values are NaN, which JSON cannot represent (bare `NaN` is
    invalid JSON; `null` destroys the NaN-vs-absent distinction that Field.__len__ and
    every math.isnan check depend on).
  * `Field.cond` dicts use int keys 8:1 over string keys. JSON keys are strings only, so
    74% of cond dicts stop comparing equal to their pre-migration selves.
  * `Field.__init__` is a *normalizing* constructor (unit scaling, ohm->mOhm, the Vsd
    min/typ swap). It cannot be reused to deserialize -- it would double-scale. Any
    from_dict must bypass __init__ and set __dict__, which is what pickle already does.
  * The corpus carries deliberate schema drift (MosfetSpecs has three attribute sets;
    unpickling bypasses __init__ so old records simply lack newer attributes, and
    load_parts() below is 130 lines of getattr-guarded fill-if-absent built on exactly
    that tolerance). JSON freezes the representation and forces versioned migrations.

Conversely, BECAUSE the blob is the same pickle bytes the old whole-file store wrote,
this module contributes nothing to how a Field stores a value, is in none of
`_FIELD_REPR_SOURCES`, and therefore MUST NOT bump any disk-cache salt. A pre-migration
cache entry served after the migration re-injects exactly the Field objects it would have
re-injected anyway.
"""
import json
import os
import pickle
import sqlite3
import threading
import time
import zlib
from copy import copy
from typing import Tuple, Dict, Optional, Generic, TypeVar, Callable, Union, List, Iterator

from dslib.cache import acquire_file_lock
from dslib.discovery import DiscoveredPart
from dslib.field import DatasheetFields
from dslib.mosfet import MosfetSpecs


class Part:
    def __init__(self, mpn=None, mfr=None, specs=None, discovered: 'DiscoveredPart' = None):
        self.mpn = mpn or discovered.mpn
        self.mfr = mfr or discovered.mfr
        self.specs: 'MosfetSpecs' = specs
        self.discovered = discovered

    @property
    def is_fet(self):
        assert self.specs
        return isinstance(self.specs, MosfetSpecs)


T = TypeVar('T')
K = TypeVar('K')


_MISSING = object()

# blob encodings. The column exists so the encoding can change without a flag day; a
# reader must understand every value it might meet, a writer emits exactly one.
ENC_PICKLE = 0
ENC_ZLIB = 1
_PICKLE_PROTOCOL = 5  # pinned, not HIGHEST_PROTOCOL, so the bytes don't drift with python


def _encode_key(key) -> str:
    """(mfr, mpn) -> a canonical, reversible TEXT key.

    Tuples become JSON arrays, scalars stay scalars. Keys must be hashable, so a JSON
    array can only ever have come from a tuple and `_decode_key` can invert it.
    """
    if isinstance(key, tuple):
        return json.dumps(list(key), separators=(',', ':'))
    return json.dumps(key, separators=(',', ':'))


def _decode_key(k: str):
    def _totuple(v):
        # recursive: json has no tuple, so a NESTED tuple comes back as a nested list and
        # would be unhashable -- i.e. the decoded key could not be used as a dict key at
        # all. Not reachable with today's flat (mfr, mpn) keys; this class is generic and
        # the next caller should not have to discover that.
        return tuple(_totuple(x) for x in v) if isinstance(v, list) else v

    return _totuple(json.loads(k))


def _key_columns(key):
    """The indexed projection. Derived from the KEY, never from the value -- that is what
    keeps this container generic over T instead of knowing about DatasheetFields."""
    if isinstance(key, tuple) and len(key) == 2 and all(isinstance(x, str) for x in key):
        return key
    return None, None


class _Backend:
    """What ObjectDatabase needs from a store.

    `keyed_get` is the discriminator: a backend that cannot fetch one record without
    materialising all of them (the pickle file) only implements iter_all/replace_all, and
    ObjectDatabase routes around the keyed methods rather than emulating them expensively.
    """

    keyed_get = False
    path = ''

    def iter_all(self, mfr=None, mpn_like=None, mfr_like=None):
        raise NotImplementedError

    def replace_all(self, mapping, **kw):
        raise NotImplementedError

    def snapshot(self, dest):
        raise NotImplementedError

    # keyed_get backends only
    def get(self, key):
        raise NotImplementedError

    def keys(self):
        raise NotImplementedError

    def count(self):
        raise NotImplementedError

    def contains(self, key):
        raise NotImplementedError

    def upsert(self, items, overwrite=True, merge=None):
        raise NotImplementedError

    def delete(self, key):
        raise NotImplementedError


class _PickleBackend(_Backend):
    """The historical store: one whole-file pickle, read and written in its entirety."""

    keyed_get = False  # cannot read one record without materialising all of them

    def __init__(self, path, lock_path):
        self.path = path
        self._lck_path = lock_path

    def iter_all(self, mfr=None, mpn_like=None, mfr_like=None):
        assert mfr is None and mpn_like is None and mfr_like is None, \
            'filtering needs the sqlite backend'
        with acquire_file_lock(self._lck_path, kill_holder=False, max_time=60):
            if not os.path.exists(self.path):
                return
            with open(self.path, 'rb') as f:
                # NOTE: deliberately NOT catching AttributeError/ModuleNotFoundError here.
                # The old code did, and degraded a 143 MB DB to {} behind a logging.warning
                # -- after which the next add() persisted that emptiness. A moved class must
                # be louder than a warning.
                d = pickle.load(f)
        for k, v in d.items():
            yield k, v

    def replace_all(self, mapping, delete_missing=True, max_delete_frac=0.02, **_):
        """Whole-file rewrite, honouring `delete_missing` the same way sqlite does.

        This used to swallow `delete_missing` in **kw and rewrite the file unconditionally,
        so `save_all(partial, delete_missing=False)` -- which the docstring promises is
        non-destructive -- silently dropped every key the mapping omitted. Worse, the
        in-process cache still held them, so the process that did it could not observe the
        loss. Both live stores are pickle, which made that the loaded gun pointing at
        exactly the 65,631-field failure mode.
        """
        with acquire_file_lock(self._lck_path, kill_holder=False, max_time=30):
            have = {}
            if os.path.exists(self.path):
                with open(self.path, 'rb') as f:
                    have = pickle.load(f)
            if delete_missing:
                doomed = set(have) - set(mapping)
                floor = max(1, int(max_delete_frac * len(have)))
                if have and max_delete_frac < 1.0 \
                        and (doomed == set(have) or len(doomed) > floor):
                    raise ValueError(
                        'refusing to delete %d of %d records -- pass delete_missing=False '
                        'if the mapping is deliberately partial, or max_delete_frac=1.0'
                        % (len(doomed), len(have)))
                out = dict(mapping)
            else:
                out = dict(have)
                out.update(mapping)

            tmp = '%s.%d.tmp' % (self.path, os.getpid())
            with open(tmp, 'wb') as f:
                pickle.dump(out, f)
            os.replace(tmp, self.path)  # atomic; the old code wrote onto the live path

    def snapshot(self, dest):
        import shutil
        shutil.copy2(self.path, dest)


class _SqliteBackend(_Backend):
    """One row per record: the "document per part" store.

    A single-key read is an index seek plus one unpickle (~0.2 ms) instead of unpickling
    the whole DB (~3.5 s, ~1.5 GB resident) -- which is what every joblib worker in
    read_parts_datasheets was doing to read two records.
    """

    keyed_get = True
    SCHEMA_VERSION = 1

    def __init__(self, path, enc=None):
        self.path = path
        # None => adopt whatever the store was built with (meta.write_enc), so a compressed
        # DB stays compressed. Without this, every later add() would write ENC_PICKLE rows
        # into a compressed store and it would silently decompress itself record by record
        # -- each row still readable, so nothing would ever look wrong.
        self._enc = enc
        self._enc_explicit = enc is not None
        # Connections are per (pid, thread) and NEVER shared: a sqlite connection must not
        # cross a fork (joblib/multiprocessing in read_parts_datasheets) or a thread (the
        # web backend). A shared fd across fork corrupts the file.
        self._conns: Dict[Tuple[int, int], sqlite3.Connection] = {}

    # ------------------------------------------------------------------ connection
    def _read_conn(self):
        """A connection for READING, or None if the store does not exist yet.

        Reads must never bring a database into being. `_conn()` creates the file and the
        schema on first use, so when a read went through it, merely LOOKING at a store
        whose pickle was temporarily absent (a fresh clone before `git lfs pull`, a repair
        script mid-rename) left an empty `.sqlite3` behind -- and since `_resolve_backend`
        prefers sqlite, every later run then served {} from it, silently, forever, with the
        150 MB pickle sitting right there. Absence of the file must not become a durable
        record that there is no data.
        """
        if not os.path.exists(self.path):
            return None
        return self._conn()

    def _conn(self) -> sqlite3.Connection:
        pid = os.getpid()
        ident = (pid, threading.get_ident())
        cx = self._conns.get(ident)
        if cx is not None:
            return cx
        # Drop any connection inherited from a parent process. Do NOT close them: the
        # underlying fd is the parent's and closing can roll back the parent's state.
        for stale in [k for k in self._conns if k[0] != pid]:
            self._conns.pop(stale, None)

        no_file = not os.path.exists(self.path)
        if no_file:
            d = os.path.dirname(self.path)
            d and os.makedirs(d, exist_ok=True)
        cx = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        cx.execute('PRAGMA busy_timeout = 30000')
        cx.execute('PRAGMA synchronous = NORMAL')

        # Keyed on the SCHEMA, not on the file: a file can exist and be schemaless (an
        # interrupted create, a stray 0-byte file), and keying on existence would then skip
        # the setup and fail later on a missing table.
        fresh = cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND "
                           "name='records'").fetchone() is None
        if fresh and no_file:
            cx.execute('PRAGMA page_size = 8192')      # must precede the first table
        # Assert WAL on EVERY open, not just at creation. journal_mode is persistent, so a
        # store that was handed over in DELETE mode (the migration collapses to one file
        # before renaming) would otherwise stay there forever and quietly lose the
        # readers-never-block-the-writer property this design depends on.
        try:
            cx.execute('PRAGMA journal_mode = WAL')
        except sqlite3.OperationalError:
            pass                                       # contended; it is already persistent
        if fresh:
            self._create_schema(cx)
        self._conns[ident] = cx

        if self._enc_explicit:
            cx.execute('INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)',
                       ('write_enc', str(self._enc)))
        else:
            row = cx.execute("SELECT value FROM meta WHERE key='write_enc'").fetchone()
            self._enc = int(row[0]) if row else ENC_PICKLE
        return cx

    def _create_schema(self, cx):
        cx.executescript(
            # A rowid table with a UNIQUE index, NOT "WITHOUT ROWID": the median row is
            # ~24 kB and WITHOUT ROWID stores the whole row inside the PK btree, turning
            # every index traversal into overflow-page chasing.
            'CREATE TABLE IF NOT EXISTS records ('
            ' id INTEGER PRIMARY KEY,'
            ' k TEXT NOT NULL,'
            ' mfr TEXT,'
            ' mpn TEXT,'
            ' enc INTEGER NOT NULL,'
            ' proto INTEGER NOT NULL,'
            ' raw_bytes INTEGER NOT NULL,'
            ' updated_at REAL NOT NULL,'
            ' blob BLOB NOT NULL,'
            ' UNIQUE (k));'
            'CREATE INDEX IF NOT EXISTS records_mfr_mpn ON records (mfr, mpn);'
            'CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);'
        )
        cx.execute('INSERT OR IGNORE INTO meta(key, value) VALUES(?,?)',
                   ('schema_version', str(self.SCHEMA_VERSION)))

    def close(self):
        for k in list(self._conns):
            if k[0] == os.getpid():
                try:
                    self._conns[k].close()
                except sqlite3.Error:
                    pass
            self._conns.pop(k, None)

    # ------------------------------------------------------------------ codec
    def _encode(self, obj):
        raw = pickle.dumps(obj, _PICKLE_PROTOCOL)
        if self._enc == ENC_ZLIB:
            return ENC_ZLIB, zlib.compress(raw, 6), len(raw)
        return ENC_PICKLE, raw, len(raw)

    @staticmethod
    def _decode(enc, blob, key=None):
        # pickle.loads on a LOCAL, self-produced artifact: data/*.sqlite3 is written only by
        # this module from objects this repo parsed, is gitignored, and is never fetched
        # from a network or supplied by a user. The trust boundary is identical to the
        # whole-file pickle this replaces. See the module docstring for why the payload
        # cannot become JSON without invalidating ~17 GB of parse cache.
        if enc == ENC_ZLIB:
            blob = zlib.decompress(blob)
        elif enc != ENC_PICKLE:
            raise ValueError('record %r has unknown blob encoding %r -- written by a '
                             'newer version of dslib.store?' % (key, enc))
        return pickle.loads(blob)

    # ------------------------------------------------------------------ reads
    def get(self, key):
        cx = self._read_conn()
        if cx is None:
            return _MISSING
        row = cx.execute(
            'SELECT enc, blob FROM records WHERE k = ?', (_encode_key(key),)).fetchone()
        if row is None:
            return _MISSING
        return self._decode(row[0], row[1], key)

    def iter_all(self, mfr=None, mpn_like=None, mfr_like=None):
        cx = self._read_conn()
        if cx is None:
            return
        sql = 'SELECT k, enc, blob FROM records'
        where, params = [], []
        if mfr is not None:
            where.append('mfr = ?')
            params.append(mfr)
        if mfr_like is not None:
            where.append('mfr LIKE ?')
            params.append(mfr_like)
        if mpn_like is not None:
            where.append('mpn LIKE ?')
            params.append(mpn_like)
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY id'   # see keys(): iteration order is part of the contract
        for k, enc, blob in cx.execute(sql, params):
            key = _decode_key(k)
            yield key, self._decode(enc, blob, key)

    def keys(self):
        # ORDER BY id. Without it SQLite answers this from the UNIQUE(k) index and returns
        # keys sorted BY KEY -- a different order from iter_all()'s table scan, which
        # silently changes any seeded sampling built on it (test/v2_eval.py picks its
        # sample from this list). Iteration order is part of the contract here, not an
        # implementation detail.
        #
        # What is guaranteed: a stable order, equal to insertion order for an append-only
        # store, which after a migration is the order the source pickle had. What is NOT:
        # `id` is a plain INTEGER PRIMARY KEY, so deleting the row holding the CURRENT MAX
        # id frees that number and the next insert reuses it rather than appending -- so a
        # delete-then-add of the newest record can leave the new key mid-sequence instead
        # of at the end. Dormant today (nothing calls del_obj on datasheets_db, which is
        # the store whose order is depended on). Make the column AUTOINCREMENT if that
        # contract ever has to hold across deletes.
        cx = self._read_conn()
        return [] if cx is None else [_decode_key(k) for (k,)
                                      in cx.execute('SELECT k FROM records ORDER BY id')]

    def count(self):
        cx = self._read_conn()
        return 0 if cx is None else cx.execute('SELECT count(*) FROM records').fetchone()[0]

    def contains(self, key):
        cx = self._read_conn()
        return cx is not None and cx.execute(
            'SELECT 1 FROM records WHERE k = ?', (_encode_key(key),)).fetchone() is not None

    # ------------------------------------------------------------------ writes
    def _write_txn(self):
        cx = self._conn()
        try:
            cx.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as e:
            # preserve the old contract: a contended store raised TimeoutError
            if 'locked' in str(e) or 'busy' in str(e):
                raise TimeoutError('could not lock %s: %s' % (self.path, e))
            raise
        return cx

    @staticmethod
    def _rollback(cx):
        """Roll back without masking whatever is already being raised.

        SQLite auto-rolls-back the transaction on some fatal errors (SQLITE_FULL, IOERR,
        NOMEM). An explicit ROLLBACK afterwards then fails with "cannot rollback - no
        transaction is active", and that useless message would replace the real cause on
        its way out of the except block.
        """
        try:
            cx.execute('ROLLBACK')
        except sqlite3.Error:
            pass

    def upsert(self, items, overwrite=True, merge=None):
        """Read-merge-write per key inside ONE transaction.

        The merge reconciles against the row ON DISK, not against a possibly-hours-stale
        in-memory snapshot the way the old add() did -- which is what let a long-running
        process stamp its stale view over another process's writes. Only the incoming keys
        are touched, so a write can no longer clobber records it never looked at.
        """
        cx = self._write_txn()
        try:
            written = {}
            for key, rec in items.items():
                ek = _encode_key(key)
                row = cx.execute('SELECT enc, blob FROM records WHERE k = ?', (ek,)).fetchone()
                stored = self._decode(row[0], row[1], key) if row is not None else None
                assert overwrite or stored is None, 'key already present: %r' % (key,)
                if merge is not None and stored is not None:
                    rec = merge(stored, rec)
                self._put(cx, key, ek, rec)
                written[key] = rec
            cx.execute('COMMIT')
            return written
        except BaseException:
            self._rollback(cx)
            raise

    def _put(self, cx, key, ek, rec):
        enc, blob, raw_bytes = self._encode(rec)
        mfr, mpn = _key_columns(key)
        cx.execute(
            'INSERT INTO records(k, mfr, mpn, enc, proto, raw_bytes, updated_at, blob)'
            ' VALUES(?,?,?,?,?,?,?,?)'
            ' ON CONFLICT(k) DO UPDATE SET mfr=excluded.mfr, mpn=excluded.mpn,'
            ' enc=excluded.enc, proto=excluded.proto, raw_bytes=excluded.raw_bytes,'
            ' updated_at=excluded.updated_at, blob=excluded.blob',
            (ek, mfr, mpn, enc, _PICKLE_PROTOCOL, raw_bytes, time.time(), blob))

    def delete(self, key):
        cx = self._write_txn()
        try:
            n = cx.execute('DELETE FROM records WHERE k = ?', (_encode_key(key),)).rowcount
            cx.execute('COMMIT')
            return n > 0
        except BaseException:
            self._rollback(cx)
            raise

    def replace_all(self, mapping, delete_missing=True, max_delete_frac=0.02, **_):
        cx = self._write_txn()
        try:
            if delete_missing:
                have = {k for (k,) in cx.execute('SELECT k FROM records')}
                doomed = have - {_encode_key(k) for k in mapping}
                # A prune this large is a bug in the caller, not an intent. The old
                # `_lib_mem = d; _write()` had no such gate and silently dropped whatever
                # was not in `d`.
                #
                # The `max(1, ...)` floor exists so a small store can still lose one stray
                # record. But a floor is anti-monotone at the bottom of the range: with
                # exactly ONE record stored the floor IS the whole store, so the single
                # worst input -- delete everything -- was the one case that slipped
                # through. Wiping the store is therefore refused on its own terms, at every
                # size, independently of the fraction.
                floor = max(1, int(max_delete_frac * len(have)))
                wipes_everything = bool(have) and doomed == have
                if have and max_delete_frac < 1.0 and (wipes_everything or len(doomed) > floor):
                    raise ValueError(
                        'refusing to delete %d of %d records (%.1f%%%s) -- pass '
                        'delete_missing=False if the mapping is deliberately partial, or '
                        'max_delete_frac=1.0 to allow it'
                        % (len(doomed), len(have), 100.0 * len(doomed) / len(have),
                           '; that is the entire store' if wipes_everything
                           else ' > %.1f%% limit' % (100.0 * max_delete_frac)))
                for ek in doomed:
                    cx.execute('DELETE FROM records WHERE k = ?', (ek,))
            for key, rec in mapping.items():
                self._put(cx, key, _encode_key(key), rec)
            cx.execute('COMMIT')
        except BaseException:
            self._rollback(cx)
            raise

    def snapshot(self, dest):
        # sqlite3's online backup: consistent even under a concurrent writer. A
        # shutil.copy2 of a WAL-mode database can produce a torn, unusable file.
        dst = sqlite3.connect(dest)
        try:
            self._conn().backup(dst)
        finally:
            dst.close()

    def set_meta(self, key, value):
        self._conn().execute('INSERT INTO meta(key, value) VALUES(?,?)'
                             ' ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                             (key, str(value)))

    def get_meta(self, key, default=None):
        row = self._conn().execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()
        return default if row is None else row[0]


class ObjectDatabase(Generic[K, T]):
    def __init__(self, name, key_func: Optional[Callable[[T], K]] = None):
        self._set_base(os.path.realpath(os.path.dirname(__file__) + f'/../data/{name}'))
        self._key_func = key_func

        # The identity map. NOT merely a speed cache: load_parts() below attaches curves and
        # conditions by MUTATING the objects it got from load(), and MosfetSpecs.from_mpn
        # reads them back via load_obj(). Without a shared instance per key, load_obj would
        # return curve-less specs and the Coss/Ciss/BV/qrr features would silently fall back
        # for 100% of parts while appearing to work.
        self._cache: Dict[K, T] = {}
        self._cache_complete = False
        self._load_error: Optional[BaseException] = None
        self._backend = None

    # ------------------------------------------------------------------ backend wiring
    def _set_base(self, base):
        self._base_path = base
        self._pkl_path = base + '.pkl'
        self._sqlite_path = base + '.sqlite3'
        self._lck_path = self._pkl_path + '.lock'
        self._backend = None

    @property
    def _lib_path(self):
        """The file that IS the database. Kept as a property so the repair/migration
        scripts keep deriving their `.bak-*` names from it.

        Deliberately does NOT resolve/memoise the backend. It used to, and reading the path
        for an unrelated reason (test helpers derive a lock filename from it) then PINNED
        the store to sqlite before the caller had chosen one -- silently changing which
        code path a test exercised, with no visible signal. A path accessor must not decide
        anything.
        """
        if self._backend is not None:
            return self._backend.path
        if os.environ.get('FETLIB_STORE') == 'pickle':
            return self._pkl_path
        if os.path.exists(self._sqlite_path):
            return self._sqlite_path
        if os.path.exists(self._pkl_path):
            return self._pkl_path
        return self._sqlite_path  # where a brand-new store would go

    @_lib_path.setter
    def _lib_path(self, value):
        # tests point a store at tmp_path by assigning this
        self._set_base(value[:-4] if value.endswith('.pkl') else value)

    def _backend_or_resolve(self):
        if self._backend is None:
            self._backend = self._resolve_backend()
        return self._backend

    def _resolve_backend(self) -> _Backend:
        """Pick a backend from what is on disk. Resolved lazily (not in __init__) because
        the module-level stores are constructed at import time, before a migration run has
        created anything."""
        if os.environ.get('FETLIB_STORE') == 'pickle':
            return _PickleBackend(self._pkl_path, self._lck_path)
        if os.path.exists(self._sqlite_path):
            be = _SqliteBackend(self._sqlite_path)
            # An EMPTY sqlite sitting next to a non-empty pickle is not a valid state --
            # it is what a half-finished or aborted migration leaves behind. Serving {}
            # from it would be the quietest possible data loss, so it is refused instead.
            if os.path.exists(self._pkl_path) and be.count() == 0 \
                    and os.path.getsize(self._pkl_path) > 0:
                raise RuntimeError(
                    '%s is empty but %s still holds data. That is an aborted migration, '
                    'not an empty store. Delete the empty sqlite to use the pickle, or '
                    're-run apps/migrate_store_to_sqlite.py'
                    % (self._sqlite_path, self._pkl_path))
            return be
        if os.path.exists(self._pkl_path):
            return _PickleBackend(self._pkl_path, self._lck_path)
        if os.path.exists(self._base_path + '.migrated'):
            # the sqlite file was migrated and has since gone missing. Falling back to a
            # stale pickle here would silently serve pre-migration data.
            raise FileNotFoundError(
                '%s was migrated to sqlite but %s is gone. Restore it, or rebuild with '
                'apps/migrate_store_to_sqlite.py' % (self._base_path, self._sqlite_path))
        return _SqliteBackend(self._sqlite_path)  # brand new store

    @property
    def uses_sqlite(self):
        return isinstance(self._backend_or_resolve(), _SqliteBackend)

    # ------------------------------------------------------------------ compat shim
    @property
    def _lib_mem(self) -> Optional[Dict[K, T]]:
        """Deprecated: the in-memory dict. Use load()/save_all()/unload().

        Kept only so the repair scripts that do `db._lib_mem = d; db._write()` keep working
        until they are ported.
        """
        return self._cache if self._cache_complete else None

    @_lib_mem.setter
    def _lib_mem(self, value):
        if value is None:
            self.unload()
        else:
            self._cache = value
            self._cache_complete = True

    # ------------------------------------------------------------------ reads
    def load(self, reload=False) -> Dict[K, T]:
        """The whole store as a dict. The returned dict is a fresh shallow copy, so the
        VALUES are shared with this store -- mutating one is visible to later load_obj()."""
        if reload:
            self.unload()
        if self._load_error is not None:
            # Sticky. Without this, an unreadable store is re-read from scratch on EVERY
            # load_obj -- and compile_part_datasheet calls that once per part, in every
            # joblib worker, so one moved class turns into thousands of 150 MB unpickle
            # attempts. Failing fast the second time keeps the error loud AND cheap.
            raise self._load_error
        if not self._cache_complete:
            try:
                for k, obj in self._backend_or_resolve().iter_all():
                    if k not in self._cache:  # already-handed-out instances stay canonical
                        self._cache[k] = obj
            except Exception as e:
                self._load_error = e
                raise
            self._cache_complete = True
        return self._cache.copy()

    def keys(self):
        if self._cache_complete:
            return self._cache.keys()
        b = self._backend_or_resolve()
        if b.keyed_get:
            return b.keys()
        self.load()
        return self._cache.keys()

    def load_obj(self, obj_or_key) -> Optional[T]:
        """One record, without materialising the rest. This is the hot path in the joblib
        workers of read_parts_datasheets.

        Takes whatever `key_func` accepts -- callers pass a record-shaped object (a
        DiscoveredPart, an MpnMfr), NOT a bare key. Returns None if absent.
        """
        key = self._key_func(obj_or_key)
        if key not in self._cache:
            if self._cache_complete:
                return None
            b = self._backend_or_resolve()
            if not b.keyed_get:
                self.load()
                if key not in self._cache:
                    return None
            else:
                obj = b.get(key)
                if obj is _MISSING:
                    return None
                self._cache[key] = obj
        return copy(self._cache[key])

    def iter_items(self, mfr=None, mpn_like=None, mfr_like=None) -> Iterator[Tuple[K, T]]:
        """Stream records without retaining them -- constant memory, and it does NOT
        populate the identity map. For audits that reduce each record to a summary row;
        use load() when you need the objects to stay alive and shared.

        `mfr` is an exact match; `mfr_like`/`mpn_like` take SQL LIKE patterns. NOTE that
        LIKE is only case-insensitive for ASCII, so a caller emulating a case-folded
        substring test must keep its own predicate as the decider and treat these purely
        as a pre-filter -- a pushdown that under-matches drops rows silently.

        NOT suspending cyclic GC here, deliberately, though it looks tempting: each record
        is a graph of a few hundred Field objects that dies immediately, and disabling the
        collector around a bare scan does measure ~7% faster. But the records are CYCLIC,
        so with the collector off they accumulate instead of being reclaimed, and any loop
        body that allocates pays for the growing heap -- method_audit's per-record
        ds_path/isfile loop measured 7.1 s deferred vs 3.4 s with GC left alone. An
        optimisation whose sign depends on the caller's loop body does not belong in the
        library. The win here comes from not materialising the DB, not from GC tricks.
        """
        b = self._backend_or_resolve()
        if b.keyed_get:
            for kv in b.iter_all(mfr=mfr, mpn_like=mpn_like, mfr_like=mfr_like):
                yield kv
            return
        if mpn_like is not None or mfr_like is not None:
            # refuse rather than silently returning everything: a filter that quietly
            # stops filtering reads as "nothing matched that pattern" at the call site
            raise NotImplementedError('LIKE filters need the sqlite backend')
        for k, v in (self._cache.items() if self._cache_complete else b.iter_all()):
            if mfr is not None and (not isinstance(k, tuple) or k[0] != mfr):
                continue
            yield k, v

    def contains(self, key: K) -> bool:
        """Takes a raw key (e.g. `(mfr, mpn)`), unlike load_obj which takes a record."""
        if key in self._cache:
            return True
        b = self._backend_or_resolve()
        return b.contains(key) if b.keyed_get else key in self.load()

    def count(self) -> int:
        b = self._backend_or_resolve()
        return b.count() if b.keyed_get else len(self.load())

    def unload(self):
        """Drop the in-memory objects. Replaces `db._lib_mem = None`.

        Also clears a sticky load failure, so this is the retry hook after repairing a
        store rather than a permanent tombstone.
        """
        self._cache = {}
        self._cache_complete = False
        self._load_error = None

    # ------------------------------------------------------------------ writes
    def del_obj(self, obj_or_key, ignore_missing=False):
        """Takes whatever `key_func` accepts, like load_obj."""
        key = self._key_func(obj_or_key)
        b = self._backend_or_resolve()
        if b.keyed_get:
            deleted = b.delete(key)
            if not deleted:
                # evict only on an actual delete: a miss should leave the store exactly as
                # it was, not quietly drop a cached instance on its way to raising
                if ignore_missing:
                    return False
                raise KeyError(key)
            self._cache.pop(key, None)
            return True
        self.load()
        if ignore_missing and key not in self._cache:
            return False
        del self._cache[key]
        self._write()
        return True

    def _items_to_dict(self, items):
        if isinstance(items, list):
            assert self._key_func is not None
            items = dict((self._key_func(o), o) for o in items)
        else:
            assert self._key_func is None
        return items

    def _write(self):
        # delete_missing=True is correct HERE and only here: the assert guarantees the cache
        # is the complete view, so a key absent from it was genuinely deleted (del_obj) and
        # must not be resurrected from disk. Public save_all() defaults the other way,
        # because its callers may legitimately pass a subset.
        assert self._cache_complete, \
            '_write() would persist a partial view; use save_all() or add()'
        self.save_all(self._cache, delete_missing=True)

    def save_all(self, mapping: Dict[K, T], delete_missing=False, max_delete_frac=0.02):
        """Persist a whole mapping in one transaction. Replaces `_lib_mem = d; _write()`.

        `delete_missing` defaults to False -- the opposite of the old `_write()`, which
        silently deleted every key absent from the dict. Callers passing a complete dict
        are unaffected; a caller passing a partial one no longer destroys the remainder.
        """
        # both backends honour these; the pickle branch used to be called without them and
        # so deleted whatever the mapping omitted, whatever the caller asked for
        self._backend_or_resolve().replace_all(
            mapping, delete_missing=delete_missing, max_delete_frac=max_delete_frac)
        if mapping is not self._cache:
            self._cache.update(mapping)

    def snapshot(self, dest_path):
        """A consistent copy of the store. Use this instead of shutil.copy2 -- copying a
        WAL-mode sqlite file while anything is writing yields a torn, unusable backup."""
        self._backend_or_resolve().snapshot(dest_path)
        return dest_path

    def add(self, new_arts: Union[Dict[K, T], List[T]], overwrite=True, merge=None):
        """Store items under their keys.

        NOTE the default: `overwrite=True` means a bare `add(items)` REPLACES each whole
        record. For a record type that accumulates (DatasheetFields), that turns a narrower
        run into a deletion -- see dslib.field.merge_keeping_absent_symbols, which exists
        because one such write cost 65,631 fields.

        `merge(stored, incoming) -> record` opts into a record-type-specific reconciliation
        for keys that already exist. It lives at the caller because this container is
        generic over T and has no business knowing what merging one means; passing nothing
        keeps the historical replace-everything behaviour.

        On sqlite, `merge` reconciles against the row ON DISK inside the write transaction,
        so it holds across processes. The old path merged against this process's snapshot,
        which could be arbitrarily stale.
        """
        new_arts = self._items_to_dict(new_arts)
        b = self._backend_or_resolve()

        if b.keyed_get:
            self._cache.update(b.upsert(new_arts, overwrite=overwrite, merge=merge))
            return

        self.load()
        for k, part in new_arts.items():
            assert overwrite or k not in self._cache
            if merge is not None and k in self._cache:
                part = merge(self._cache[k], part)
            self._cache[k] = part
        self._write()


Mfr = str
Mpn = str
parts_db = ObjectDatabase[Tuple[Mfr, Mpn], Part]('parts-lib', key_func=lambda p: (p.mfr, p.mpn))


def load_parts():
    parts = parts_db.load()
    # Attach datasheet Coss(V)/Crss(V) curves by MPN onto the loaded specs, so the pickle
    # DB need not be rebuilt to add a curve. Only fills a curve that isn't already present.
    # A missing curves module is tolerated (older checkout); any OTHER error is a real bug in
    # the curve subsystem and must surface (Fab's rule: never silently degrade) rather than
    # leave every part quietly curve-less.
    try:
        from dslib.coss_curves import coss_curve_for
    except ImportError:
        coss_curve_for = None
    # Import Ciss SEPARATELY: a combined import would let a broken/renamed
    # ciss_curve_for silently disable the Coss attach too (same except clause),
    # violating the never-silently-degrade contract stated above.
    try:
        from dslib.coss_curves import ciss_curve_for
    except ImportError:
        ciss_curve_for = None
    if coss_curve_for is not None:
        for key, p in parts.items():
            specs = getattr(p, 'specs', None)
            if specs is None or getattr(specs, 'coss_curve', None):
                continue
            mfr, mpn = (key if isinstance(key, tuple) else (getattr(p, 'mfr', None),
                                                            getattr(p, 'mpn', None)))
            curve = coss_curve_for(mfr, mpn)
            if curve:
                specs.coss_curve = curve
    # Ciss(V) pairs ride the same module but attach in an INDEPENDENT pass gated only on
    # ciss_curve_for: nesting this under `coss_curve_for is not None` (as it first shipped)
    # would let a broken/renamed coss_curve_for silently disable the Ciss attach too — the
    # exact combined-failure anti-pattern the separate imports above exist to prevent. Two
    # passes over parts.items() is cheap vs the unpickle cost. Older pickled specs predate
    # the attribute, so set it via getattr-guarded assignment (unpickling bypasses __init__).
    # None -> consumers keep their gate-charge-partition Cgs basis.
    if ciss_curve_for is not None:
        for key, p in parts.items():
            specs = getattr(p, 'specs', None)
            if specs is None or getattr(specs, 'ciss_curve', None):
                continue
            mfr, mpn = (key if isinstance(key, tuple) else (getattr(p, 'mfr', None),
                                                            getattr(p, 'mpn', None)))
            ciss = ciss_curve_for(mfr, mpn)
            specs.ciss_curve = ciss if ciss else None
    # Same for the body-diode reverse-recovery test conditions (IF/di-dt/VR/Tj the datasheet
    # Qrr+trr were measured at). Scalars without their operating point can't be re-scaled or
    # fitted to a charge-control diode; see dslib/qrr_conditions.py and fl4p/fetlib#37.
    try:
        from dslib.qrr_conditions import qrr_conditions_for
    except ImportError:
        qrr_conditions_for = None
    if qrr_conditions_for is not None:
        for key, p in parts.items():
            specs = getattr(p, 'specs', None)
            if specs is None or getattr(specs, 'qrr_cond', None):
                continue
            mfr, mpn = (key if isinstance(key, tuple) else (getattr(p, 'mfr', None),
                                                            getattr(p, 'mpn', None)))
            cond = qrr_conditions_for(mfr, mpn)
            if cond:
                specs.qrr_cond = cond
    # And the multi-di/dt reverse-recovery rows (generated dslib/qrr_points.py):
    # parts carrying these get a per-part two-point (tau, TM, q0) fit in Qrr_op
    # instead of the global QRR_QOSS_FRACTION assumption (fl4p/fetlib#37).
    try:
        from dslib.qrr_points import qrr_points_for
    except ImportError:
        qrr_points_for = None
    if qrr_points_for is not None:
        for key, p in parts.items():
            specs = getattr(p, 'specs', None)
            if specs is None or getattr(specs, 'qrr_points', None):
                continue
            mfr, mpn = (key if isinstance(key, tuple) else (getattr(p, 'mfr', None),
                                                            getattr(p, 'mpn', None)))
            pts = qrr_points_for(mfr, mpn)
            if pts:
                specs.qrr_points = pts
    # And the digitized V(BR)DSS(Tj) breakdown-onset lines (dslib/bv_specs.py):
    # min-anchored intercept + typical-die slope from the human-verified chart
    # digitization. The pickle never carried BV-vs-Tj, so this is fill-if-absent.
    try:
        from dslib.bv_specs import bv_specs_for
    except ImportError:
        bv_specs_for = None
    if bv_specs_for is not None:
        for key, p in parts.items():
            specs = getattr(p, 'specs', None)
            if specs is None or getattr(specs, 'bv_tj', None):
                continue
            mfr, mpn = (key if isinstance(key, tuple) else (getattr(p, 'mfr', None),
                                                            getattr(p, 'mpn', None)))
            bv = bv_specs_for(mfr, mpn)
            if bv:
                specs.bv_tj = bv
    # And the curated gate/channel specs (dslib/gate_specs.py): the gate-charge TEST
    # current Id_gc (NOT the ID_25 rating already in `Id`), gfs and Vgs_th — parsed by
    # the PDF layer but not consumed into the pickle; fill only what's absent/NaN so a
    # rebuilt DB that carries them natively wins over the curated values.
    try:
        from dslib.gate_specs import gate_specs_for
    except ImportError:
        gate_specs_for = None
    if gate_specs_for is not None:
        import math as _math
        for key, p in parts.items():
            specs = getattr(p, 'specs', None)
            if specs is None:
                continue
            mfr, mpn = (key if isinstance(key, tuple) else (getattr(p, 'mfr', None),
                                                            getattr(p, 'mpn', None)))
            gs = gate_specs_for(mfr, mpn)
            if not gs:
                continue
            for k, v in gs.items():
                cur = getattr(specs, k, None)
                if cur is None or (isinstance(cur, float) and _math.isnan(cur)):
                    setattr(specs, k, v)
                elif (isinstance(v, float) and not _math.isnan(v)
                      and isinstance(cur, (int, float))
                      and abs(cur - v) > 0.2 * max(abs(v), 1e-12)):
                    # a rebuilt DB carries parser-populated values that WIN over the
                    # curated ones — but the curated numbers here are human-verified,
                    # so a >20% disagreement means the parser picked a different table
                    # row/condition and must not displace them silently
                    import warnings as _w
                    _w.warn(f"gate_specs: {mfr}:{mpn} parser {k}={cur!r} disagrees "
                            f">20% with the curated (human-verified) {v!r} — parser "
                            f"value kept; re-check the datasheet parse or the curation")
    # Finally attach human-verified saturation-channel Vth_eff(T)+K(T) fits.
    # An attached fit is safety-significant: consumers refuse any status other
    # than verified and require an explicit cold_anchor_conflict=False.
    try:
        from dslib.channel_temp_specs import channel_temp_specs_for
    except ImportError:
        channel_temp_specs_for = None
    if channel_temp_specs_for is not None:
        for key, p in parts.items():
            specs = getattr(p, 'specs', None)
            if specs is None or getattr(specs, 'channel_temp', None) is not None:
                continue
            mfr, mpn = (key if isinstance(key, tuple) else (getattr(p, 'mfr', None),
                                                            getattr(p, 'mpn', None)))
            temp = channel_temp_specs_for(mfr, mpn)
            if temp:
                specs.channel_temp = temp
    return parts


datasheets_db = ObjectDatabase[Tuple[Mfr, Mpn], DatasheetFields]('datasheets-lib',
                                                                 lambda d: (d.part.mfr, d.part.mpn) if hasattr(d,
                                                                                                               'part') else (
                                                                 d.mfr, d.mpn))

if __name__ == '__main__':
    parts = load_parts()
    print('loaded', len(parts))
