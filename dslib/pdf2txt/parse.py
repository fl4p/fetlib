import math
import os.path
import re
import traceback
import warnings
from typing import List, Tuple, Union, Optional

import pandas as pd

from dslib.cache import disk_cache
from dslib.field import Field, DatasheetFields
from dslib.pdf2txt import expr, strip_no_print_latin, ocr_post_subs, whitespaces_to_space, \
    whitespaces_remove, normalize_text, ocr_strip_string, whitespace_to_space
from dslib.pdf2txt.expr import get_field_detect_regex, dim_regs_csv, dim_regs_multiline
from dslib.pdf2txt.pipeline import convertapi, pdf2pdf


def _empty(s):
    return not s or str(s).lower() == 'nan'


class TooManyPages(ValueError):
    pass


def subsctract_needed_symbols(a: set, b: set, copy=False):
    if not isinstance(b, set):
        b = set(b)

    assert isinstance(a, set)

    if len(b) > 0:
        assert set(map(type, b)) == {str}, set(map(type, b))

    if copy:
        a = a.copy()

    for ia in list(a):
        if isinstance(ia, tuple):
            for iia in ia:
                if iia in b:
                    a.remove(ia)
                    break
        else:
            assert isinstance(ia, str)
            if ia in b:
                a.remove(ia)

    if copy:
        return a


@disk_cache(ttl='30d', file_dependencies=[0], salt='v03')
def extract_text(pdf_path, try_ocr=False):
    import fitz  # PyMuPDF
    pdf_document = fitz.open(pdf_path)

    if len(pdf_document) > 30:
        raise TooManyPages(pdf_path + ' has more than 25 pages ' + str(len(pdf_document)))

    pdf_text = ""
    for page_number in range(len(pdf_document)):
        page = pdf_document[page_number]
        pdf_text += page.get_text()

    pdf_document.close()

    if try_ocr and (len(pdf_text) < 20 or try_ocr == 'force'):
        ocr_path = pdf_path + '.convertapi_ocr.pdf'
        if not os.path.exists(ocr_path):
            convertapi(pdf_path, ocr_path, 'ocr')
        ocr_text = extract_text(ocr_path, try_ocr=False)
        if len(ocr_text) > 20:
            print(pdf_path, 'successfully extracted', len(ocr_text), 'characters using OCR')
        return ocr_text

    return pdf_text


