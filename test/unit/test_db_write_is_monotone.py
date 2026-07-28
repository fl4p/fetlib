"""A DB write must never delete a symbol -- dslib.field.merge_keeping_absent_symbols.

The failure this guards is not hypothetical. On 2026-07-27 a main.py run wrote a narrower
parse over the DB and 1348 records lost 65,631 fields; `ObjectDatabase.add` assigns
`_lib_mem[k] = record` and its `overwrite` parameter defaults to True, so the plainest
possible call was the destructive one.

Two things are asserted throughout, because only the first is usually tested:

  * the guard FIRES  -- the stored symbol survives a narrower write;
  * the guard's DIRECTION -- for symbols the fresh parse DID produce, the fresh value is
    what remains. A merge that kept the stored value everywhere would also "not lose
    fields", and would silently pin every record to its first-ever parse, defeating
    re-parses that exist to correct bad values.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dslib.field import DatasheetFields, Field, merge_keeping_absent_symbols  # noqa: E402
from dslib.store import ObjectDatabase  # noqa: E402


def _ds(mpn, **syms):
    """A record with one max-stat field per symbol: {'Rds_on': (16.0, 'mOhm'), ...}"""
    ds = DatasheetFields('mfr', mpn)
    for sym, (val, unit) in syms.items():
        ds.add(Field(sym, min=float('nan'), typ=float('nan'), max=val, unit=unit))
    return ds


def _max_of(ds, sym):
    return ds.fields_filled[sym].max


# --------------------------------------------------------------- the known-bad input
def test_narrower_write_does_not_delete_the_difference():
    """THE calibration case: the 12:03 shape, reduced. A fresh parse that simply did not
    look for Rg/Qrr must not turn 'did not look' into 'not there'."""
    stored = _ds('X', Rds_on=(16.0, 'mOhm'), Rg=(1.5, 'Ohm'), Qrr=(120.0, 'nC'))
    fresh = _ds('X', Rds_on=(15.0, 'mOhm'))

    # calibration: without the merge, the replacement loses them -- watch it fail first.
    assert set(fresh.fields_lists) == {'Rds_on'}
    assert 'Rg' not in fresh.fields_lists and 'Qrr' not in fresh.fields_lists

    merged = merge_keeping_absent_symbols(stored, fresh)

    assert set(merged.fields_lists) == {'Rds_on', 'Rg', 'Qrr'}
    # 1500.0, not 1.5: Field canonicalises resistance to mΩ on construction. Asserted in
    # canonical units on purpose -- a merge that carried the field across while dropping
    # its unit would still satisfy a 1.5 expectation, and that is the 1000x class.
    assert _max_of(merged, 'Rg') == 1500.0
    assert merged.fields_filled['Rg'].unit == 'mΩ'
    assert _max_of(merged, 'Qrr') == 120.0


def test_fresh_wins_for_symbols_it_has():
    """Direction. The re-parse is the newer evidence -- e.g. a font-encoding repair fixing
    a corrupt 88000 back to 88 -- so it must REPLACE, not be shadowed by the stored value."""
    stored = _ds('X', Rds_on=(88000.0, 'mOhm'), Vds=(600.0, 'V'))
    fresh = _ds('X', Rds_on=(88.0, 'mOhm'))

    merged = merge_keeping_absent_symbols(stored, fresh)

    assert _max_of(merged, 'Rds_on') == 88.0, 'stale corrupt value shadowed the repair'
    assert _max_of(merged, 'Vds') == 600.0


def test_no_duplicate_candidates_for_a_symbol_fresh_already_has():
    """Symbol granularity, not field granularity: re-appending the stored candidate would
    pile near-duplicate re-parses into fields_lists and shift the aggregate via fill()."""
    stored = _ds('X', Rds_on=(16.0, 'mOhm'))
    fresh = _ds('X', Rds_on=(15.0, 'mOhm'))

    merged = merge_keeping_absent_symbols(stored, fresh)

    assert len(merged.fields_lists['Rds_on']) == 1
    assert _max_of(merged, 'Rds_on') == 15.0


def test_neither_argument_is_mutated():
    """main.py keeps using `fresh` to build the CSV after the write. A run's OUTPUT should
    report what that run actually read, not values folded back in from the database."""
    stored = _ds('X', Rds_on=(16.0, 'mOhm'), Rg=(1.5, 'Ohm'))
    fresh = _ds('X', Rds_on=(15.0, 'mOhm'))

    merge_keeping_absent_symbols(stored, fresh)

    assert set(fresh.fields_lists) == {'Rds_on'}, 'fresh gained DB fields; CSV would lie'
    assert set(stored.fields_lists) == {'Rds_on', 'Rg'}


def test_absent_stored_record_is_a_passthrough():
    """A part seen for the first time has no stored record; None must not crash the write."""
    fresh = _ds('X', Rds_on=(15.0, 'mOhm'))
    assert merge_keeping_absent_symbols(None, fresh) is fresh


# --------------------------------------------------------------- through the real store
@pytest.mark.parametrize('backend', ['sqlite', 'pickle'])
def test_field_count_never_decreases_across_a_real_add(tmp_path, monkeypatch, backend):
    """End-to-end through ObjectDatabase.add, because the defect lives in the CALL, not in
    the merge function -- a correct merge nobody passes is worth nothing.

    Also pins the default: the same write WITHOUT merge= still destroys, so this test
    keeps measuring something real if the call site regresses.

    PARAMETRIZED over both storage backends. It used to run on whichever one the store
    happened to resolve to for an empty tmp_path -- i.e. sqlite only, silently, once the
    sqlite backend landed -- which left `add`'s other merge branch, and the documented
    FETLIB_STORE=pickle rollback path, covered by nothing.
    """
    if backend == 'pickle':
        monkeypatch.setenv('FETLIB_STORE', 'pickle')
    else:
        monkeypatch.delenv('FETLIB_STORE', raising=False)

    def n_fields(db):
        return sum(sum(len(v) for v in ds.fields_lists.values()) for ds in db.values())

    def fresh_db(name):
        name = '%s-%s' % (name, backend)
        db = ObjectDatabase(name, key_func=lambda ds: (ds.part.mfr, ds.part.mpn))
        db._lib_path = str(tmp_path / (name + '.pkl'))
        db._lck_path = db._lib_path + '.lock'
        db._lib_mem = {}
        assert (type(db._backend_or_resolve()).__name__
                == ('_PickleBackend' if backend == 'pickle' else '_SqliteBackend')), \
            'this run is not exercising the %s backend it claims to' % backend
        return db

    stored = _ds('X', Rds_on=(16.0, 'mOhm'), Rg=(1.5, 'Ohm'), Qrr=(120.0, 'nC'))
    narrow = _ds('X', Rds_on=(15.0, 'mOhm'))

    guarded = fresh_db('guarded')
    guarded.add([stored])
    before = n_fields(guarded._lib_mem)
    guarded.add([narrow], merge=merge_keeping_absent_symbols)
    assert n_fields(guarded._lib_mem) >= before
    assert set(guarded._lib_mem[('mfr', 'X')].fields_lists) == {'Rds_on', 'Rg', 'Qrr'}
    assert _max_of(guarded._lib_mem[('mfr', 'X')], 'Rds_on') == 15.0

    # the unguarded default, still destructive -- this is the behaviour merge= opts out of
    unguarded = fresh_db('unguarded')
    unguarded.add([_ds('X', Rds_on=(16.0, 'mOhm'), Rg=(1.5, 'Ohm'), Qrr=(120.0, 'nC'))])
    unguarded.add([_ds('X', Rds_on=(15.0, 'mOhm'))])
    assert set(unguarded._lib_mem[('mfr', 'X')].fields_lists) == {'Rds_on'}


def test_main_passes_the_merge_at_the_call_site():
    """The guard's own precondition. merge= is opt-in, so the function can be perfect and
    the DB still be destroyed by a bare add(dss) -- exactly how this shipped for months."""
    import re
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'main.py')
    with open(main_py) as fh:
        src = fh.read()

    calls = re.findall(r'^\s*[^#\n]*datasheets_db\.add\((.*?)\)\s*$', src, re.M)
    assert calls, 'no live datasheets_db.add call found -- did it move?'
    for arglist in calls:
        assert 'merge=' in arglist, (
            'datasheets_db.add(%s) writes without merge= and will delete symbols the '
            'stored record has' % arglist)


def test_merge_keeps_the_stored_discovered_part():
    """Identity metadata follows the same rule as symbols: what fresh lacks is kept.

    The 2026-07-28 sweep merged parse_datasheet-built records (bare MpnMfr part) over
    stored records carrying a DiscoveredPart, and 5641 records silently lost catalog
    specs/package/provenance. The symbol-level check missed it by construction, so the
    guarantee lives in the merge itself.
    """
    class _Specs:
        Rds_on_10v_max = 0.016

    class _Discovered:
        mfr, mpn = 'mfr', 'X'
        specs = _Specs()

    stored = _ds('X', Rds_on=(16.0, 'mOhm'))
    stored.part = _Discovered()
    fresh = _ds('X', Rds_on=(15.0, 'mOhm'))  # bare MpnMfr part

    merged = merge_keeping_absent_symbols(stored, fresh)
    assert merged.part is stored.part, 'bare fresh part replaced the stored DiscoveredPart'
    assert _max_of(merged, 'Rds_on') == 15.0  # fresh values still win

    # and when FRESH carries the real part, it wins -- newer identity is not discarded
    fresh2 = _ds('X', Rds_on=(15.0, 'mOhm'))
    fresh2.part = _Discovered()
    plain = _ds('X', Rds_on=(16.0, 'mOhm'))
    assert merge_keeping_absent_symbols(plain, fresh2).part is fresh2.part
