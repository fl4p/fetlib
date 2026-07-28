import asyncio
import datetime
import hashlib
import os
import pickle
import random
import re
import string
import threading
import time
import traceback
from functools import wraps
from os.path import expanduser
from threading import Thread, Lock, RLock
from typing import Callable, Optional

import psutil

from dslib import get_logger


class _LazyPandas:
    """Defer `import pandas` until something actually touches `pd`.

    WHY: importing pandas costs ~1.7 s, and it dominated the cost of simply READING THE PARTS DB.
    dslib/store.py imports exactly one symbol from this module -- acquire_file_lock -- which does
    not use pandas at all; pandas is only needed by the dataframe disk-cache helpers below
    (read_parquet / read_pickle / to_timedelta / DataFrame). So every consumer that just wanted
    load_parts() was paying 1.7 s to build a dataframe stack it never called. Measured on
    `import dslib.store`: 2.18 s total, of which pandas was 1.67 s and the actual unpickle 0.21 s.

    SAFETY: this only works because every use of `pd` in this module is a plain attribute access
    inside a function body (`pd.read_pickle(...)`, `isinstance(df, pd.Series)`, ...). There is no
    `-> pd.DataFrame` annotation or `pd.X` default arg -- those are evaluated at DEF time, i.e. at
    import, and would silently defeat the whole thing. Nothing does `from dslib.cache import pd`.
    Keep it that way, or this quietly goes back to being eager.

    The proxy REPLACES itself in module globals on first touch, so only the first attribute access
    pays the indirection; everything after binds straight to the real module.
    """
    __slots__ = ()

    def __getattr__(self, name):
        import pandas
        globals()["pd"] = pandas
        return getattr(pandas, name)


pd = _LazyPandas()


def _lazy_timedelta(ttl):
    """Defer `pd.to_timedelta(ttl)` from DECORATION time to first CALL.

    mem_cache/disk_cache are decorator FACTORIES, so their bodies run when the decorator is
    APPLIED -- i.e. at import of every module that decorates. Converting ttl there touched `pd`
    and so re-imported pandas eagerly, which is exactly what _LazyPandas exists to avoid: it is
    how `import dslib.store` still paid for pandas via dslib/pdf/expr.py's module-level @mem_cache,
    even after the top-level import was made lazy.

    Every ttl consumer inside the two factories runs at CALL time, so deferring is safe, and a
    cached function that is never called never pays for pandas at all.
    """
    box = []

    def get():
        if not box:
            box.append(ttl if isinstance(ttl, datetime.timedelta) else pd.to_timedelta(ttl))
        return box[0]

    return get

# try:
#    from streamz.collection import Streaming
# except ImportError:
#    print('failed to import streamz module')

# from lib.data.util import concat, random_str
# from lib.util import to_closed_time_range, setup_custom_logger, to_iso, timedelta_to_str

home = expanduser("~")
data_dir = os.path.dirname(__file__) + "/../data"
cache_dir = os.path.realpath(data_dir + "/cache")
logger = get_logger()

# HOW DISK-CACHE EVICTION ACTUALLY WORKS -- read before adding a sweeper here.
#
# There is none, by design. `disk_cache` stores `(value, now() + ttl, meta)` per entry and
# `_try_read` refuses anything past its own `exp`, so every entry governs its own lifetime
# and a stale one is simply never served. Nothing deletes files; `data/cache/` therefore
# grows without bound (~17 GB) and is reclaimed deliberately, not on a timer.
#
# A blanket age-based sweep over this tree is NOT the fix, however tempting the disk usage
# makes it look: read_parts_datasheets is `@disk_cache(ttl='999d', ...)` (main.py), so an
# N-day sweeper deletes entries the decorator considers valid for years and buys a
# multi-day Tabula/OCR re-parse of ~6k datasheets. This file used to carry exactly such a
# sweeper -- `_disk_cache_housekeeping(days_max=7)`, reachable only from an influx helper
# that no longer had callers, and non-recursive besides, so it had never deleted a single
# nested entry. It was removed rather than "fixed", because fixing it as written was the
# destructive option. To reclaim space, prune whole subtrees on purpose with
# `delete_disk_cache_tree(prefix)` -- see apps/disk_cache_report.py.


def get_parquet_engine():
    try:
        import pyarrow
        return 'pyarrow'
    except ImportError:
        logger.warning("pyarrow not installed")
        try:
            import fastparquet
            return 'fastparquet'
        except ImportError:
            logger.warning("fastparquet not installed")
            return 'auto'


_parquet_engine = None


def parquet_engine():
    """Resolve the parquet engine on FIRST USE, not at import.

    This ran at module level and imported pyarrow (~0.32 s) on every `import dslib.cache` --
    including the one behind `import dslib.store`, i.e. every parts-DB read paid for pyarrow to
    answer a question only ParquetFileStore.write() ever asks. Same class of eager module-level
    work as the pandas import above and the regex tables in dslib/pdf/expr.py.
    """
    global _parquet_engine
    if _parquet_engine is None:
        _parquet_engine = get_parquet_engine()
    return _parquet_engine

