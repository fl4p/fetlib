"""The configured gate voltage must reach condition selection.

`get_mosfet_specs` selects `Rds_on` and `Qg` at a gate voltage, and `main.get_fet_specs`
called it with NO argument — so every design was read at that method's 10 V default no matter
what `gateDrive.voltage` said in the YAML.

MEASURED IMPACT, so the claim stays bounded:
  * 10 V -> 11 V (what every apps/proj config except one actually uses): ZERO parts change.
    The condition matcher picks the same rows, so the common case was never wrong.
  * 10 V -> 5 V (fugu_gan.yaml's syncFet section): 211 Qg and 36 Rds_on selections change,
    in the physically correct direction — Rds_on RISES as Vgs falls (MCAC50N10Y-TP
    6.0 -> 10.0 mΩ, IXTK170N10P 7.0 -> 9.0, NVMFS4C302NWFET1G 1.15 -> 1.7).
  * GaN is LATENT: the shipped DB contains 0 GaN parts, so the Von_GaN path changes nothing
    today. It is wired because the config models it, not because it is firing.
"""
import math

import pytest

from dslib.field import DatasheetFields, Field, _DATASHEET_REF_VGS
from dslib.mosfet import GateDrive
from main import gate_drive_vgs, get_fet_specs

NA = math.nan


class _Specs:
    def __init__(self, isGaN=False):
        self.isGaN = isGaN


class _Part:
    def __init__(self, isGaN=False):
        self.specs = _Specs(isGaN)
        self.mfr = 'mfr'
        self.mpn = 'mpn'


def _ds(isGaN=False):
    ds = DatasheetFields()
    ds.part = _Part(isGaN)
    return ds


def _gd(Von=11.0, Von_GaN=NA):
    return GateDrive(rg_total=4.7, rg_total_dis=4.7, Von=Von, Von_GaN=Von_GaN)


def test_silicon_uses_von():
    assert gate_drive_vgs(_ds(), _gd(Von=11.0)) == 11.0


def test_gan_uses_von_gan_when_configured():
    """GaN is driven at 5-6 V, not 10; Rds_on and Qg differ materially at that point."""
    assert gate_drive_vgs(_ds(isGaN=True), _gd(Von=11.0, Von_GaN=5.0)) == 5.0


def test_gan_falls_back_to_von_when_von_gan_is_unset():
    """Von_GaN defaults to NaN. Inventing a GaN-specific voltage would be worse than using
    the one the user did state, and NaN must never reach the condition matcher."""
    v = gate_drive_vgs(_ds(isGaN=True), _gd(Von=11.0, Von_GaN=NA))
    assert v == 11.0 and not math.isnan(v)


def test_silicon_ignores_von_gan():
    assert gate_drive_vgs(_ds(isGaN=False), _gd(Von=11.0, Von_GaN=5.0)) == 11.0


def test_get_fet_specs_requires_a_gate_drive():
    """The whole point of the change. A future call site must not be able to reintroduce the
    silent 10 V default by simply forgetting an argument."""
    with pytest.raises(TypeError):
        get_fet_specs(_ds())            # noqa - missing gd is the assertion


def test_get_fet_specs_actually_forwards_the_design_vgs():
    """The assertion this file was missing.

    The other tests exercise gate_drive_vgs and the selector INDEPENDENTLY, so a regression
    back to a bare ds.get_mosfet_specs() would have passed every one of them — the change
    would be undone and the suite still green. A spy on the received Vgs is what makes the
    forwarding itself observable.
    """
    seen = []

    class SpyDS(DatasheetFields):
        def get_mosfet_specs(self, Vgs=None):
            seen.append(Vgs)
            return 'specs'

        def get_row(self):
            return {}

    ds = SpyDS()
    ds.part = _Part()
    assert get_fet_specs(ds, _gd(Von=11.0)) == 'specs'
    assert seen == [11.0], 'get_fet_specs did not forward the design Vgs (got %r)' % (seen,)

    seen.clear()
    gan = SpyDS()
    gan.part = _Part(isGaN=True)
    get_fet_specs(gan, _gd(Von=11.0, Von_GaN=5.0))
    assert seen == [5.0], 'GaN part was not read at Von_GaN (got %r)' % (seen,)


def test_generic_db_builders_use_the_reference_path_not_a_design_one():
    """Guards the regression I actually shipped.

    Making `gd` required broke apps/process_parts.py and apps/refresh_part_specs.py, which
    call this from generic parts-DB builders that have no converter to speak for. They now
    use get_reference_fet_specs. The deeper reason they must NOT invent a GateDrive: parts_db
    is keyed on (mfr, mpn) with no Vgs recorded, so persisting design-selected specs there
    lets one config run overwrite the reference values every later consumer reads.
    """
    import inspect
    import main

    assert callable(getattr(main, 'get_reference_fet_specs', None)), \
        'the named reference path is gone; the DB builders have nowhere safe to go'
    # takes no gate drive, by design
    assert list(inspect.signature(main.get_reference_fet_specs).parameters) == ['ds']

    for mod_path in ('apps/process_parts.py', 'apps/refresh_part_specs.py'):
        src = open(mod_path, encoding='utf-8').read()
        assert 'get_reference_fet_specs' in src, '%s lost the reference path' % mod_path
        assert 'get_fet_specs(ds)' not in src, \
            '%s calls get_fet_specs with no GateDrive; that is a TypeError' % mod_path


def test_get_mosfet_specs_default_is_the_documented_reference_not_a_config_value():
    """Vgs=None stays permissive for datasheet.py and the tests, and resolves to the
    conventional 10 V — never to a design's real Von, which only get_fet_specs supplies."""
    assert _DATASHEET_REF_VGS == 10.0


def test_lower_vgs_selects_a_higher_rds_on():
    """Direction, not just 'a difference'. Rds_on must RISE as the gate voltage falls; a
    change in the other direction would mean the matcher is picking rows at random."""
    ds = DatasheetFields()
    ds.part = _Part()
    ds.add(Field('Rds_on', NA, NA, 6.0, 'mΩ', cond=dict(Vgs=10)))
    ds.add(Field('Rds_on', NA, NA, 10.0, 'mΩ', cond=dict(Vgs=4.5)))

    at10 = ds.select_rds_on_milliohm(stat='max', cond=dict(Vgs=10))
    at45 = ds.select_rds_on_milliohm(stat='max', cond=dict(Vgs=4.5))
    assert at10 == 6.0
    assert at45 == 10.0
    assert at45 > at10, 'Rds_on did not increase at the lower gate voltage'
