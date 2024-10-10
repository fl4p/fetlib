"""
ideas:

# table grid
- virtually increase distance between elements that are separted by a line. char_margin=2 -> should be more than that

"""
import os
import re
from collections import defaultdict
from typing import List, Dict, Union

import PIL.Image
import cv2
import numpy as np

from dslib.cache import disk_cache
from dslib.pdf.ascii import pdf_to_ascii, Row
from dslib.pdf.to_html import Annotation
from dslib.pdf.tree import bbox_union, Bbox, Page
from dslib.pdf2txt import normalize_text, whitespaces_to_space
from dslib.pdf2txt.parse import detect_fields, DetectedSymbol


class DetectedRowField():
    def __init__(self, symbol: DetectedSymbol, row: Row, row_index: int, string_offset: int) -> None:
        self.symbol = symbol
        self.row = row
        self.row_index = row_index
        self.string_offset = string_offset

    @property
    def is_head(self):
        return self.symbol.symbol == 'HEAD'

    def get_bbox_for_match_group(self, group: Union[int, str] = 1) -> Bbox:
        m = self.symbol.match
        o = self.string_offset
        elements = self.row.elements_by_range(o + m.start(group), o + m.end(group))
        if len(elements) == 0:
            return Bbox(0, 0, 0, 0)
        return bbox_union([el.bbox for el in elements])

    def __repr__(self):
        return f'DetectedField(@{round(self.row.bbox[1])},{self.symbol}, {self.symbol.match}, {self.row})'

    def __str__(self):
        return repr(self)


class Table:
    def __init__(self, rows: List[DetectedRowField], page: Page = None):
        if page is None:
            page = rows[0].row.page
        else:
            assert rows[0].row.page == page

        self.page = page
        self.rows = rows
        self.bbox = bbox_union(list(r.row.bbox for r in self.rows))

    def __getitem__(self, item):
        return self.rows[item]

    def append(self, row: DetectedRowField):
        self.rows.append(row)
        self.bbox = self.bbox.union(row.row.bbox)

    def expand_bbox_to_surrounding_rows(self, page_rows: List[Row]):
        # compute bbox of given table and extend it upwards and downwards until the next overlapping rows
        # this ensures we capture the relevant table grid structure

        self.bbox = bbox_union(list(r.row.bbox for r in self.rows))

        table = self.rows

        if not table[0].is_head:
            # extend upwards
            index_bbox = table[0].row.el(0).bbox
            i = table[0].row_index - 1
            while i > 0:
                if index_bbox.h_overlap_rel(page_rows[i].bbox) > .5:
                    self.bbox = self.bbox.union(page_rows[i].bbox)
                    break
                i -= 1

        # extend downwards
        index_bbox = table[-1].row.el(0).bbox
        i = table[-1].row_index + 1
        while i < len(page_rows):
            if index_bbox.h_overlap_rel(page_rows[i].bbox) > .5:
                self.bbox = self.bbox.union(page_rows[i].bbox)
                break
            i += 1

        return self.bbox

    def extend(self, other_table: 'Table'):
        self.rows.extend(other_table.rows)
        self.bbox = self.bbox.union(other_table.bbox)


