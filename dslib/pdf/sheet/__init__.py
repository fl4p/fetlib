"""
ideas:

# table grid
- virtually increase distance between elements that are separted by a line. char_margin=2 -> should be more than that

"""
import math
import re
import warnings
from collections import defaultdict
from typing import List, Optional, Tuple, Dict, Literal

from dslib.cache import disk_cache
from dslib.field import Field, DatasheetFields, parse_field_value
from dslib.pdf.ascii import pdf_to_ascii, Row, Phrase
from dslib.pdf.expr import get_cond_regex
from dslib.pdf.parse import detect_fields, DetectedSymbol
from dslib.pdf.pdf2txt import normalize_text, whitespaces_to_space
from dslib.pdf.sheet.annotation import pdf_raster_annot
from dslib.pdf.sheet.spatial import SpatialQuery, take
from dslib.pdf.sheet.tables import table_segregation, DetectedRowField, Table
from dslib.pdf.to_html import Annotation
from dslib.pdf.tree import bbox_union, GraphicBlock, Bbox

head_re = re.compile(
    '((\s+|^\s*)('
    '(?P<sym>Symbol)'
    '|(?P<param>Parameters?|Characteristics?)'
    '|(?P<min>Min(\.|imum)?)'
    '|(?P<typ>Typ(\.|ycal)?)'
    '|(?P<max>Max(\.|imum)?)'
    '|(?P<cond>(Note *(/|or)? *)?(Test(ing)?\s+)?Conditions?)'
    '|(?P<values>(Value|Rating)s?)'
    '|(?P<unit>Units?)'
    ')(?=$|\s+))+', re.IGNORECASE)

head_re_groups = ('sym', 'param', 'min', 'typ', 'max', 'unit', 'cond')

head_stop = (
    # 'RATINGS', 'Ratings',
    # 'Power',
    'Avalanche', 'allowable', 'limited', 'Lead',
    'Static', 'Electrical', 'Dynamic', 'curves', 'above',
    'Continuous', 'Pulsed',  # Max drain current
    'Thermal', 'Resistance',
    'Absolute'  # Toshiba: section head `Absolute Maximum Ratings`
)


def _header_filter(row: Row, m_head: re.Match):
    head_words = {g: row.element_by_tpos(m_head.start(g)) for g, v in m_head.groupdict().items() if v}
    # d = m_head.groupdict()

    h = max(w.bbox.height for p, w in head_words.values())
    if h < 7.5:
        # too small
        return False

    for sw in head_stop:
        if sw in str(row):
            return False

    return True


def read_sheet_inner(pdf_file, expand=True, merge=True, debug_annotations=False, multiline_conditions=True):
    all_lines = pdf_to_ascii(pdf_file, grouping='line',
                             sort_vert=True,
                             spacing=' ',
                             output='rows_graphics',
                             line_overlap=.3,
                             char_margin=4.0,  # 4.0: generously merge words into lines during detection
                             )

    mfr = pdf_file.split('/')[-2]
    mpn = pdf_file.split('/')[-1].split('.')[0]

    for pn, lines in all_lines.items():
        for row in lines:
            if row.text:
                row.text = normalize_text(row.text)
            if hasattr(row, 'elements'):
                for el in row.elements.values():
                    el.s = normalize_text(el.s)

    annotations = defaultdict(list)
    ds = DatasheetFields(mfr, mpn)

    for pn, rows in all_lines.items():
        page_annotations: List[Annotation] = []
        ds.add_multiple(_process_page(pdf_file, mfr, rows, pn, page_annotations, merge, expand, multiline_conditions))
        if page_annotations:
            for a in page_annotations:
                a.page_bbox = a.page_bbox or rows[0].page.mediabox
            annotations[pn] = page_annotations

    if debug_annotations:
        from dslib.util import open_file_with_default_app
        open_file_with_default_app(pdf_raster_annot(pdf_file, 250, annotations))

    return ds

    """
    - for each detected field, do a local table analysis
    - horizontal pane intersection with table structure to find out-of-line units and testing conditions
    - 
    """


