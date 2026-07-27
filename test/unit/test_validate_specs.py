"""Physical-consistency checks (dslib/validate.py).

Two properties matter more than the happy path:

  1. Every check is SEEN TO FIRE on a constructed known-bad input. A guard never observed
     to fail is not a guard -- and this repo has just been through the opposite case, where
     the FoM assert passed a 1000x-low Rds_on and rejected the corrected value.

  2. Missing input yields UNCHECKED, never PASS. Absence of evidence must not encode
     absence of the problem, so `violations() == []` must not be readable as "verified".
"""
import math

import pytest

from dslib.validate import (FAIL, PASS, QGD_QGS_MAX, QGD_QGS_MIN, QG_SUM_RATIO_MAX,
                            UNCHECKED, VDROP_MIN_MV, CHECKS, run_checks, violations)


class FakeField:
    def __init__(self, v):
        self.typ_or_max_or_min = v


class FakeDS:
    """Minimal stand-in exposing just what the checks touch."""

    def __init__(self, rds_milliohm=math.nan, **syms):
        self.fields_filled = {k: FakeField(v) for k, v in syms.items() if v is not None}
        self._rds = rds_milliohm

    def get_resistance_milliohm(self, sym, **kw):
        return self._rds


def _status(ds, name):
    return next(r.status for r in run_checks(ds) if r.name == name)


# --------------------------------------------------------------------- fires on bad input
@pytest.mark.parametrize('name,ds', [
    ('Ciss>Crss', FakeDS(Ciss=100.0, Crss=730.0)),          # IXFK170N10P
    ('Coss>Crss', FakeDS(Coss=10.5, Crss=187.0)),           # NTTYS009N08HLTWG
    ('Vpl>Vgs_th', FakeDS(Vpl=3.0, Vgs_th=3.0)),            # NTMFS005N10MCLT1G (equal)
    ('Qg>=Qgs+Qgd', FakeDS(Qg=9.0, Qgs=6.0, Qgd=5.4)),      # NVTFS8D1N08HTAG
    ('Qg/(Qgs+Qgd)', FakeDS(Qg=100.0, Qgs=5.0, Qgd=5.0)),   # ratio 10
    ('Qgd/Qgs', FakeDS(Qgs=1.0, Qgd=32.0)),                 # observed max
    ('ID_25*Rds_on', FakeDS(rds_milliohm=0.16, ID_25=46.0)),  # IXTX46N50L, 1000x low
])
def test_each_check_fires(name, ds):
    assert _status(ds, name) == FAIL, '%s did not fire on a known-bad input' % name


@pytest.mark.parametrize('name,ds', [
    ('Ciss>Crss', FakeDS(Ciss=2000.0, Crss=50.0)),
    ('Coss>Crss', FakeDS(Coss=300.0, Crss=50.0)),
    ('Vpl>Vgs_th', FakeDS(Vpl=4.5, Vgs_th=3.0)),
    ('Qg>=Qgs+Qgd', FakeDS(Qg=60.0, Qgs=15.0, Qgd=18.0)),
    ('Qg/(Qgs+Qgd)', FakeDS(Qg=60.0, Qgs=15.0, Qgd=18.0)),
    ('Qgd/Qgs', FakeDS(Qgs=15.0, Qgd=18.0)),
    ('ID_25*Rds_on', FakeDS(rds_milliohm=160.0, ID_25=46.0)),  # IXTX46N50L, corrected
])
def test_each_check_passes_a_good_part(name, ds):
    assert _status(ds, name) == PASS


