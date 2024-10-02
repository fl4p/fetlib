import re


def test_pdf_to_ascii():

    from dslib.pdf.ascii import pdf_to_ascii
    lines = pdf_to_ascii('../../datasheets/littelfuse/IXFP110N15T2.pdf', output='lines' )
    assert len(lines) > 50
    txt = '\n'.join(lines)
    assert ' Min.           Typ.             Max.' in txt



def test_line_overlap():

    from dslib.pdf.ascii import pdf_to_ascii
    lines = pdf_to_ascii('../../datasheets/onsemi/NTMFSC4D2N10MC.pdf', output='lines' )
    txt ='\n'.join(lines)
    assert 'QG(TOT) ' in txt

    lines = pdf_to_ascii('../../datasheets/onsemi/NTMFSC4D2N10MC.pdf', output='lines', line_overlap=.5)
    txt = '\n'.join(lines)
    assert 'QG(TOT) ' not in txt
    assert 'G(TOT) ' in txt

def test_to_html():
    from dslib.pdf.to_html import pdf_to_html
    doc = pdf_to_html('../../datasheets/infineon/IRFS3107TRLPBF.pdf', return_html=True)
    assert '––– Ω' not in doc

def test_test_merge_lines():
    from dslib.pdf.ascii import pdf_to_ascii

    lines = pdf_to_ascii('../../datasheets/infineon/IRFS3107TRLPBF.pdf', output='lines')
    assert len(sum((re.compile('RG\s+Internal\s+Gate\s+Resistance\s+–––\s+1.2\s+–––\s+[\S]\s*$').findall(l) for l in lines), [])) == 1

    lines = pdf_to_ascii('../../datasheets/infineon/IPA029N06NXKSA1.pdf', output='lines')
    assert len(sum((re.compile('2\.6\s+2\.9').findall(l) for l in lines),[])) == 1
    assert len(sum((re.compile('3\.0\s+3\.5').findall(l) for l in lines), [])) == 1

    lines = pdf_to_ascii('../../datasheets/infineon/IPA029N06NXKSA1.pdf', output='lines', sort_vert=False)
    assert len(sum((re.compile('2\.6\s+2\.9').findall(l) for l in lines),[])) == 0
    assert len(sum((re.compile('3\.0\s+3\.5').findall(l) for l in lines), [])) == 0

def test_strip_whitespace():
    # ixfp dspick (33 ... ns)
    raise NotImplementedError()


def test_char_margin():
    'RS6P100BHTB1'
    raise NotImplementedError()



if __name__ == '__main__':
    test_pdf_to_ascii()
    test_line_overlap()
    test_strip_whitespace()