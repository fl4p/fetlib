import math

from dslib.pdf.sheet import read_sheet, head_re

n = math.nan

def test_head_re():
    row_text = '\nParameter Symbol Note or test condition Values Unit '
    d = head_re.search(row_text).groupdict()
    assert d['param']
    assert d['cond']
    assert d['unit']


    row_text = ' (TJ = 25°C, Unless Otherwise Specified) Min. Typ. Max. ⌘ High Power Density '
    d = head_re.search(row_text).groupdict()
    assert d['min']
    assert d['max']
    assert d['typ']

def test_read_sheet():
    ds = read_sheet('../../datasheets/littelfuse/IXTQ180N10T.pdf')
    assert ds.Qgs == (n,39,n)
    assert ds.Qgd == (n, 45, n)

    ds = read_sheet('../../datasheets/ao/AOT20N25.pdf')
    assert ds.tRise == (n,31,n)
    assert ds.tFall == (n,25,n)

    ds = read_sheet('../../datasheets/ao/AOW482.pdf')
    assert ds.Rg.unit != 'pF'

    ds = read_sheet('datasheets/nxp/BUK764R2-80E,118.pdf')
    assert ds.Rg.typ != 80