# --------------------------------------------------------- missing input is NOT a pass
@pytest.mark.parametrize('ds', [
    FakeDS(),                                        # nothing at all
    FakeDS(Ciss=2000.0),                             # half of an ordering
    FakeDS(Qg=60.0, Qgs=15.0),                       # Qgd absent
    FakeDS(Qg=60.0, Qgs=0.0, Qgd=0.0),               # sum is zero -> undefined ratio
    FakeDS(ID_25=46.0),                              # Rds_on NaN
    FakeDS(rds_milliohm=160.0),                      # ID_25 absent
    FakeDS(rds_milliohm=160.0, ID_25=0.0),           # non-positive current
    FakeDS(Ciss=float('nan'), Crss=float('nan')),
])
def test_missing_input_is_unchecked_never_pass(ds):
    for r in run_checks(ds):
        assert r.status != PASS, '%s reported PASS without usable input' % r.name


def test_every_check_is_exercised_by_the_firing_suite():
    """Guards against a check being added to CHECKS but never calibrated: the parametrised
    firing test above must name every check that exists."""
    fired = {'Ciss>Crss', 'Coss>Crss', 'Vpl>Vgs_th', 'Qg>=Qgs+Qgd',
             'Qg/(Qgs+Qgd)', 'Qgd/Qgs', 'ID_25*Rds_on'}
    present = {r.name for r in run_checks(FakeDS())}
    assert present == fired, 'uncalibrated check(s): %s' % (present ^ fired)


# ------------------------------------------------------------------------ direction
def test_conduction_drop_catches_the_1000x_direction_specifically():
    """The whole point: it must reject the value that is 1000x LOW and accept the correct
    one -- not merely 'notice a difference'. This is the check the FoM assert got backwards.
    """
    corrupt = FakeDS(rds_milliohm=0.16, ID_25=46.0)     # 7.4 mV
    correct = FakeDS(rds_milliohm=160.0, ID_25=46.0)    # 7360 mV
    assert _status(corrupt, 'ID_25*Rds_on') == FAIL
    assert _status(correct, 'ID_25*Rds_on') == PASS
    assert 0.16 * 46 < VDROP_MIN_MV <= 160.0 * 46


def test_violations_returns_messages_only_for_failures():
    ds = FakeDS(Ciss=100.0, Crss=730.0, Qg=60.0, Qgs=15.0, Qgd=18.0)
    v = violations(ds)
    assert len(v) == 1 and 'Ciss>Crss' in v[0]


def test_empty_violations_does_not_mean_verified():
    """A record with no usable symbols yields no violations AND no passes. The docstring
    contract is that callers must read n_passed, not an empty list."""
    rs = run_checks(FakeDS())
    assert violations(FakeDS()) == []
    assert all(r.status == UNCHECKED for r in rs)
    assert not any(r.status == PASS for r in rs)


def test_a_raising_check_is_unchecked_not_pass():
    rs = run_checks(_Exploding())
    assert rs and all(r.status == UNCHECKED for r in rs)
    assert not any(r.status == PASS for r in rs)


class _Exploding(FakeDS):
    @property
    def fields_filled(self):
        raise RuntimeError('boom')

    @fields_filled.setter
    def fields_filled(self, v):
        pass


def test_a_raising_check_is_VISIBLE_not_merely_not_pass():
    """The bug this pins: run_checks records a crash as UNCHECKED-with-message, but
    violations() used to filter on FAIL only, so the message went nowhere and a validator
    that fell over looked exactly like a clean part. Asserting 'not PASS' (as the test above
    does) passes even then -- the surfaced output is what has to be checked."""
    v = violations(_Exploding())
    assert v, 'a crashing validator reported nothing at all'
    assert any('check error' in m for m in v)


# --------------------------------------------------------------- polarity (p-channel)
@pytest.mark.parametrize('vpl,vth,expect', [
    (4.5, 3.0, PASS),        # n-channel
    (-6.1, -5.3, PASS),      # IJCQ75RM16J1: legitimate negative-gate part
    (3.0, 4.5, FAIL),        # plateau below threshold
    (-5.3, -6.1, FAIL),      # same, negative polarity
    (-7.4, 3.5, FAIL),       # IPA60R125: mixed signs, cannot both be right
    (7.4, -3.5, FAIL),
])
def test_vpl_vth_uses_sign_then_magnitude(vpl, vth, expect):
    """abs() on both would pass the mixed-sign rows, a signed compare would fail the
    negative-gate ones. Neither alone is correct."""
    assert _status(FakeDS(Vpl=vpl, Vgs_th=vth), 'Vpl>Vgs_th') == expect