def extract_fields_from_text(pdf_text: str, mfr, pdf_path='', verbose=True):
    assert mfr
    mpn = pdf_path.split('/')[-1].split('.')[0] if pdf_path else None

    source_name = os.path.basename(pdf_path)

    lines = pdf_text.split('\n')
    lines = [normalize_text(ocr_strip_string(line)) for line in lines]

    fields = DatasheetFields(mfr, mpn)
    detected = set()

    i = 0
    while i < len(lines):
        line = lines[i]
        m_detect, field_sym = detect_fields(mfr, [line])
        if m_detect:
            dim = field_sym[0]
            detected.add(field_sym)

            ctx_lines = lines[i:(i + 12)]
            f, m_parse = parse_field_multiline(
                '\n'.join(ctx_lines),
                dim=dim,
                field_sym=field_sym,
                cond=ctx_lines,
                capture_match=True,
                source=[source_name, 'text'],
                mfr=mfr,
            )

            if f:
                fields.add(f)
                i += max(1, m_parse[0].count('\n') - 1)  # step forward
                continue
            else:
                def is_number(s):
                    try:
                        float(s)
                        return True
                    except ValueError:
                        return False

                def is_list(lines: List[str]):
                    syms = {"Qgs", "Qgs1", "Qgd", "Qsw", "Qoss", "trr", "Qrr", "Vdsf", "Qgodr"}
                    if len(lines) <= 3:
                        return False
                    nns = (
                        sum(map(is_number, lines)),
                        sum(s.startswith('•') for s in lines)
                    )
                    for nn in nns:
                        if nn > 3 and nn >= (len(lines) - 2) * 0.6:
                            return True

                    lines = list(filter(bool, lines))

                    if len(set(s[:1] for s in lines)) / (len(lines) - 2) <= 0.4:
                        return True

                    if len({'0.1', '1', '10', '100', '100'} - set(lines)) == 0:
                        return True

                    return False

                other_detected_in_context = set(detect_fields(mfr, [l])[1] for l in ctx_lines[:5]) - {field_sym, None}

                if verbose and field_sym != 'Rg':
                    print('\n', field_sym, 'not parsed', mfr, pdf_path)

                    if other_detected_in_context:
                        print('other_detected_in_context', other_detected_in_context)

                    if len(ctx_lines) > 2 and len(other_detected_in_context) <= 2 and not is_list(ctx_lines):
                        print('    v---v ')
                        for l in ctx_lines: print(l)
                        print('    ^---^ ')
                        print('')

                        if verbose == 'debug':
                            print('regexs for dim', field_sym[0])
                            for r in dim_regs_multiline[field_sym[0]]:
                                print(field_sym, r.pattern.replace('"', '\\"'))
                            print('')

        i += 1

    # special Qrr case
    pat = expr.QRR.get(mfr)
    if pat:
        rg = re.compile(pat, re.MULTILINE | re.IGNORECASE)
        qrr_ms = list(rg.finditer(pdf_text))

        # if len(qrr_ms) != 1:
        #    if len(qrr_ms) == 2 and mpn in {'IQD016N08NM5ATMA1', 'FDMC007N08LC', 'FDMS4D4N08C'}:
        #        pass
        #    else:
        #        assert len(qrr_ms) == 0, (pdf_path, qrr_m)
        #        print(pdf_path, 'no Qrr match', pdf_text[:200].replace('\n', '<br>'))

        # if verbose and len(qrr_ms) == 0:
        #    print(pdf_path, 'no Qrr match', pdf_text[:200].replace('\n', '<br>'))

        for qrr_m in qrr_ms:
            qrr_d = qrr_m.groupdict()
            for k, v in list(qrr_d.items()):
                if v and k.endswith('2') or k.endswith('3'):
                    assert not qrr_d.get(k[:-1])
                    qrr_d[k[:-1]] = v
                    del qrr_d[k]

            fields.add(Field('Qrr',
                             min=qrr_d.get('min'), typ=qrr_d.get('typ'), max=qrr_d.get('max'),
                             mul=1,
                             cond=dict(
                                 i_f=qrr_d.get('if'),
                                 didt=qrr_d.get('didt'),
                                 vds=qrr_d.get('vds')),
                             unit=qrr_d.get('unit'),
                             source=[source_name, 'text']
                             ))  # vgs
    else:
        pass
        # if mfr:
        #    print('no Qrr pattern for ', mfr)

    return fields


def validate_datasheet_text(mfr, mpn, text):
    if len(text) < 60:
        # print('text too short ' + str(len(text)))
        return False

    _n = lambda s: whitespaces_remove(strip_no_print_latin(s.lower().replace('o', '0')))

    if _n(mpn).split(',')[0][:7] not in _n(text):
        print(mpn + ' not found in PDF text(%s)' % whitespaces_to_space(text)[:30])
        return False

    return True


regex_ver_salt = ('v46', dim_regs_csv, get_field_detect_regex('any'))


class NoTabularData(ValueError):
    pass


