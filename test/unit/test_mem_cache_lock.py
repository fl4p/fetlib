"""ManagedMemCache housekeeping must never hold the lock while it is slow.

The bug: `_housekeeping` held `self._lock` across psutil, `clear()` (which
measured the cache with pympler.asizeof), `gc.collect()` and a 120-second
`time.sleep`. On a machine above the memory-pressure threshold, every `get` and
`set` in the process therefore blocked for two minutes at a time.

It was found by accident -- benchmark processes sat at 0% CPU making no
progress -- and it silently corrupts any measurement taken on such a machine.
This repo's own constants sweeps were invalidated by it twice.

The probe below runs in a SEPARATE THREAD on purpose. `self._lock` is an RLock,
so a same-thread `acquire(blocking=False)` succeeds even when the lock IS held
by that thread, and a test written that way passes against the broken code.
"""
import datetime
import os
import sys
import types
from threading import Thread

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import dslib.cache as cache_mod                        # noqa: E402
from dslib.cache import ManagedMemCache, now           # noqa: E402


class _Stop(Exception):
    """Breaks the otherwise-infinite housekeeping loop."""


def _bare_cache():
    """A ManagedMemCache with NO housekeeping thread running.

    __init__ starts one, and a live loop would race whatever the test drives
    by hand.
    """
    mc = object.__new__(ManagedMemCache)
    mc.cache = {}
    mc._lock = cache_mod.RLock()
    mc._now = now()
    mc._housekeeping_thread = None
    return mc


def _lock_free_from_other_thread(lock, timeout=0.4):
    """Can a DIFFERENT thread take the lock right now?"""
    res = []

    def probe():
        got = lock.acquire(timeout=timeout)
        if got:
            lock.release()
        res.append(got)

    t = Thread(target=probe)
    t.start()
    t.join(timeout + 1.0)
    return bool(res) and res[0]


def _under_pressure(monkeypatch, percent=99.0):
    monkeypatch.setattr(cache_mod.psutil, 'virtual_memory',
                        lambda: types.SimpleNamespace(percent=percent))


def test_backoff_sleep_does_not_hold_the_lock(monkeypatch):
    mc = _bare_cache()
    mc.cache['k'] = ('v', now() + datetime.timedelta(hours=1))
    _under_pressure(monkeypatch)

    seen = []

    def fake_sleep(secs):
        seen.append((secs, _lock_free_from_other_thread(mc._lock)))
        raise _Stop

    monkeypatch.setattr(cache_mod.time, 'sleep', fake_sleep)
    with pytest.raises(_Stop):
        mc._housekeeping()

    assert seen, 'housekeeping never slept'
    secs, lock_was_free = seen[0]
    assert secs == mc._MEM_BACKOFF_S, f'expected the backoff sleep first, got {secs}'
    assert lock_was_free, 'lock was HELD during the memory-pressure backoff'


def test_idle_sleep_does_not_hold_the_lock(monkeypatch):
    """The ordinary 30 s tick must not hold it either."""
    mc = _bare_cache()
    _under_pressure(monkeypatch, percent=10.0)          # no pressure

    seen = []

    def fake_sleep(secs):
        seen.append((secs, _lock_free_from_other_thread(mc._lock)))
        raise _Stop

    monkeypatch.setattr(cache_mod.time, 'sleep', fake_sleep)
    with pytest.raises(_Stop):
        mc._housekeeping()

    assert seen and seen[0][1], 'lock was HELD during the idle sleep'


def test_pressure_actually_sheds_the_cache(monkeypatch):
    """Direction, not just 'it did not deadlock'.

    A fix that stopped shedding under pressure would pass the lock tests above
    while removing the behaviour they exist to protect.
    """
    mc = _bare_cache()
    mc.cache['k'] = ('v', now() + datetime.timedelta(hours=1))
    _under_pressure(monkeypatch)
    monkeypatch.setattr(cache_mod.time, 'sleep', lambda s: (_ for _ in ()).throw(_Stop()))
    with pytest.raises(_Stop):
        mc._housekeeping()
    assert mc.cache == {}, 'cache was not shed under memory pressure'


def test_no_pressure_keeps_unexpired_entries(monkeypatch):
    mc = _bare_cache()
    mc.cache['k'] = ('v', now() + datetime.timedelta(hours=1))
    _under_pressure(monkeypatch, percent=10.0)
    monkeypatch.setattr(cache_mod.time, 'sleep', lambda s: (_ for _ in ()).throw(_Stop()))
    with pytest.raises(_Stop):
        mc._housekeeping()
    assert 'k' in mc.cache, 'entry dropped without memory pressure'


def test_clear_sheds_without_measuring_the_graph(monkeypatch):
    """clear() must not depend on size_bytes(), in either direction.

    The old form was `mb = size_bytes()/1e6 ... if mb > 0: self.cache.clear()`,
    so a run where asizeof returned 0 or raised left the cache fully populated
    while reporting nothing -- a shedding path that declines to shed exactly
    when it cannot measure.
    """
    mc = _bare_cache()
    mc.cache['k'] = ('v', now() + datetime.timedelta(hours=1))

    def boom():
        raise AssertionError('clear() must not call size_bytes()')

    monkeypatch.setattr(mc, 'size_bytes', boom)
    mc.clear()
    assert mc.cache == {}


def test_expired_entries_are_dropped(monkeypatch):
    mc = _bare_cache()
    mc.cache['old'] = ('v', now() - datetime.timedelta(seconds=1))
    mc.cache['new'] = ('v', now() + datetime.timedelta(hours=1))
    _under_pressure(monkeypatch, percent=10.0)
    monkeypatch.setattr(cache_mod.time, 'sleep', lambda s: (_ for _ in ()).throw(_Stop()))
    with pytest.raises(_Stop):
        mc._housekeeping()
    assert 'old' not in mc.cache and 'new' in mc.cache