import pytz


def now():
    return datetime.datetime.utcnow().replace(tzinfo=pytz.utc)


def random_str(n=12):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def init_cache():
    if not os.path.exists(cache_dir):
        mkdir_p(cache_dir)


def get_data_dir():
    return data_dir


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        import errno
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def touch(fname, times=None):
    with open(fname, 'a'):
        os.utime(fname, times)


def _get_fn(key, ext):
    path = cache_dir + "/" + key + "." + ext
    dn = os.path.dirname(path)
    # noinspection PyBroadException
    try:
        if not os.path.isdir(dn):
            mkdir_p(dn)
    except:
        pass
    return path


def delete_disk_cache_tree(prefix):
    """Delete the cache subtree at ``data/cache/<prefix>/**``.

    Returns True when a tree was actually removed, False when nothing exists at
    that prefix. Any other outcome raises -- this function must never report or
    imply a deletion that did not happen (its rmtree spent a year commented out
    while the log line above it said "deleting").

    ``prefix`` is joined with the same string concat the writer uses
    (``_get_fn``: ``cache_dir + "/" + key``), NOT os.path.join: module prefixes
    are absolute paths like ``/Users/.../parse.py`` (see disk_cache_key), which
    os.path.join would let replace cache_dir entirely. The concat re-roots them
    inside the cache, exactly where the kernel's slash-collapsing put the keys.
    The resolved target must stay inside data/cache: a prefix that escapes via
    ``..`` or a symlinked subtree raises ValueError rather than being skipped,
    because an escaping target means the caller's prefix is wrong and silently
    ignoring that hides the bug while still deleting whatever else looked fine.
    Deletion errors surface (no ignore_errors): this tree costs a multi-day
    reparse, so a half-deleted subtree must not look fully deleted.
    """
    import shutil
    if not isinstance(prefix, str) or len(prefix) <= 1:
        raise ValueError('refusing cache-tree delete: bad prefix %r' % (prefix,))
    root = os.path.realpath(cache_dir)
    real = os.path.realpath(root + "/" + prefix)
    if real == root or not real.startswith(root + os.sep):
        raise ValueError('refusing cache-tree delete: prefix %r resolves to %s, outside %s'
                         % (prefix, real, root))
    if not os.path.exists(real):
        return False
    if not os.path.isdir(real):
        raise NotADirectoryError('cache-tree prefix %r is a file, not a directory: %s' % (prefix, real))
    logger.warning('deleting %s/**', real)
    shutil.rmtree(real)
    return True


def delete_module_disk_cache_tree(mod):
    return delete_disk_cache_tree(get_module_cache_key_prefix(mod))


def _set_df_file_store_mtime(fn, df):
    try:
        if not df.empty:
            t = df.index[-1].timestamp()
            os.utime(fn, (t, t))
    except Exception as e:
        logger.error('Failed to set mtime for parquet file %s: %s', fn, e)


class CacheStorage:
    def get(self, key):
        raise NotImplementedError()

    def get_default(self, key, returns_default_value: Callable, ttl):
        raise NotImplementedError()

    def set(self, key, value, ttl, ignore_overwrite):
        raise NotImplementedError()

    def __delitem__(self, key):
        raise NotImplementedError()


class ParquetFileStore:
    def __init__(self):
        pass

    # noinspection PyMethodMayBeStatic
    def read(self, key):
        # noinspection PyBroadException
        try:
            fn = _get_fn(key, ext='parquet')
            df = pd.read_parquet(fn)
            if len(df.columns) == 1 and df.columns[0] == '__series':
                df = df.loc[:, '__series']
            elif len(df.columns) == 1 and df.columns[0] == '__empty':
                df = pd.DataFrame()

            touch(fn)
            return df
        except:
            return None

    # noinspection PyMethodMayBeStatic
    def write(self, key, df):
        fn = _get_fn(key, ext='parquet')
        if isinstance(df, pd.Series):
            df = pd.DataFrame({'__series': df})

        if not df.empty:
            df.index = df.index.tz_convert('UTC')
        elif len(df.columns) == 0:
            df = pd.DataFrame({'__empty': []})

        try:
            df.to_parquet(fn + '.tmp', engine=parquet_engine(), compression='snappy')
        except ValueError as e:
            # columns as MultiIndex fails !
            raise ValueError('failed to parquet dataframe: %s %s %s' % (e, df.columns, df.head()))

        os.replace(fn + '.tmp', fn)

        _set_df_file_store_mtime(fn, df)

    # noinspection PyMethodMayBeStatic
    def delete(self, key):
        fn = _get_fn(key, ext='parquet')
        os.path.exists(fn) and os.unlink(fn)


class PandasPickleFileStore:
    def __init__(self):
        pass

    def read(self, key):
        # noinspection PyBroadException
        try:
            fn = _get_fn(key, ext='pkl.gz')
            df = pd.read_pickle(fn)
            touch(fn)
            return df
        except:
            return None

    # noinspection PyMethodMayBeStatic
    def write(self, key, df):
        fn = _get_fn(key, ext='pkl.gz')
        df.to_pickle(fn + '.tmp', compression='gzip')
        os.replace(fn + '.tmp', fn)
        _set_df_file_store_mtime(fn, df)


