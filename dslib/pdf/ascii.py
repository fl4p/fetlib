"""
the name ascii.py refers more to ascii art technique, presenting the contents of a pdf with ascii or unicode
chars.
"""
import os
from typing import Literal, Dict, List, Union, Tuple

from pdfminer.layout import LAParams

from dslib.cache import disk_cache
from dslib.pdf.tree import vertical_sort, vertical_merge, pdf_blocks_pdfminer_six, bbox_union, Word
from dslib.pdf2txt import whitespaces_to_space


@disk_cache(ttl='1d', file_dependencies=[0], hash_func_code=True)
def pdf_to_ascii(pdf_path, grouping: Literal['block', 'line', 'word'] = 'line', sort_vert=True, spacing=50,
                 overwrite=False,
                 line_overlap=0.3, char_margin=2.0,
                 output: Literal['html', 'lines', 'rows_by_page'] = 'html') -> Union[str, List[str], Dict[int, List['Row']]]:
    assert output in {'html', 'lines', 'rows_by_page'}

    from dslib.pdf.fonts import pdfminer_fix_custom_glyphs_encoding_monkeypatch
    pdfminer_fix_custom_glyphs_encoding_monkeypatch()

    from dslib.pdf.fonts import PdfFonts
    fonts = PdfFonts(pdf_path)

    blocks = pdf_blocks_pdfminer_six(pdf_path, LAParams(
        # https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html
        line_overlap=line_overlap,  # higher will produce more lines 0.4 is too high (NTMFSC4D2N10MC)
        char_margin=char_margin,
        line_margin=0.5,  # lower values → more lines (only matters when grouping = 'block')
        # boxes_flow=-1.0 # -1= H-only   1=V
        all_texts=True,  # needed for OCRed (ocrmypdf) files
    ), fonts=fonts.font_map, html_spans=output == 'html')

    print(repr(blocks))

    pagenos = set(blocks.keys())

    rows_by_page:Dict[int, List[Row]] = dict()
    for page_num in sorted(pagenos):
        rows = process_page(blocks[page_num], grouping, sort_vert, spacing, overwrite)
        rows_by_page[page_num] = rows

    ascii_lines = []


    for pn, rows in rows_by_page.items():
        ascii_lines += [r.text for r in rows]
        ascii_lines += ["", "-" * 80, "", ""]

    # for ascii_line in ascii_lines:
    #    print(ascii_line)

    if not ascii_lines:
        print('No lines extracted from', pdf_path)
        return None

    if output == 'html':
        name = os.path.basename(pdf_path).split('.')[0]

        css = """

        .annot {
            display: inline-block;
            width: 4em; margin-right: -4em;
            position: relative;
            top: -.7em;
            background-color: rgba(255, 255, 255, .7);
            color: green;
            border-left: 1px solid;
            padding-bottom: .3em;
            margin-top: -0.3em;
            font: 10px arial;
            margin-left: -1px;
        }    


        .annot:hover {
            z-index: 10;
            font-size: 120%;
        }
            """

        html = (f'<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"><title>{name}</title>'
                f'<style>\n{fonts.css("data/out")}\n{css}</style></head>'
                f'<body><pre style="font-size:80%">{chr(10).join(ascii_lines)}</pre></body></html>')

        import pathlib
        pathlib.Path("data/out").mkdir(parents=True, exist_ok=True)
        html_path = "data/out/" + name + ".ascii.html"
        pathlib.Path(html_path).write_bytes(html.encode('utf-8'))
        print('written', html_path)

        return html_path

    if output == 'rows_by_page':
        return rows_by_page
    else:
        return ascii_lines

class Row():
    def __init__(self, text, elements:Dict[int, Word]):
        self.text = text
        self.elements = elements
        self.bbox = bbox_union([el.bbox for el in elements.values()])

    def element_by_tpos(self, pos) -> Tuple[int, Word]:
        sel = -1, None
        for el_start, el in self.elements.items():
            if sel:
                assert el_start > sel[0]
            if el_start <= pos:
                sel = el_start, el
            else:
                break
        return sel

    def __str__(self):
        return whitespaces_to_space(self.text)

    def __repr__(self):
        return 'Row(%d ~ %d, %r)' % (self.bbox[1], self.bbox[3], whitespaces_to_space(self.text).strip())

    def el(self, i):
        return list(self.elements.values())[i]


def process_page(blocks, grouping, sort_vert: bool, spacing: float, overwrite: bool):
    # apply grouping
    if grouping == 'block':
        elements = blocks
    elif grouping == 'line':
        elements = sum(map(list, blocks), [])
    else:
        raise ValueError(grouping)

    # sort & merge lines (or blocks) vertically
    # sometimes not sorting can result more tidy tables
    # vertical_merge is an alternative to increasing char_margin in LAParams
    if sort_vert:
        vertical_sort(elements)
        vertical_merge(elements)

    # loop helper vars
    empty_rows = 0
    prev_y = elements[0].bbox[1]

    rows = []  # output

    max_x = 0
    max_len = 0

    for el in elements:
        row_text = ""
        row_objs = {}

        # compute blank lines for vertical spacing
        dy = el.bbox[1] - prev_y
        pad_lines = int(-dy / 10) - 1  # 18 param: line spacing
        if pad_lines > 0:
            row_text += '\n' * pad_lines
        prev_y = el.bbox[1]

        i = 0
        for line in el:

            # only overwrite at least this number of chars, otherwise overhang
            ow_th = 2

            assert line.bbox[0] <= line.bbox[2], line.bbox
            if line.bbox[0] > max_x:
                max_x = line.bbox[0]

            ci = int((line.bbox[0] - 30) / (100 / spacing))
            pad = max(1, ci - len(row_text))

            if ci <= len(row_text) - ow_th:

                if len(row_text) - ci > 20:
                    print('WARNING', 'more than 20 chars overlap, elements might not be h-sorted')

                if overwrite:
                    row_text = row_text[:(ci)] + '…'
                    pad = 0

            annot = f'x{round(line.bbox[0])} i{i} l{len(row_text) + pad} p{pad}'
            s = str(line)
            assert '\n' not in s, s
            # f"""<span class="annot" style="">{annot}</span>"""
            row_objs[len(row_text) + pad] = line
            row_text += ' ' * pad + s


            if len(row_text) > max_len:
                max_len = len(row_text)
            i += 1

        # if len(row) > 500:
        #    print(el.page_num, el.index, 'long row', len(row), repr(row.strip()[:40]))
        #    row = row[:200]

        if not row_text.strip():
            empty_rows += 1
            if empty_rows > 5:
                continue
        else:
            empty_rows = 0

        rows.append(Row(row_text, row_objs))

    # print(blocks[0].page_num, 'max_x', round(max_x), 'max_len', max_len, 'spacing=', spacing)

    return rows
