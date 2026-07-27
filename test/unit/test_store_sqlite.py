"""The sqlite blob backend of dslib.store.

The point of the migration is that reading ONE record stops costing the whole database:
every joblib worker in read_parts_datasheets called load_obj() and unpickled 150 MB (~3.5 s,
~1.5 GB resident) to read two records. So the headline test here does not assert "it
returned the right record" -- that would pass just as well on the old whole-file store. It
asserts HOW MANY ROWS WERE READ, which is the property that actually changed.

Likewise the merge test is written so that it FAILS on the pickle implementation: merging
against this process's stale snapshot instead of the row on disk is the defect, and a test
that both backends pass would not be measuring it.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest  # noqa: E402

from dslib.field import (DatasheetFields, Field, MpnMfr,  # noqa: E402
                         merge_keeping_absent_symbols)
from dslib.store import ObjectDatabase, _SqliteBackend, _encode_key, _decode_key  # noqa: E402

KEY_FUNC = (lambda d: (d.part.mfr, d.part.mpn) if hasattr(d, 'part') else (d.mfr, d.mpn))


def _ds(mpn, mfr='mfr', **syms):
    ds = DatasheetFields(mfr, mpn)
    for sym, (val, unit) in syms.items():
        ds.add(Field(sym, min=float('nan'), typ=float('nan'), max=val, unit=unit))
    return ds


def _db(tmp_path, name='t'):
    db = ObjectDatabase(name, key_func=KEY_FUNC)
    db._lib_path = str(tmp_path / (name + '.pkl'))  # no .pkl there -> brand new sqlite
    return db


# ------------------------------------------------------------------ the headline property
def test_load_obj_reads_exactly_one_row(tmp_path):
    """THE reason for the migration. Not 'it found the record' -- how much it had to read.

    A regression here (e.g. someone reintroducing a full materialisation inside load_obj)
    would still return correct data and still pass every other test in this file, while
    quietly restoring the 1.5 GB-per-worker cost.
    """
    seed = _db(tmp_path)
    seed.add([_ds('A', Rds_on=(1.0, 'mOhm')), _ds('B', Rds_on=(2.0, 'mOhm')),
              _ds('C', Rds_on=(3.0, 'mOhm'))])

    db = _db(tmp_path)
    backend = db._backend_or_resolve()
    cx = backend._conn()

    statements = []
    cx.set_trace_callback(statements.append)
    got = db.load_obj(MpnMfr('mfr', mpn='B'))
    cx.set_trace_callback(None)

    assert got is not None and got.part.mpn == 'B'
    selects = [s for s in statements if s.lstrip().upper().startswith('SELECT')]
    assert len(selects) == 1, 'expected one keyed SELECT, got: %r' % selects
    # the trace callback reports the statement with parameters already expanded, so the
    # bound key is visible here -- which is itself the evidence it was a keyed lookup
    assert 'WHERE k =' in selects[0] and '"mfr","B"' in selects[0]
    # and it must NOT have populated a full cache behind our back
    assert db._cache_complete is False
    assert len(db._cache) == 1


def test_load_obj_missing_key_returns_none(tmp_path):
    db = _db(tmp_path)
    db.add([_ds('A', Rds_on=(1.0, 'mOhm'))])
    assert db.load_obj(MpnMfr('mfr', mpn='NOPE')) is None


# ------------------------------------------------------------------ identity semantics
def test_load_hands_out_stable_instances(tmp_path):
    """load_parts() mutates the objects load() returns and MosfetSpecs.from_mpn reads them
    back via load_obj(). If those are different instances the attach silently does nothing
    and every curve/Qrr feature falls back for 100% of parts while appearing to work."""
    seed = _db(tmp_path)
    seed.add([_ds('A', Rds_on=(1.0, 'mOhm'))])

    db = _db(tmp_path)
    first = db.load()
    second = db.load()
    assert first[('mfr', 'A')] is second[('mfr', 'A')]

    after_reload = db.load(reload=True)
    assert after_reload[('mfr', 'A')] is not first[('mfr', 'A')]


def test_mutation_through_load_is_visible_to_load_obj(tmp_path):
    """The load_parts() -> from_mpn contract, pinned."""
    seed = _db(tmp_path)
    seed.add([_ds('A', Rds_on=(1.0, 'mOhm'))])

    db = _db(tmp_path)
    db.load()[('mfr', 'A')].attached_marker = 'curve'
    got = db.load_obj(MpnMfr('mfr', mpn='A'))
    assert getattr(got, 'attached_marker', None) == 'curve'

    db.unload()
    assert getattr(db.load_obj(MpnMfr('mfr', mpn='A')), 'attached_marker', None) is None


def test_load_after_partial_load_obj_keeps_the_handed_out_instance(tmp_path):
    seed = _db(tmp_path)
    seed.add([_ds('A', Rds_on=(1.0, 'mOhm')), _ds('B', Rds_on=(2.0, 'mOhm'))])

    db = _db(tmp_path)
    db.load_obj(MpnMfr('mfr', mpn='A'))
    held = db._cache[('mfr', 'A')]
    full = db.load()
    assert full[('mfr', 'A')] is held, 'a full load replaced an already-shared instance'
    assert set(full) == {('mfr', 'A'), ('mfr', 'B')}


# ------------------------------------------------- the cross-process merge (the real fix)
def test_merge_reconciles_against_disk_not_a_stale_snapshot(tmp_path):
    """Calibration against the known-bad behaviour.

    Handle A loads (taking a snapshot), handle B writes new symbols, then A adds with
    merge=. On the old whole-file store, A merged against ITS OWN stale snapshot and then
    rewrote the entire file, so B's write vanished. Here the merge reads the row inside the
    write transaction, so B survives.

    This test is expected to FAIL on the pickle backend -- see the companion below, which
    pins that so this one keeps measuring something real.
    """
    seed = _db(tmp_path)
    seed.add([_ds('X', Rds_on=(16.0, 'mOhm'))])

    a = _db(tmp_path)
    a.load()                                     # A takes its snapshot HERE

    b = _db(tmp_path)
    b.add([_ds('X', Rds_on=(16.0, 'mOhm'), Qrr=(120.0, 'nC'))],
          merge=merge_keeping_absent_symbols)    # B adds a symbol A has never seen

    a.add([_ds('X', Rds_on=(15.0, 'mOhm'))], merge=merge_keeping_absent_symbols)

    final = _db(tmp_path).load_obj(MpnMfr('mfr', mpn='X'))
    assert 'Qrr' in final.fields_lists, "B's concurrent write was clobbered by A's snapshot"
    assert final.fields_filled['Qrr'].max == 120.0
    assert final.fields_filled['Rds_on'].max == 15.0, 'the fresher value must still win'


def test_pickle_backend_still_loses_the_concurrent_write(tmp_path, monkeypatch):
    """The negative control. If this ever starts passing, the test above has stopped
    discriminating and its assertion is no longer evidence of anything."""
    monkeypatch.setenv('FETLIB_STORE', 'pickle')
    seed = _db(tmp_path, 'p')
    seed.add([_ds('X', Rds_on=(16.0, 'mOhm'))])

    a = _db(tmp_path, 'p')
    a.load()
    b = _db(tmp_path, 'p')
    b.add([_ds('X', Rds_on=(16.0, 'mOhm'), Qrr=(120.0, 'nC'))],
          merge=merge_keeping_absent_symbols)
    a.add([_ds('X', Rds_on=(15.0, 'mOhm'))], merge=merge_keeping_absent_symbols)

    final = _db(tmp_path, 'p').load_obj(MpnMfr('mfr', mpn='X'))
    assert 'Qrr' not in final.fields_lists, (
        'the pickle backend no longer loses a concurrent write -- the sqlite merge test '
        'is no longer a discriminating check')


# ------------------------------------------------------------------ deletes
def test_del_obj_missing_key_raises_unless_ignored(tmp_path):
    db = _db(tmp_path)
    db.add([_ds('A', Rds_on=(1.0, 'mOhm'))])
    assert db.del_obj(MpnMfr('mfr', mpn='A')) is True
    assert db.count() == 0
    with pytest.raises(KeyError):
        db.del_obj(MpnMfr('mfr', mpn='A'))
    assert db.del_obj(MpnMfr('mfr', mpn='A'), ignore_missing=True) is False


def test_del_obj_does_not_rewrite_other_records(tmp_path):
    db = _db(tmp_path)
    db.add([_ds('A', Rds_on=(1.0, 'mOhm')), _ds('B', Rds_on=(2.0, 'mOhm'))])
    db.del_obj(MpnMfr('mfr', mpn='A'))
    assert set(_db(tmp_path).keys()) == {('mfr', 'B')}


# ------------------------------------------------------------------ save_all's prune gate
def test_save_all_does_not_delete_by_default(tmp_path):
    """The old `_lib_mem = d; _write()` silently deleted everything absent from d."""
    db = _db(tmp_path)
    db.add([_ds('A', Rds_on=(1.0, 'mOhm')), _ds('B', Rds_on=(2.0, 'mOhm'))])
    db.save_all({('mfr', 'A'): _ds('A', Rds_on=(9.0, 'mOhm'))})
    assert set(_db(tmp_path).keys()) == {('mfr', 'A'), ('mfr', 'B')}


def test_save_all_refuses_a_mass_prune(tmp_path):
    db = _db(tmp_path)
    db.add([_ds('P%d' % i, Rds_on=(1.0, 'mOhm')) for i in range(100)])
    keep = {('mfr', 'P0'): _ds('P0', Rds_on=(1.0, 'mOhm'))}
    with pytest.raises(ValueError, match='refusing to delete'):
        db.save_all(keep, delete_missing=True)
    assert _db(tmp_path).count() == 100, 'the refused prune must not have partially applied'


def test_save_all_allows_a_small_prune(tmp_path):
    """Monotone in the right direction: the gate refuses MORE deletion, not less."""
    db = _db(tmp_path)
    db.add([_ds('P%d' % i, Rds_on=(1.0, 'mOhm')) for i in range(100)])
    keep = {('mfr', 'P%d' % i): _ds('P%d' % i, Rds_on=(1.0, 'mOhm')) for i in range(99)}
    db.save_all(keep, delete_missing=True)
    assert _db(tmp_path).count() == 99


@pytest.mark.parametrize('n', [1, 2, 3, 10, 100])
def test_save_all_never_wipes_the_whole_store(tmp_path, n):
    """The far tail, not just the near miss.

    The percentage gate needs a floor so a small store can still lose one stray record,
    but a floor is anti-monotone at the bottom: with exactly ONE record the floor IS the
    whole store, so 'delete everything' -- the single worst input -- was the one case that
    passed. Swept across sizes because the hole only existed at n == 1.
    """
    db = _db(tmp_path, 'wipe%d' % n)
    db.add([_ds('P%d' % i, Rds_on=(1.0, 'mOhm')) for i in range(n)])
    with pytest.raises(ValueError, match='refusing to delete'):
        db.save_all({}, delete_missing=True)
    assert _db(tmp_path, 'wipe%d' % n).count() == n


def test_save_all_wipe_is_possible_with_an_explicit_override(tmp_path):
    """The gate must be escapable on purpose, or callers will reach past it."""
    db = _db(tmp_path)
    db.add([_ds('A', Rds_on=(1.0, 'mOhm'))])
    db.save_all({}, delete_missing=True, max_delete_frac=1.0)
    assert _db(tmp_path).count() == 0


def test_save_all_on_an_empty_store_is_not_a_prune(tmp_path):
    """What the gate does when it cannot evaluate its input: an empty store has nothing to
    protect, and must not raise on a first write."""
    db = _db(tmp_path)
    db.save_all({('mfr', 'A'): _ds('A', Rds_on=(1.0, 'mOhm'))}, delete_missing=True)
    assert _db(tmp_path).count() == 1


# ------------------------------------------------------------------ payload fidelity
def test_nan_and_numpy_and_cond_shapes_round_trip(tmp_path):
    np = pytest.importorskip('numpy')
    db = _db(tmp_path)

    ds = _ds('A', Rds_on=(1.0, 'mOhm'))
    f = ds.fields_filled['Rds_on']
    assert math.isnan(f.min), 'fixture no longer carries a NaN; the check below is empty'
    f.typ = np.float64(2.5)

    variants = ds.fields_lists['Rds_on']
    for cond in ({'Vgs': 10}, [('Vgs', 10)], None, 'Vgs=10V', {0: 'a', 1: ''}):
        v = Field('Qg', min=float('nan'), typ=float('nan'), max=1.0, unit='nC', cond=cond)
        ds.add(v)
        variants = ds.fields_lists['Qg']
    assert variants

    db.add([ds])
    got = _db(tmp_path).load_obj(MpnMfr('mfr', mpn='A'))
    g = got.fields_filled['Rds_on']
    assert math.isnan(g.min), 'NaN did not survive'
    assert isinstance(g.typ, np.float64) and g.typ == 2.5, 'numpy scalar demoted'
    conds = [x.cond for x in got.fields_lists['Qg']]
    assert any(isinstance(c, dict) for c in conds)
    assert any(c is None for c in conds)
    assert any(isinstance(c, str) for c in conds)


def test_record_missing_a_newer_attribute_round_trips(tmp_path):
    """Unpickling bypasses __init__, so older records simply lack newer attributes and the
    consumers use getattr guards. The store must not "helpfully" normalise that away."""
    db = _db(tmp_path)
    ds = _ds('A', Rds_on=(1.0, 'mOhm'))
    del ds.errors
    db.add([ds])
    got = _db(tmp_path).load_obj(MpnMfr('mfr', mpn='A'))
    assert not hasattr(got, 'errors')


def test_key_codec_round_trips():
    for key in [('infineon', 'IPT015N10N5'), ('ts', 'A/B "quoted"'), ('mfr', 'µnicode-Ω'),
                ('a', ''), 'scalar', ('a', 'b', 'c'), (('a', 'b'), 'c')]:
        got = _decode_key(_encode_key(key))
        assert got == key, '%r -> %r' % (key, got)
        # a decoded key must still be usable AS a key; json has no tuple, so a nested
        # tuple decoded naively comes back as an unhashable list
        hash(got)


# ------------------------------------------------------------------ corrupt data
def test_a_corrupt_blob_raises_rather_than_being_skipped(tmp_path):
    """Absence of evidence must not encode absence of the problem: the old store caught
    unpickle errors and returned {}, after which the next add() persisted that emptiness."""
    db = _db(tmp_path)
    db.add([_ds('A', Rds_on=(1.0, 'mOhm')), _ds('B', Rds_on=(2.0, 'mOhm'))])

    other = _db(tmp_path)
    cx = other._backend_or_resolve()._conn()
    cx.execute('UPDATE records SET blob = ? WHERE k = ?',
               (b'not a pickle', _encode_key(('mfr', 'A'))))

    fresh = _db(tmp_path)
    with pytest.raises(Exception):
        fresh.load()


def test_unknown_encoding_raises(tmp_path):
    db = _db(tmp_path)
    db.add([_ds('A', Rds_on=(1.0, 'mOhm'))])
    cx = _db(tmp_path)._backend_or_resolve()._conn()
    cx.execute('UPDATE records SET enc = 99')
    with pytest.raises(ValueError, match='unknown blob encoding'):
        _db(tmp_path).load()


# ------------------------------------------------------------------ backend resolution
def test_reading_lib_path_does_not_pin_the_backend(tmp_path):
    """A path accessor must not decide anything.

    It used to resolve AND memoise the backend, so a helper reading `_lib_path` merely to
    derive a lock filename pinned the store to sqlite before the caller had chosen. That is
    how test_db_write_is_monotone -- the guard against the 65,631-field incident -- silently
    stopped covering the pickle branch it was written against.
    """
    import pickle
    db = ObjectDatabase('lazy', key_func=KEY_FUNC)
    db._lib_path = str(tmp_path / 'lazy.pkl')
    _ = db._lib_path                       # the accidental read
    assert db._backend is None, '_lib_path resolved the backend as a side effect'

    with open(tmp_path / 'lazy.pkl', 'wb') as fh:   # a pickle appears afterwards
        pickle.dump({('mfr', 'A'): _ds('A', Rds_on=(1.0, 'mOhm'))}, fh)
    assert db.uses_sqlite is False, 'the earlier read had already chosen sqlite'


def test_a_compressed_store_stays_compressed(tmp_path):
    """Every later write must adopt the store's own encoding.

    If `add()` defaulted to uncompressed, a compressed DB would decompress itself one
    record at a time -- every row still perfectly readable, so nothing would ever look
    wrong; the file would just quietly grow back by 4x.
    """
    from dslib.store import ENC_ZLIB, ENC_PICKLE, _SqliteBackend as SB

    path = str(tmp_path / 'z.sqlite3')
    seed = SB(path, enc=ENC_ZLIB)
    cx = seed._conn()
    cx.execute('BEGIN IMMEDIATE')
    seed._put(cx, ('mfr', 'A'), _encode_key(('mfr', 'A')), _ds('A', Rds_on=(1.0, 'mOhm')))
    cx.execute('COMMIT')
    seed.close()

    db = ObjectDatabase('z', key_func=KEY_FUNC)
    db._lib_path = str(tmp_path / 'z.pkl')
    db.add([_ds('B', Rds_on=(2.0, 'mOhm'))])          # a plain add, no encoding named

    encs = {e for (e,) in SB(path)._conn().execute('SELECT DISTINCT enc FROM records')}
    assert encs == {ENC_ZLIB}, 'the store decompressed itself: %r' % encs
    assert ENC_PICKLE not in encs
    assert set(_db_at(tmp_path, 'z').keys()) == {('mfr', 'A'), ('mfr', 'B')}


def _db_at(tmp_path, name):
    db = ObjectDatabase(name, key_func=KEY_FUNC)
    db._lib_path = str(tmp_path / (name + '.pkl'))
    return db


def test_a_read_never_creates_a_store(tmp_path):
    """Looking at an absent store must not bring one into being.

    `_conn()` creates the file and schema on first use. When reads went through it, a
    glance at a store whose pickle was temporarily missing (fresh clone before `git lfs
    pull`, a repair script mid-rename) left an empty .sqlite3 behind -- and since sqlite is
    preferred over pickle, every later run then served {} from it, forever, with the 150 MB
    pickle sitting untouched next to it.
    """
    db = ObjectDatabase('ghost', key_func=KEY_FUNC)
    db._lib_path = str(tmp_path / 'ghost.pkl')

    assert db.load() == {}
    assert list(db.keys()) == [] and db.count() == 0
    assert db.load_obj(MpnMfr('mfr', mpn='A')) is None

    stray = [p.name for p in tmp_path.iterdir()]
    assert stray == [], 'a read materialised %r' % stray


def test_an_empty_sqlite_never_shadows_a_populated_pickle(tmp_path):
    """The other half of the same failure: an aborted migration must not read as an empty
    store. Serving {} from it would be the quietest possible data loss."""
    import pickle
    with open(tmp_path / 'aborted.pkl', 'wb') as fh:
        pickle.dump({('mfr', 'A'): _ds('A', Rds_on=(1.0, 'mOhm'))}, fh)

    empty = _SqliteBackend(str(tmp_path / 'aborted.sqlite3'))
    empty._conn()                                   # an empty but valid sqlite store
    empty.close()

    db = ObjectDatabase('aborted', key_func=KEY_FUNC)
    db._lib_path = str(tmp_path / 'aborted.pkl')
    with pytest.raises(RuntimeError, match='aborted migration'):
        db.load()


def test_save_all_partial_does_not_drop_records_on_either_backend(tmp_path, monkeypatch,
                                                                  ):
    """save_all's docstring promises delete_missing=False is non-destructive. The pickle
    backend used to swallow the flag and rewrite the whole file anyway -- and the cache
    still served the dropped keys, so the process doing it could not see the damage."""
    for backend in ('sqlite', 'pickle'):
        if backend == 'pickle':
            monkeypatch.setenv('FETLIB_STORE', 'pickle')
        else:
            monkeypatch.delenv('FETLIB_STORE', raising=False)
        name = 'partial-' + backend
        db = _db(tmp_path, name)
        db.add([_ds('A', Rds_on=(1.0, 'mOhm')), _ds('B', Rds_on=(2.0, 'mOhm'))])

        db.save_all({('mfr', 'A'): _ds('A', Rds_on=(9.0, 'mOhm'))})

        # re-read FROM DISK, not from the cache that would hide the loss
        fresh = _db(tmp_path, name)
        fresh.unload()
        on_disk = fresh.load()
        assert set(on_disk) == {('mfr', 'A'), ('mfr', 'B')}, \
            '%s backend dropped the omitted key' % backend
        assert on_disk[('mfr', 'A')].fields_filled['Rds_on'].max == 9.0


def test_del_obj_persists_on_both_backends(tmp_path, monkeypatch):
    """The converse of the fix above: _write() must still be a complete-view write, or a
    deletion gets resurrected from disk by the merge."""
    for backend in ('sqlite', 'pickle'):
        if backend == 'pickle':
            monkeypatch.setenv('FETLIB_STORE', 'pickle')
        else:
            monkeypatch.delenv('FETLIB_STORE', raising=False)
        name = 'del-' + backend
        db = _db(tmp_path, name)
        db.add([_ds('A', Rds_on=(1.0, 'mOhm')), _ds('B', Rds_on=(2.0, 'mOhm'))])
        db.del_obj(MpnMfr('mfr', mpn='A'))
        assert set(_db(tmp_path, name).keys()) == {('mfr', 'B')}, \
            '%s backend resurrected a deleted key' % backend


def test_a_failed_load_fails_fast_the_second_time(tmp_path):
    """compile_part_datasheet calls load_obj once per part in every joblib worker. Without
    a sticky failure, one unreadable store means thousands of full re-read attempts."""
    db = _db(tmp_path, 'sticky')
    db.add([_ds('A', Rds_on=(1.0, 'mOhm'))])

    broken = _db(tmp_path, 'sticky')
    cx = broken._backend_or_resolve()._conn()
    cx.execute('UPDATE records SET blob = ?', (b'not a pickle',))

    fresh = _db(tmp_path, 'sticky')
    reads = []
    fresh._backend_or_resolve()._conn().set_trace_callback(reads.append)
    for _ in range(3):
        with pytest.raises(Exception):
            fresh.load()
    selects = [s for s in reads if s.lstrip().upper().startswith('SELECT')]
    assert len(selects) == 1, 'the store was re-read after a known failure: %r' % selects

    fresh.unload()                       # ...and unload() is the retry hook
    with pytest.raises(Exception):
        fresh.load()


def test_existing_pickle_is_still_used(tmp_path):
    """An unmigrated checkout must keep working, unchanged."""
    import pickle
    p = tmp_path / 'legacy.pkl'
    with open(p, 'wb') as fh:
        pickle.dump({('mfr', 'A'): _ds('A', Rds_on=(1.0, 'mOhm'))}, fh)
    db = ObjectDatabase('legacy', key_func=KEY_FUNC)
    db._lib_path = str(p)
    assert db.uses_sqlite is False
    assert set(db.keys()) == {('mfr', 'A')}


def test_sqlite_wins_when_both_exist(tmp_path):
    import pickle
    db = _db(tmp_path, 'both')
    db.add([_ds('FROM_SQLITE', Rds_on=(1.0, 'mOhm'))])
    with open(tmp_path / 'both.pkl', 'wb') as fh:
        pickle.dump({('mfr', 'FROM_PICKLE'): _ds('FROM_PICKLE', Rds_on=(2.0, 'mOhm'))}, fh)
    assert set(_db(tmp_path, 'both').keys()) == {('mfr', 'FROM_SQLITE')}


def test_missing_sqlite_after_migration_refuses_to_serve_the_stale_pickle(tmp_path):
    """A silent fallback here would serve pre-migration data as if it were current."""
    import pickle
    with open(tmp_path / 'gone.pkl', 'wb') as fh:
        pickle.dump({('mfr', 'OLD'): _ds('OLD', Rds_on=(1.0, 'mOhm'))}, fh)
    (tmp_path / 'gone.migrated').write_text('1')
    os.unlink(tmp_path / 'gone.pkl')

    db = ObjectDatabase('gone', key_func=KEY_FUNC)
    db._lib_path = str(tmp_path / 'gone.pkl')
    with pytest.raises(FileNotFoundError, match='migrated to sqlite'):
        db.load()


# ------------------------------------------------------------------ isolation
def test_load_obj_works_in_a_forked_child(tmp_path):
    """read_parts_datasheets forks via joblib. A sqlite connection must not cross the fork;
    the child has to open its own or the file gets corrupted."""
    if not hasattr(os, 'fork'):
        pytest.skip('no fork')

    seed = _db(tmp_path)
    seed.add([_ds('A', Rds_on=(7.0, 'mOhm'))])

    db = _db(tmp_path)
    db.load_obj(MpnMfr('mfr', mpn='A'))          # parent opens a connection first

    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            got = db.load_obj(MpnMfr('mfr', mpn='A'))
            code = 0 if got is not None and got.fields_filled['Rds_on'].max == 7.0 else 2
        finally:
            os.close(r)
            os.write(w, b'x')
            os.close(w)
            os._exit(code)
    os.close(w)
    os.read(r, 1)
    os.close(r)
    _, status = os.waitpid(pid, 0)
    assert os.WEXITSTATUS(status) == 0, 'child could not read through an inherited store'
    assert db.load_obj(MpnMfr('mfr', mpn='A')) is not None, 'parent connection broken'


def test_snapshot_is_readable(tmp_path):
    db = _db(tmp_path)
    db.add([_ds('A', Rds_on=(1.0, 'mOhm'))])
    dest = str(tmp_path / 'snap.sqlite3')
    db.snapshot(dest)
    assert dict(_SqliteBackend(dest).iter_all()).keys() == {('mfr', 'A')}


def test_iter_items_streams_without_populating_the_cache(tmp_path):
    db = _db(tmp_path)
    db.add([_ds('A', Rds_on=(1.0, 'mOhm')), _ds('B', Rds_on=(2.0, 'mOhm'))])

    fresh = _db(tmp_path)
    seen = [k for k, _ in fresh.iter_items()]
    assert set(seen) == {('mfr', 'A'), ('mfr', 'B')}
    assert fresh._cache == {} and fresh._cache_complete is False


def test_keys_and_iter_agree_on_order_and_it_is_insertion_order(tmp_path):
    """Iteration order is part of the contract, not an implementation detail.

    test/v2_eval.py picks a SEEDED sample from keys(). Left to itself SQLite answers
    keys() from the UNIQUE(k) index -- sorted by key -- while iter_items() scans the table
    in rowid order. The two disagreed, so the same seed selected a different sample after
    the migration: no error, no failing test, just a silently different experiment.
    """
    inserted = ['M', 'A', 'Z', 'B']
    db = _db(tmp_path, 'order')
    for mpn in inserted:                     # one at a time, so rowid order != sorted order
        db.add([_ds(mpn)])

    fresh = _db(tmp_path, 'order')
    from_keys = [k[1] for k in fresh.keys()]
    from_iter = [k[1] for k, _ in fresh.iter_items()]
    from_load = [k[1] for k in _db(tmp_path, 'order').load()]

    assert from_keys == inserted, 'keys() is not in insertion order: %r' % from_keys
    assert from_keys == from_iter == from_load
    assert from_keys != sorted(from_keys), 'fixture cannot tell the two orders apart'


def test_order_survives_an_upsert_but_not_a_max_row_delete(tmp_path):
    """The precise limit of the ordering guarantee, pinned rather than assumed.

    Re-adding an existing key keeps its position (upsert leaves the id alone). But `id` is
    a plain INTEGER PRIMARY KEY, so deleting the row with the CURRENT MAX id frees that
    number for reuse -- the next insert lands mid-sequence instead of at the end. Recorded
    here so the ordering contract is not read as stronger than it is; making the column
    AUTOINCREMENT is the fix if it ever needs to hold across deletes.
    """
    db = _db(tmp_path, 'ord2')
    for mpn in ('A', 'B', 'C'):
        db.add([_ds(mpn)])

    db.add([_ds('A', Rds_on=(9.0, 'mOhm'))])          # upsert an existing key
    assert [k[1] for k in _db(tmp_path, 'ord2').keys()] == ['A', 'B', 'C'], \
        'an upsert moved a record'

    db.del_obj(MpnMfr('mfr', mpn='C'))                # C holds the max id
    db.add([_ds('D')])
    order = [k[1] for k in _db(tmp_path, 'ord2').keys()]
    assert order == ['A', 'B', 'D'], order            # D reused C's slot; here == the end
    assert set(order) == {'A', 'B', 'D'}


def test_iter_items_leaves_the_collector_alone(tmp_path):
    """A scan must not change process-global GC state.

    An earlier version suspended cyclic GC during iteration -- ~7% faster on a bare scan,
    but 2x SLOWER for any loop body that allocates, because the records are cyclic and
    accumulate with the collector off. Pinned so it does not come back.
    """
    import gc
    db = _db(tmp_path, 'gcx')
    db.add([_ds('A'), _ds('B'), _ds('C')])

    assert gc.isenabled(), 'fixture assumes gc starts enabled'
    for _ in _db(tmp_path, 'gcx').iter_items():
        assert gc.isenabled(), 'iter_items disabled the collector mid-scan'
    assert gc.isenabled()


def test_iter_items_filters_by_mfr(tmp_path):
    db = _db(tmp_path)
    db.add([_ds('A', mfr='infineon', Rds_on=(1.0, 'mOhm')),
            _ds('B', mfr='onsemi', Rds_on=(2.0, 'mOhm'))])
    got = [k for k, _ in _db(tmp_path).iter_items(mfr='onsemi')]
    assert got == [('onsemi', 'B')]
