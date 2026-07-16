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
        #items = self._items_to_dict(items)
        self._buffer.add(items)


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
            if specs is None:
                continue
            mfr, mpn = (key if isinstance(key, tuple) else (getattr(p, 'mfr', None),
                                                            getattr(p, 'mpn', None)))
            if not getattr(specs, 'coss_curve', None):
                curve = coss_curve_for(mfr, mpn)
                if curve:
                    specs.coss_curve = curve
            # Ciss(V) pairs ride the same module; older pickled specs predate the
            # attribute, so set it via getattr-guarded assignment (unpickling bypasses
            # __init__). None -> consumers keep their gate-charge-partition Cgs basis.
            if ciss_curve_for is not None and not getattr(specs, 'ciss_curve', None):
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
    return parts


datasheets_db = ObjectDatabase[Tuple[Mfr, Mpn], DatasheetFields]('datasheets-lib',
                                                                 lambda d: (d.part.mfr, d.part.mpn) if hasattr(d,
                                                                                                               'part') else (
                                                                 d.mfr, d.mpn))

if __name__ == '__main__':
    parts = load_parts()
    print('loaded', len(parts))