def read_sheet_debug(pdf_file, expand=True, merge=True, multiline_conditions=True):
    return read_sheet_inner(pdf_file, expand, merge, debug_annotations=True, multiline_conditions=multiline_conditions)


@disk_cache(ttl='999d', file_dependencies=[0], hash_func_code=True, salt=('v07'))
def read_sheet(pdf_file, expand=True, merge=True, multiline_conditions=True):
    try:
        return read_sheet_inner(pdf_file, expand, merge, debug_annotations=False,
                                multiline_conditions=multiline_conditions)
    except AttributeError:  # 'PSKeyword' object has no attribute 'decode'
        from dslib.pdf.pipeline import pdf2pdf
        pdf2pdf(pdf_file, pdf_file + '.gs.pdf', 'gs')
        return read_sheet_inner(pdf_file + '.gs.pdf', expand, merge, debug_annotations=False,
                                multiline_conditions=multiline_conditions)


def _process_page(pdf_file, mfr, rows, pn, annotations: List[Annotation], merge, expand, multiline_conditions) -> List[
    Field]:
    sq = SpatialQuery(rows)
    # detect HEADs and symbols
    detected: List[DetectedRowField] = []
    for i, row in enumerate(rows):
        if not row.text:
            continue
        m_head = head_re.search(row.text)

        phrases = row.to_phrases()

        # cell_strings = row.text.split(cell_delim)
        strings = [' '.join(w.s for w in phrase) for phrase in phrases]
        offsets = [phrase[0].line_offset for phrase in phrases]

        syms = detect_fields(mfr, strings, multi=True)

        # only rows qualifying as headers that do not contain a symbol match
        if not syms and m_head and _header_filter(row, m_head):
            head_sym = DetectedSymbol(0, m_head, 'HEAD')
            detected.append(DetectedRowField(head_sym, row, i, 0))

        for sym in syms:
            # cell_strings_offset = np.append(np.zeros(1, int), np.array(list(map(len, cell_strings))) + len(cell_delim)).cumsum()
            # print('detected', field_sym, 'in line', whitespaces_to_space(row.text))
            detected.append(DetectedRowField(sym, row, i, string_offset=offsets[sym.index]))

    if not detected:
        return []

    table_row_dist = 30

    # group detected headers and symbol field rows into tables
    tables: List[Table] = [Table(detected[:1])]

    for d in detected[1:]:
        prev_row = tables[-1][-1]
        dy = round(prev_row.row.bbox[1] - d.row.bbox[3], 1)
        if not prev_row.is_head and (d.is_head or dy >= table_row_dist):
            # print(pn, 'new table between symbols %r .. %r' % (prev_row.row, d.row), 'dist=', dy)
            tables.append(Table([d]))
        else:
            tables[-1].append(d)

    if expand:
        # expand tables vertically to capture potential vector line structure (merged cells)
        # we will need this later for actual tabular data extraction
        for table in tables:
            table.expand_bbox_to_surrounding_rows(rows)
            table.bbox = table.bbox.pad(10, 20, 6, 0)

    # merge tables after expansion
    i = 0
    while merge and i < len(tables) - 1:
        table = tables[i]
        next_table = tables[i + 1]
        dy = table.bbox.y1 - next_table.bbox.y2
        # assert dy >= 0, 'out-of-order tables %s' % (dy)

        if not next_table[0].is_head and dy < table_row_dist:
            # merge tables
            table.extend(next_table)
            tables.pop(i + 1)
        else:
            i += 1

    hs = TableHeaderState()
    cb = dict()

    # _indentify_units(tables, sq, annotations)

    fields = []
    for table in tables:
        fields.extend(_process_table(pdf_file, table, hs, cb, sq,
                                     multiline_conditions=multiline_conditions,
                                     annotations=annotations))

    return fields


