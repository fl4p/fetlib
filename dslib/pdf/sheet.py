"""
ideas:

# table grid
- virtually increase distance between elements that are separted by a line. char_margin=2 -> should be more than that

"""
import os
import re
from collections import defaultdict
from typing import List, Dict

import PIL.Image
import cv2
import numpy as np

from dslib.pdf.ascii import pdf_to_ascii, Row
from dslib.pdf.to_html import pdf_to_html, Annotation
from dslib.pdf.tree import bbox_union
from dslib.pdf2txt.parse import detect_fields


class DetectedField():
    def __init__(self, symbol: str, re_match: re.Match, row: Row, row_index: int) -> None:
        self.symbol = symbol
        self.re_match = re_match
        self.row = row
        self.row_index = row_index

    def __repr__(self):
        return f'DetectedField(@{round(self.row.bbox[1])},{self.symbol}, {self.re_match}, {self.row})'

    def __str__(self):
        return repr(self)


def read_sheet(pdf_file):
    all_lines = pdf_to_ascii(pdf_file, grouping='line',
                             sort_vert=True,
                             spacing=100,
                             output='rows_by_page',
                             line_overlap=.3,
                             char_margin=4.0,  # generously merge words into lines during detection
                             )

    re_head = re.compile(
        '(?P<min>Min(\.|imum)?)\s+(?P<typ>Typ(\.|ycal)?)\s+(?P<max>Max(\.|imum)?)(\s+(?P<unit>Units?))?', re.IGNORECASE)

    annotations = defaultdict(list)

    for pn, rows in all_lines.items():

        # detect HEADs and symbols
        detected: List[DetectedField] = []
        for i, row in enumerate(rows):
            m_head = re_head.search(row.text)
            if m_head:
                head_words = {g: row.element_by_tpos(m_head.start(g)) for g, v in m_head.groupdict().items() if v}
                d = m_head.groupdict()
                detected.append(DetectedField('HEAD', m_head, row, i))
            else:

                m, field_sym = detect_fields('any', row.text.split('  '))

                if m:
                    # print('detected', field_sym, 'in line', whitespaces_to_space(row.text))
                    detected.append(DetectedField(m, field_sym, row, i))

        if detected:

            # group detected rows into tables

            table_row_dist = 30
            table_min_width = 120

            def h_overlap(b1, b2):
                # TODO simplify
                if b2[0] <= b1[2] and b1[0] <= b2[2]:
                    return min(abs(b1[0] - b2[2]), abs(b1[2] - b2[0]))
                else:
                    return 0

            def w_min(b1, b2):
                return min(b1[2] - b1[0], b2[2] - b2[0])

            def h_overlap_rel(b1, b2):
                return h_overlap(b1, b2) / w_min(b1, b2)

            def _extend_table_to_surrounding_rows(table: List[DetectedField]):
                # compute bbox of given table and extend it upwards and downwards until the next overlapping rows
                # this ensures we capture the relevant table grid structure

                table_bbox = bbox_union(list(r.row.bbox for r in table))

                # extend upwards
                if table[0].symbol != 'HEAD':
                    index_bbox = table[0].row.el(0).bbox
                    i = table[0].row_index - 1
                    while i > 0:
                        if h_overlap_rel(index_bbox, rows[i].bbox) > .5:
                            table_bbox = bbox_union(table_bbox, rows[i].bbox)
                            break
                        i -= 1

                # extend down
                index_bbox = table[-1].row.el(0).bbox
                i = table[-1].row_index + 1
                while i < len(rows):
                    if h_overlap_rel(index_bbox, rows[i].bbox) > .5:
                        table_bbox = bbox_union(table_bbox, rows[i].bbox)
                        break
                    i += 1

                return table_bbox

            tables_rows = [[detected[0]]]
            for d in detected[1:]:
                last = tables_rows[-1][-1]
                dy = round(last.row.bbox[1] - d.row.bbox[3], 1)
                if d.symbol != 'HEAD' and (dy < table_row_dist or last.symbol == 'HEAD'):
                    tables_rows[-1].append(d)
                else:
                    print(pn, 'new table between symbols %r .. %r' % (last.row, d.row), 'dist=', dy)
                    tables_rows.append([d])

            for table in tables_rows:

                table_bbox = _extend_table_to_surrounding_rows(table)

                if table_bbox[2] - table_bbox[0] < table_min_width:
                    continue
                annotations[pn].append(Annotation(
                    'table ' + ','.join(r.symbol for r in table), table_bbox, '',
                page_bbox=table[0].row.page.mediabox))

    html_file = pdf_to_html(pdf_file, 'line', annotations=annotations)
    from dslib.util import open_file_with_default_app
    #open_file_with_default_app(html_file)

    open_file_with_default_app(pdf_raster_annot(pdf_file, 250, annotations))

    """
    - for each detected field, do a local table analysis
    - horizontal pane intersection with table structure to find out-of-line units and testing conditions
    - 
    """


def draw_annotations(image: PIL.Image.Image, page_annotations: List[Annotation]):

    rgb = np.array(image)# .convert('RGB')
    # Convert RGB to BGR
    #bgr = rgb[:, :, ::-1].copy()

    pb =  page_annotations[0].page_bbox

    s = rgb.shape[0] / pb[3]
    rint = lambda f: int(round(s * f))

    for a in page_annotations:
        cv2.rectangle(rgb, (rint(a.bbox[0])-1, rint(pb[3]-a.bbox[3])-1), (rint(a.bbox[2])+1, rint(pb[3]-a.bbox[1])+1), (255, 0, 0), 2)
        #cv2.putText(img, a.name, )

    return PIL.Image.fromarray(rgb)


def pdf_raster_annot(pdf_path, dpi, annotations: Dict[int, List[Annotation]]):
    from pdf2image import convert_from_path
    images = convert_from_path(pdf_path, dpi=dpi, fmt='png')  # rm dpi?
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


def detect_tables(pdf_path):
    import tabula
    tabula.read_pdf(pdf_path,
                    pages='all',
                    multiple_tables=True,
                    # force_subprocess=_force_subprocess,
                    output_format='json'
                    )


if __name__ == '__main__':
    read_sheet('../../datasheets/infineon/IRFS3107TRLPBF.pdf')
    #read_sheet('../../datasheets/infineon/IPA029N06NXKSA1.pdf')
    # read_sheet(sys.argv[1])