class PickleFileStore:
    def __init__(self):
        pass

    def get_path(self, key):
        return _get_fn(key, ext='pickle')

    # noinspection PyMethodMayBeStatic
    def read(self, key):
        # noinspection PyBroadException
        try:
            fn = _get_fn(key, ext='pickle')
            with open(fn, 'rb') as fh:
                ret = pickle.load(fh)
            touch(fn)
            return ret
        except:
            return None

    # noinspection PyMethodMayBeStatic
    def write(self, key, df):
        assert isinstance(key, str)
        fn = _get_fn(key, ext='pickle')
        s = f'.{random_str(6)}.tmp'
        with open(fn + s, 'wb') as fh:
            pickle.dump(df, fh, pickle.HIGHEST_PROTOCOL)
        os.replace(fn + s, fn)
        # _set_df_file_store_mtime(fn, df)

    def delete(self, key):
        fn = _get_fn(key, ext='pickle')
        os.path.exists(fn) and os.unlink(fn)


class NoDataException(Exception):
    pass


def hashable_to_sha224(obj):
    return hashlib.sha224(bytes(str(obj), 'utf-8')).hexdigest()


dict_keys_t = type({}.keys())


# def _chunk_cache_default_store():
#    return PandasPickleFileStore

def get_module_cache_key_prefix(mod):
    """The prefix every disk_cache key of ``mod`` starts with: its ``__file__``.

    This is the single source for disk_cache_key's ``mod_file`` -- keys are
    ``<mod_file>/<path_hash>/<func>/...``, so the module's cache tree lives at
    ``data/cache/<mod_file>/`` (leading slash collapsed by the kernel). It used
    to return ``mod.__name__``, a dotted name like ``dslib.pdf.parse`` that
    matches nothing on disk and made delete_module_disk_cache_tree a no-op.
    Changing this changes every cache key -- don't."""
    return mod.__file__.replace('__mp_main__', '__main__')


def chunk_cache(chunk_time, no_data_exception=NoDataException, write_empty=True, store=ParquetFileStore(),
                upper_cache_time: Callable = None):
    chunk_time = pd.to_timedelta(chunk_time)
    _mem_cache = shared_managed_mem_cache()
    mem_ttl = datetime.timedelta(seconds=120)

    def decorate(target):
        import inspect
        mod = inspect.getmodule(target)
        func_name = (mod.__file__, target.__name__)
        _last_err_str = None

        @mem_cache(ttl=mem_ttl, ignore_kwargs={'args', 'kwargs', 'use_cache'}, synchronized=True)
        def _chunk(args, kwargs, tr, use_cache, cache_key_str):
            chunk = store.read(cache_key_str) if use_cache != False and store else None

            if chunk is None:
                try:
                    chunk = target(*args, time_range=tr, **kwargs)
                except no_data_exception:
                    chunk = pd.DataFrame()

                if write_empty or not chunk.empty and use_cache:
                    # print('cache write', cache_key_obj)
                    try:
                        store.write(cache_key_str, chunk)
                    except Exception as e:
                        nonlocal _last_err_str
                        if str(e) != _last_err_str:  # to prevent spamming logs
                            logger.warning('Error storing DataFrame using %s: %s', store, e)
                            _last_err_str = str(e)

            return chunk

        def _chunk_cache_wrapper(*args, **kwargs):
            _upper_cache_time = upper_cache_time() if upper_cache_time is not None else None

            _now = now()
            tr_inp = kwargs.pop('time_range', None)  # or kwargs.pop('since', None) or kwargs.pop('date_range', None)
            assert tr_inp, "chunk_cache decorator expects a `time_range`, `since` or `date_range` kwarg"
            tr_inp = to_closed_time_range(tr_inp)
            t0 = tr_inp[0].floor(chunk_time)
            t_end = min(tr_inp[1], _now)

            chunks = []
            while t0 < t_end:
                tr = [t0, min(t0 + chunk_time, t_end)]

                use_cache = store is not None and min(tr[1] - tr[0], _now - tr[1]) > chunk_time / 4
                if use_cache and _upper_cache_time is not None:
                    use_cache &= (tr[1] < _upper_cache_time)

                cache_key_obj = (func_name, to_hashable(args), to_hashable(kwargs), to_hashable(tr))
                cache_key_hash = hashlib.sha224(bytes(str(cache_key_obj), 'utf-8')).hexdigest()
                cache_key_str = '/'.join([mod.__name__, target.__name__, cache_key_hash])

                chunk = _mem_cache.get(cache_key_str)
                if chunk is None:
                    chunk = _chunk(args=args, kwargs=kwargs, tr=tr, use_cache=use_cache, cache_key_str=cache_key_str)

                if not chunk.empty:
                    if chunk.index[0] < tr[0]:
                        chunk = chunk.loc[tr[0]:]
                    assert chunk.index[0] >= tr[0], "chunk start %s < tr[0]=%s" % tuple(to_iso([chunk.index[0], tr[0]]))
                    if chunk.index[-1] > tr[1]:
                        store.delete(cache_key_str)
                        _mem_cache.set(cache_key_str, None, ttl=0)
                        raise ValueError("chunk ends %s, after tr[1] %s, %s" % (chunk.index[-1], tr[1], chunk.tail()))
                    chunks.append(chunk)

                t0 += chunk_time

            df = concat(chunks)

            return df

        return _chunk_cache_wrapper

    return decorate


