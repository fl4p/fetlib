import math
import re


def test_right_strip_nan():
    from dslib.pdf.parse import right_strip_nan

    nan = math.nan

    l = ['Q gs', nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan,
         nan, nan, nan, nan, nan]
    l2 = right_strip_nan(l, 2)
    assert l2 == l[:3]

    l = ['Q gs', nan, nan, nan, nan, nan, 'a', ]
    l2 = right_strip_nan(l, 2)
    assert l2 == l

    l = ['Q gs', nan, nan, nan, nan, nan, 'a', nan]
    l2 = right_strip_nan(l, 2)
    assert l2 == l

    l = ['Q gs', nan, nan, nan, nan, nan, 'a', nan, nan]
    l2 = right_strip_nan(l, 2)
    assert l2 == l

    l = ['Q gs', nan, nan, nan, nan, nan, 'a', nan, nan, nan]
    l2 = right_strip_nan(l, 2)
    assert l2 == l[:-1]


def test_validate_datasheet_text():
    from dslib.pdf.parse import validate_datasheet_text

    assert validate_datasheet_text('mfr', 'HY3208B', 'HY3208P/M/B')
    assert not validate_datasheet_text('mfr', 'HY3810C', 'lorem HY3810NA2P/B ' + ('fill it' * 20))
    assert validate_datasheet_text('mfr', 'HY3810NA2B', 'lorem HY3810NA2P/B ' + ('fill it' * 20))



def test_parse_field_value():
    from dslib.field import parse_field_value
    assert math.isnan(parse_field_value('---', no_raise=True))
    assert math.isnan(parse_field_value('~', no_raise=True))
    assert math.isnan(parse_field_value('~~', no_raise=True))

    from dslib.field import Field
    f = Field('Qg', '---', 12, '--', '')
    assert f.typ == 12


def test_parse_field():

    from dslib.pdf.expr import DIMENSIONS
    assert re.match(DIMENSIONS.V.head_regex, 'V (BR)DSS', re.IGNORECASE)
    assert re.match(DIMENSIONS.V.head_regex, 'V DSS', re.IGNORECASE)

    from dslib.pdf.parse import parse_field_csv
    field, parse_match = parse_field_csv(
        #'Drain-source breakdown voltage,V (BR)DSS,V GS=0 V,I D=1 mA,150,-,-,V',
        'Drain-source breakdown voltage,V(BR)DSS,150,-,-,V',
        'V', field_sym='Vds',
        cond={0: 'Drain-source breakdown voltage', 1: 'V (BR)DSS', 2: 'V GS=0 V, I D=1 mA', 3: '150', 4: '-', 5: '-',
              6: 'V'},
        capture_match=True,
        source=['parse_csv'],
        mfr='infineon',
        mpn='BSZ900N15NS3 G',
    )
    assert field
    assert parse_match
