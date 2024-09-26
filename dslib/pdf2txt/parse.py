import math
import os.path
import re
import traceback
import warnings
from typing import Iterable, List, Tuple, Union, Optional

import pandas as pd

from dslib.cache import disk_cache
from dslib.field import Field, DatasheetFields
from dslib.pdf2txt import expr, normalize_dash, strip_no_print_latin, ocr_post_subs, whitespaces_to_space, \
    whitespaces_remove
from dslib.pdf2txt.expr import get_field_detect_regex, dim_regs
from dslib.pdf2txt.pipeline import convertapi, pdf2pdf
from dslib.pdf2txt.tabular import NoTextInPdfError


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

    if try_ocr and len(pdf_text) < 20:
        ocr_path = pdf_path + '.convertapi_ocr.pdf'
        if not os.path.exists(ocr_path):
            convertapi(pdf_path, ocr_path, 'ocr')
        ocr_text = extract_text(ocr_path, try_ocr=False)
        if len(ocr_text) > 20:
            print(pdf_path, 'successfully extracted', len(ocr_text), 'characters using OCR')
        return ocr_text

    return pdf_text


def normalize_pdf_text(pdf_text: str):
    pdf_text = pdf_text.replace('\0x04', '\x03')  # utf8 b'\xe2\x80\x93' toshiba
    pdf_text = pdf_text.replace('', '\x03')  # toshiba
    pdf_text = pdf_text.replace('\0x03', '\x03')
    pdf_text = pdf_text.replace('', '\x03')
    pdf_text = normalize_dash(pdf_text)
    return pdf_text


def extract_fields_from_text(pdf_text: str, mfr, pdf_path):
    fields = []

    assert mfr

    source_name = os.path.basename(pdf_path)

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

            fields.append(Field('Qrr',
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
        if mfr:
            print('no Qrr pattern for ', mfr)

    return fields


def validate_datasheet_text(mfr, mpn, text):
    if len(text) < 60:
        print('text too short ' + str(len(text)))
        return False

    if mpn.split(',')[0][:7].lower() not in whitespaces_remove(strip_no_print_latin(text)).lower():
        print(mpn + ' not found in PDF text(%s)' % whitespaces_to_space(text)[:30])
        return False

    return True


regex_ver_salt = ('v42', dim_regs)


class NoTabularData(ValueError):
    pass


@disk_cache(ttl='99d', file_dependencies=[0], salt=regex_ver_salt, ignore_missing_inp_paths=True)
def parse_datasheet(pdf_path=None, mfr=None, mpn=None,
                    tabular_pre_methods=None,
                    need_symbols=None
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
        methods = ['qpdf_decrypt', 'ocrmypdf_redo', 'ocrmypdf_r400', 'r400_ocrmypdf']

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

    pdf_text = normalize_pdf_text(pdf_text)

    # S19-0181-Rev. A, 25-Feb-2019, "S16-0163-Rev. A, 01-Feb-16"
    # "November 2021", "2021-01"
    # Rev.2.1,2022-03-28
    # "SLPS553 -OCTOBER 2015", "July 21,2022", " S23-1102-Rev. B, 11-Dec-2023
    # Submit Datasheet Feedback                   August 18, 2014

    ds = DatasheetFields(mfr, mpn)

    txt_fields = extract_fields_from_text(pdf_text, mfr=mfr, pdf_path=pdf_path)
    ds.add_multiple(txt_fields)
    # TODO do extract_fields_from_text again afet raster_ocr

    if need_symbols:
        subsctract_needed_symbols(need_symbols, ds.keys())
    else:
        need_symbols = None

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

    from dslib.pdf2txt.tabular import tabula_browser

    last_e = None

    try:
        dfs += tabula_browser(pdf_path)
    except NoTextInPdfError as e:
        print(pdf_path, e)
    except TimeoutError:
        raise # these are fatal, should not happen
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


def parse_field_csv(csv_line, dim, field_sym, cond=None, capture_match=False, source=None) \
        -> Union[Optional[Field], Tuple[Optional[Field], Optional[re.Match]]]:
    range = valid_range.get(field_sym)
    err = []
    for r in dim_regs[dim]:
        # print(csv_line, dim , r.pattern)
        m: re.Match = next(r.finditer(csv_line), None)
        # print('done.')
        if m is None:
            continue

        vd = m.groupdict()
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
            err.append((field_sym, 'error parsing field row', csv_line, 'dim=', dim, e))
            continue
    for e in err:
        print(*e)
    if capture_match:
        return None, None
    return None


def detect_fields(mfr, strings: Iterable[str]):
    fields_detect = get_field_detect_regex(mfr)
    for field_sym, field_re in fields_detect.items():
        if isinstance(field_re, tuple):
            stop_words = field_re[1]
            assert not isinstance(stop_words, str)
            field_re = field_re[0]
        else:
            stop_words = []

        def detect_field(s):
            s = normalize_dash(str(s)).strip(' -')
            s = strip_no_print_latin(s)
            s = whitespaces_to_space(s)

            if len(s) > 80:
                return False
            if not field_re.search(s):
                return False
            if stop_words and max(map(lambda sw: sw in s, stop_words)):
                return False
            return True

        m = next(filter(detect_field, strings), None)
        if m is not None:
            return m, field_sym

    return None, None


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

                rl = normalize_dash(','.join(map(lambda v: str(v).strip(' ,\'"/|'), right_strip_nan(row, 2))))
                rl_bf = normalize_dash(','.join(map(lambda v: str(v).strip(' ,'), df_bfill.iloc[i])))
                rl_ff = normalize_dash(','.join(map(lambda v: str(v).strip(' ,'), df_ffill.iloc[i])))

                # OCR
                rl = ocr_post_subs(rl)
                rl = strip_no_print_latin(rl)
                rl = whitespaces_to_space(rl)

                field = parse_field_csv(rl, dim, field_sym=field_sym, cond=dict(row.dropna()),
                                        source=[source_base, source_name, 'parse_csv'])

                if not field and len(list(filter(bool, row.dropna()))) > 2:
                    print(ds_path, field_sym, 'no value match in ', f'"{rl}"')

                if field:
                    if verbose > 1:
                        print('add regex field', field, 'from', rl)
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
                            print(ds_path, 'error parsing field with col_idx', dict(**col_idx, typ=col_typ), e)
                            #print(row.values)
                            print(rl, rl_ff, rl_bf)
                            #print(rl_ff)
                            #print(rl_bf)
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
def tabula_read(ds_path, pre_process_methods=None, need_symbols=None) -> DatasheetFields:
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
            'sips', 'gs', 'cups',
            'ocrmypdf_redo',
            # fix image datasheets, weird encoding
            'ocrmypdf_r400',
            'r400_ocrmypdf',

            'ocrmypdf_r600',
            'r600_ocrmypdf',
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
        f2 = ds_path + '.' + method + '.pdf'
        try:

            pdf2pdf(ds_path, f2, method=method)

            dfs = tabula_pdf_dataframes(ds_path if method == 'nop' else f2)

            if len(dfs) > 0:
                if method != 'nop':
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
                lambda s: (isinstance(s, str) and whitespaces_to_space(
                    strip_no_print_latin(ocr_post_subs(normalize_dash(s))))) or s).to_csv(side_csv, header=False)

        fields = extract_fields_from_dataframes(dfs, mfr=mfr, ds_path=ds_path)

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