# cache_key_str = hashlib.sha224(bytes(str(cache_key_obj), 'utf-8')).hexdigest()

def _sort_key(o):
    return str(o)


def to_hashable(obj):
    if is_hashable(obj):
        return obj  # , type(obj)

    if isinstance(obj, set):
        obj = sorted(obj, key=_sort_key)
    elif isinstance(obj, dict):
        obj = sorted(obj.items())
    elif isinstance(obj, dict_keys_t):
        obj = sorted(obj)

    if isinstance(obj, (list, tuple)):
        return tuple(map(to_hashable, obj))

    # if isinstance(obj, (Streaming, NDFrame)):
    #    return type(obj), id(obj)

    raise ValueError(
        "%r can not be hashed. Try providing a custom key function."
        % obj)


def is_hashable(obj):
    # noinspection PyBroadException
    try:
        hash(obj)
        return True
    except Exception:
        return False


class ManagedMemCache(CacheStorage):
    def __init__(self):
        self.cache = {}
        self._lock = RLock()
        self._now = now()
        self._housekeeping_thread: Optional[Thread] = None
        self._start_housekeeping()

    def _start_housekeeping(self):
        assert self._housekeeping_thread is None, "Housekeeping thread already running"
        self._housekeeping_thread = Thread(target=self._housekeeping, name='MemCacheHousekeeping', daemon=True)
        self._housekeeping_thread.start()

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop('lock', None)
        state.pop('housekeeping_thread', None)
        return state

    def __setstate__(self, state):
        assert not state.get('lock')
        assert not state.get('housekeeping_thread')
        self.__dict__.update(state)
        self._lock = RLock()
        self._start_housekeeping()

    # System memory above this percentage means drop the cache and back off.
    _MEM_PRESSURE_PCT = 92
    # How long to stay out of the way after shedding the cache, in seconds.
    _MEM_BACKOFF_S = 120

    def _housekeeping(self):
        """Expire entries, and shed the cache under system memory pressure.

        Everything slow happens OUTSIDE ``self._lock``. The first version held
        it across psutil, ``clear()`` (which measured the cache with
        pympler.asizeof), ``gc.collect()`` and a 120-second ``time.sleep`` — so
        on a machine sitting above the pressure threshold every ``get`` and
        ``set`` in the process blocked for two minutes at a time. That is a
        stall, not a slowdown: the caller is not doing less work, it is doing
        none. It also silently corrupts any measurement taken on such a
        machine, which is how it was found — benchmark processes sat at 0% CPU
        while the housekeeping thread slept holding the lock.

        The lock is now held only for the two operations that actually mutate
        the dict, each O(n) and no worse than the map itself.
        """
        while True:
            _now = now()
            self._now = _now + datetime.timedelta(seconds=15)

            with self._lock:
                for key, (value, expire_at) in list(self.cache.items()):
                    if _now > expire_at:
                        del self.cache[key]
                n_entries = len(self.cache)

            # A syscall, and nothing about it needs the cache held.
            mem_usage_percent = psutil.virtual_memory().percent
            shed = mem_usage_percent > self._MEM_PRESSURE_PCT and n_entries
            if shed:
                logger.warning('High memory usage %.1f%%, shedding mem cache (%d entries)',
                               mem_usage_percent, n_entries)
                self.clear()

            # Back off unlocked, so readers keep working while we stay small.
            if shed:
                time.sleep(self._MEM_BACKOFF_S)
            time.sleep(30)

    def set(self, key, value, ttl, ignore_overwrite=False):
        if not isinstance(ttl, datetime.timedelta):
            ttl = pd.to_timedelta(ttl)
        with self._lock:
            if not ignore_overwrite and key in self.cache and now() < self.cache[key][1] and value is not None:
                t = threading.currentThread()
                logger.warning(
                    'MMC: overwrite key %s expiring at %s (in %s) (cache might be inefficient due to race condition in thread %s#%s)',
                    key, self.cache[key][1], (self.cache[key][1] - now()), t.name, t.ident)
            self.cache[key] = (value, now() + ttl)

    def get(self, key):
        with self._lock:
            got = self.cache.get(key)
        if got is None or got[1] <= now():
            return None
        return got[0]

    def get_default(self, key, default, ttl):
        with self._lock:
            v = self.get(key)
            if v is None:
                v = default()
                self.set(key, v, ttl=ttl)
        return v

    def clear(self):
        """Drop every entry.

        Does NOT call ``size_bytes()``: that walks the whole object graph with
        pympler.asizeof purely to produce a log line, and it ran while holding
        the lock. Entry count carries the same operational signal for free.

        The old form also gated the clear itself on that measurement --
        ``if mb > 0: self.cache.clear()`` -- so any run where asizeof returned
        0 or raised left the cache fully populated while reporting nothing. A
        cache-shedding path that declines to shed when it cannot measure is the
        absence-of-evidence failure again, and this is the one place it matters
        most: it fires only under memory pressure.
        """
        with self._lock:
            n = len(self.cache)
            self.cache.clear()
        if n:
            logger.info('Cleared mem cache (%d entries)', n)
            import gc
            gc.collect()

    def __delitem__(self, key):
        with self._lock:
            del self.cache[key]

    def size_bytes(self):
        from pympler import asizeof
        return asizeof.asizeof(self.cache)

    def __getitem__(self, item):
        # TODO add locking?
        if item not in self:
            raise KeyError(item)
        return self.cache[item][0]

    def __contains__(self, item):
        # TODO add locking?
        return item in self.cache and self.cache[item][1] >= now()

    def print_stats(self):
        from pympler import asizeof
        size_by_key = {}
        with self._lock:
            items = list(self.cache.items())
        for key, (value, expire_at) in items:
            size_by_key[key] = asizeof.asizeof(value)

        cache_size = asizeof.asizeof(self.cache)
        print('ManagedMemCache size by key (total = %.1fMB):' % cache_size / 1e6)
        for key, size in sorted(size_by_key.items(), key=lambda kv: kv[1], reverse=True)[:20]:
            print('%20s: %8.1fkB' % (key[:20], size / 1e3))