@disk_cache(ttl='99d', file_dependencies=[0], salt=(regex_ver_salt, 'v01'), ignore_missing_inp_paths=True)
def parse_datasheet(pdf_path=None, mfr=None, mpn=None,
                    tabular_pre_methods=None,
                    need_symbols=None,
                    no_ocr=False,
                    ) -> DatasheetFields:
    if not pdf_path:
        assert mfr
        pdf_path = f'datasheets/{mfr}/{mpn}.pdf'

    if not mfr:
        assert pdf_path
        pdf_path = os.path.realpath(pdf_path)
        mfr = pdf_path.split('/')[-2]
        assert len(mfr) >= 2

    if not mpn:
        mpn = os.path.basename(pdf_path).split('.')[0]

    pdf_text = extract_text(pdf_path, try_ocr=False)

    if not validate_datasheet_text(mfr, mpn, pdf_text):
        methods = ['qpdf_decrypt']  # 'r400_ocrmypdf'
        if not no_ocr:
            methods += ['r600_ocrmypdf', 'ocrmypdf_redo', 'ocrmypdf_r400', ]

            if not pdf_text:
                methods.remove('ocrmypdf_redo')
                methods.append('ocrmypdf_redo')  # move to end, because its intense

        for method in methods:
            try:
                out_path = pdf_path + '.' + method + '.pdf'
                pdf2pdf(pdf_path, out_path, method)

                pdf_text = extract_text(out_path, try_ocr=False)

                if not validate_datasheet_text(mfr, mpn, pdf_text):
                    print(pdf_path, 'text extraction error using', method)
                    continue

                pdf_path = out_path
                print(pdf_path, 'extracted', len(pdf_text), 'characters using', method)

                break

            except TooManyPages as e:
                print(e)
                raise

    if len(pdf_text) < 40:
        print(pdf_path, 'no/little text extracted')

    with open(pdf_path + '.txt', 'w') as f:
        f.write(pdf_text)

    pdf_text = normalize_text(pdf_text)

    # S19-0181-Rev. A, 25-Feb-2019, "S16-0163-Rev. A, 01-Feb-16"
    # "November 2021", "2021-01"
    # Rev.2.1,2022-03-28
    # "SLPS553 -OCTOBER 2015", "July 21,2022", " S23-1102-Rev. B, 11-Dec-2023
    # Submit Datasheet Feedback                   August 18, 2014

    ds = DatasheetFields(mfr, mpn)

    txt_fields = extract_fields_from_text(pdf_text, mfr=mfr, pdf_path=pdf_path)
    ds.add_multiple(txt_fields.all_fields())
    # TODO do extract_fields_from_text again afet raster_ocr

    if need_symbols:
        subsctract_needed_symbols(need_symbols, ds.keys())
    else:
        need_symbols = None

    if no_ocr:
        assert not tabular_pre_methods
        tabular_pre_methods = ('nop', 'gs', 'cups',)
    try:
        # if verbose:
        # print(pdf_path, 'tabular read ...  need=', need_symbols)
        tabular_ds = tabula_read(pdf_path, pre_process_methods=tabular_pre_methods, need_symbols=need_symbols)
        if not tabular_ds:
            raise NoTabularData(pdf_path)
        if tabular_ds:
            ds.add_multiple(tabular_ds.all_fields())
    except Exception as e:
        if not isinstance(e, NoTabularData):
            print(pdf_path, 'tabula error', type(e).__name__, e)
        raise

    if not ds:
        raise NoTabularData(pdf_path)

    return ds


try:
    import jpype

    _force_subprocess = False
except ImportError:
    # print('jpype not found')
    _force_subprocess = True


@disk_cache(ttl='99d', file_dependencies=True, salt='browser_v04_both')
def tabula_pdf_dataframes(pdf_path=None):
    import tabula

    # /Users/fab/Downloads/tabula/Tabula.app/Contents/Java/tabula.jar

    dfs = []

    from dslib.pdf2txt.tabular import tabula_browser, NoTextInPdfError

    last_e = None

    try:
        dfs += tabula_browser(pdf_path)
    except NoTextInPdfError as e:
        print(pdf_path, e)
    except TimeoutError:
        raise  # these are fatal, should not happen
    except Exception as e:
        last_e = e
        print(traceback.format_exc())
        print('tabula_browser error', e)
        # '/Users/fab/dev/pv/pwr-mosfet-lib/datasheets/nxp/PSMN3R9-100YSFX.pdf'
        #

    try:
        dfs += tabula.read_pdf(pdf_path, pages='all', pandas_options={'header': None}, multiple_tables=True,
                               force_subprocess=_force_subprocess)
        for df in dfs:
            df.index.name = 'tabula_cli_guess'
    except Exception as e:
        last_e = e
        print('tabula.read_pdf error', e)

    if len(dfs) == 0 and last_e:
        raise last_e

    """
     from subprocess import check_output
        out = check_output(["java" "-jar" "~/dev/tabula-java/target/tabula-1.0.6-SNAPSHOT-jar-with-dependencies.jar",
                            "--guess",
                            "--pages", "all",
                            '""'])
        #'~dev/crypto/venv-arm/lib/python3.9/site-packages/tabula/tabula-1.0.5-jar-with-dependencies.jar'
    """

    return dfs


