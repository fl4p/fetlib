import pytest

from dslib.field import DatasheetFields, Field
import dslib.pdf.parse as parse
import dslib.v2


def test_fix_font_failure_continues_to_ocr(monkeypatch, tmp_path):
    pdf_path = str(tmp_path / 'PART.pdf')
    (tmp_path / 'PART.pdf').write_bytes(b'%PDF fixture')
    methods = []

    def fake_pdf2pdf(_in_path, _out_path, method):
        methods.append(method)
        if method == 'fix_font_enc':
            raise ValueError('no bad fonts nothing to fix')

    def fake_extract_text(path, **_kwargs):
        if path.endswith('.r600_ocrmypdf.pdf'):
            text = 'valid repaired text from the OCR fallback'
        else:
            text = 'bad text'
        return text, parse.DataSheetFileMeta('', None, None)

    monkeypatch.setattr(parse, 'pdf2pdf', fake_pdf2pdf)
    monkeypatch.setattr(parse, 'extract_text', fake_extract_text)
    monkeypatch.setattr(parse, 'validate_datasheet_text',
                        lambda _mfr, _mpn, text: text.startswith('valid'))
    monkeypatch.setattr(parse, 'extract_dates', lambda _text: [])
    monkeypatch.setattr(
        parse, 'extract_fields_from_text',
        lambda *_args, **_kwargs: DatasheetFields(
            'test', 'PART', fields=[Field('Qg', float('nan'), 10, float('nan'), 'nC')]))
    monkeypatch.setattr(
        dslib.v2, 'parse_datasheet',
        lambda *_args, **_kwargs: DatasheetFields(
            'test', 'PART', fields=[Field('Qg', float('nan'), 10, float('nan'), 'nC')]))
    monkeypatch.setattr(parse, 'read_charts', lambda *_args, **_kwargs: [])

    ds = parse.parse_datasheet.__wrapped__(
        pdf_path, mfr='test', mpn='PART', need_symbols=set())

    assert methods == ['gs', 'fix_font_enc', 'r600_ocrmypdf']
    assert ds.Qg.typ == 10


def test_fix_font_no_output_continues_to_ocr(monkeypatch, tmp_path):
    """A rung that neither raises nor writes its file (infineon/IRFP3710PBF:
    fix_font_enc returns without producing output) is a failed rung. The
    missing derivative surfaces as FileNotFoundError from extract_text's cache
    dependency, which must be skipped, not propagated."""
    pdf_path = str(tmp_path / 'PART.pdf')
    (tmp_path / 'PART.pdf').write_bytes(b'%PDF fixture')
    methods = []

    monkeypatch.setattr(parse, 'pdf2pdf',
                        lambda _i, _o, method: methods.append(method))

    def fake_extract_text(path, **_kwargs):
        if path.endswith('.fix_font_enc.pdf'):
            raise FileNotFoundError(path)
        if path.endswith('.r600_ocrmypdf.pdf'):
            return 'valid repaired text from the OCR fallback', \
                parse.DataSheetFileMeta('', None, None)
        return 'bad text', parse.DataSheetFileMeta('', None, None)

    monkeypatch.setattr(parse, 'extract_text', fake_extract_text)
    monkeypatch.setattr(parse, 'validate_datasheet_text',
                        lambda _mfr, _mpn, text: text.startswith('valid'))
    monkeypatch.setattr(parse, 'extract_dates', lambda _text: [])
    monkeypatch.setattr(
        parse, 'extract_fields_from_text',
        lambda *_a, **_k: DatasheetFields(
            'test', 'PART', fields=[Field('Qg', float('nan'), 10, float('nan'), 'nC')]))
    monkeypatch.setattr(
        dslib.v2, 'parse_datasheet',
        lambda *_a, **_k: DatasheetFields(
            'test', 'PART', fields=[Field('Qg', float('nan'), 10, float('nan'), 'nC')]))
    monkeypatch.setattr(parse, 'read_charts', lambda *_a, **_k: [])

    ds = parse.parse_datasheet.__wrapped__(
        pdf_path, mfr='test', mpn='PART', need_symbols=set())

    assert methods == ['gs', 'fix_font_enc', 'r600_ocrmypdf']
    assert ds.Qg.typ == 10


