import math
import re
from typing import List

import pandas as pd

from dslib.cache import disk_cache
from dslib.field import Field
from dslib.pdf2txt import expr, normalize_dash


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

    pdf_text = pdf_text.replace('\0x04', '\x03')  # utf8 b'\xe2\x80\x93' toshiba
    pdf_text = pdf_text.replace('', '\x03')  # toshiba
    pdf_text = pdf_text.replace('\0x03', '\x03')
    pdf_text = pdf_text.replace('', '\x03')
    pdf_text = normalize_dash(pdf_text)

    fields: List[Field] = []

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

        if len(qrr_ms) == 0:
            print(pdf_path, 'no Qrr match', pdf_text[:200].replace('\n', '<br>'))

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
                                unit=qrr_d.get('unit')))  # vgs
    else:
        print('no Qrr pattern for ', mfr)

    try:
        tab_fields = tabula_read(pdf_path)
        fields.extend(tab_fields.values())
    except Exception as e:
        print(pdf_path, 'tabula error', e)
        raise

    # build dict taking first symbol
    d = dict()
    for f in fields:
        if f.symbol not in d:
            d[f.symbol] = f

    return d


@disk_cache(ttl='99d', file_dependencies=True)
def tabula_pdf_dataframes(pdf_path=None):
    import tabula

    fails = {'datasheets/onsemi/NVMFS6H800NLT1G.pdf',
             'datasheets/onsemi/NVMFS6H800NT1G.pdf', 'datasheets/onsemi/NTMFS6H800NLT1G.pdf',
             'datasheets/onsemi/FDD86367.pdf', 'datasheets/onsemi/FDD86369.pdf', 'datasheets/onsemi/NTMFS6H800NT1G.pdf',
             'datasheets/onsemi/NTMFWS1D5N08XT1G.pdf', 'datasheets/onsemi/FDMC008N08C.pdf',
             'datasheets/onsemi/NVMFS6H800NWFT1G.pdf', 'datasheets/onsemi/NVMFS6H800NLWFT1G.pdf',
             'datasheets/onsemi/NTMFS08N2D5C.pdf', 'datasheets/nxp/PSMN4R3-80ES,127.pdf',
             'datasheets/nxp/PSMN3R5-80PS,127.pdf', 'datasheets/nxp/PSMN4R3-80PS,127.pdf',
             'datasheets/onsemi/FDD86367-F085.pdf', 'datasheets/onsemi/NVMFWS6D2N08XT1G.pdf',
             'datasheets/onsemi/FDD86369-F085.pdf', 'datasheets/onsemi/NVMFWS1D9N08XT1G.pdf',
             'datasheets/ao/AOTL66811.pdf',

             'datasheets/diodes/DMT10H9M9SCT.pdf',  # unsupported operation
             }
    if pdf_path in fails:
        raise Exception(f'PDF {pdf_path} known to fail')
    dfs = tabula.read_pdf(pdf_path, pages='all', pandas_options={'header': None})

    """
     from subprocess import check_output
        out = check_output(["java" "-jar" "~/dev/tabula-java/target/tabula-1.0.6-SNAPSHOT-jar-with-dependencies.jar",
                            "--guess",
                            "--pages", "all",
                            '""'])
        #'~dev/crypto/venv-arm/lib/python3.9/site-packages/tabula/tabula-1.0.5-jar-with-dependencies.jar'
    """

    return dfs


def is_gan(d):
    return 'EPC' in d


def find_dim_match(csv_line, regexs):
    for r in regexs:
        m = next(r.finditer(csv_line), None)
        if m is not None:
            return m
        # print(r, 'not found in', csv_line)
    return None


def parse_row_value(csv_line, dim, field_sym, cond=None):
    for r in dim_regs[dim]:
        m = next(r.finditer(csv_line), None)
        if m is None:
            continue

        vd = m.groupdict()
        try:
            return Field(symbol=field_sym,
                         min=vd.get('min', '').rstrip('-'),
                         typ=vd.get('typ', '').rstrip('-'),
                         max=vd.get('max'),
                         mul=1,
                         cond=cond,
                         unit=vd.get('unit'))
        except:
            print(field_sym, 'error parsing field row', csv_line, 'dim=', dim)
            continue
    return None


