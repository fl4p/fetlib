from typing import List, Union

from dslib.pdf.ascii import Row
from dslib.pdf.sheet.annotation import display_borderless_tables
from dslib.pdf.to_html import Annotation
from dslib.pdf.tree import Bbox, bbox_union, Page
from dslib.pdf2txt.parse import DetectedSymbol


class DetectedRowField():
    def __init__(self, symbol: DetectedSymbol, row: Row, row_index: int, string_offset: int) -> None:
        self.symbol = symbol
        self.row = row
        self.row_index = row_index
        self.string_offset = string_offset

    @property
    def is_head(self):
        return self.symbol.symbol == 'HEAD'

    def get_groups_by_start(self):
        m = self.symbol.match
        return {k: m.start(k) for k, v in m.groupdict().items() if v}

    def get_bbox_for_match_group(self, group: Union[int, str] = 1, allow_missing=False, allow_empty=True) -> Bbox:
        m = self.symbol.match
        if allow_missing and not m.groupdict().get(group, None):
            return Bbox(0, 0, 0, 0)
        o = self.string_offset
        elements = self.row.elements_by_range(o + m.start(group), o + m.end(group))
        if len(elements) == 0:
            if not allow_empty:
                raise ValueError(f'No elements found for group {group} within {(o + m.start(group), o + m.end(group))}')
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
                          multiple_tables=True,
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
                    name='td' + repr(td['text'].strip()),
                    bbox=bbox,
                    text='',
                    page_bbox=table.page.bbox,
                    color=(0, 255, 0),
                    thickness=1,
                ))

    return boxes