def is_gan(mfr):
    return 'epc' in mfr.lower()


# def find_dim_match(csv_line, regexs):
#    for r in regexs:
##        m = next(r.finditer(csv_line), None)
#        if m is not None:
#            return m
#        # print(r, 'not found in', csv_line)
#    return None


def check_range(v, range):
    if len(range) == 3 and range[2]:
        v = abs(v)
    return math.isnan(v) or (v >= range[0] and v <= range[1])


valid_range = dict(
    # min,max,abs?
    Vpl=(1, 10, False),
    Vsd=(0.1, 4, True),
    # Qgd=(0, 2000, False), # Gate to Drain Charge
)


def parse_field(s, regs, field_sym, cond=None, capture_match=False, source=None, mfr=None) \
        -> Union[Optional[Field], Tuple[Optional[Field], Optional[re.Match]]]:
    range = valid_range.get(field_sym)
    err = []
    m: Optional[re.Match] = None

    det_re = get_field_detect_regex(mfr)[field_sym] if len(field_sym) > 1 else None
    stop_words = det_re[1] if isinstance(det_re, tuple) else []

    for r in regs:
        # print(csv_line, dim , r.pattern)
        try:
            # print(r.pattern.replace('\'', '\\\''),'\non\n', repr(s),'..')
            m: re.Match = next(r.finditer(s), None)
            # print('..done.')
        except:
            print(traceback.format_exc())
            print("finding '%s' in %r" % (r.pattern.replace('\'', '\\\''), s))
            raise

        # print('done.')
        if m is None:
            continue
        vd = m.groupdict()

        val_g = m.re.groupindex.get('typ') or m.re.groupindex.get('max') or m.re.groupindex.get('min')
        head = vd.get('head') or s[:m.start(val_g)]
        stop = False
        for sw in stop_words:
            if sw in head:
                print('parsing', field_sym, 'in', s, 'but found stop word', sw, 'in match head:', head)
                stop = True
                break
            if sw in m[0]:
                warnings.warn(
                    f'parsing {field_sym}: stop word `{sw}` in match `{m[0]}` but not in head `{head}`, ignoring')

        if stop:
            continue

        try:
            f = Field(symbol=field_sym,
                      min=(vd.get('min') or '').rstrip('-'),
                      typ=(vd.get('typ') or '').rstrip('-'),
                      max=vd.get('max'),
                      mul=1,
                      cond=cond,
                      unit=vd.get('unit'),
                      source=source)
            if range and not (check_range(f.min, range) and check_range(f.typ, range) and check_range(f.max, range)):
                err.append((field_sym, 'field out of range', f, range))
                continue

            if capture_match:
                return f, m

            return f
        except Exception as e:
            err.append((field_sym, 'error parsing field row', s, e))
            continue
    for e in err:
        print(*e)

    if capture_match:
        return None, m

    return None


def parse_field_csv(csv_line, dim, **kwargs) \
        -> Union[Optional[Field], Tuple[Optional[Field], Optional[re.Match]]]:
    return parse_field(csv_line, dim_regs_csv[dim], **kwargs)


def parse_field_multiline(text, dim, field_sym, cond=None, capture_match=False, source=None, mfr=None) \
        -> Union[Optional[Field], Tuple[Optional[Field], Optional[re.Match]]]:
    return parse_field(text, dim_regs_multiline[dim], field_sym, cond, capture_match, source, mfr=mfr)