_managed_mem_cache = None


def shared_managed_mem_cache() -> ManagedMemCache:
    global _managed_mem_cache
    if _managed_mem_cache is None:
        _managed_mem_cache = ManagedMemCache()
    return _managed_mem_cache


def disk_cache_key(mod, target, ignore_kwargs, args, kwargs):
    # TODO    target.__code__
    kwargs_cache = {k: v for k, v in kwargs.items() if k not in ignore_kwargs}
    cache_key_obj = (to_hashable(args), to_hashable(kwargs_cache))
    cache_key_hash = hashlib.sha224(bytes(str(cache_key_obj), 'utf-8')).hexdigest()

    mod_file = get_module_cache_key_prefix(mod)
    path_hash = hashlib.sha224(bytes(mod_file, 'utf-8')).hexdigest()[:4]

    cache_key_prefix = ''
    for a in args:
        if isinstance(a, str) and len(a) < 20:  # TODO increase 20 to 30
            cache_key_prefix += a + '_'
        else:
            break
    for k, a in kwargs.items():
        if isinstance(a, str) and len(a) < 20:
            cache_key_prefix += k + '=' + a + '_'
        else:
            break
    if cache_key_prefix:
        cache_key_prefix = re.sub(r'[^\w_. -]', '_', cache_key_prefix)

    cache_key_str = '/'.join([mod_file, path_hash, target.__name__, cache_key_prefix + cache_key_hash])
    return cache_key_str


def fallback_cache(exception=None, ignore_kwargs=None):
    if ignore_kwargs is None:
        ignore_kwargs = set()

    exception = exception or Exception
    disk_cache = PickleFileStore()

    def decorate(target):
        import inspect
        mod = inspect.getmodule(target)

        # noinspection PyBroadException
        @wraps(target)
        def _fallback_cache_wrapper(*args, **kwargs):
            cache_key_str = 'fb_' + disk_cache_key(mod, target, ignore_kwargs, args=args, kwargs=kwargs)

            try:
                ret = target(*args, **kwargs)
                try:
                    disk_cache.write(cache_key_str, ret)
                except Exception as _e:
                    logger.warning('Fall-back cache: error storing: %s', _e)
                    pass
            except exception as e:
                ret = disk_cache.read(cache_key_str)
                if ret is None:
                    logger.error('Fall-back cache: %s failed (%s) and no previous return value found', target, e)
                    raise e
                logger.warning('Fall-back cache: %s failed (%s), but recovered previous return value (key %s)', target,
                               e, cache_key_str)
                logger.warning('Stack: %s', traceback.format_exc())

            return ret

        return _fallback_cache_wrapper

    return decorate


class CacheStorageRedis(CacheStorage):
    def __init__(self, serializer):
        self.serializer = serializer
        # from lib.data.redis import r_tsc
        self.redis = None  # r_tsc
        self._lock = RLock()

    def get(self, key):
        v = self.redis.get('csr:' + key)
        if v is None:
            return None
        return self.serializer.loads(v)

    def get_default(self, key, default_value, ttl):
        with self._lock:
            v = self.get(key)
            if v is None:
                v = default_value()
                self.set(key, v, ttl=ttl)
        return v

    def set(self, key, value, ttl=None, ignore_overwrite=False):
        assert isinstance(key, str), "key must be string"
        ser_val = self.serializer.dumps(value)
        self.redis.set('csr:' + key, ser_val, px=ttl)

    def __delitem__(self, key):
        self.redis.delete('csr:' + key)