def _indentify_units(tables: List[Table], sq: SpatialQuery, annotations: List[Annotation]):
    for table in tables:
        for row in table.rows:
            if row.is_head:
                bbox = row.get_bbox_for_match_group('unit', allow_missing=True)
                annotations.append(Annotation('TH:unit', bbox, color=(255, 0, 255)))
                for u in sq.ray('y2', bbox, 600, min_overlap=.5, limit=99, types=Phrase):
                    u: Phrase = u
                    str(u)


class TableHeaderState():
    def __init__(self):
        self.states = {}
        pass

    def set_span(self, g: str, bbox_cell: Bbox, rank: int, bbox_match: str):
        """

        :param g:
        :param bbox_cell:
        :param rank: how many symbols we found in the row
        :param bbox_match:
        :return:
        """
        assert g in head_re_groups
        assert bbox_cell
        assert 1 <= rank <= len(head_re_groups)
        assert bbox_match in {'cell', 'sq'}

        self.states[g] = (bbox_cell, rank, bbox_match)

    def get_span(self, g) -> Optional[Bbox]:
        if g not in self.states:
            return None
        return self.states[g][0]


def _extend_bbox_vertically(bbox: Bbox, sq: SpatialQuery, multiline=False):
    top = sq.ray('y1', bbox, 200, 0.9, 10)
    bottom = sq.ray('y2', bbox, 200, 0.9, 10, start_from_bbox_center=True)

    if multiline:
        top = take(filter(lambda el: isinstance(el, GraphicBlock), top), 10)
        bottom = take(filter(lambda el: isinstance(el, GraphicBlock), bottom), 10)

    if top and bottom:
        b = bottom[0]
        t = top[0]
        bbox = Bbox(
            bbox.x1,
            # if the bottom/top element is a text (not graphical), meet in the middle
            b.bbox.y2 if isinstance(b, GraphicBlock) else (bbox.y1 + b.bbox.y2) / 2,
            bbox.x2,
            t.bbox.y1 if isinstance(t, GraphicBlock) else (bbox.y2 + t.bbox.y1) / 2
        )

    return bbox


def _vertically_expand_column_cells(bbox_head: Bbox, cells, sq: SpatialQuery, multiline, annotations: List[Annotation]):
    annotations.append(Annotation('HEAD', bbox_head, color=(255, 0, 255)))

    els: List[Phrase] = []

    ray: List[Phrase] = sq.ray('y2', bbox_head, 600, min_overlap=.5, limit=99, types=Phrase)

    for u in ray:

        bbox_cell = _find_cell_bbox(u.bbox, cells)

        if bbox_cell.height < u.bbox.height * 1.05:
            bbox_cell = _extend_bbox_vertically(u.bbox, sq, multiline=multiline)

        if bbox_cell.height / u.bbox.height > 20:  # toshiba/2SK1062: ns unit
            bbox_cell = u.bbox

        annotations.append(Annotation('td:vex' + whitespaces_to_space(str(u)), bbox_cell, color=(255, 0, 255),
                                      vcenter=True))
        els.append(u.extend_bbox(bbox_cell))

    return els


def _find_cell_bbox(bbox, cells, min_area_overlap=.3):
    boxes = []
    for cell in cells:
        if bbox.overlap_area(cell) > bbox.area * min_area_overlap:
            boxes.append(cell)
    return bbox_union(boxes) if boxes else Bbox(0, 0, 0, 0)


def parse_cond_str(cond):
    # 'VGS = 0 V, ID = 250 mA'
    symbols = {s.lower(): s for s in {'Vgs', 'Id', 'Vds'}}

    res = dict()
    m_all = list(get_cond_regex().finditer(cond))
    for m in m_all:
        d = m.groupdict()
        u = d['cond_unit']
        s = 1
        if u:
            if u[0] == 'm':
                s = 1e-3
            elif u[0] in {'µ', 'u'}:
                s = 1e-6
            elif u[0] == 'n':
                s = 1e-9
            elif u[0] == 'k':
                s = 1e3
            elif u[0] == 'M':
                s = 1e6

        sym = d['cond_sym']
        if d['cond_val'] is not None:
            res[symbols.get(sym.lower(), sym)] = float(d['cond_val']) * s
    return res


