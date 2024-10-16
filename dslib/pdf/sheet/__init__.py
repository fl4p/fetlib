"""
ideas:

# table grid
- virtually increase distance between elements that are separted by a line. char_margin=2 -> should be more than that

"""
import glob
import re
import warnings
from collections import defaultdict
from typing import List

from dslib.field import Field, DatasheetFields
from dslib.pdf.ascii import pdf_to_ascii, Row, Phrase
from dslib.pdf.sheet.annotation import pdf_raster_annot
from dslib.pdf.sheet.spatial import SpatialQuery, take
from dslib.pdf.sheet.tables import table_segregation, DetectedRowField, Table
from dslib.pdf.to_html import Annotation
from dslib.pdf.tree import bbox_union, GraphicBlock, Bbox
from dslib.pdf2txt import normalize_text
from dslib.pdf2txt.parse import detect_fields, DetectedSymbol

head_re = re.compile(
    '((\s+|^\s*)('
    '(?P<sym>Symbol)'
    '|(?P<param>Parameter|Characteristics)'
    '|(?P<min>Min(\.|imum)?)'
    '|(?P<typ>Typ(\.|ycal)?)'
    '|(?P<max>Max(\.|imum)?)'
    '|(?P<unit>Units?)'
    '|(?P<cond>(Test(ing)?\s+)?Conditions?))(?=$|\s+))+', re.IGNORECASE)

head_re_groups = ('sym', 'param', 'min', 'typ', 'max', 'unit', 'cond')

head_stop = ('RATINGS', 'Ratings', 'Power', 'Avalanche', 'allowable', 'limited', 'Lead',
             'Static', 'Electrical', 'Dynamic', 'curves', 'above',
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


def read_sheet(pdf_file, expand=True, merge=True, debug_annotations=True):
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

    annotations = defaultdict(list)
    ds = DatasheetFields(mfr, mpn)

    for pn, rows in all_lines.items():
        page_annotations: List[Annotation] = []
        ds.add_multiple(_process_page(pdf_file, mfr, rows, pn, page_annotations, merge, expand))
        if page_annotations:
            for a in page_annotations:
                a.page_bbox = a.page_bbox or rows[0].page.mediabox
            annotations[pn] = page_annotations

    ds.print(show_cond=True)

    if debug_annotations:
        from dslib.util import open_file_with_default_app
        open_file_with_default_app(pdf_raster_annot(pdf_file, 250, annotations))

    """
    - for each detected field, do a local table analysis
    - horizontal pane intersection with table structure to find out-of-line units and testing conditions
    - 
    """


def _process_page(pdf_file, mfr, rows, pn, annotations: List[Annotation], merge, expand) -> List[Field]:
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
            #print(pn, 'new table between symbols %r .. %r' % (prev_row.row, d.row), 'dist=', dy)
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

    # _indentify_units(tables, sq, annotations)

    fields = []
    for table in tables:
        fields.extend(_process_table(pdf_file, table, hs, sq, annotations))

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


def _extend_bbox_vertically(bbox: Bbox, sq: SpatialQuery):
    top = sq.ray('y1', bbox, 200, 0.9, 10)
    bottom = sq.ray('y2', bbox, 200, 0.9, 10, start_from_bbox_center=True)

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


def _vertically_expand_column_cells(bbox_head: Bbox, cells, sq: SpatialQuery, annotations: List[Annotation]):
    annotations.append(Annotation('HEAD', bbox_head, color=(255, 0, 255)))

    els: List[Phrase] = []

    ray: List[Phrase] = sq.ray('y2', bbox_head, 600, min_overlap=.5, limit=99, types=Phrase)

    for u in ray:

        bbox_cell = _find_cell_bbox(u.bbox, cells)

        if bbox_cell.height < u.bbox.height * 1.05:
            bbox_cell = _extend_bbox_vertically(u.bbox, sq)

        if bbox_cell.height / u.bbox.height > 20: # toshiba/2SK1062: ns unit
            bbox_cell = u.bbox

        annotations.append(Annotation('td:vex', bbox_cell, color=(255, 0, 255)))
        els.append(u.extend_bbox(bbox_cell))

    return els


def _find_cell_bbox(bbox, cells, min_area_overlap=.3):
    boxes = []
    for cell in cells:
        if bbox.overlap_area(cell) > bbox.area * min_area_overlap:
            boxes.append(cell)
    return bbox_union(boxes) if boxes else Bbox(0, 0, 0, 0)


def _process_table(pdf_file, table: Table, head: TableHeaderState, sq: SpatialQuery, annotations: List[Annotation]):
    fields: List[Field] = []

    table_min_width = 120

    table_bbox = table.bbox
    if table_bbox[2] - table_bbox[0] < table_min_width:
        # skip small tables
        return

    # if set(r.symbol for r in table.rows) == {'HEAD'}:
    #    # skip HEAD only tables (no body)
    #    return

    annotations.append(Annotation(
        name='table ' + ','.join(r.symbol.symbol for r in table),
        bbox=table_bbox,
        page_bbox=table[0].row.page.mediabox)
    )

    cells = table_segregation(pdf_path=pdf_file, table=table, annotations=annotations)

    header_boxes = dict()
    column_boxes = dict()

    for row in table.rows:

        if row.is_head:

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
                        assert l.bbox.x2 < x1
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

                if row_head_rank > 1:
                    header_boxes[g] = bbox_cell

                if g in {'unit', 'cond'}:
                    column_boxes[g] = _vertically_expand_column_cells(bbox_cell, cells, sq, annotations)

            # place virtual 'unit' header
            if 'unit' not in starts_idx and 'max' in starts_idx and 'typ' in starts_idx:
                bbox = header_boxes['max']
                w = bbox.height + min(bbox.width, 25)
                if not sq.ray('x1', bbox, w, min_overlap=0.1):
                    bbox = Bbox(bbox.x2 + bbox.height, bbox.y1, bbox.x2 + w, bbox.y2)
                    column_boxes['unit'] = _vertically_expand_column_cells(bbox, cells, sq, annotations)

        else:  # if not HEAD

            sym_bbox = row.get_bbox_for_match_group('detect')
            assert sym_bbox, row.symbol.match

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
                    name='detected ' + row.symbol.symbol,
                    bbox=bbox_sym, thickness=2, color=(128, 128, 255)
                ))

            units: List[Phrase] = column_boxes.get('unit', [])
            els = filter(lambda el: bbox_sym.v_overlap(el.bbox) > 0.8, units)
            els = take(els, 10)
            assert len(els) <= 1
            unit = str(els[0]) if els else None


            conds: List[Phrase] = column_boxes.get('cond', [])
            els = filter(lambda el: bbox_sym.v_overlap(el.bbox) > 0.8, conds)
            cond = take(map(str, els), 20)

            val = dict()

            for mtm in ('min', 'typ', 'max'):
                if not header_boxes.get(mtm):
                    warnings.warn('Detected field %s in %r, but no typ header' % (row.symbol.symbol, row))
                    val[mtm] = None
                else:
                    bbox_head = header_boxes[mtm]
                    els: List[Phrase] = sq.cast('y2', bbox_sym.y2 + bbox_sym.height, bbox_sym.y1)
                    els = filter(lambda el: isinstance(el, Phrase), els)
                    els = filter(lambda el: bbox_head.h_overlap(el.bbox) > 0.8, els)
                    els = filter(lambda el: bbox_sym.v_overlap(el.bbox) > 0.8, els)
                    els = take(els, 10)
                    len(els)
                    assert len(els) <= 1, repr(els)
                    if els:
                        annotations.append(Annotation(name=str(els[0]), bbox=els[0].bbox, color=(255, 128, 0)))
                        val[mtm] = str(els[0])
                    else:
                        val[mtm] = None
            if len(list(filter(bool, val.values()))):
                try:
                    f = Field(row.symbol.symbol, **val, unit=unit, cond=cond)
                    fields.append(f)
                    # assert f
                except:
                    print('error parsing field %s in %r' % (row.symbol.symbol, row.row))
                    raise

    return fields

    # for each detected symbol (or parameter name) find the bbox of the table segregation
    # across the x-axis, within the y-range of the bbox, find matching elements


