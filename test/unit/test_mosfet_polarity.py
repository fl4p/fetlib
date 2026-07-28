import math

import pytest

from dslib.discovery import DiscoveredPart, MosfetBasicSpecs
from dslib.field import DatasheetFields
from dslib.mosfet import MosfetSpecs, mosfet_polarity


def _basic(vds, polarity=None):
    return MosfetBasicSpecs(
        Vds_max=vds,
        Rds_on_10v_max=0.015,
        # Parametric catalogs commonly publish current/threshold magnitudes
        # even when their P-channel Vds rating is signed.
        ID_25=85,
        Vgs_th_min=math.nan,
        Vgs_th_typ=math.nan,
        Vgs_th_max=4,
        Qg_typ=240,
        Qg_max=math.nan,
        source=['test'],
        polarity=polarity,
    )


def _specs(vds, polarity=None):
    return MosfetSpecs(
        Vds_max=vds,
        Rds_on=15e-3,
        Qg=240e-9,
        tRise=75e-9,
        tFall=45e-9,
        Qrr=1250e-9,
        trr=176e-9,
        Qgd=120e-9,
        Qgs=45e-9,
        Qg_th=20e-9,
        Vpl=4.0,
        Vsd=-3.3 if vds < 0 else 1.0,
        polarity=polarity,
    )


@pytest.mark.parametrize(('vds', 'expected'), [
    (100, 'N'),
    (-100, 'P'),
    (math.nan, None),
])
def test_polarity_is_inferred_from_signed_vds(vds, expected):
    assert mosfet_polarity(vds) == expected


@pytest.mark.parametrize(('factory', 'vds', 'expected'), [
    (_basic, 100, 'N'),
    (_basic, -100, 'P'),
    (_specs, 100, 'N'),
    (_specs, -100, 'P'),
])
def test_spec_models_expose_polarity(factory, vds, expected):
    assert factory(vds).polarity == expected


@pytest.mark.parametrize('factory', [_basic, _specs])
def test_explicit_matching_polarity_is_accepted(factory):
    assert factory(-100, polarity='P').polarity == 'P'


@pytest.mark.parametrize('factory', [_basic, _specs])
def test_explicit_conflicting_polarity_is_rejected(factory):
    with pytest.raises(ValueError, match='conflicts with signed Vds'):
        factory(-100, polarity='N')


def test_basic_specs_update_tracks_p_channel_precedence():
    specs = _basic(100)
    specs.update(_basic(-100))
    assert specs.Vds_max == -100
    assert specs.polarity == 'P'


@pytest.mark.parametrize(('first', 'second'), [
    (_basic(math.nan, polarity='P'), _basic(100)),
    (_basic(100), _basic(math.nan, polarity='P')),
])
def test_basic_specs_update_rejects_explicit_polarity_conflict(first, second):
    with pytest.raises(ValueError, match='conflicts with signed Vds'):
        first.update(second)


@pytest.mark.parametrize(('first', 'second'), [
    (_basic(math.nan, polarity='P'), _basic(-100)),
    (_basic(-100), _basic(math.nan, polarity='P')),
])
def test_basic_specs_update_accepts_matching_explicit_polarity(first, second):
    first.update(second)
    assert first.Vds_max == -100
    assert first.polarity == 'P'


@pytest.mark.parametrize(('cls', 'vds_key'), [
    (MosfetBasicSpecs, 'Vds_max'),
    (MosfetSpecs, 'Vds'),
])
def test_legacy_pickled_state_is_backfilled(cls, vds_key):
    specs = object.__new__(cls)
    specs.__setstate__({vds_key: -100})
    assert specs.polarity == 'P'


def test_basic_polarity_propagates_when_datasheet_vds_is_missing():
    basic = _basic(math.nan, polarity='P')
    part = DiscoveredPart(
        mfr='fixture',
        mpn='P-UNKNOWN-VDS',
        ds_url=None,
        package=None,
        specs=basic,
    )
    ds = DatasheetFields(part=part, fields=basic.fields())
    assert ds.get_mosfet_specs().polarity == 'P'
