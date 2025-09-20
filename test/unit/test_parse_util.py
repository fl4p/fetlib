import math

def test_right_strip_nan():
    from dslib.pdf.parse import right_strip_nan

    nan = math.nan

    l = ['Q gs', nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan]
    l2 = right_strip_nan(l, 2)
    assert l2 == l[:3]

    l = ['Q gs', nan, nan, nan, nan, nan, 'a',]
    l2 = right_strip_nan(l, 2)
    assert l2 == l

    l = ['Q gs', nan, nan, nan, nan, nan, 'a',nan]
    l2 = right_strip_nan(l, 2)
    assert l2 == l

    l = ['Q gs', nan, nan, nan, nan, nan, 'a',nan, nan]
    l2 = right_strip_nan(l, 2)
    assert l2 == l

    l = ['Q gs', nan, nan, nan, nan, nan, 'a',nan, nan,nan]
    l2 = right_strip_nan(l, 2)
    assert l2 == l[:-1]


def test_validate_datasheet_text():
    from dslib.pdf.parse import validate_datasheet_text

    assert not validate_datasheet_text('mfr', 'HY3810C', 'lorem HY3810NA2P/B ' + ('fill it' * 20))
    assert validate_datasheet_text('mfr', 'HY3810NA2B', 'lorem HY3810NA2P/B '+ ('fill it' * 20))


def test_parse_field_value():
    from dslib.field import parse_field_value
    assert math.isnan(parse_field_value('---', no_raise=True))
    assert math.isnan(parse_field_value('~', no_raise=True))
    assert math.isnan(parse_field_value('~~', no_raise=True))

    from dslib.field import Field
    f = Field('Qg', '---', 12, '--', '')
    assert f.typ == 12