def test_exhausted_repair_ladder_allows_identity_heuristic_false_negative(
        monkeypatch, tmp_path):
    pdf_path = str(tmp_path / 'IXTH75N10.pdf')
    (tmp_path / 'IXTH75N10.pdf').write_bytes(b'%PDF fixture')
    methods = []

    def fake_pdf2pdf(_in_path, _out_path, method):
        methods.append(method)
        if method == 'fix_font_enc':
            raise AssertionError('corrupt cmap')

    monkeypatch.setattr(parse, 'pdf2pdf', fake_pdf2pdf)
    monkeypatch.setattr(
        parse, 'extract_text',
        lambda *_args, **_kwargs: (
            'IXTH / IXTM 75N10 family datasheet text that does not contain '
            'the normalized filename spelling',
            parse.DataSheetFileMeta('', None, None)))
    monkeypatch.setattr(parse, 'validate_datasheet_text',
                        lambda _mfr, _mpn, _text: False)
    monkeypatch.setattr(parse, 'extract_dates', lambda _text: [])
    monkeypatch.setattr(
        parse, 'extract_fields_from_text',
        lambda *_args, **_kwargs: DatasheetFields(
            'littelfuse', 'IXTH75N10',
            fields=[Field('Qg', float('nan'), 42, float('nan'), 'nC')]))
    monkeypatch.setattr(
        dslib.v2, 'parse_datasheet',
        lambda *_args, **_kwargs: DatasheetFields(
            'littelfuse', 'IXTH75N10',
            fields=[Field('Qg', float('nan'), 42, float('nan'), 'nC')]))
    monkeypatch.setattr(parse, 'read_charts', lambda *_args, **_kwargs: [])

    ds = parse.parse_datasheet.__wrapped__(
        pdf_path, mfr='littelfuse', mpn='IXTH75N10', need_symbols=set())

    assert methods == ['gs', 'fix_font_enc', 'r600_ocrmypdf']
    assert ds.Qg.typ == 42


def test_repeated_near_neighbor_mpn_rejects_wrong_datasheet(monkeypatch, tmp_path):
    pdf_path = str(tmp_path / 'IRF540N-HXY.pdf')
    (tmp_path / 'IRF540N-HXY.pdf').write_bytes(b'%PDF fixture')
    wrong_text = (
        'International Rectifier IRF640N power MOSFET datasheet with enough '
        'text for extraction, but it identifies the wrong device number.')

    monkeypatch.setattr(parse, 'pdf2pdf', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        parse, 'extract_text',
        lambda *_args, **_kwargs: (
            wrong_text, parse.DataSheetFileMeta('', None, None)))

    with pytest.raises(parse.NoTabularData,
                       match=r'conflicting datasheet MPN.*irf640'):
        parse.parse_datasheet.__wrapped__(
            pdf_path, mfr='hxy', mpn='IRF540N-HXY', need_symbols=set())


def test_exhausted_ladder_keeps_longest_extracted_text(monkeypatch, tmp_path):
    pdf_path = str(tmp_path / '8070.0.pdf')
    (tmp_path / '8070.0.pdf').write_bytes(b'%PDF fixture')
    original_text = 'GOFORD 8070 valid family text ' + 'complete ' * 20
    shorter_texts = {
        '.gs.pdf': 'GOFORD 8070 short GS text',
        '.fix_font_enc.pdf': 'GOFORD 8070 shorter fixed text',
        '.r600_ocrmypdf.pdf': 'GOFORD 8070 noisy OCR',
    }
    parsed_texts = []

    monkeypatch.setattr(parse, 'pdf2pdf', lambda *_args, **_kwargs: None)

    def fake_extract_text(path, **_kwargs):
        text = next(
            (value for suffix, value in shorter_texts.items()
             if path.endswith(suffix)),
            original_text)
        return text, parse.DataSheetFileMeta('', None, None)

    monkeypatch.setattr(parse, 'extract_text', fake_extract_text)
    monkeypatch.setattr(parse, 'validate_datasheet_text',
                        lambda _mfr, _mpn, _text: False)
    monkeypatch.setattr(parse, 'extract_dates', lambda _text: [])

    def fake_extract_fields(text, *_args, **_kwargs):
        parsed_texts.append(text)
        return DatasheetFields(
            'goford', '8070.0',
            fields=[Field('Qg', float('nan'), 7, float('nan'), 'nC')])

    monkeypatch.setattr(parse, 'extract_fields_from_text', fake_extract_fields)
    monkeypatch.setattr(
        dslib.v2, 'parse_datasheet',
        lambda *_args, **_kwargs: DatasheetFields(
            'goford', '8070.0',
            fields=[Field('Qg', float('nan'), 7, float('nan'), 'nC')]))
    monkeypatch.setattr(parse, 'read_charts', lambda *_args, **_kwargs: [])

    ds = parse.parse_datasheet.__wrapped__(
        pdf_path, mfr='goford', mpn='8070.0', need_symbols=set())

    assert parsed_texts == [original_text]
    assert ds.Qg.typ == 7


def test_fix_font_extraction_error_is_not_hidden(monkeypatch, tmp_path):
    pdf_path = str(tmp_path / 'PART.pdf')
    (tmp_path / 'PART.pdf').write_bytes(b'%PDF fixture')

    monkeypatch.setattr(parse, 'pdf2pdf', lambda *_args, **_kwargs: None)

    def fake_extract_text(path, **_kwargs):
        if path.endswith('.fix_font_enc.pdf'):
            raise ValueError('unexpected extraction failure')
        return 'bad text', parse.DataSheetFileMeta('', None, None)

    monkeypatch.setattr(parse, 'extract_text', fake_extract_text)
    monkeypatch.setattr(parse, 'validate_datasheet_text',
                        lambda _mfr, _mpn, _text: False)

    with pytest.raises(ValueError, match='unexpected extraction failure'):
        parse.parse_datasheet.__wrapped__(
            pdf_path, mfr='test', mpn='PART', need_symbols=set())