class DetectedSymbol:
    def __init__(self, index: int, match: re.Match, symbol: str):
        self.index = index
        self.match = match
        self.symbol = symbol


def detect_fields(mfr, strings: List[str], multi=False) -> Union[Optional[DetectedSymbol], List[DetectedSymbol]]:
    # strings = [whitespaces_to_space(s).strip(' -') for s in strings]
    # normalize_text(str(s)).strip(' -')

    #strings = [whitespace_to_space(s) for s in strings]
    strings = [whitespace_to_space(s).lower() for s in strings]

    fields_detect = get_field_detect_regex(mfr)
    detected = []

    for field_sym, field_re in fields_detect.items():
        if isinstance(field_re, tuple):
            stop_words = field_re[1]
            assert not isinstance(stop_words, str)
            field_re = field_re[0]
        else:
            stop_words = []

        for i in range(len(strings)):
            s = strings[i]

            if len(s) > 80:
                continue

            if stop_words and max(map(lambda sw: sw in s, stop_words)):
                continue

            m = field_re.search(s)

            if m:
                ds =  DetectedSymbol(i, m, field_sym)
                if multi:
                    detected.append(ds)
                else:
                    return ds
    return detected if multi else None


def right_strip_nan(v, n):
    if len(v) <= n:
        return v
    i = None
    for i in range(len(v) - 1, -1, -1):
        if not _empty(v[i]):
            break
    if i + n + 1 < len(v):
        v = v[0:i + n + 1]
    return v