# noinspection PyShadowingNames
def mem_cache(ttl, touch=False, ignore_kwargs=None, synchronized=False, expired=None, ignore_rc=False,
              cache_storage: CacheStorage = shared_managed_mem_cache(),
              key_func: Callable = None):
    """
    Decorator
    :param touch: touch key time on hit
    :param ttl:
    :param ignore_kwargs: a set of keyword arguments to ignore when building the cache key
    :param expired Callable to evaluate whether the cached value has expired/invalidated
    :return:
    """

    if ignore_kwargs is None:
        ignore_kwargs = set()

    _ttl = _lazy_timedelta(ttl)      # NOT at decoration time — see _lazy_timedelta
    _mem_cache = cache_storage
    _lock_cache = shared_managed_mem_cache()

    def decorate(target):

        if key_func:
            def _cache_key_obj(args, kwargs):
                return key_func(*args, **kwargs)
        else:
            def _cache_key_obj(args, kwargs):
                kwargs_cache = {k: v for k, v in kwargs.items() if k not in ignore_kwargs}
                return (target, to_hashable(args), to_hashable(kwargs_cache))

        @wraps(target)
        def _inner_wrapper(cache_key_obj, args, kwargs):
            ret = _mem_cache.get(cache_key_obj)

            if expired and ret is not None and expired(ret):
                del _mem_cache[cache_key_obj]
                ret = None

            if ret is None:
                ret = target(*args, **kwargs)
                _mem_cache.set(cache_key_obj, ret, ttl=_ttl(), ignore_overwrite=ignore_rc)
            elif touch:
                _mem_cache.set(cache_key_obj, ret, ttl=_ttl(), ignore_overwrite=True)

            return ret

        if synchronized:
            target_lock = Lock()

            @wraps(target)
            def _mem_cache_synchronized_wrapper(*args, **kwargs):
                cache_key_obj = _cache_key_obj(args, kwargs)

                with target_lock:
                    lock = _lock_cache.get_default((cache_key_obj, target_lock), Lock, ttl=_ttl())

                with lock:
                    return _inner_wrapper(cache_key_obj, args, kwargs)

            return _mem_cache_synchronized_wrapper

        else:
            @wraps(target)
            def _mem_cache_wrapper(*args, **kwargs):
                cache_key_obj = _cache_key_obj(args, kwargs)
                return _inner_wrapper(cache_key_obj, args, kwargs)

            return _mem_cache_wrapper

    return decorate


_disk_cache_disabled = False

# Per-process memo for file-dependency content signatures, keyed by realpath ->
# ((realpath, mtime, size), sig). Bounds memo size to the number of distinct
# paths touched, and rehashes only when mtime/size actually change.
_file_sig_memo = {}
_file_sig_lock = Lock()


