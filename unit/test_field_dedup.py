import math

from dslib.field import DatasheetFields, Field


def test_exact_duplicate_field_is_kept_once():
    ds = DatasheetFields(mfr='infineon', mpn='X')
    a = Field('Vds', math.nan, math.nan, 150.0, source=['infineon_products'])
    b = Field('Vds', math.nan, math.nan, 150.0, source=['infineon_products'])

    ds.add(a)
    ds.add(b)

    assert len(ds.fields_lists['Vds']) == 1
    assert ds.get_max_or_min_or_typ('Vds') == 150.0


def test_same_value_from_different_source_is_not_deduped():
    ds = DatasheetFields(mfr='infineon', mpn='X')
    ds.add(Field('Vds', math.nan, math.nan, 150.0, source=['infineon_products']))
    ds.add(Field('Vds', math.nan, math.nan, 150.0, source=['digikey']))

    assert len(ds.fields_lists['Vds']) == 2


def test_nan_stats_and_conditions_compare_logically():
    ds = DatasheetFields(mfr='infineon', mpn='X')
    cond = {'Vgs': 10.0, 'Tj': math.nan}
    ds.add(Field('Rds_on', math.nan, 12.0, math.nan, unit='mΩ', cond=cond, source=['v2']))
    ds.add(Field('Rds_on', math.nan, 12.0, math.nan, unit='mΩ', cond=dict(reversed(cond.items())), source=['v2']))

    assert len(ds.fields_lists['Rds_on']) == 1