def _is_valid_value(mtm, s):
    if mtm not in Field.StatKeys or not math.isnan(parse_field_value(s, no_raise=True)):
        return True
    return False


def _process_table(pdf_file, table: Table, head: TableHeaderState, column_boxes, sq: SpatialQuery, multiline_conditions,
                   annotations: List[Annotation]):
    fields: List[Field] = []

    table_min_width = 120

    table_bbox = table.bbox
    if table_bbox[2] - table_bbox[0] < table_min_width:
        # skip small tables
        return []

    # if set(r.symbol for r in table.rows) == {'HEAD'}:
    #    # skip HEAD only tables (no body)
    #    return

    annotations.append(Annotation(
        name='table ' + ','.join(r.symbol.symbol for r in table),
        bbox=table_bbox,
        page_bbox=table[0].row.page.mediabox)
    )

    cells = []
    try:
        cells = table_segregation(pdf_path=pdf_file, table=table, annotations=annotations)
    except Exception as e:
        print(pdf_file, 'table_segregation err', e)

    parsed = []

    # val_re = re.compile(r'[+-]*(' + NumValReSet(True, nan_empty=False).val_nan + ')', re.IGNORECASE)

    # header_row = False

    for row in table.rows:

        if row.is_head:

            # header_row = True

            row_head_rank = len(list(filter(bool, row.symbol.match.groupdict().values())))

            starts = row.get_groups_by_start()
            starts_idx = list(starts.keys())

            for g in head_re_groups:
                head_bbox = row.get_bbox_for_match_group(g, allow_missing=True)

                if not head_bbox:
                    continue

                bbox_cell = _find_cell_bbox(head_bbox, cells)

                if bbox_cell.width > head_bbox.width * 1.05 and bbox_cell.height > head_bbox.height * 1.05:
                    annotations.append(Annotation(
                        name=row.symbol.symbol + ':' + g,
                        bbox=bbox_cell, thickness=2, color=(64, 64, 255)
                    ))

                    head.set_span(g, bbox_cell, rank=row_head_rank, bbox_match='cell')

                else:

                    is_first = starts_idx[0] == g or g == 'min'
                    is_last = starts_idx[-1] == g or g == 'max'

                    # if we can't find a covering cell, horizontally extend
                    right = sq.ray('x1', head_bbox, 60 if is_last else 200, 0.2, 10)
                    left = sq.ray('x2', head_bbox, 60 if is_first else 200, 0.2, 10)

                    bbox = head_bbox
                    x1 = bbox.x1
                    x2 = bbox.x2

                    if left:
                        l = left[0]
                        assert l.bbox.x2 <= x1, (l.bbox.x2, x1, l.bbox)
                        x1 = l.bbox.x2 if isinstance(l, GraphicBlock) else (bbox.x1 + l.bbox.x2) / 2
                    else:
                        x1 -= 4 if not is_first else 2

                    if right:
                        r = right[0]
                        assert r.bbox.x1 > x2
                        x2 = r.bbox.x1 if isinstance(r, GraphicBlock) else (bbox.x2 + r.bbox.x1) / 2
                    else:
                        x2 += 4 if not is_last else 2  # pad a bit on the right (assuming header is left aligned)
                        # littlefuse: unit col has no header so extend Max col range carefully

                    bbox_cell = Bbox(x1, bbox.y1, x2, bbox.y2)

                    head.set_span(g, bbox_cell, rank=row_head_rank, bbox_match='sq')

                    annotations.append(Annotation(
                        name=row.symbol.symbol + ' ' + g,
                        bbox=bbox_cell, thickness=2, color=(128, 128, 255)
                    ))

                # if row_head_rank > 1:
                # header_boxes[g] = bbox_cell
                # head.set_span(g, bbox_cell, rank=row_head_rank, bbox_match='sq')

                if g in {'unit', 'cond'}:
                    # TODO this only works for cells within the current table
                    column_boxes[g] = _vertically_expand_column_cells(bbox_cell, cells, sq,
                                                                      multiline=multiline_conditions and g == 'cond',
                                                                      annotations=annotations)

            # place virtual 'unit' header
            if 'unit' not in starts_idx and 'max' in starts_idx and 'typ' in starts_idx:
                bbox = head.get_span('max')
                w = bbox.height + min(bbox.width, 25)
                if not sq.ray('x1', bbox, w, min_overlap=0.1):
                    bbox = Bbox(bbox.x2 + bbox.height, bbox.y1, bbox.x2 + w, bbox.y2)
                    column_boxes['unit'] = _vertically_expand_column_cells(bbox, cells, sq,
                                                                           multiline=False,
                                                                           annotations=annotations)

        else:  # if not HEAD

            sym_bbox = row.get_bbox_for_match_group('detect')
            if not sym_bbox:
                warnings.warn('empty detect bbox %s' % row.symbol.match)
                continue
            # assert sym_bbox, row.symbol.match

            # print('det', row.symbol.symbol, sym_bbox)

            bbox_cell = _find_cell_bbox(sym_bbox, cells)

            if bbox_cell.height > sym_bbox.height * 1.05:

                bbox_sym = bbox_cell

                annotations.append(Annotation(
                    name='detCell ' + row.symbol.symbol,
                    bbox=bbox_cell, thickness=2, color=(64, 64, 255)
                ))

            else:
                # local boundary

                bbox_sym = _extend_bbox_vertically(sym_bbox, sq)

                annotations.append(Annotation(
                    name='detd ' + row.symbol.symbol,
                    bbox=bbox_sym, thickness=2, color=(128, 128, 255)
                ))

            units: List[Phrase] = column_boxes.get('unit', [])
            els = filter(lambda el: bbox_sym.v_overlap(el.bbox) > 0.8, units)
            els = take(els, 10)
            # assert len(els) <= 1
            unit = str(els[0]) if els else None

            # val = defaultdict(list)
            val_fields: List[Tuple[Bbox, Dict[Literal['min', 'typ', 'max'], str]]] = []

            for mtm in ('min', 'typ', 'max'):
                if not head.get_span(mtm):
                    # warnings.warn('Detected field %s in %r, but no typ header' % (row.symbol.symbol, row))
                    pass
                else:
                    bbox_head = head.get_span(mtm)
                    els: List[Phrase] = sq.cast('y2', bbox_sym.y2 + bbox_sym.height, bbox_sym.y1)
                    els = filter(lambda el: isinstance(el, Phrase), els)
                    els = filter(lambda el: bbox_head.h_overlap_rel(el.bbox) > 0.8, els)
                    els = filter(lambda el: bbox_sym.v_overlap_rel(el.bbox) > 0.8, els)
                    els = filter(lambda el: el.bbox.x1 > bbox_sym.x2, els)
                    els = take(els, 10)
                    len(els)
                    # assert len(els) == len(cond), (row.symbol.symbol, row.row, repr(els), repr(cond))
                    for el in els:
                        annotations.append(Annotation(name=f'{el}({mtm})', bbox=el.bbox, color=(255, 128, 0)))  # orange
                        for f_bbox, val in val_fields:
                            if el.bbox.v_overlap_rel(f_bbox) > 0.8:
                                # assert mtm not in val, "%s: dupe %s=%s in %s" % (row.symbol.symbol, mtm, str(el),val)
                                s = str(el)
                                if _is_valid_value(mtm, s):
                                    if mtm in val:
                                        warnings.warn("%s: dupe %s=%s in %s" % (row.symbol.symbol, mtm, str(el), val))
                                    val[mtm] = s
                                    f_bbox.extend(el.bbox)
                                break
                        else:
                            s = str(el)
                            if _is_valid_value(mtm, s):
                                val_fields.append((Bbox(el.bbox), {mtm: s}))

            conds: List[Phrase] = column_boxes.get('cond', [])
            for f_bbox, val in val_fields:
                for p in parsed:
                    if p.v_overlap_rel(f_bbox) > 0.8:
                        break
                else:

                    cond = None
                    try:
                        els = filter(lambda el: f_bbox.v_overlap_rel(el.bbox) > 0.8, conds)
                        cond = take(map(str, els), 200)
                        cond = parse_cond_str(', '.join(cond))
                    except Exception as e:
                        print(pdf_file, 'error parsing field cond', e, cond)

                    try:
                        f = Field(row.symbol.symbol,
                                  **{k: val.get(k, math.nan) for k in ('min', 'typ', 'max')},
                                  unit=unit,
                                  cond=cond,
                                  source=['sheet', f'pg{table.page.page_num+1}',
                                          f't{round(table.bbox.y2)}',
                                          f'td{round(f_bbox.y2)}'])
                        fields.append(f)
                        parsed.append(f_bbox)
                    except Exception as e:
                        print(pdf_file, 'error parsing field %s in %r: %s' % (row.symbol.symbol, row.row, e))
                        # raise

    return fields

    # for each detected symbol (or parameter name) find the bbox of the table segregation
    # across the x-axis, within the y-range of the bbox, find matching elements


