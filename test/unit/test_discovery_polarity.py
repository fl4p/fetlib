import asyncio
import math

import pandas as pd
import pytest

from dslib.discovery import parse_mosfet_polarity
import dslib.discovery.ao as ao
import dslib.discovery.infineon as infineon
import dslib.discovery.onsemi as onsemi


@pytest.mark.parametrize(('label', 'expected'), [
    ('N', 'N'),
    ('P', 'P'),
    ('N-Channel', 'N'),
    ('P-channel MOSFET', 'P'),
    ('N-ch', 'N'),
    ('P-ch x2', 'P'),
    ('N+N', 'N'),
    ('P+P', 'P'),
    ('N-ch + Active Clamp Zener', 'N'),
    ('N with Schottky', 'N'),
])
def test_parts_list_polarity_spellings(label, expected):
    assert parse_mosfet_polarity(label) == expected


@pytest.mark.parametrize('label', [None, math.nan, '', '  '])
def test_missing_parts_list_polarity(label):
    assert parse_mosfet_polarity(label) is None


@pytest.mark.parametrize('label', [
    'N+P',
    'N/P',
    'Complementary',
    'Power block',
    'MOSFET',
])
def test_compound_or_unknown_polarity_is_not_guessed(label):
    with pytest.raises(ValueError):
        parse_mosfet_polarity(label)


def test_ao_polarity_column_reaches_basic_specs(tmp_path, monkeypatch):
    parts_list = tmp_path / 'ao.csv'
    pd.DataFrame([{
        'Product': 'FIXTURE-P',
        'Polarity': 'P',
        'VDS (V)': -100,
        'RDS(ON) max (mΩ) at VGS=10V': 15,
        'Qg (10V)(nC)': 240,
        'ID @ 25°C (A)': 85,
        'VGS(th) max (V)': 4,
        'Package': 'TEST',
    }]).to_csv(parts_list, index=False)

    async def local_parts_list(*args, **kwargs):
        return str(parts_list)

    monkeypatch.setattr(ao, 'download_parts_list', local_parts_list)
    part, = asyncio.run(ao.aosmd_medium_voltage_mosfets())

    assert part.specs.polarity == 'P'
    assert part.specs.Vds_max == -100


def test_infineon_schottky_polarity_reaches_basic_specs(monkeypatch):
    item = {
        'ispnName': 'FIXTURE-N-SCHOTTKY',
        'dataSheet': {'assetDmPath': 'fixture.pdf'},
        'opns': [{'opnName': 'FIXTURE-N-SCHOTTKY'}],
        'parameterValues': [
            {'parameterName': 'Polarity', 'valueChar': 'N with Schottky'},
            {'parameterName': 'VDS', 'valueMax': 25},
            {'parameterName': 'RDS (on)', 'valueMax': 1.3},
            {'parameterName': 'QG', 'valueNumber': 20},
            {'parameterName': 'ID', 'valueMax': 30},
            {'parameterName': 'VGS(th)', 'valueMax': 3},
        ],
    }

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return [item]

    monkeypatch.setattr(infineon.requests, 'get', lambda *args, **kwargs: Response())
    part, = asyncio.run(infineon.infineon_mosfets())

    assert part.specs.polarity == 'N'
    assert part.specs.Vds_max == 25


def test_onsemi_polarity_column_reaches_basic_specs(tmp_path, monkeypatch):
    parts_list = tmp_path / 'onsemi.csv'
    pd.DataFrame([{
        'Product Group': 'FIXTURE-P',
        'Channel Polarity': 'P-Channel, ',
        'Configuration': 'Single, ',
        'V(BR)DSS Min (V)': '-30, ',
        'RDS(on) Max @ VGS = 10 V  (mΩ)': '50, ',
        'Vgs(th) Max (V)': '-1, ',
        'Qg Typ @ VGS = 10 V (nC)': '20, ',
        'ID Max (A)': '-5, ',
        'Package Type': 'TEST',
    }]).to_csv(parts_list, index=False)

    async def local_parts_list(*args, **kwargs):
        return str(parts_list)

    monkeypatch.setattr(onsemi, 'download_parts_list', local_parts_list)
    parts = asyncio.run(onsemi.onsemi_mosfets())

    assert len(parts) == 3  # the parser requests three MOSFET categories
    assert {part.specs.polarity for part in parts} == {'P'}
    assert {part.specs.Vds_max for part in parts} == {-30}
