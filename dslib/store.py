import os
import pickle
import threading
import time
from copy import copy
from typing import Tuple, Dict, Optional, Generic, TypeVar, Callable, Union, List

from dslib.cache import acquire_file_lock
from dslib.field import DatasheetFields
from dslib.parts_discovery import DiscoveredPart
from dslib.spec_models import MosfetSpecs


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
        self._thread:Optional[threading.Thread] = None
        self._running = False

    def add(self, items:dict):
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
                self._write_func(dict(items))
            else:
                time.sleep(4)
                waiting += 1
                if waiting == 10:
                    self._running = False


class ObjectDatabase(Generic[K, T]):
    def __init__(self, name, key_func: Optional[Callable[[T], K]] = None):
        self._lib_path = os.path.realpath(os.path.dirname(__file__) + f'/../{name}.pkl')
        self._lck_path = self._lib_path + '.lock'

        self._lib_mem: Optional[Dict[K, T]] = None
        self._key_func = key_func

        self._buffer = WriteBuffer(self.add)

    def load(self, reload=False) -> Dict[K, T]:
        if self._lib_mem and not reload:
            return self._lib_mem.copy()

        with acquire_file_lock(self._lck_path, kill_holder=False):
            if os.path.exists(self._lib_path):
                with open(self._lib_path, 'rb') as f:
                    self._lib_mem = pickle.load(f)
                    return self._lib_mem.copy()

        if self._lib_mem is None:
            self._lib_mem = {}

        return {}

    def load_obj(self, key: K) -> T:
        if not self._lib_mem:
            self.load()
        key = self._key_func(key)
        return copy(self._lib_mem.get(key))

    def _items_to_dict(self, items):
        if isinstance(items, list):
            assert self._key_func is not None
            items = dict((self._key_func(o), o) for o in items)
        else:
            assert self._key_func is None
        return items

    def add(self, new_arts: Union[Dict[K, T], List[T]], overwrite=True):
        self.load()

        new_arts = self._items_to_dict(new_arts)

        for k, part in new_arts.items():
            assert overwrite or k not in self._lib_mem
            self._lib_mem[k] = part

        with acquire_file_lock(self._lck_path, kill_holder=False, max_time=20):
            with open(self._lib_path, 'wb') as f:
                pickle.dump(self._lib_mem, f)

    def add_background(self, items: Union[Dict[K, T], List[T]], overwrite=True):
        assert overwrite == True
        items = self._items_to_dict(items)
        self._buffer.add(items)


Mfr = str
Mpn = str
parts_db = ObjectDatabase[Tuple[Mfr, Mpn], Part]('parts-lib', lambda p: (p.mfr, p.mpn))


def load_parts():
    return parts_db.load()


datasheets_db = ObjectDatabase[Tuple[Mfr, Mpn], DatasheetFields]('datasheets-lib', lambda d: (d.part.mfr, d.part.mpn) if hasattr(d, 'part') else (d.mfr, d.mpn))

