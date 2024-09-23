import math
import os.path
import re
from typing import Iterable, List, cast

import pandas as pd

from dslib import mfr_tag
from dslib.cache import disk_cache, mem_cache
from dslib.field import Field, DatasheetFields
from dslib.pdf2txt import expr, normalize_dash
from dslib.pdf2txt.pipeline import convertapi, pdf2pdf, raster_ocr


def _empty(s):
    return not s or str(s).lower() == 'nan'


@disk_cache(ttl='30d', file_dependencies=[0], salt='v03')
def extract_text(pdf_path, try_ocr=False):
    import fitz  # PyMuPDF
    pdf_document = fitz.open(pdf_path)

    if len(pdf_document) > 25:
        raise ValueError(pdf_path + ' has more than 25 pages ' + len(pdf_document))

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
        if mfr:
            print('no Qrr pattern for ', mfr)

    return fields


@disk_cache(ttl='90d', file_dependencies=[0], salt='v13', ignore_missing_inp_paths=True)
def parse_datasheet(pdf_path=None, mfr=None, mpn=None, tabular_pre_methods=None) -> DatasheetFields:
    if not pdf_path:
        assert mfr
        pdf_path = f'datasheets/{mfr}/{mpn}.pdf'

    if not mfr:
        assert pdf_path
        mfr = pdf_path.split('/')[-2]


    pdf_text = extract_text(pdf_path, try_ocr=False)

    ocr_path = None

    if len(pdf_text) < 40:
        ocr_path = pdf_path + '.ocrmypdf.pdf'
        raster_ocr(pdf_path, ocr_path, method='ocrmypdf')
        pdf_text = extract_text(ocr_path, try_ocr=False)
        if len(pdf_text) < 40:
            print(pdf_path, 'no text extracted')
        else:
            print(ocr_path, 'extracted', len(pdf_text), 'characters using OCR')
            pdf_path = ocr_path

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

    try:
        tabular_ds = tabula_read(pdf_path, pre_process_methods=tabular_pre_methods)
        assert tabular_ds, 'empty tabular data'
        ds.add_multiple(tabular_ds.all_fields())
    except Exception as e:
        print(pdf_path, 'tabula error', e)
        raise

    assert ds, 'empty tabular data ' + pdf_path

    return ds


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
             'datasheets/littelfuse/IXTA160N10T7.pdf',
             'datasheets/goford/GT023N10Q.pdf',
             'datasheets/onsemi/FDB047N10.pdf',
             'datasheets/onsemi/FDP047N10.pdf',
             'datasheets/infineon/IPB033N10N5LFATMA1.pdf',
             'datasheets/infineon/ISC030N10NM6ATMA1.pdf',

             'datasheets/diodes/DMT10H9M9SCT.pdf',  # unsupported operation
             'datasheets/diodes/DMT10H9M9LCT.pdf',
             'datasheets/good_ark/GSFT3R110.pdf',
             'datasheets/diodes/DMTH10H005SCT.pdf',
             }
    # if pdf_path in fails:
    #    raise Exception(f'PDF {pdf_path} known to fail')
    dfs = tabula.read_pdf(pdf_path, pages='all', pandas_options={'header': None})

    # pd.concat(dfs, ignore_index=True, axis=0).to_csv(pdf_path+'.csv', index=False)

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


#def find_dim_match(csv_line, regexs):
#    for r in regexs:
##        m = next(r.finditer(csv_line), None)
#        if m is not None:
#            return m
#        # print(r, 'not found in', csv_line)
#    return None


def check_range(v, range):
    return math.isnan(v) or (v >= range[0] and v <= range[1])


valid_range = dict(
    Vpl=(1, 10),
    Vsd=(0.1, 4),
)


def parse_field_csv(csv_line, dim, field_sym, cond=None) -> Field:
    range = valid_range.get(field_sym)
    err = []
    for r in dim_regs[dim]:
        # print(csv_line, dim , r.pattern)
        m = next(r.finditer(csv_line), None)
        # print('done.')
        if m is None:
            continue

        vd = m.groupdict()
        try:
            f = Field(symbol=field_sym,
                      min=vd.get('min', '').rstrip('-'),
                      typ=vd.get('typ', '').rstrip('-'),
                      max=vd.get('max'),
                      mul=1,
                      cond=cond,
                      unit=vd.get('unit'))
            if range and not (check_range(f.min, range) and check_range(f.typ, range) and check_range(f.max, range)):
                err.append((field_sym, 'field out of range', f, range))
                continue

            return f
        except Exception as e:
            err.append((field_sym, 'error parsing field row', csv_line, 'dim=', dim, e))
            continue
    for e in err: print(*e)
    return None


