"""
the name ascii.py refers more to ascii art technique, presenting the contents of a pdf with ascii or unicode
chars.
"""
import os
from typing import Literal, List

import pdfminer.pdfpage
from pdfminer.layout import LAParams

from dslib.pdf.tree import vertical_sort, pdf_blocks_pdfminer_six, Block


def pdf_to_html(pdf_path, grouping: Literal['block', 'line', 'word'] = 'line', merge_lines=False):
    from dslib.pdf.fonts import pdfminer_fix_custom_glyphs_encoding_monkeypatch
    pdfminer_fix_custom_glyphs_encoding_monkeypatch()

    from dslib.pdf.fonts import PdfFonts
    fonts = PdfFonts(pdf_path)

    # TODO
    blocks = pdf_blocks_pdfminer_six(pdf_path, LAParams(
        line_overlap=0.5,  # higher will produce more lines
        char_margin=0.5, # default:2
        line_margin=0.5,  # lower values → more lines (only matters when grouping = 'block')
        # boxes_flow=-1.0 # -1= H-only   1=V
        all_texts=True,  # needed for OCRed (ocrmypdf) files
    ), fonts=fonts.font_map)

    pagenos = set(blocks.keys())

    html = []
    for page_num in sorted(pagenos):
        pg = blocks[page_num][0].page
        pgbox = pg.mediabox
        assert pgbox[0] == 0 and pgbox[1] == 0, pgbox
        html.append(f'<div class=page data-pgn={page_num} style="width:{pgbox[2]}px;height:{pgbox[3]}px">')
        process_page(html, pg, blocks[page_num], grouping, merge_lines)
        html.append('</div>')

    if not html:
        print('No HTML extracted from', pdf_path)
        return None

    css = """
    .page { 
    position: relative;
    width: 720px;
    height: 100%;
    border: 1px solid black;
    margin: 2em auto;
    font-size: 50%;
    }
    
    .page div {
        position: absolute;
        white-space: nowrap;
    }
    
    .page div:hover {
        margin: -1px;
        border: 1px solid lightgreen;
        cursor: default;
    }
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

    name = os.path.basename(pdf_path).split('.')[0]
    html_doc = (f'<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"><title>{name}</title>'
                f'<style>\n{fonts.css("data/out")}\n{css}</style></head>'
                f'<body><div class=doc>{chr(10).join(html)}</div></body></html>')

    import pathlib
    html_path = "data/out/" + name + ".html"
    pathlib.Path(html_path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(html_path).write_bytes(html_doc.encode('utf-8'))
    print('written', html_path)

    return html_path


def process_page(html, page:pdfminer.pdfpage.PDFPage, blocks: List[Block], grouping, merge_lines=False):
    # apply grouping
    if grouping == 'block':
        elements = blocks
    elif grouping == 'line':
        elements = sum(map(list, blocks), [])
    else:
        raise ValueError(grouping)

    # sort & merge lines (or blocks) vertically
    if merge_lines:
        vertical_sort(elements)
        # vertical_merge(elements)

    # loop helper vars

    for el in elements:

        left = round(el.bbox[0], 2)
        top = round(page.mediabox[3]- el.bbox[1], 2)
        width = round(el.bbox[2] - el.bbox[0], 2)
        height = round(el.bbox[3] - el.bbox[1], 2)

        html.append(f'<div style="left:{left}px;top:{top}px;width:{width}px;height:{height}px">{str(el)}</div>')