def extract_fields_from_dataframes(dfs: List[pd.DataFrame], mfr, ds_path='', verbose=False) -> DatasheetFields:
    assert mfr
    assert not ds_path or mfr in ds_path, (mfr, ds_path)
    fields_detect = get_field_detect_regex(mfr)

    source_base = os.path.basename(ds_path) if ds_path else ''

    dim_units = dict(
        t={'us', 'ns', 'μs', 'ms'},
        Q={'uC', 'nC', 'μC'},
        C={'uF', 'nF', 'μF'},
        V={'mV', 'V'},
        R={'mΩ', 'Ω', 'kΩ', 'MΩ', 'mOhm', 'Ohm', 'kOhm', 'MOhm', 'megOhm'},
    )

    # noinspection PyTypeChecker
    all_units = set(sum(map(list, dim_units.values()), []))

    fields = DatasheetFields()

    from collections import defaultdict
    col_idx = defaultdict(lambda: 0)
    other_cols = ['min', 'max', 'unit']

    for df in dfs:
        col_idx.clear()
        unit = None
        col_typ = 0

        source_name = df.index.name

        # ffill unit
        # df.mask(~df.isnumeric(), None).ffill()

        df_ffill = df.ffill()
        df_bfill = df.bfill()

        for i, row in df.iterrows():

            if col_idx['unit'] and row[col_idx['unit']] and isinstance(row[col_idx['unit']], str) and row[
                col_idx['unit']].strip() in all_units:
                unit = row[col_idx['unit']].strip()

            try:
                low = row.iloc[1:].str.lower().str.strip().str
            except AttributeError:
                low = pd.Series().str
            h_typ = low.startswith('typ')
            if h_typ.sum() == 1:
                assert h_typ.sum() == 1, low.lower()
                col_typ = h_typ.idxmax()
                col_idx.clear()
                unit = None

                for col in other_cols:
                    is_h = low.startswith(col)
                    if is_h.sum() == 1:
                        # this can fail 'PSMN009-100P,127.pdf':7
                        # assert is_h.sum() == 1, (row, col)
                        col_idx[col] = is_h.idxmax()
                    elif is_h.sum() > 1:
                        warnings.warn(f'{source_base} {df.index.name} {row.to_list()}'
                                      f' potential header row has more than 1 {col}')

            m, field_sym = detect_fields(mfr, row.iloc[:4])

            if m:

                if verbose:
                    print('field detected', field_sym, m, 'in row', i, 'of', df.index.name,
                          '"' + ','.join(row.astype(str).to_list()))

                dim = field_sym[0]

                def _fill_unit(row, columns, fill_row, units):
                    if len(row) < 2: columns.remove(-2)
                    if len(row) < 3: columns.remove(-3)
                    assert len(row) == len(fill_row)

                    for col in columns:
                        fv = fill_row.iloc[col]
                        if (_empty(row.iloc[col]) and not _empty(fv) and not fv in row.values
                                and isinstance(fv, str) and fv.strip() in units):
                            row.iloc[col] = fv
                            return fv

                row = row.copy()
                # ffill or bfill unit in case of vertically merged cells
                if col_idx['unit'] and _empty(
                        row[col_idx['unit']]) and unit not in row.values and unit in dim_units[dim]:
                    row[col_idx['unit']] = unit
                else:
                    (_fill_unit(row, [-1, -2, -3], df_ffill.iloc[i], dim_units[dim]) or
                     _fill_unit(row, [-1, -2, -3], df_bfill.iloc[i], dim_units[dim]))

                rl = normalize_text(','.join(map(lambda v: str(v).strip(' ,\'"/|'), right_strip_nan(row, 2))))
                rl_bf = normalize_text(','.join(map(lambda v: str(v).strip(' ,'), df_bfill.iloc[i])))
                rl_ff = normalize_text(','.join(map(lambda v: str(v).strip(' ,'), df_ffill.iloc[i])))

                # OCR
                rl = ocr_post_subs(rl)
                rl = whitespaces_to_space(rl)

                field, parse_match = parse_field_csv(rl, dim, field_sym=field_sym, cond=dict(row.dropna()),
                                                     capture_match=True,
                                                     source=[source_base, source_name, 'parse_csv'],
                                                     mfr=mfr,
                                                     )

                if not field and len(list(filter(bool, row.dropna()))) > 2:
                    print(ds_path, field_sym, 'no value match in ', f'"{rl}"')

                if field:
                    if verbose > 0:
                        print(field_sym, 'field values parsed', repr(field), 'from', rl,
                              '\n   regex: ', parse_match.re.pattern,
                              '\n   match: ',
                              ' '.join(map('='.join, (t for t in parse_match.groupdict().items() if t[1]))),
                              )
                    fields.add(field)

                elif col_typ:
                    for row_ in [row, df_bfill.iloc[i], df_ffill.iloc[i]]:
                        v_typ = row_[col_typ]
                        try:
                            field = Field(
                                symbol=field_sym,
                                min=row_[col_idx['min']] if col_idx['min'] else math.nan,
                                typ=v_typ.split(' ')[0] if isinstance(v_typ, str) else v_typ,
                                max=row_[col_idx['max']] if col_idx['max'] else math.nan,
                                mul=1, cond=dict(row_.dropna()), unit=unit,
                                source=[source_base, source_name, 'iter_table']
                            )
                            if verbose > 1:
                                print('add row_ field', field, 'from', row_)
                            fields.add(field)
                            break
                        except Exception as e:
                            if verbose:
                                print(ds_path, 'error parsing field with col_idx', dict(**col_idx, typ=col_typ), e)
                                # print(row.values)
                                print(rl, rl_ff, rl_bf)
                                # print(rl_ff)
                                # print(rl_bf)
                                # raise
                else:
                    if verbose:
                        print(ds_path, 'found field tag but col_typ unknown', field_sym, list(row))

    for s in fields_detect.keys():
        if s not in fields and not is_gan(ds_path):
            # print(ds_path, 'no value detected for field', s)
            pass

    return fields


