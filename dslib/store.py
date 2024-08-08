import os
import pickle
from copy import copy
from typing import Iterable


class Part:
    def __init__(self, mpn, mfr, specs):
        self.mpn = mpn
        self.mfr = mfr
        self.specs = specs

    @property
    def is_fet(self):
        assert self.specs
        from dslib.spec_models import MosfetSpecs
        return isinstance(self.specs, MosfetSpecs)

def lib_file_path():
    return os.path.realpath(os.path.dirname(__file__) + '/../parts-lib.pkl')

_lib_mem = None

def load_parts(reload=False):
    global _lib_mem
    if _lib_mem and not reload:
        return _lib_mem.copy()
    if os.path.exists(lib_file_path()):
        with open(lib_file_path(), 'rb') as f:
            _lib_mem = pickle.load(f)
            return _lib_mem.copy()
    return {}

def load_part(mpn, mfr) ->Part:
    if not _lib_mem:
        load_parts()
    return copy(_lib_mem.get((mfr, mpn)))

def add_parts(new_arts: Iterable[Part], overwrite=True):
    load_parts()
    for part in new_arts:
        k = (part.mfr, part.mpn)
        assert overwrite or k not in _lib_mem
        _lib_mem[k] = part
    with open(lib_file_path(), 'wb') as f:
        pickle.dump(_lib_mem, f)