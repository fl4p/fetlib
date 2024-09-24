import os
import pickle
from copy import copy
from typing import Iterable, Tuple, Dict, Optional

from dslib.cache import acquire_file_lock
from dslib.parts_discovery import DiscoveredPart
from dslib.spec_models import MosfetSpecs


class Part:
    def __init__(self, mpn=None, mfr=None, specs=None, discovered: 'DiscoveredPart'=None):
        self.mpn = mpn or discovered.mpn
        self.mfr = mfr or discovered.mfr
        self.specs: 'MosfetSpecs' = specs
        self.discovered = discovered

    @property
    def is_fet(self):
        assert self.specs
        from dslib.spec_models import MosfetSpecs
        return isinstance(self.specs, MosfetSpecs)


def lib_file_path():
    return os.path.realpath(os.path.dirname(__file__) + '/../parts-lib.pkl')

def lock_file_path():
    return lib_file_path() + '.lock'


Mfr = str
Mpn = str

_lib_mem: Optional[Dict[Tuple[Mfr, Mpn], Part]] = None


def load_parts(reload=False):
    global _lib_mem
    if _lib_mem and not reload:
        return _lib_mem.copy()

    with acquire_file_lock(lock_file_path(), kill_holder=False):
        if os.path.exists(lib_file_path()):
            with open(lib_file_path(), 'rb') as f:
                _lib_mem = pickle.load(f)
                return _lib_mem.copy()

    if _lib_mem is None:
        _lib_mem = {}

    return {}


def load_part(mpn, mfr) -> Part:
    if not _lib_mem:
        load_parts()
    return copy(_lib_mem.get((mfr, mpn)))


def add_parts(new_arts: Iterable[Part], overwrite=True):
    load_parts()
    for part in new_arts:
        k = (part.mfr, part.mpn)
        assert overwrite or k not in _lib_mem
        _lib_mem[k] = part

    with acquire_file_lock(lock_file_path(), kill_holder=False, max_time=20):
        with open(lib_file_path(), 'wb') as f:
            pickle.dump(_lib_mem, f)