def read_sheet(pdf_file, expand=True, merge=True):

    all_lines = pdf_to_ascii(pdf_file, grouping='line',
                             sort_vert=True,
                             spacing=' ',
                             output='rows_by_page',
                             line_overlap=.3,
                             char_margin=4.0,  # 4.0: generously merge words into lines during detection
                             )

    for pn, lines in all_lines.items():
        for row in lines:
            row.text = normalize_text(row.text)

    re_head = re.compile(
        '((\s+|^)('
        '(?P<sym>Symbol)'
        '(?P<param>Parameter)'
        '|(?P<min>Min(\.|imum)?)'
        '|(?P<typ>Typ(\.|ycal)?)'
        '|(?P<max>Max(\.|imum)?)'
        '|(?P<unit>Units?)'
        '|(?P<cond>(Test(ing)?\s+)?Conditions?))(?=$|\s+))+', re.IGNORECASE)

    head_stop = ('RATINGS',)

    annotations = defaultdict(list)

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

    for pn, rows in all_lines.items():

        # detect HEADs and symbols
        detected: List[DetectedRowField] = []
        for i, row in enumerate(rows):
            m_head = re_head.search(row.text)

            phrases = row.to_phrases(0.3)

            # cell_strings = row.text.split(cell_delim)
            strings = [' '.join(w.s for w in phrase) for phrase in phrases]
            offsets = [phrase[0].line_offset for phrase in phrases]

            sym = detect_fields('any', strings)

            # only rows qualifying as headers that do not contain a symbol match
            if m_head and not sym and _header_filter(row, m_head):
                head_sym = DetectedSymbol(0, m_head, 'HEAD')
                detected.append(DetectedRowField(head_sym, row, i, 0))
            elif sym:
                # cell_strings_offset = np.append(np.zeros(1, int), np.array(list(map(len, cell_strings))) + len(cell_delim)).cumsum()
                # print('detected', field_sym, 'in line', whitespaces_to_space(row.text))
                detected.append(DetectedRowField(sym, row, i, string_offset=offsets[sym.index]))

        if detected:

            table_row_dist = 30
            table_min_width = 120

            # group detected headers and symbol field rows into tables
            tables: List[Table] = [Table(detected[:1])]

            for d in detected[1:]:
                prev_row = tables[-1][-1]
                dy = round(prev_row.row.bbox[1] - d.row.bbox[3], 1)
                if not prev_row.is_head and (d.is_head or dy >= table_row_dist):
                    print(pn, 'new table between symbols %r .. %r' % (prev_row.row, d.row), 'dist=', dy)
                    tables.append(Table([d]))
                else:
                    tables[-1].append(d)

            if expand:
                # expand tables vertically to capture potential vector line structure (merged cells)
                # we will need this later for actual tabular data extraction
                for table in tables:
                    table.expand_bbox_to_surrounding_rows(rows)
                    table.bbox = table.bbox.pad(10, 20, 0, 0)

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

            for table in tables:
                table_bbox = table.bbox
                if table_bbox[2] - table_bbox[0] < table_min_width:
                    # skip small tables
                    continue
                if set(r.symbol for r in table.rows) == {'HEAD'}:
                    # skip HEAD only tables (no body)
                    continue

                annotations[pn].append(Annotation(
                    name='table ' + ','.join(r.symbol.symbol for r in table),
                    bbox=table_bbox,
                    text='',
                    page_bbox=table[0].row.page.mediabox)
                )

                cells = table_segregation(pdf_path=pdf_file, table=table, annotations=annotations[pn])

                for row in table.rows:

                    if row.is_head:
                        pass
                    else:

                        boxes = []
                        sym_bbox = row.get_bbox_for_match_group('detect')
                        if not sym_bbox:
                            row.get_bbox_for_match_group('detect')
                        assert sym_bbox, row.symbol.match
                        for cell in cells:
                            if sym_bbox.overlap_area(cell) > sym_bbox.area * 0.3:
                                boxes.append(cell)

                        if boxes:
                            bbox_union(boxes)
                            annotations[pn].append(Annotation(
                                name='detected ' + row.symbol.symbol,
                                bbox=bbox_union(boxes),
                                text='',
                                page_bbox=table[0].row.page.mediabox,
                                thickness=2,
                                color=(64, 64, 255)
                            ))

                # for each detected symbol (or parameter name) find the bbox of the table segregation
                # across the x-axis, within the y-range of the bbox, find matching elements

    # html_file = pdf_to_html(pdf_file, 'line', annotations=annotations)
    from dslib.util import open_file_with_default_app
    # open_file_with_default_app(html_file)

    open_file_with_default_app(pdf_raster_annot(pdf_file, 250, annotations))

    """
    - for each detected field, do a local table analysis
    - horizontal pane intersection with table structure to find out-of-line units and testing conditions
    - 
    """


def draw_annotations(image: PIL.Image.Image, page_annotations: List[Annotation]):
    rgb = np.array(image)  # .convert('RGB')
    # Convert RGB to BGR
    # bgr = rgb[:, :, ::-1].copy()

    pb = page_annotations[0].page_bbox

    sc = rgb.shape[0] / pb[3]
    rint = lambda f: int(round(sc * f))

    for a in page_annotations:
        p0 = (rint(a.bbox[0]) - 1, rint(pb[3] - a.bbox[3]) - 1)
        s = normalize_text(a.name)
        s = whitespaces_to_space(s)
        cv2.rectangle(rgb, p0, (rint(a.bbox[2]) + 1, rint(pb[3] - a.bbox[1]) + 1), a.color, a.thickness)
        cv2.putText(rgb, s, (p0[0] + 4, p0[1] + 22), cv2.FONT_HERSHEY_PLAIN, 1.6, a.color, a.thickness)

    return PIL.Image.fromarray(rgb)


@disk_cache(ttl='99d', file_dependencies=True)
def pdf_rasterize(pdf_path, dpi):
    from pdf2image import convert_from_path
    images = convert_from_path(pdf_path, dpi=dpi, fmt='png')  # rm dpi?
    return images


def pdf_raster_annot(pdf_path, dpi, annotations: Dict[int, List[Annotation]]):
    images = pdf_rasterize(pdf_path, dpi)
    assert images

    images2 = []

    for pn, page_annotations in annotations.items():
        print('draw annotations on page', pn, len(page_annotations))
        images2.append(draw_annotations(images[pn], page_annotations))

    images = images2

    out_path = pdf_path + '.annot.pdf'
    images[0].save(
        out_path, "PDF", resolution=float(dpi), save_all=True, append_images=images[1:]
    )
    assert os.path.isfile(out_path)
    return out_path