if __name__ == '__main__':
    # read_sheet('../../../datasheets/infineon/IRFS3107TRLPBF.pdf')  # Qrr multi-row

    # read_sheet('../../../datasheets/littelfuse/IXFK360N15T2.pdf')

    #read_sheet('../../../datasheets/toshiba/2SK1062.pdf') # long vertical unit cell

    read_sheet('../../../datasheets/toshiba/SSM3K361R.pdf') # multi-cond Rdson

    for fn in sorted(glob.glob('../../../datasheets/toshiba/*.pdf')):
        try:
            read_sheet(fn, debug_annotations=False)
        except:
            print('error parsing %r' % fn)
            raise

    #read_sheet('../../../datasheets/toshiba/TPH1110ENH.pdf')

    # read_sheet('../../../datasheets/onsemi/NTP011N15MC.pdf')

    # read_sheet('../../../datasheets/nxp/PSMN009-100B,118.pdf')
    # read_sheet('../../../datasheets/diotec/DI048N08PQ.pdf')

    # read_sheet('../../../datasheets/ti/CSD19506KTT.pdf')

    # read_sheet('../../../datasheets/ao/AOW482.pdf') # rdson @Tj=125°C

    # read_sheet('../../../datasheets/epc/EPC2021.pdf')  # rdson @Tj=125°C

    # read_sheet('../../../datasheets/mcc/MCAC7D5N10YL-TP.pdf')

    # read_sheet('../../../datasheets/rohm/RX3P07CBHC16.pdf')

    # read_sheet('../../../datasheets/infineon/IPA029N06NXKSA1.pdf')# todo crpboix?, expand=False, merge=False)
    # read_sheet(sys.argv[1])
