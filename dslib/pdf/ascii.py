"""
the name ascii.py refers more to ascii art technique, presenting the contents of a pdf with ascii or unicode
chars.
"""
import os
from typing import Literal

from pdfminer.layout import LAParams

from dslib.pdf.tree import vertical_sort, vertical_merge, pdf_blocks_pdfminer_six


def pdf_to_ascii(pdf_path, grouping: Literal['block', 'line', 'word'] = 'line', sort_vert=True, spacing=50,
                 overwrite=False, line_overlap=0.33,
                 output='html'):
    from dslib.pdf.fonts import pdfminer_fix_custom_glyphs_encoding_monkeypatch
    pdfminer_fix_custom_glyphs_encoding_monkeypatch()

    from dslib.pdf.fonts import PdfFonts
    fonts = PdfFonts(pdf_path)

    blocks = pdf_blocks_pdfminer_six(pdf_path, LAParams(
        # https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html
        line_overlap=line_overlap,  # higher will produce more lines 0.4 is too high (NTMFSC4D2N10MC)
        line_margin=0.5,  # lower values → more lines (only matters when grouping = 'block')
        # boxes_flow=-1.0 # -1= H-only   1=V
        all_texts=True,  # needed for OCRed (ocrmypdf) files
    ), fonts=fonts.font_map)

    pagenos = set(blocks.keys())
    # pagenos = {0,1}

    ascii_lines = []
    for page_num in sorted(pagenos):
        ascii_lines += process_page(blocks[page_num], grouping, sort_vert, spacing, overwrite)
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

    if output == 'lines':
        return ascii_lines


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
    if sort_vert:
        vertical_sort(elements)
        vertical_merge(elements)

    # loop helper vars
    empty_rows = 0
    prev_y = elements[0].bbox[1]

    ascii_lines = []  # output

    max_x = 0
    max_len = 0

    for el in elements:
        row = ""

        # compute blank lines for vertical spacing
        dy = el.bbox[1] - prev_y
        pad_lines = int(-dy / 10) - 1  # 18 param: line spacing
        if pad_lines > 0:
            row += '\n' * pad_lines
        prev_y = el.bbox[1]

        i = 0
        for line in el:

            # only overwrite at least this number of chars, otherwise overhang
            ow_th = 2

            assert line.bbox[0] <= line.bbox[2], line.bbox
            if line.bbox[0] > max_x:
                max_x = line.bbox[0]

            ci = int((line.bbox[0] - 30) / (100 / spacing))
            pad = max(1, ci - len(row))

            if ci <= len(row) - ow_th:

                if len(row) - ci > 20:
                    print('WARNING', 'more than 20 chars overlap, elements might not be h-sorted')

                if overwrite:
                    row = row[:(ci)] + '…'
                    pad = 0

            annot = f'x{round(line.bbox[0])} i{i} l{len(row) + pad} p{pad}'
            s = str(line)
            assert '\n' not in s, s
            # f"""<span class="annot" style="">{annot}</span>"""
            row += ' ' * pad + s

            if len(row) > max_len:
                max_len = len(row)
            i += 1

        # if len(row) > 500:
        #    print(el.page_num, el.index, 'long row', len(row), repr(row.strip()[:40]))
        #    row = row[:200]

        if not row.strip():
            empty_rows += 1
            if empty_rows > 5:
                continue
        else:
            empty_rows = 0

        ascii_lines.append(row)

    # print(blocks[0].page_num, 'max_x', round(max_x), 'max_len', max_len, 'spacing=', spacing)

    return ascii_lines
