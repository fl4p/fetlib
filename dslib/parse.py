import math
import re
from typing import List

from dslib import expr


def parse_datasheet(pdf_path=None, mfr=None, mpn=None):
    import fitz  # PyMuPDF

    if not pdf_path:
        pdf_path = f'datasheets/{mfr}/{mpn}.pdf'

    pdf_document = fitz.open(pdf_path)

    pdf_text = ""
    for page_number in range(len(pdf_document)):
        page = pdf_document[page_number]
        pdf_text += page.get_text()

    pdf_document.close()

    if not pdf_text:
        print(pdf_path, 'no text extracted')

    pdf_text = pdf_text.replace('‑', '-')  # utf8 b'\xe2\x80\x91'
    pdf_text = pdf_text.replace('−', '-')  # utf8 b'\xe2\x80\x92'
    pdf_text = pdf_text.replace('–', '-')  # utf8 b'\xe2\x80\x93'
    pdf_text = pdf_text.replace('—', '-')
    pdf_text = pdf_text.replace('\0x04', '\x03')  # utf8 b'\xe2\x80\x93' toshiba
    pdf_text = pdf_text.replace('', '\x03')  # toshiba
    pdf_text = pdf_text.replace('\0x03', '\x03')
    pdf_text = pdf_text.replace('', '\x03')

    fields: List[Field] = []

    pat = expr.QRR.get(mfr)

    if pat:
        rg = re.compile(pat, re.MULTILINE | re.IGNORECASE)
        # qrr_m = rg.findall(pdf_text)
        qrr_ms = list(rg.finditer(pdf_text))
        # if len(qrr_ms) != 1:
        #    if len(qrr_ms) == 2 and mpn in {'IQD016N08NM5ATMA1', 'FDMC007N08LC', 'FDMS4D4N08C'}:
        #        pass
        #    else:
        #        assert len(qrr_ms) == 0, (pdf_path, qrr_m)
        #        print(pdf_path, 'no Qrr match', pdf_text[:200].replace('\n', '<br>'))

        if len(qrr_ms) == 0:
            print(pdf_path, 'no Qrr match', pdf_text[:200].replace('\n', '<br>'))

        for qrr_m in qrr_ms:
            qrr_d = qrr_m.groupdict()
            for k, v in list(qrr_d.items()):
                if v and k.endswith('2') or k.endswith('3'):
                    assert not qrr_d.get(k[:-1])
                    qrr_d[k[:-1]] = v
                    del qrr_d[k]

            if qrr_d.get('unit') == 'μC':
                mul = 1000
            else:
                mul = 1

            fields.append(Field('Qrr',
                                min=qrr_d.get('min'), typ=qrr_d.get('typ'), max=qrr_d.get('max'),
                                mul=mul,
                                cond=dict(
                                    i_f=qrr_d.get('if'),
                                    didt=qrr_d.get('didt'),
                                    vds=qrr_d.get('vds'))))  # vgs
    else:
        print('no Qrr pattern for ', mfr)

    tabula_read(pdf_path)

    # build dict taking first symbol
    d = dict()
    for f in fields:
        if f.symbol not in d:
            d[f.symbol] = f

    return d


def tabula_read(ds_path):
    import tabula

    dfs = tabula.read_pdf(ds_path, pages='all')
    return dfs
    #dfs[]


class Field():

    def __init__(self, symbol: str, min, typ, max, mul, cond):
        self.symbol = symbol
        self.min = parse_field_value(min) * mul
        self.typ = parse_field_value(typ) * mul
        self.max = parse_field_value(max) * mul
        self.cond = cond

    def __repr__(self):
        return f'Field("{self.symbol}", min={self.min}, typ={self.typ}, max={self.max}, cond={self.cond})'


def parse_field_value(s):
    if not s:        return math.nan
    s = s.strip().strip('\x03')
    if not s or s == '-' or set(s) == {'-'}:        return math.nan
    return float(s)


def find_value(pdf_text, label, unit):
    matches = re.findall(r"%s\s+[^0-9]*([0-9.]+)\s*%s" % (label, unit), pdf_text)
    val = matches[0] if matches else None
    return val