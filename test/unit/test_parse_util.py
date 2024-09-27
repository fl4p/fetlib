import math

def test_right_strip_nan():
    from dslib.pdf2txt.parse import right_strip_nan

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