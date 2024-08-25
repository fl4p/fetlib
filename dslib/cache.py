import datetime
import hashlib
import os
import pickle
import random
import string
import threading
import time
import traceback
from functools import wraps
from os.path import expanduser
from threading import Thread, Lock, RLock
from typing import Callable, Optional, Tuple, Union

import pandas as pd
import psutil
from pandas.core.generic import NDFrame

from dslib import get_logger

try:
    from streamz.collection import Streaming
except ImportError:
    print('failed to import streamz module')

# from lib.data.util import concat, random_str
# from lib.util import to_closed_time_range, setup_custom_logger, to_iso, timedelta_to_str

home = expanduser("~")
data_dir = os.path.dirname(__file__) + "/../data"
cache_dir = os.path.realpath(data_dir + "/cache")
ran_housekeeping = False
logger = get_logger()


def get_parquet_engine():
    try:
        import pyarrow
        return 'pyarrow'
    except ImportError:
        logger.warning("pyarrow not installed, using engine `fastparquet`")
        return 'fastparquet'


parquet_engine = get_parquet_engine()

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


def _disk_cache_housekeeping(days_max=7):
    global ran_housekeeping
    if ran_housekeeping:
        return

    _now = time.time()

    if os.path.exists(cache_dir):
        for f in os.listdir(cache_dir):
            # noinspection PyBroadException
            try:
                fp = cache_dir + '/' + f
                ft = max(os.path.getmtime(fp), os.path.getatime(fp))
                if (_now - ft) // (24 * 3600) >= days_max:
                    os.unlink(fp)
            except:
                pass
    ran_housekeeping = True


def _get_cache_file(host, db, q, index_format: Union[Tuple[str], str]):
    h = hashlib.sha224(
        (((host + ":") if host is not None else '') + db + ">" + q + str(index_format)).encode('utf-8')).hexdigest()
    return cache_dir + "/" + h + ".pkl"


def read_influx_cache(**kwargs):
    try:
        cache_file = _get_cache_file(**kwargs)
        if os.path.exists(cache_file):
            touch(cache_file)
            df = pd.read_pickle(cache_file)
            return df
        else:
            return None
    finally:
        _disk_cache_housekeeping()


def write_influx_cache(df, **kwargs):
    df.to_pickle(_get_cache_file(**kwargs))


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
            df.to_parquet(fn + '.tmp', engine=parquet_engine, compression='snappy')
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


def to_hashable(obj):
    if is_hashable(obj):
        return obj  # , type(obj)

    if isinstance(obj, set):
        obj = sorted(obj)
    elif isinstance(obj, dict):
        obj = sorted(obj.items())

    if isinstance(obj, (list, tuple)):
        return tuple(map(to_hashable, obj))

    if isinstance(obj, (Streaming, NDFrame)):
        return type(obj), id(obj)

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

    def _housekeeping(self):
        while True:
            _now = now()
            self._now = _now + datetime.timedelta(seconds=15)
            with self._lock:
                for key, (value, expire_at) in list(self.cache.items()):
                    if _now > expire_at:
                        del self.cache[key]

                mem_usage_percent = psutil.virtual_memory().percent
                if mem_usage_percent > 92 and len(self.cache):
                    logger.warning('High memory usage %.1f', mem_usage_percent)
                    self.clear()
                    time.sleep(120)

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
        with self._lock:
            mb = (self.size_bytes() / 1e6) if self.cache else 0
            if mb > 1:
                logger.info('Clearing mem cache (size=%.1fMB)', mb)
            if mb > 0:
                self.cache.clear()
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

    mod_file = mod.__file__.replace('__mp_main__', '__main__')
    path_hash = hashlib.sha224(bytes(mod_file, 'utf-8')).hexdigest()[:4]

    cache_key_str = '/'.join([mod_file, path_hash, target.__name__, cache_key_hash])
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
            cache_key_str = disk_cache_key(mod, target, ignore_kwargs, args=args, kwargs=kwargs)

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

    ttl = pd.to_timedelta(ttl)
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
                _mem_cache.set(cache_key_obj, ret, ttl=ttl, ignore_overwrite=ignore_rc)
            elif touch:
                _mem_cache.set(cache_key_obj, ret, ttl=ttl, ignore_overwrite=True)

            return ret

        if synchronized:
            target_lock = Lock()

            @wraps(target)
            def _mem_cache_synchronized_wrapper(*args, **kwargs):
                cache_key_obj = _cache_key_obj(args, kwargs)

                with target_lock:
                    lock = _lock_cache.get_default((cache_key_obj, target_lock), Lock, ttl=ttl)

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


def disk_cache(ttl, ignore_kwargs=None, file_dependencies=None, salt=None):
    if ignore_kwargs is None:
        ignore_kwargs = set()

    disk_cache_store = PickleFileStore()
    ttl = pd.to_timedelta(ttl)

    def decorate(target):
        import inspect
        mod = inspect.getmodule(target)

        def _cache_key(*args, **kwargs):
            mtimes = {}
            if file_dependencies:
                fd_arg_names = file_dependencies
                if isinstance(fd_arg_names, bool) and fd_arg_names == True:
                    fd_arg_names = [0]
                for arg_name in fd_arg_names:
                    if isinstance(arg_name, int):
                        arg_val = args[arg_name] if arg_name < len(args) else None
                    else:
                        arg_val = kwargs.get(arg_name)
                    if arg_val is None:
                        return None
                    arg_val = os.path.realpath(arg_val)
                    mtimes['__mtime:' + arg_val] = os.path.getmtime(arg_val)
            if salt is not None:
                mtimes['__salt__'] = salt
            cache_key_str = disk_cache_key(mod, target, ignore_kwargs, args=args, kwargs={**kwargs, **mtimes})
            return cache_key_str

        def _invalidate(*args, **kwargs):
            cache_key_str = _cache_key(*args, **kwargs)
            if cache_key_str is None:
                return
            disk_cache_store.delete(cache_key_str)

        # noinspection PyBroadException
        @wraps(target)
        def _disk_cache_wrapper(*args, **kwargs):
            cache_key_str = _cache_key(*args, **kwargs)
            if cache_key_str is None:
                return target(*args, **kwargs)
            try:
                cache_val = disk_cache_store.read(cache_key_str)
                if cache_val is not None:
                    ret, exp = cache_val
                    if now() <= exp:
                        return ret
            except Exception as _e:
                logger.warning("Disk cache error reading %s: %s", cache_key_str, _e)

            ret = target(*args, **kwargs)
            try:
                disk_cache_store.write(cache_key_str, (ret, now() + ttl))
            except Exception as _e:
                logger.warning('Disk cache: error storing: %s', _e)
                pass

            return ret

        _disk_cache_wrapper.invalidate = _invalidate
        return _disk_cache_wrapper

    return decorate


init_cache()