def field_value_regex_variations(head, unit):
    """
    Output Capacitance Coss VDS = 50V, --,3042,--,pF
    Output Capacitance Coss VDS = 50V, --,2730,--,pF

    Coss no value match Output Capacitance Coss VDS = 50V, --,380,--,pF

    Qrr no value match Reverse Recovery Charge Qrr nCIF = 80A, VGS = 0V--,297,--,nan


     Qrr no value match Reverse Recovery Charge Qrr nCIF = 50A, VGS = 0V--,87,--,nan
    "/dt = 100 A/μsReverse recovery charge,Q rr,-dI DR,nan,nan,35,nan,nC"

    :param head:
    :param unit:
    :return:
    """

    test_cond_broad = r'[-\s=/a-z0-9.,;μ°]+,'

    field = r'[0-9]+(\.[0-9]+)?'
    field_nan = r'-*|nan|' + field

    return [
        re.compile(  # min typ max
            head + r',(?P<min>(nan|-*|[0-9]+(\.[0-9]+)?)),(?P<typ>([0-9]+(\.[0-9]+)?)),(?P<max>(nan|-*|[0-9]+(\.[0-9]+)?)),(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        re.compile(  # typ surrounded by nan/-
            head + r',((-*|nan),){0,4}(?P<typ>[-0-9]+(\.[0-9]+)?),((-*|nan),){0,2}(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        re.compile(  # min,typ,max with (scrambled) testing conditions and unit
            rf'{head}({test_cond_broad})?(?P<min>{field_nan}),(?P<typ>{field}),(?P<max>{field_nan}),(?P<unit>{unit})(,|$)',
            re.IGNORECASE),

        re.compile(  # typ only with (scrambled) testing conditions
            rf'{head},({test_cond_broad})?(?P<typ>[0-9]+(\.[0-9]+)?),(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        # typ surrounded by nan/-  and no unit
        re.compile(head + r'[-\s]*,(-|nan|),(?P<typ>[-0-9]+(\.[0-9]+)?),(-|nan|),nan',
                   re.IGNORECASE),

        re.compile(
            head + r'[-\s]{,2}\s*,?\s*(?P<min>nan|-*|[0-9.]+)\s*,?\s*(?P<typ>nan|-*|[0-9.]+)\s*,?\s*(?P<max>nan|-*|[0-9.]+)\s*,?\s*(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        re.compile(
            r'(charge|Q[\s_]?[a-z]{1,3})([\s=/a-z0-9.,μ]+)?(?P<min>-*|nan|[0-9]+(\.[0-9]+)?),(?P<typ>-*|nan|[0-9]+(\.[0-9]+)?),(?P<max>-*|nan|[0-9]+(\.[0-9]+)?),(?P<unit>[uμnp]C)(,|$)',
            re.IGNORECASE),
    ]


def get_dimensional_regular_expressions():
    # regex matched on csv row
    # noinspection RegExpEmptyAlternationBranch
    dim_regs = dict(
        t=[
            re.compile(r'(time|t\s?[rf]),([ =/a-z,]+,)?(?P<typ>[-0-9]+(\.[0-9]+)?),(?P<unit>[uμn]s)(,|$)',
                       re.IGNORECASE),
            re.compile(
                r'[, ](?P<min>nan|-+||[-0-9]+(\.[0-9]+)?),(?P<typ>nan|-*|[-0-9.]+)[, ](?P<max>nan|-+||[-0-9.]+),(nan,)?(?P<unit>[uμn]s)(,|$)',
                re.IGNORECASE),
            re.compile(r'(time|t\s?[rf]),([\s=/a-z0-9.,]+,)?(?P<typ>[-0-9]+(\.[0-9]+)?),(?P<unit>[uμn]s)(,|$)',
                       re.IGNORECASE),

            re.compile(r'(time|t\s?[rf]),(-|nan|),(?P<typ>[-0-9]+(\.[0-9]+)?),(-|nan|),nan',
                       re.IGNORECASE),

            re.compile(
                r'(time|t[_\s]?[rf])\s*,?\s*(?P<min>nan|-*|[-0-9.]+)\s*,?\s*(?P<typ>nan|-*|[-0-9.]+)\s*,?\s*(?P<max>nan|-*|[-0-9.]+)\s*,?\s*(?P<unit>[uμn]s)(,|$)',
                re.IGNORECASE),

        ],
        # Q=
        Q=[

              re.compile(
                  r'(V|charge|Q[ _]?[a-z]{1,3}),(?P<min>(nan|-*|[0-9]+(\.[0-9]+)?)),(?P<typ>([0-9]+(\.[0-9]+)?)),(?P<max>(nan|-*|[0-9]+(\.[0-9]+)?)),(?P<unit>[uμnp]C)(,|$)',
                  re.IGNORECASE),

              re.compile(
                  r'(charge|Q[\s_]?[a-z]{1,3}),((-|nan|),){0,4}(?P<typ>[-0-9]+(\.[0-9]+)?),((-|nan|),){0,2}(?P<unit>[uμnp]C)(,|$)',
                  re.IGNORECASE),

              re.compile(
                  r'(charge|Q[ _]?[a-z]{1,3}),([\s=/a-z0-9.,μ]+,)?(?P<typ>[0-9]+(\.[0-9]+)?),(?P<unit>[uμnp]C)(,|$)',
                  re.IGNORECASE),

              re.compile(r'(charge|Q[\s_]?[a-z]{1,3})[-\s]*,(-|nan|),(?P<typ>[-0-9]+(\.[0-9]+)?),(-|nan|),nan',
                         re.IGNORECASE),

              re.compile(
                  r'(charge|Q[\s_]?[a-z]{1,3})[-\s]{,2}\s*,?\s*(?P<min>nan|-*|[0-9.]+)\s*,?\s*(?P<typ>nan|-*|[0-9.]+)\s*,?\s*(?P<max>nan|-*|[0-9.]+)\s*,?\s*(?P<unit>[uμn]C)(,|$)',
                  re.IGNORECASE),

              re.compile(
                  r'(charge|Q[\s_]?[a-z]{1,3})([\s=/a-z0-9.,μ]+)?(?P<min>-*|nan|[0-9]+(\.[0-9]+)?),(?P<typ>-*|nan|[0-9]+(\.[0-9]+)?),(?P<max>-*|nan|[0-9]+(\.[0-9]+)?),(?P<unit>[uμnp]C)(,|$)',
                  re.IGNORECASE),

              # datasheets/vishay/SIR622DP-T1-RE3.pdf Qrr no value match Body diode reverse recovery charge Qrr -,350,680,nan,nC
          ] + field_value_regex_variations(r'(charge|Q[\s_]?[a-z]{1,3})', r'[uμnp]C'),
        C=field_value_regex_variations(r'(capacitance|C[\s_]?[a-z]{1,3})', r'[uμnp]F')
    )
    return dim_regs


def tabula_read(ds_path):
    try:
        dfs = tabula_pdf_dataframes(ds_path)
    except Exception as e:
        print(ds_path, e)
        dfs = []
        return {}

    # regex matched on cell contents
    fields_detect = dict(
        tRise=re.compile(r'(rise\s+time|^t\s?r$)', re.IGNORECASE),
        tFall=re.compile(r'(fall\s+time|^t\s?f$)', re.IGNORECASE),
        Qrr=re.compile(r'^((?!Peak)).*(reverse[−\s+]recover[edy]{1,2}[−\s+]charge|^Q[ _]?rr?($|\srecover))',
                       re.IGNORECASE),
        Coss=re.compile(r'(output\s+capacitance|^C[ _]?oss([ _]?eff\.?\s*\(?ER\)?)?$)', re.IGNORECASE),
        # Qrr=re.compile(r'(reverse[−\s+]recover[edy]{1,2}[−\s+]charge|^Q[ _]?rr?($|\srecover))',
        #               re.IGNORECASE),

    )

    dim_regs = get_dimensional_regular_expressions()

    dim_units = dict(
        t={'us', 'ns', 'μs'},
        Q={'uC', 'nC', 'μC'},
        C={'uF', 'nF', 'μF'},
    )

    all_units = set(sum(map(list, dim_units.values()), []))

    values = []

    col_typ = 0
    from collections import defaultdict
    col_idx = defaultdict(lambda: 0)
    other_cols = ['min', 'max', 'unit']
    unit = None

    for df in dfs:
        col_idx.clear()
        unit = None
        col_typ = 0

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
                    if is_h.sum():
                        assert is_h.sum() == 1
                        col_idx[col] = is_h.idxmax()

            for field_sym, field_re in fields_detect.items():
                detect_field = lambda s: (len(str(s)) < 80) and field_re.search(str(s).strip(' -'))
                m = next(filter(detect_field, row.iloc[:3]), None)

                def _empty(s):
                    return not s or str(s).lower() == 'nan'

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

                    rl = normalize_dash(','.join(map(lambda v: str(v).strip(' ,'), row)))
                    rl_bf = normalize_dash(','.join(map(lambda v: str(v).strip(' ,'), df_bfill.iloc[i])))
                    rl_ff = normalize_dash(','.join(map(lambda v: str(v).strip(' ,'), df_ffill.iloc[i])))

                    field = parse_row_value(rl, dim, field_sym=field_sym, cond=dict(row.dropna()))

                    if not field:
                        print(ds_path, field_sym, 'no value match in ', f'"{rl}"')

                    if field:
                        values.append(field)

                    elif col_typ:
                        v_typ = row[col_typ]
                        try:
                            values.append(Field(symbol=field_sym,
                                                min=row[col_idx['min']] if col_idx['min'] else math.nan,
                                                typ=v_typ.split(' ')[0] if isinstance(v_typ, str) else v_typ,
                                                max=row[col_idx['max']] if col_idx['max'] else math.nan,
                                                mul=1, cond=dict(row.dropna()), unit=unit),
                                          )
                        except Exception as e:
                            print(ds_path, 'error parsing field with col_idx', dict(col_idx), e)
                            print(row.values, rl, rl_ff, rl_bf)
                            # raise
                    else:
                        print(ds_path, 'found field tag but col_typ unknown', field_sym, list(row))

    # build dict taking first symbol
    d = dict()
    for f in values:
        if f.symbol not in d:
            d[f.symbol] = f

    for s in fields_detect.keys():
        if s not in d and not is_gan(ds_path):
            print(ds_path, 'no value detected for field', s)

    return d


def find_value(pdf_text, label, unit):
    matches = re.findall(r"%s\s+[^0-9]*([0-9.]+)\s*%s" % (label, unit), pdf_text)
    val = matches[0] if matches else None
    return val


dim_regs = get_dimensional_regular_expressions()