def display_borderless_tables(img: 'Image', extracted_tables) -> np.ndarray:
    # Create image displaying extracted tables
    display_image = img.copy()  # list(img.images)[0].copy()
    for tb in extracted_tables:
        for row in tb.content.values():
            for cell in row:
                cv2.rectangle(display_image, (cell.bbox.x1, cell.bbox.y1), (cell.bbox.x2, cell.bbox.y2),
                              (255, 0, 0), 2)

    # Create white separator image
    width = min(display_image.shape[1] // 10, 100)
    # white_img = cv2.cvtColor(255 * np.ones((display_image.shape[0], width), dtype=np.uint8), cv2.COLOR_GRAY2RGB)

    final_image = display_image

    # Stack images
    # final_image = np.hstack([
    # list(img.images)[0].copy(),
    #                    white_img,
    #                         display_image])

    return final_image


def table_borderify(pdf_path: str, table: Table):
    from img2table.document import PDF

    pdf = PDF(pdf_path, pages=[table.page.page_num + 0], detect_rotation=False, pdf_text_extraction=True)
    img = pdf.images[0]
    h, w, _ = img.shape

    sc = w / table.page.bbox.width
    ph = table.page.bbox.height

    img = img[round((ph - table.bbox.y2) * sc):round((ph - (table.bbox.y1 - 20)) * sc),
          round(table.bbox.x1 * sc):round(table.bbox.x2 * sc)]

    from img2table.tables.image import TableImage
    tables = TableImage(
        img=img,
        min_confidence=10,  # higher values: crops off borderless cells
    ).extract_tables(
        implicit_rows=True,
        implicit_columns=False,
        borderless_tables=True
    )

    img = display_borderless_tables(img, [t.extracted_table for t in tables])
    from PIL import Image as PILImage
    PILImage.fromarray(img).show('bordered')

    # tables = img.extract_tables(ocr=None,
    #                            borderless_tables=True,
    #                            implicit_rows=False,
    #                            implicit_columns=True,
    #                           min_confidence=50,  # higher values: crops off borderless cells
    #                           )
    return pdf


def table_seg_mu(pdf_path: str, table: Table, annotations: List[Annotation] = None):
    import pymupdf
    mudoc = pymupdf.open(pdf_path)[table.page.page_num]

    # doc; https://pymupdf.readthedocs.io/en/latest/page.html#Page.find_tables
    tset = {
        "clip": table.bbox.t,
        # lines_strict is more robust but needs a table frame
        "vertical_strategy": "lines",  # (text,lines)
        "horizontal_strategy": "lines",
        "snap_tolerance": 1,  # this causes offset issues
        "join_tolerance": 2,
        "edge_min_length": 2,
        "min_words_vertical": 1,
        "min_words_horizontal": 2,
        "intersection_tolerance": 2,
        "text_tolerance": 2,
    }

    tabs = mudoc.find_tables(**tset)  # locate and extract any tables on page

    if annotations is not None:
        for tag in tabs.tables:
            for cell in tag.cells:
                annotations.append(Annotation(
                    name='',
                    bbox=Bbox(cell),
                    text='',
                    page_bbox=table.page.bbox,
                    color=(0, 0, 255),
                    thickness=1,
                ))


def table_segregation(pdf_path: str, table: Table, annotations: List[Annotation] = None):
    # table_borderify(pdf_path, table)

    top = table.page.mediabox.y2 - table.bbox.y2
    left = table.bbox.x1
    bottom = table.page.mediabox.y2 - table.bbox.y1
    right = table.bbox.x2

    import tabula
    res = tabula.read_pdf(pdf_path,
                          pages=table.page.page_num + 1,
                          multiple_tables=False,
                          # force_subprocess=_force_subprocess,
                          output_format='json',
                          guess=False,
                          area=(top, left, bottom, right),
                          # stream=True,
                          # options='--use-line-returns'
                          )

    assert res

    boxes = []

    # assert len(res) == 1, len(res)
    for tr in res[0]['data']:
        for td in tr:
            bbox = Bbox(
                td['left'],
                table.page.mediabox.y2 - (td['top'] + td['height']),
                td['left'] + td['width'],
                table.page.mediabox.y2 - td['top'],
            )
            boxes.append(bbox)

            if not td['text'].strip():
                continue

            if annotations is not None:
                annotations.append(Annotation(
                    name='td:' + td['text'].strip(),
                    bbox=bbox,
                    text='',
                    page_bbox=table.page.bbox,
                    color=(0, 255, 0),
                    thickness=1,
                ))

    return boxes


if __name__ == '__main__':
    read_sheet('../../datasheets/infineon/IRFS3107TRLPBF.pdf')  # Qrr multi-row

    # read_sheet('../../datasheets/littelfuse/IXFK360N15T2.pdf')

    # read_sheet('../../datasheets/toshiba/TPH1110ENH.pdf')
    # read_sheet('../../datasheets/onsemi/NTP011N15MC.pdf')

    # read_sheet('../../datasheets/nxp/PSMN009-100B,118.pdf')
    # read_sheet('../../datasheets/diotec/DI048N08PQ.pdf')

    # read_sheet('../../datasheets/infineon/IPA029N06NXKSA1.pdf', expand=False, merge=False)
    # read_sheet(sys.argv[1])