def test_violations_reach_the_real_output_path_not_just_get_row():
    """The integration bug: violations were merged only inside get_row(), but main.py builds
    its result rows independently at four sites using ', '.join(ds.errors). So all 150 flags
    were absent from the CSV and the ranking -- the validator was observational dead code
    where it mattered. all_errors() is now the single source both paths use.
    """
    import inspect

    import main
    from dslib.field import DatasheetFields

    assert hasattr(DatasheetFields, 'all_errors')
    src = inspect.getsource(main)
    assert "', '.join(ds.errors)" not in src, \
        'a result row still joins ds.errors directly and will drop spec violations'


def test_every_result_row_surfaces_errors_for_every_device_it_reports():
    """The property, not the spelling.

    Counting occurrences of the accessor only proved the string was present. It said
    nothing about WHICH DatasheetFields each row reads -- and the staged-switching row is a
    pair (ds || ds2) whose Rds_max comes from ds2, so it was quietly reporting only ds's
    errors while stating ds2's resistance. So: for each result_rows block, whichever device
    objects it mentions must all appear in its errors= expression.
    """
    import ast
    import inspect
    import re

    import main

    src = inspect.getsource(main)
    tree = ast.parse(src)
    lines = src.split('\n')

    checked = 0
    saw_paired = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'dict'):
            continue
        if 'errors' not in {k.arg for k in node.keywords if k.arg}:
            continue
        block = '\n'.join(lines[node.lineno - 1:(node.end_lineno or node.lineno)])
        err_expr = next(ast.get_source_segment(src, k.value) or ''
                        for k in node.keywords if k.arg == 'errors')
        # every ds-like object the row reads from must be represented in its errors
        used = set(re.findall(r'\b(ds2?)\b', block))
        for name in used:
            assert re.search(r'\b%s\.all_errors\(\)' % name, err_expr), (
                'result row at main.py:%d reads %s but its errors= does not include '
                '%s.all_errors() -- that device\'s violations are dropped'
                % (node.lineno, name, name))
        if 'ds2' in used:
            saw_paired = True
        checked += 1

    assert checked, 'found no result dicts to check -- the test has gone blind'
    assert saw_paired, ('never saw the staged-switching paired row (ds || ds2); it is the '
                        'one that regressed, so the test must actually reach it')


def test_all_errors_includes_both_parse_errors_and_violations():
    from dslib.field import DatasheetFields

    ds = DatasheetFields()
    ds.errors.append('parse boom')
    ds.fields_filled = {'Ciss': FakeField(100.0), 'Crss': FakeField(730.0)}
    out = ds.all_errors()
    assert 'parse boom' in out
    assert any('Ciss>Crss' in m for m in out)


def test_nonpositive_resistance_is_refused():
    """No MOSFET has Rds_on or Rg <= 0 at any scale. IXTK/IXTR/IXTX170P10P store Rg=-14.2
    and the reader was returning -14200 mOhm. Must be refused BEFORE scaling, so a
    miscapture is not laundered into a plausible magnitude."""
    from dslib.field import DatasheetFields, Field

    for unit in ('mΩ', 'Ω', None):
        ds = DatasheetFields()
        f = Field('Rg', math.nan, -14.2, math.nan, unit=unit)
        ds.fields_filled = {'Rg': f}
        assert math.isnan(ds.get_resistance_milliohm('Rg')), unit


def test_bounds_are_ordered_and_sane():
    assert 0 < QGD_QGS_MIN < 1 < QGD_QGS_MAX
    assert QG_SUM_RATIO_MAX > 1.0        # 1.0 is the exact identity, handled separately
    assert VDROP_MIN_MV > 0
    assert len(CHECKS) == 7
