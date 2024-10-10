import re

from dslib.pdf2txt import whitespaces_to_space


def test_pdf_to_ascii():
    from dslib.pdf.ascii import pdf_to_ascii
    lines = pdf_to_ascii('../../datasheets/littelfuse/IXFP110N15T2.pdf', output='lines')
    assert len(lines) > 50
    txt = '\n'.join(lines)
    assert ' Min.           Typ.             Max.' in txt


def test_line_overlap():
    from dslib.pdf.ascii import pdf_to_ascii
    lines = pdf_to_ascii('../../datasheets/onsemi/NTMFSC4D2N10MC.pdf', output='lines')
    txt = whitespaces_to_space('\n'.join(lines))
    assert 'QG(TOT) ' in txt

    lines = pdf_to_ascii('../../datasheets/onsemi/NTMFSC4D2N10MC.pdf', output='lines', line_overlap=.5)
    txt = whitespaces_to_space('\n'.join(lines))
    assert 'QG(TOT) ' not in txt
    assert 'G(TOT) ' in txt

    lines = pdf_to_ascii('../../datasheets/littelfuse/IXFK360N15T2.pdf', output='lines')
    txt = whitespaces_to_space('\n'.join(lines))
    assert 'VGS' in txt
    assert 'VDSS' in txt
    assert 'RDS(on)' in txt


def test_to_html():
    from dslib.pdf.to_html import pdf_to_html
    doc = pdf_to_html('../../datasheets/infineon/IRFS3107TRLPBF.pdf', return_html=True)
    assert '––– Ω' not in doc


def test_test_merge_lines():
    from dslib.pdf.ascii import pdf_to_ascii

    lines = pdf_to_ascii('../../datasheets/infineon/IRFS3107TRLPBF.pdf', output='lines')
    assert len(
        sum((re.compile('RG\s+Internal\s+Gate\s+Resistance\s+–––\s+1.2\s+–––\s+[\S]\s*$').findall(l) for l in lines),
            [])) == 1

    lines = pdf_to_ascii('../../datasheets/infineon/IPA029N06NXKSA1.pdf', output='lines')
    assert len(sum((re.compile('2\.6\s+2\.9').findall(l) for l in lines), [])) == 1
    assert len(sum((re.compile('3\.0\s+3\.5').findall(l) for l in lines), [])) == 1

    lines = pdf_to_ascii('../../datasheets/infineon/IPA029N06NXKSA1.pdf', output='lines', sort_vert=False)
    assert len(sum((re.compile('2\.6\s+2\.9').findall(l) for l in lines), [])) == 0
    assert len(sum((re.compile('3\.0\s+3\.5').findall(l) for l in lines), [])) == 0


def test_strip_whitespace():
    # ixfp dspick (33 ... ns)
    raise NotImplementedError()


def test_char_margin():
    'RS6P100BHTB1'
    raise NotImplementedError()


def test_row():
    from dslib.pdf.ascii import Row
    from dslib.pdf.tree import Word, Bbox
    A = Word(0, Bbox(0, 0, 0, 0), 'A')
    r = Row('abc', {0: A}, None)

    w = r.elements_by_range(0, 1)
    assert w == [A]

    w = r.elements_by_range(0, 2)
    assert w == [A]

    w = r.elements_by_range(1, 2)
    assert w == []

    B = Word(1, Bbox(0, 0, 0, 0), 'B')
    r = Row('abc', {0: A, 1: B}, None)
    w = r.elements_by_range(0, 1)
    assert w == [A]
    w = r.elements_by_range(1, 2)
    assert w == [B]
    w = r.elements_by_range(0, 2)
    assert w == [A, B]
    w = r.elements_by_range(2, 3)
    assert w == []


def test_unicode_mapping_symbol():
    from dslib.pdf.ascii import pdf_to_ascii
    txt = ' '.join(pdf_to_ascii('../../datasheets/littelfuse/IXFK360N15T2.pdf', output='lines'))
    assert '25qC' not in txt
    assert '25°C' in txt
    assert '±' in txt
    assert '4.0mΩ' in txt


def test_word_line():
    from dslib.pdf.ascii import pdf_to_ascii
    txt = '\n'.join(pdf_to_ascii('../../datasheets/infineon/IRFS3107TRLPBF.pdf', output='lines', spacing=20))
    assert 'ΔV(BR)DSS/ΔTJ' in txt
    assert 'Qg  ' in txt
    assert '  Total Gate Charge  ' in txt
    assert re.compile(r'RG\s+Internal Gate Resistance\s+–+ +1.2 +–+').search(txt)
    assert re.compile(r'RG\s+Internal Gate Resistance\s+–+ +1.2 +–+\s+Ω').search(txt)

    rows = pdf_to_ascii('../../datasheets/infineon/IRFS3107TRLPBF.pdf', output='rows_by_page', spacing=20)[1]
    assert rows


def test_vertical_merge():
    from dslib.pdf.tree import Line, Word
    els = [Line((11, 0), [Word((11, 0, 0), (381.8, 572.8, 388.7, 581.8), 'Ω')]), Line((13, 2), [
        Word((13, 2, 0), (98.0, 570.8, 128.3, 579.8), 'Internal'),
        Word((13, 2, 1), (130.8, 570.8, 150.4, 579.8), 'Gate'),
        Word((13, 2, 2), (152.9, 570.8, 197.7, 579.8), 'Resistance')]),
           Line((7, 9), [Word((7, 9, 0), (294.0, 570.8, 309.0, 579.8), '–––')]),
           Line((9, 8), [Word((9, 8, 0), (323.2, 570.8, 335.8, 579.8), '1.2')]),
           Line((8, 10), [Word((8, 10, 0), (349.8, 570.8, 364.9, 579.8), '–––')]),
           Line((14, 0), [Word((14, 0, 0), (38.4, 570.1, 49.5, 580.2), 'RG')])]
    from dslib.pdf.tree import vertical_merge
    vertical_merge(els)
    assert len(els) == 1


if __name__ == '__main__':
    test_pdf_to_ascii()
    test_line_overlap()
    test_strip_whitespace()
