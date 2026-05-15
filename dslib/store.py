import logging
import os
import pickle
import threading
import time
from copy import copy
from typing import Tuple, Dict, Optional, Generic, TypeVar, Callable, Union, List

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
        from dslib.spec_models import MosfetSpecs
        return isinstance(self.specs, MosfetSpecs)


T = TypeVar('T')
K = TypeVar('K')


class WriteBuffer():
    def __init__(self, write_func):
        self._write_func = write_func
        self._buffer = dict()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def add(self, items: dict):
        self._buffer.update(items)

        self._running = True
        if not self._thread or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop)
            self._thread.start()

    def _loop(self):
        waiting = 0
        while self._running:
            items = []
            while self._buffer:
                items.append(self._buffer.popitem())
            if items:
                self._write_func(items)
            else:
                time.sleep(4)
                waiting += 1
                if waiting == 10:
                    self._running = False


class ObjectDatabase(Generic[K, T]):
    def __init__(self, name, key_func: Optional[Callable[[T], K]] = None):
        self._lib_path = os.path.realpath(os.path.dirname(__file__) + f'/../data/{name}.pkl')
        self._lck_path = self._lib_path + '.lock'

        self._lib_mem: Optional[Dict[K, T]] = None
        self._key_func = key_func

        self._buffer = WriteBuffer(self.add)

    def load(self, reload=False) -> Dict[K, T]:
        if self._lib_mem and not reload:
            return self._lib_mem.copy()

        with acquire_file_lock(self._lck_path, kill_holder=False, max_time=60):
            if os.path.exists(self._lib_path):
                with open(self._lib_path, 'rb') as f:
                    try:
                        self._lib_mem = pickle.load(f)
                    except (AttributeError, ModuleNotFoundError) as e:
                        logging.warning(f'Failed to unpickle {self._lib_path}: %s', e)
                        # some types moved etc
                        self._lib_mem = {}
                    return self._lib_mem.copy()

        if self._lib_mem is None:
            self._lib_mem = {}

        return {}

    def keys(self):
        return self._lib_mem.keys()

    def load_obj(self, key: K) -> T:
        if not self._lib_mem:
            self.load()
        key = self._key_func(key)
        return copy(self._lib_mem.get(key))

    def del_obj(self, key: K, ignore_missing=False):
        self.load()
        key = self._key_func(key)
        if ignore_missing and key not in self._lib_mem:
            return False
        del self._lib_mem[key]
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
        with acquire_file_lock(self._lck_path, kill_holder=False, max_time=30):
            with open(self._lib_path, 'wb') as f:
                pickle.dump(self._lib_mem, f)

    def add(self, new_arts: Union[Dict[K, T], List[T]], overwrite=True):
        self.load()

        new_arts = self._items_to_dict(new_arts)

        for k, part in new_arts.items():
            assert overwrite or k not in self._lib_mem
            self._lib_mem[k] = part

        self._write()

    def add_background(self, items: Union[Dict[K, T], List[T]], overwrite=True):
        assert overwrite == True
        items = self._items_to_dict(items)
        self._buffer.add(items)


Mfr = str
Mpn = str
parts_db = ObjectDatabase[Tuple[Mfr, Mpn], Part]('parts-lib', key_func=lambda p: (p.mfr, p.mpn))


def load_parts():
    return parts_db.load()


datasheets_db = ObjectDatabase[Tuple[Mfr, Mpn], DatasheetFields]('datasheets-lib',
                                                                 lambda d: (d.part.mfr, d.part.mpn) if hasattr(d,
                                                                                                               'part') else (
                                                                 d.mfr, d.mpn))

if __name__ == '__main__':
    parts = load_parts()
    print('loaded', len(parts))