def _file_content_sig(fn: str) -> str:
    """Content-based signature of a file dependency, used in the disk-cache key
    INSTEAD of its mtime.

    WHY: keying on mtime meant any operation that rewrites mtimes without
    changing content -- a fresh clone, a file copy, and notably the 2026-07
    Git-LFS migration of the datasheets repo -- silently invalidated the ENTIRE
    disk cache, forcing every parse cold. Content hashing is stable across all of
    those; the cache only misses when the bytes actually differ.

    COST (measured): ~2.4 ms at p50 (669 KB), ~7 ms p90, ~49 ms p99, 0.6 s for the
    lone 178 MB outlier -- vs ~3 us for the old stat. Memoized per process by
    (realpath, mtime, size), so each file is hashed at most once per run
    regardless of how many cached stages key on it; an mtime-only bump re-hashes
    once to the SAME digest, so the cache key is unchanged. Adds ~0.6 s to a warm
    run over a few hundred candidates -- noise against minute-scale parses.

    Raises like os.path.getmtime did (FileNotFoundError on a missing path), so
    callers that previously relied on that behaviour are unaffected.
    """
    st = os.stat(fn)  # raises FileNotFoundError on a missing path, as getmtime did
    memo_key = (fn, st.st_mtime, st.st_size)
    with _file_sig_lock:
        cached = _file_sig_memo.get(fn)
    if cached is not None and cached[0] == memo_key:
        return cached[1]
    h = hashlib.sha256()
    with open(fn, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    sig = 'sha256:' + h.hexdigest()
    with _file_sig_lock:
        _file_sig_memo[fn] = (memo_key, sig)
    return sig


def _disk_cache_get_file_names(args, kwargs, pwd: str, deps, ignore_missing_inp_paths: bool):
    if not deps:
        return []

    file_names = []
    fd_arg_names = deps
    if isinstance(fd_arg_names, bool) and fd_arg_names == True:
        fd_arg_names = [0]
    for arg_name in fd_arg_names:
        if isinstance(arg_name, int):
            arg_val = args[arg_name] if arg_name < len(args) else None
        elif isinstance(arg_name, str) and ('.' in arg_name or '/' in arg_name):
            arg_val = arg_name
            if not os.path.isabs(arg_val):
                arg_val = os.path.join(pwd, arg_val)
        else:
            arg_val = kwargs.get(arg_name)
        if arg_val is None:
            if ignore_missing_inp_paths:
                arg_val = None
            else:
                raise ValueError('missing input file path arg %s' % arg_name)
        else:
            arg_val = os.path.realpath(arg_val)
        file_names.append(arg_val)
    return file_names


def disk_cache(ttl, ignore_kwargs=None, file_dependencies=None, out_files=None, salt=None,
               ignore_missing_inp_paths=False,
               hash_func_code=False, file_dep_sig='content'):
    """
    :param file_dep_sig: how each `file_dependencies` file enters the cache key.
        'content' (default) -> a memoized content hash, stable across mtime-only
        rewrites (fresh clone, file copy, the Git-LFS migration). 'mtime' -> the
        old os.path.getmtime() behaviour (cheaper stat, but any mtime bump misses
        the cache). Toggle per decorator; the two produce different keys, so
        switching a given function rebuilds its cache once.
    """
    if ignore_kwargs is None:
        ignore_kwargs = set()
    if file_dep_sig not in ('content', 'mtime'):
        raise ValueError("file_dep_sig must be 'content' or 'mtime', got %r" % file_dep_sig)

    disk_cache_store = PickleFileStore()
    _ttl = _lazy_timedelta(ttl)      # NOT at decoration time — see _lazy_timedelta

    def decorate(target):
        import inspect
        mod = inspect.getmodule(target)
        pwd = os.path.dirname(mod.__file__)

        source_code = inspect.getsource(target) if hash_func_code else None

        _dep_sig = (lambda fn: ('__mtime:' + fn, os.path.getmtime(fn))) if file_dep_sig == 'mtime' \
            else (lambda fn: ('__csig:' + fn, _file_content_sig(fn)))

        def _cache_key(*args, **kwargs):
            mtimes = {}
            if file_dependencies:
                mtimes = dict(
                    _dep_sig(fn)
                    for fn in _disk_cache_get_file_names(args, kwargs, pwd, file_dependencies, ignore_missing_inp_paths)
                    if
                    not ignore_missing_inp_paths or fn is not None)
            if salt is not None:
                # callable salts (also inside a tuple) resolve at call time, so decoration (import)
                # stays cheap when the salt is expensive to build (e.g. parse.py's regex tables).
                # The resolved value must equal what an eager salt would have been, or existing
                # cache entries are orphaned. NB hash_func_code hashes the decorator line too, so
                # the call-site spelling `salt=(regex_ver_salt, 'v01')` must not change either.
                if callable(salt):
                    mtimes['__salt__'] = salt()
                elif isinstance(salt, tuple):
                    mtimes['__salt__'] = tuple(s() if callable(s) else s for s in salt)
                else:
                    mtimes['__salt__'] = salt
            if hash_func_code:
                mtimes['__target_source'] = source_code
            cache_key_str = disk_cache_key(mod, target, ignore_kwargs, args=args, kwargs={**kwargs, **mtimes})
            return cache_key_str

        def _invalidate(*args, **kwargs):
            try:
                cache_key_str = _cache_key(*args, **kwargs)
                if cache_key_str is None:
                    return
            except:
                return
            disk_cache_store.delete(cache_key_str)

        is_coro = asyncio.iscoroutinefunction(target)

        def _prepare(args, kwargs):
            """Compute cache key and out-file state; return (key, out_fns, out_sizes, in_mtime, invalidate)."""
            cache_key_str = _cache_key(*args, **kwargs)
            inv = bool(_disk_cache_disabled)
            out_fns = None
            out_sizes = None
            in_mtime = None

            if out_files:
                # TODO store times in cache and
                assert file_dependencies
                out_fns = _disk_cache_get_file_names(args, kwargs, pwd, out_files, True)
                out_mtimes = {fn: os.path.getmtime(fn) if os.path.exists(fn) else 0 for fn in out_fns}
                out_sizes = {fn: os.path.getsize(fn) if os.path.exists(fn) else 0 for fn in out_fns}

                in_fns = _disk_cache_get_file_names(args, kwargs, pwd, file_dependencies, ignore_missing_inp_paths)
                in_mtime = max(os.path.getmtime(fn) for fn in in_fns)
                # Make-style "input newer than output -> rebuild" staleness guard.
                # ONLY under file_dep_sig='mtime': in 'content' mode the cache KEY already
                # encodes the input's content hash, so an mtime-only bump (fresh clone /
                # LFS checkout) yields the SAME key and the existing output is still valid
                # -- letting this comparison force inv=True would recompute the expensive
                # out_files producers (ocrmypdf/rasterize) for exactly the reason
                # file_dep_sig='content' exists to prevent. A genuine input-content change
                # changes the key (miss -> rebuild); a deleted/resized output is caught by
                # _meta_valid's size check. So the mtime override is redundant here.
                if file_dep_sig == 'mtime' and in_mtime > min(out_mtimes.values()):
                    inv = True

            return cache_key_str, out_fns, out_sizes, in_mtime, inv

        def _meta_valid(meta, out_fns, out_sizes):
            if not out_files:
                return True
            for param, disk_state in {
                # 'mtimes': out_mtimes,
                'sizes': out_sizes
            }.items():
                m_out_files = meta.get('out_files_' + param)
                if not m_out_files:
                    print('not meta data about out', param, 'cache is not valid', out_fns)
                    return False
                for fn, mt in disk_state.items():
                    if fn not in m_out_files or mt != m_out_files[fn]:
                        print(fn, 'changed', param, 'cache=', m_out_files.get(fn), 'disk=', mt,
                              '(', round(mt - m_out_files.get(fn)), ')')
                        return False
            return True

        def _try_read(cache_key_str, out_fns, out_sizes):
            """Return (value, hit) — hit=True when a fresh, valid cached value was found."""
            try:
                cache_val = disk_cache_store.read(cache_key_str)
                if cache_val is None:
                    return None, False
                if len(cache_val) == 2:
                    ret, exp = cache_val
                    meta = {}
                else:
                    ret, exp, meta = cache_val
                if now() <= exp and _meta_valid(meta, out_fns, out_sizes):
                    return ret, True
            except Exception as _e:
                logger.warning("Disk cache error reading %s: %s", cache_key_str, _e)
            return None, False

        def _build_meta(out_fns, in_mtime):
            meta = {}
            if out_files:
                for fn in out_fns:
                    if not os.path.exists(fn):
                        logger.warning('out file %s does not exist', fn)
                    else:
                        mt = os.stat(fn).st_mtime
                        if mt < in_mtime:
                            logger.warning('out file %s has mtime %s < input %s', fn, mt, in_mtime)
                meta['out_files_mtimes'] = {fn: os.path.getmtime(fn) if os.path.exists(fn) else 0 for fn in out_fns}
                meta['out_files_sizes'] = {fn: os.path.getsize(fn) if os.path.exists(fn) else 0 for fn in out_fns}
            return meta

        def _store(cache_key_str, ret, meta):
            try:
                disk_cache_store.write(cache_key_str, (ret, now() + _ttl(), meta))
            except Exception as _e:
                logger.warning('Disk cache: error storing: %s', _e)

        if is_coro:
            @wraps(target)
            async def _disk_cache_wrapper(*args, **kwargs):
                cache_key_str, out_fns, out_sizes, in_mtime, inv = _prepare(args, kwargs)

                if cache_key_str is None:
                    return await target(*args, **kwargs)

                if not inv:
                    ret, hit = _try_read(cache_key_str, out_fns, out_sizes)
                    if hit:
                        return ret

                ret = await target(*args, **kwargs)
                _store(cache_key_str, ret, _build_meta(out_fns, in_mtime))
                return ret
        else:
            # noinspection PyBroadException
            @wraps(target)
            def _disk_cache_wrapper(*args, **kwargs):
                cache_key_str, out_fns, out_sizes, in_mtime, inv = _prepare(args, kwargs)

                if cache_key_str is None:
                    return target(*args, **kwargs)

                if not inv:
                    ret, hit = _try_read(cache_key_str, out_fns, out_sizes)
                    if hit:
                        return ret

                ret = target(*args, **kwargs)
                _store(cache_key_str, ret, _build_meta(out_fns, in_mtime))
                return ret

        _disk_cache_wrapper.invalidate = _invalidate
        _disk_cache_wrapper.cache_key = _cache_key
        _disk_cache_wrapper.store = disk_cache_store

        return _disk_cache_wrapper

    return decorate


def disk_cache_disable(disable: bool):
    global _disk_cache_disabled
    if disable and not _disk_cache_disabled:
        logger.info('Disk cache disabled')
    _disk_cache_disabled = disable


setattr(disk_cache, 'disable', disk_cache_disable)


class NopLock:
    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        pass


def acquire_file_lock(fn, kill_holder, max_time=10):
    if os.name == 'nt':
        logger.warning('File locks not supported on Windows! (file %s)', fn)
        return NopLock()

    import signal
    import fcntl
    import backoff

    fh = open(fn, 'a+')

    @backoff.on_exception(backoff.expo, OSError, max_time=max_time, logger=None)  #
    def _lockf_backoff(_fh):

        fcntl.lockf(_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.seek(0), fh.truncate(), fh.seek(0)
        fh.write('%d' % os.getpid())
        fh.flush()
        # logger.info('%s lock acquired!', fn)

    try:
        _lockf_backoff(fh)
    except OSError:
        fh.seek(0)
        pid = int(fh.read())

        if kill_holder:
            logger.warning('%s locked by %d sending SIGTERM', fn, pid)
            os.kill(pid, signal.SIGTERM)
            try:
                _lockf_backoff(fh)
            except OSError:
                logger.warning('%s still locked by %d sending SIGKILL !', fn, pid)
                os.kill(pid, signal.SIGKILL)
                _lockf_backoff(fh)
        else:
            raise TimeoutError('%s locked by %d' % (fn, pid))

    return fh


init_cache()