if __name__ == '__main__':
    # read_sheet('../../../datasheets/infineon/IRFS3107TRLPBF.pdf')  # Qrr multi-row

    # read_sheet('../../../datasheets/littelfuse/IXFK360N15T2.pdf')

    # read_sheet('../../../datasheets/toshiba/2SK1062.pdf') # long vertical unit cell, image conditions

    # read_sheet('../../../datasheets/toshiba/SSM3K361R.pdf') # multi-cond Rdson

    # ds = read_sheet('../../../datasheets/onsemi/NVMFS4C305NET1G-YE.pdf', debug_annotations=True)  # multi-cond Rdson

    ds = read_sheet_debug('../../../datasheets/littelfuse/IXTQ180N10T.pdf')  # multi-cond Rdson

    # read_sheet('../../../datasheets/onsemi/FDB075N15A-F085.pdf')

    # read_sheet('../../../datasheets/onsemi/FDB2614.pdf') # fix table cell expansion
    # read_sheet('../../../datasheets/onsemi/FDB075N15A-F085.pdf')
    ds.print(show_cond=True)
    ds.get_mosfet_specs()
    exit(0)

    for fn in sorted(glob.glob('../../../datasheets/infineon/*.pdf')):
        if '.annot.pdf' in fn or '.gs.pdf' in fn or '.cups.pdf' in fn:
            continue

        try:
            print(fn)
            ds = read_sheet(fn, debug_annotations=False)
            ds.print(show_cond=True)
            ds.get_mosfet_specs()
        except:
            print('error parsing %r' % fn)
            raise

    # read_sheet('../../../datasheets/toshiba/TPH1110ENH.pdf')

    # read_sheet('../../../datasheets/onsemi/NTP011N15MC.pdf')

    # read_sheet('../../../datasheets/nxp/PSMN009-100B,118.pdf')
    # read_sheet('../../../datasheets/diotec/DI048N08PQ.pdf')

    # read_sheet('../../../datasheets/ti/CSD19506KTT.pdf')

    # read_sheet('../../../datasheets/ao/AOW482.pdf') # rdson @Tj=125°C

    # read_sheet('../../../datasheets/epc/EPC2021.pdf')  # rdson @Tj=125°C

    # read_sheet('../../../datasheets/mcc/MCAC7D5N10YL-TP.pdf')

    # read_sheet('../../../datasheets/rohm/RX3P07CBHC16.pdf')

    # IQE046N08LM5CGSCATMA1.pdf # border-less conditions
    # TK2R4A08QM,S4X.pdf conditions reference to figure

    # read_sheet('../../../datasheets/infineon/IPA029N06NXKSA1.pdf')# todo crpboix?, expand=False, merge=False)
    # read_sheet(sys.argv[1])
