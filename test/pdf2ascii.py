import os.path
import pathlib
from typing import List, Literal

from pdfminer.layout import LAParams

from dslib.pdf.ascii import process_page
from dslib.pdf.fonts import PdfFonts
from dslib.pdf.tree import TextBlock, pdf_blocks_pdfminer_six

csv = []

pdf_path = (
    # "../datasheets/infineon/2N7002DWH6327XTSA1.pdf"  # nice
    # "../datasheets/infineon/IPA029N06NXKSA1.pdf"
    # "../datasheets/infineon/IRFS4228PBF.pdf"  # not so well
    "../datasheets/onsemi/NTMFSC4D2N10MC.pdf"
    # "../datasheets/infineon/BSC050N10NS5ATMA1.pdf" # vectorized text
    #
)

sort_vert = True
grouping: Literal['block', 'line', 'word'] = 'line'
# line_overlap =.2 # higher will produce more lines
overwrite = False
spacing = 30


def main():
    from dslib.pdf.fonts import pdfminer_fix_custom_glyphs_encoding_monkeypatch
    pdfminer_fix_custom_glyphs_encoding_monkeypatch()

    fonts = PdfFonts(pdf_path)

    blocks: List[TextBlock] = pdf_blocks_pdfminer_six(pdf_path, LAParams(
        line_overlap=0.5,  # higher will produce more lines
        line_margin=0.5,  # lower values → more lines (only matters when grouping = 'block')
        # boxes_flow=-1.0 # -1= H-only   1=V
    ), fonts={f.basefont: f for f in fonts.fonts})

    pagenos = set(b.page_num for b in blocks)
    # pagenos = {0,1}

    ascii_lines = []
    for page_num in sorted(pagenos):
        page_blocks = [b for b in blocks if b.page_num == page_num]  # TODO this is slow
        ascii_lines += process_page(page_blocks)
        ascii_lines += ["", "-" * 80, "", ""]

    # for ascii_line in ascii_lines:
    #    print(ascii_line)

    name = os.path.basename(pdf_path).split('.')[0]
    html = (f'<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"><title>{name}</title>'
            f'<style>\n{fonts.css()}\n</style></head>'
            f'<body><pre style="font-size:80%">{chr(10).join(ascii_lines)}')

    html_path = name + ".html"
    pathlib.Path(html_path).write_bytes(html.encode('utf-8'))
    print('written', html_path)


if __name__ == '__main__':
    main()