@disk_cache(ttl='99d', file_dependencies=[0], salt=regex_ver_salt)
def tabula_read(ds_path, pre_process_methods=None, need_symbols=None, verbose=False) -> DatasheetFields:
    """

    nop
    sips
    gs
    cups
    if no text:
        convertapi_ocr
        rasterize,convertapi_ocr
    else: #weirdly encoded text
        rasterize,convertapi_ocr


    :param ds_path:
    :param pre_process_methods:
    :return:
    """

    mfr = ds_path.split('/')[-2]

    need_symbols = need_symbols and set(need_symbols)

    if pre_process_methods is None:
        pre_process_methods = (
            # fix java.lang.IllegalArgumentException: lines must be orthogonal, vertical and horizontal:
            'nop',
            # 'sips',
            'gs', 'cups',
            'r600_ocrmypdf',
            'ocrmypdf_redo',
            # fix image datasheets, weird encoding
            'ocrmypdf_r400',
            'r400_ocrmypdf',

            'ocrmypdf_r600',
            # 'r600_ocrmypdf',
        )
    elif isinstance(pre_process_methods, str):
        pre_process_methods = (pre_process_methods,)

    assert len(set(pre_process_methods)) == len(pre_process_methods), 'duplicate pre_process_methods'

    for method in list(pre_process_methods):
        if f'.{method}.' in ds_path:
            print(ds_path, 'already has method', method, 'applied')
            pre_process_methods = list(pre_process_methods)
            pre_process_methods.remove(method)
            if 'nop' not in pre_process_methods:
                pre_process_methods.insert(0, 'nop')

    combined_fields = DatasheetFields()

    last_e = None
    for method in pre_process_methods:
        f2 = ds_path + '.' + method + '.pdf' if method != 'nop' else ds_path
        try:
            pdf2pdf(ds_path, f2, method=method)

            dfs = tabula_pdf_dataframes(ds_path if method == 'nop' else f2)

            if len(dfs) > 0:
                if method != 'nop' and verbose:
                    print(ds_path, 'extracted', len(dfs), 'dataframes using method', method)
                last_e = None
            else:
                print(ds_path, 'tabula empty', method)
                continue
        except TimeoutError:
            raise
        except Exception as e:
            last_e = e
            print(ds_path, 'tabula error with method', method, e)
            continue

        if len(dfs):  # and not os.path.isfile(ds_path + '.csv'):
            side_csv = ds_path + '.' + method + '.csv'
            # print('writing sidecar csv', side_csv)
            pd.concat(dfs, ignore_index=True, axis=0).map(
                lambda s: (isinstance(s, str) and whitespaces_to_space(ocr_post_subs(normalize_text(s)))) or s).to_csv(
                side_csv, header=False)

        fields = extract_fields_from_dataframes(dfs, mfr=mfr, ds_path=f2, verbose=verbose)

        if len(fields) > 0:
            combined_fields.add_multiple(fields.all_fields())
            if need_symbols:
                missing = subsctract_needed_symbols(need_symbols, combined_fields.keys(), copy=True)

                if missing:
                    print(ds_path, 'extracted', len(fields), 'fields with method', method, 'but still missing fields:',
                          missing)
                    continue
                else:
                    return combined_fields
            return fields
        else:
            if verbose:
                print(ds_path, 'tabula no fields extracted with method', method)

    if need_symbols and combined_fields:
        missing = subsctract_needed_symbols(need_symbols, combined_fields.keys(), copy=True)
        print(ds_path, 'needed', need_symbols, ', have', set(combined_fields.keys()), 'missing fields:', missing)
        return combined_fields
        # raise ValueError('missing fields ' + str(missing))

    # no fields found..
    txt = extract_text(ds_path, try_ocr=False)
    if len(txt) < 20:
        print(ds_path, 'probably needs OCR')
        raise ValueError('probably need OCR ' + ds_path)
    else:
        print(ds_path, 'tabula no methods working, tried', ', '.join(pre_process_methods))
        if last_e:
            raise last_e

# def find_value(pdf_text, label, unit):
#    matches = re.findall(r"%s\s+[^0-9]*([0-9.]+)\s*%s" % (label, unit), pdf_text)
#    val = matches[0] if matches else None
#   return val