def field_value_regex_variations(head, unit, signed=False):
    """
    Output Capacitance Coss VDS = 50V, --,3042,--,pF
    Output Capacitance Coss VDS = 50V, --,2730,--,pF

    Coss no value match Output Capacitance Coss VDS = 50V, --,380,--,pF

    Qrr no value match Reverse Recovery Charge Qrr nCIF = 80A, VGS = 0V--,297,--,nan


     Qrr no value match Reverse Recovery Charge Qrr nCIF = 50A, VGS = 0V--,87,--,nan
    "/dt = 100 A/μsReverse recovery charge,Q rr,-dI DR,nan,nan,35,nan,nC"

    TODO
    tFall no value match in  "tf fall time,nan,nan,- 49.5 - ns"

    :param head:
    :param unit:
    :return:
    """

    test_cond_broad = r'[-\s=≈/a-z0-9äöü.,;:μΩ°()"\']+'  # parameter lab testing conditions (temperature, I, U, didit,...)

    field = r'[0-9]+(\.[0-9]+)?'
    if signed:
        field = r'-?' + field
    nan = r'[-\s_]*|nan'
    field_nan = nan + r'|' + field

    return [
        re.compile(  # min typ max
            head + rf',(?P<min>({field_nan})),(?P<typ>({field})),(?P<max>({field_nan})),I?(?P<unit>' + unit + r')(,|$|\s)',
            re.IGNORECASE),

        re.compile(  # typ surrounded by nan/-
            head + r',((-*|nan),){0,4}(?P<typ>(' + field + r')),((-*|nan),){0,4}(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        re.compile(  # head,nan?,typ -,unit ...,
            head + r',(('+field_nan+'),){0,4}(?P<typ>(' + field + r'))\s*-+\s*,(?P<unit>' + unit + r')(,|$|\s)',
            re.IGNORECASE),

        re.compile(  # min,typ,max with (scrambled) testing conditions and unit
            rf'{head}({test_cond_broad},)?(?P<min>{field_nan}),(?P<typ>{field}),(?P<max>{field_nan}),(?P<unit>{unit})(,|$)',
            re.IGNORECASE),

        #re.compile(  # head,nan?,nan,max,unit
        #    rf'{head},(({nan}),)?({nan}),(?P<max>{field}),(?P<unit>' + unit + r')(,|$)',
        #    re.IGNORECASE),

        re.compile(  # typ only with (scrambled) testing conditions
            rf'{head},({test_cond_broad},)?(?P<typ>{field}),(nan,)?(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        # typ surrounded by nan/- or max  and no unit
        re.compile(head + rf'[-\s]*,(-|nan|),(-,)?(?P<typ>{field}),(?P<max>{field_nan}),nan',
                   re.IGNORECASE),

        re.compile(
            head + r'[-\s]{,2}\s*,?\s*(?P<min>' + field_nan + r')\s*,?\s*(?P<typ>' + field_nan + r')\s*,?\s*(?P<max>' + field_nan + r')\s*,?\s*(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        re.compile(
            head + r'([\s=/a-z0-9.,μ]+)?(?P<min>' + field_nan + r'),(?P<typ>' + field_nan + r'),(?P<max>' + field_nan + r'),(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        # QgsGate charge gate to source,17,nC,nan,nan,nan,nan,nan
        re.compile(
            head + r'([\s/a-z0-9."]+)?,(?P<typ>' + field + r'),(?P<unit>' + unit + r')(,|$)',
            re.IGNORECASE),

        # "tf fall time,nan,nan,- 49.5 - ns"
        re.compile(
            head + rf'(,({nan}))*,-\s+(?P<typ>{field})\s+-[,\s](?P<unit>{unit})(,|$)',
            re.IGNORECASE),

        # "Coss Output Capacitance,---,319,---,VDS = 50V,nan"
        # "Reverse Recovery Charge Qrr nCIF = 80A, VGS = 0V--,297,--,nan"
        re.compile(
            head + rf'({test_cond_broad})?,?-+,(?P<typ>{field}),-+(,|$)',
            re.IGNORECASE),

        # 'nan,Coss,nan,7.0,nan'
        re.compile(head + rf',nan,(?P<typ>{field}),nan$', re.IGNORECASE),

        # 'COSS(ER),Effective Output Capacitance, Energy Related (Note 1),VDS = 0 to 50 V, VGS = 0 V,nan,1300,nan,nan', 'C'
        re.compile(head + rf'({test_cond_broad})?,nan,(?P<typ>{field}),nan,nan$', re.IGNORECASE),

        # 'Gate plateau voltage,Vplateau,nan,nan,4.7,nan,
        re.compile(head + rf',nan,nan,(?P<typ>{field}),nan(,|$)', re.IGNORECASE),

        #'Vsp,Diode Forward Voltage,-_- -_-,1.3,Vv,Ty=25°C, 15 =22A, Ves =0V @,nan', 'V'
        re.compile(head + rf',({field_nan})[\s,]({field_nan}),(?P<max>{field}),(?P<unit>{unit})(,|$|\s)', re.IGNORECASE),
    ]


def get_dimensional_regular_expressions():
    # regex matched on csv row
    # noinspection RegExpEmptyAlternationBranch
    dim_regs = dict(
        t=[
              re.compile(r'(time|t\s?[rf]),([ =/a-z,]+,)?(?P<typ>[-0-9]+(\.[0-9]+)?),(?P<unit>[uμnm]s)(,|$)',
                         re.IGNORECASE),
              re.compile(
                  r'[, ](?P<min>nan|-+||[-0-9]+(\.[0-9]+)?),(?P<typ>nan|-*|[-0-9.]+)[, ](?P<max>nan|-+||[-0-9.]+),(nan,)?(?P<unit>[uμnm]s)(,|$)',
                  re.IGNORECASE),
              re.compile(r'(time|t\s?[rf]),([\s=/a-z0-9.,]+,)?(?P<typ>[-0-9]+(\.[0-9]+)?),(?P<unit>[uμnm]s)(,|$)',
                         re.IGNORECASE),

              re.compile(r'(time|t\s?[rf]),(-|nan|),(?P<typ>[-0-9]+(\.[0-9]+)?),(-|nan|),nan',
                         re.IGNORECASE),

              re.compile(
                  r'(time|t[_\s]?[rf])\s*,?\s*(?P<min>nan|-*|[-0-9.]+)\s*,?\s*(?P<typ>nan|-*|[-0-9.]+)\s*,?\s*(?P<max>nan|-*|[-0-9.]+)\s*,?\s*(?P<unit>[uμnm]s)(,|$)',
                  re.IGNORECASE),

          ] + field_value_regex_variations(r'(time|[tf][_\s]?[rf]?)', r'[uμnm]s'), # f for OCR confusing t
        # Q=
        Q=[

              re.compile(
                  r'(V|charge|Q[ _]?[a-z]{1,3}),(?P<min>(nan|-*|[0-9]+(\.[0-9]+)?)),(?P<typ>([0-9]+(\.[0-9]+)?)),(?P<max>(nan|-*|[0-9]+(\.[0-9]+)?)),(?P<unit>[uμnp]C)(,|$)',
                  re.IGNORECASE),

              re.compile(
                  r'(charge|Q[\s_]?[a-z]{1,3}),((-|nan|),){0,4}(?P<typ>[-0-9]+(\.[0-9]+)?),((-|nan|),){0,2}(?P<unit>[uμnp]C)(,|$)',
                  re.IGNORECASE),

              # re.compile(
              #    r'(charge|Q[ _]?[a-z]{1,3}),([\s=/a-z0-9.,μ]+,)?(?P<typ>[0-9]+(\.[0-9]+)?),(?P<unit>[uμnp]C)(,|$)',
              #    re.IGNORECASE),

              re.compile(r'(charge|Q[\s_]?[a-z]{1,3})[-\s]*,(-|nan|),(?P<typ>[-0-9]+(\.[0-9]+)?),(-|nan|),nan',
                         re.IGNORECASE),

              re.compile(
                  r'(charge|Q[\s_]?[a-z]{1,3})[-\s]{,2}\s*,?\s*(?P<min>nan|-*|[0-9.]+)\s*,?\s*(?P<typ>nan|-*|[0-9.]+)\s*,?\s*(?P<max>nan|-*|[0-9.]+)\s*,?\s*(?P<unit>[uμn]C)(,|$)',
                  re.IGNORECASE),

              re.compile(
                  r'(charge|Q[\s_]?[a-z]{1,3})([\s=/a-z0-9.,μ]+)?(?P<min>-*|nan|[0-9]+(\.[0-9]+)?),(?P<typ>-*|nan|[0-9]+(\.[0-9]+)?),(?P<max>-*|nan|[0-9]+(\.[0-9]+)?),(?P<unit>[uμnp]C)(,|$)',
                  re.IGNORECASE),

              # datasheets/vishay/SIR622DP-T1-RE3.pdf Qrr no value match Body diode reverse recovery charge Qrr -,350,680,nan,nC
          ] + field_value_regex_variations(
            r'(charge(\s+gate[\s-]to[\s-](source|drain)\s*)?(\s+at\s+V[ _]?th)?|Q[\s_]?[0-9a-z]{1,3}([\s_]?\([a-z]{2,5}\))?)',
            r'[uμnp]C'),

        C=field_value_regex_variations(r'(capacitance|C[\s_]?[a-z]{1,3})', r'[uμnp]F'),
        V=field_value_regex_variations(r'(voltage|V[\s_]?[a-z]{1,8})', r'[m]?Vv?', signed=True)
    )
    return dim_regs


def detect_fields(mfr, strings: Iterable[str]):
    fields_detect = get_field_detect_regex(mfr)
    for field_sym, field_re in fields_detect.items():
        if isinstance(field_re, tuple):
            stop_words = field_re[1]
            field_re = field_re[0]
        else:
            stop_words = []

        def detect_field(s):
            s = normalize_dash(str(s)).strip(' -')
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


@mem_cache(ttl='1min')
def get_field_detect_regex(mfr):
    mfr = mfr_tag(mfr, raise_unknown=False)

    qgs = r'Q[ _]?gs'
    if mfr == 'toshiba':
        # toshiba: Qgs1 = charge from 0 to miller plateau start
        # others: Qgs1 = charge from Qg_th to miller plateau start
        qgs += '1?'

    # regex matched on cell contents
    fields_detect = dict(
        tRise=(re.compile(r'(rise\s+time|^t\s?r$)', re.IGNORECASE), ('reverse', 'recover')),
        tFall=(re.compile(r'(fall\s+time|^t\s?f$)', re.IGNORECASE), ('reverse', 'recover')),
        Qrr=re.compile(
            r'^((?!Peak)).*(reverse[−\s+]recover[edy]{1,2}[−\s+]charge|^Q\s*_?(f\s*r|r\s*[rm]?)($|\s+recover))',
            re.IGNORECASE),  # QRM
        Coss=re.compile(r'(output\s+capacitance|^C[ _]?oss([ _]?eff\.?\s*\(?ER\)?)?$)', re.IGNORECASE),
        Qg=re.compile(rf'(total[\s-]+gate[\s-]+charge|^Q[ _]?g([\s_]?\(?(tota?l?|on)\)?)?$)', re.IGNORECASE),
        Qgs=re.compile(
            rf'(gate[\s-]+(to[\s-]+)?source[\s-]+(gate[\s-]+)?charge|Gate[\s-]+Charge[\s-]+Gate[\s-]+to[\s-]+Source|^{qgs})',
            re.IGNORECASE),
        Qgs2=re.compile(r'(Gate[\s-]+Charge.+Plateau|^Q[ _]?gs2$)', re.IGNORECASE),
        Qgd=re.compile(r'(gate[\s-]+(to[\s-]+)?drain[\s-]+(\(?"?miller"?\)?[\s-]+)?charge|^Q[ _]?gd)', re.IGNORECASE),
        Qg_th=re.compile(r'(gate[\s-]+charge\s+at\s+V[ _]?th|^Q[ _]?g\(?th\)?$)', re.IGNORECASE),
        Qsw=re.compile(r'(gate[\s-]+switch[\s-]+charge|switching[\s-]+charge|^Q[ _]?sw$)', re.IGNORECASE),

        Vpl=re.compile(r'(gate\s+plate\s*au\s+voltage|V[ _]?(plateau|pl|gp)$)', re.IGNORECASE),

        Vsd=re.compile(r'(diode[\s-]+forward[\s-]+voltage|V[ _]?(sd)$)', re.IGNORECASE),
        # plate au
        # Qrr=re.compile(r'(reverse[−\s+]recover[edy]{1,2}[−\s+]charge|^Q[ _]?rr?($|\srecover))',
        #               re.IGNORECASE),

    )
    return fields_detect


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

def extract_fields_from_dataframes(dfs: List[pd.DataFrame], mfr, ds_path) -> DatasheetFields:
    fields_detect = get_field_detect_regex(mfr)

    dim_units = dict(
        t={'us', 'ns', 'μs', 'ms'},
        Q={'uC', 'nC', 'μC'},
        C={'uF', 'nF', 'μF'},
        V={'mV', 'V'},
    )

    all_units = set(sum(map(list, dim_units.values()), []))

    fields = DatasheetFields()

    from collections import defaultdict
    col_idx = defaultdict(lambda: 0)
    other_cols = ['min', 'max', 'unit']

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



                rl = normalize_dash(','.join(map(lambda v: str(v).strip(' ,\'"/|'), right_strip_nan(row,2))))
                rl_bf = normalize_dash(','.join(map(lambda v: str(v).strip(' ,'), df_bfill.iloc[i])))
                rl_ff = normalize_dash(','.join(map(lambda v: str(v).strip(' ,'), df_ffill.iloc[i])))

                # OCR
                rl = ','.join(map(lambda s:s.strip(' /'), rl.replace('{','|').replace('/','|').split('|')))

                field = parse_field_csv(rl, dim, field_sym=field_sym, cond=dict(row.dropna()))

                if not field:
                    print(ds_path, field_sym, 'no value match in ', f'"{rl}"')

                if field:
                    fields.add(field)

                elif col_typ:
                    for row_ in [row, df_bfill.iloc[i], df_ffill.iloc[i]]:
                        v_typ = row_[col_typ]
                        try:
                            fields.add(Field(
                                symbol=field_sym,
                                min=row_[col_idx['min']] if col_idx['min'] else math.nan,
                                typ=v_typ.split(' ')[0] if isinstance(v_typ, str) else v_typ,
                                max=row_[col_idx['max']] if col_idx['max'] else math.nan,
                                mul=1, cond=dict(row_.dropna()), unit=unit
                            ))
                            break
                        except Exception as e:
                            print(ds_path, 'error parsing field with col_idx', dict(**col_idx, typ=col_typ), e)
                            print(row.values)
                            print(rl)
                            print(rl_ff)
                            print(rl_bf)
                            # raise
                else:
                    print(ds_path, 'found field tag but col_typ unknown', field_sym, list(row))

    for s in fields_detect.keys():
        if s not in fields and not is_gan(ds_path):
            # print(ds_path, 'no value detected for field', s)
            pass

    return fields


def tabula_read(ds_path, pre_process_methods=None) -> DatasheetFields:
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

    if pre_process_methods is None:
        pre_process_methods = (
            # fix java.lang.IllegalArgumentException: lines must be orthogonal, vertical and horizontal:
            'nop', 'sips', 'gs', 'cups', 'ocrmypdf_redo',
            # fix image datasheets, weird encoding
            'ocrmypdf_r400')
    elif isinstance(pre_process_methods, str):
        pre_process_methods = (pre_process_methods,)

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
        except Exception as e:
            last_e = e
            print('tabula error with method', method, e)
            continue

        if len(dfs): # and not os.path.isfile(ds_path + '.csv'):
            pd.concat(dfs, ignore_index=True, axis=0).map(
                lambda s: (isinstance(s, str) and normalize_dash(s)) or s).to_csv(ds_path + '.csv', header=False)

        fields = extract_fields_from_dataframes(dfs, mfr=mfr, ds_path=ds_path)
        if len(fields) > 0:
            return fields
        else:
            print(ds_path, 'tabula no fields extracted with method', method)

    txt = extract_text(ds_path, try_ocr=False)
    if len(txt) < 20:
        print(ds_path, 'probably needs OCR')
        raise ValueError('probably need OCR ' + ds_path)
    else:
        print(ds_path, 'tabula no methods working')
        if last_e:
            raise last_e


def find_value(pdf_text, label, unit):
    matches = re.findall(r"%s\s+[^0-9]*([0-9.]+)\s*%s" % (label, unit), pdf_text)
    val = matches[0] if matches else None
    return val


dim_regs = get_dimensional_regular_expressions()
