"""
the name ascii.py refers more to ascii art technique, presenting the contents of a pdf with ascii or unicode
chars.
"""
import os
from copy import copy
from typing import Literal, Dict, List, Union, Tuple

from pdfminer.layout import LAParams

from dslib.cache import disk_cache
from dslib.pdf.tree import vertical_sort, vertical_merge, pdf_blocks_pdfminer_six, bbox_union, Word, GraphicBlock, \
    TextBlock
from dslib.pdf2txt import whitespaces_to_space


@disk_cache(ttl='1d', file_dependencies=[0], hash_func_code=True, salt=('v10', pdf_blocks_pdfminer_six.__code__.co_code))
def pdf_to_ascii(pdf_path,
                 grouping: Literal['block', 'line', 'word'] = 'line',
                 sort_vert=True,
                 spacing: Union[int, str] = 50,
                 overwrite=False,
                 line_overlap=0.3, char_margin=2.0,
                 output: Literal['html', 'lines', 'rows', 'rows_graphics'] = 'html'
                 ) -> Union[
    str, List[str], Dict[int, List['Row']]]:
    assert output in {'html', 'lines', 'rows', 'rows_graphics'}

    from dslib.pdf.fonts import pdfminer_fix_custom_glyphs_encoding_monkeypatch
    pdfminer_fix_custom_glyphs_encoding_monkeypatch()

    from dslib.pdf.fonts import PdfFonts
    fonts = PdfFonts(pdf_path)

    blocks = pdf_blocks_pdfminer_six(
        pdf_path,
        LAParams(
            # https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html
            line_overlap=line_overlap,  # higher will produce more lines 0.4 is too high (NTMFSC4D2N10MC)
            char_margin=char_margin,
            line_margin=0.5,  # lower values → more lines (only matters when grouping = 'block')
            # boxes_flow=-1.0 # -1= H-only   1=V
            all_texts=True,  # needed for OCRed (ocrmypdf) files
        ),
        fonts=fonts.font_map,
        html_spans=output == 'html',
        other_visuals=True
    )

    # print(repr(blocks))

    pagenos = set(blocks.keys())

    rows_by_page: Dict[int, List[Row]] = dict()
    for page_num in sorted(pagenos):
        text_blocks = [b for b in blocks[page_num] if isinstance(b, TextBlock)]
        rows = process_page(text_blocks, grouping, sort_vert, spacing, overwrite)
        if output == 'rows_graphics':
            rows += [b for b in blocks[page_num] if isinstance(b, GraphicBlock)]
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

    if output.startswith('rows'):
        return rows_by_page
    else:
        return ascii_lines


class Phrase:
    """
    A collection of words that are spatially close.
    """

    def __init__(self, words: List[Word], parent=None):
        self.words = words
        self.bbox = bbox_union(list(w.bbox for w in words))
        self.parent:Row = parent

    def __iter__(self):
        return iter(self.words)

    def __getitem__(self, idx):
        return self.words[idx]

    def __str__(self):
        return ' '.join(w.s for w in self.words)

    def __repr__(self):
        return f'{self.__class__.__name__}({self.words})'

    def extend_bbox(self, bbox):
        c = copy(self)
        c.bbox = self.bbox.union(bbox)
        return c


class Row():
    def __init__(self, text: str, elements: Dict[int, Word], page):
        self.text = text
        self.elements = elements
        self.bbox = bbox_union([el.bbox for el in elements.values()])
        self.page = page

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

    def elements_by_range(self, start, end) -> List[Word]:
        assert end > start

        sel = []
        el_starts = list(self.elements.keys())
        for i, el_start in enumerate(el_starts):
            el = self.elements[el_start]
            # el_end = el_starts[i + 1] if i + 1 < len(el_starts) else len(self.text)
            el_end = el_start + len(el.s)
            if start <= el_start < end or start < el_end <= end:
                sel.append(el)

        return sel

    def __str__(self):
        return whitespaces_to_space(self.text)

    def __repr__(self):
        return 'Row(%d ~ %d, %r)' % (self.bbox[1], self.bbox[3], whitespaces_to_space(self.text).strip())

    def el(self, i):
        return list(self.elements.values())[i]

    def to_phrases(self, word_distance=0.5) -> List[Phrase]:
        els = list(self.elements.values())
        offsets = list(self.elements.keys())
        phrases = []
        for i in range(0, len(els)):
            if i == 0:
                d = float('inf')
                h = 1
            else:
                d = els[i].bbox.x1 - phrases[-1][-1].bbox.x2
                h = max(els[i].bbox.height, phrases[-1][-1].bbox.height)
            w: Word = copy(els[i])
            w.line_offset = offsets[i]

            if d / h <= word_distance:
                phrases[-1].append(w)
            else:
                phrases.append([w])
        return list(map(lambda wl: Phrase(wl, parent=self), phrases))


def process_page(blocks, grouping, sort_vert: bool, spacing: float, overwrite: bool):
    # apply grouping
    if grouping == 'block':
        elements = blocks
    elif grouping == 'line':
        elements = sum(map(list, blocks), [])
    else:
        raise ValueError(grouping)

    if not elements:
        return []

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

            if isinstance(spacing, str):
                pad = 1
                pad_char = ' '
            else:

                ci = int((line.bbox[0] - 30) / (100 / spacing))
                pad = max(1, ci - len(row_text))
                pad_char = ' '

                if ci <= len(row_text) - ow_th:

                    if len(row_text) - ci > 20:
                        print('WARNING', 'more than 20 chars overlap, elements might not be h-sorted')

                    if overwrite:
                        row_text = row_text[:(ci)] + '…'
                        pad = 0

            # annot = f'x{round(line.bbox[0])} i{i} l{len(row_text) + pad} p{pad}'

            s = str(line)
            assert '\n' not in s, s
            # f"""<span class="annot" style="">{annot}</span>"""
            row_objs[len(row_text) + pad] = line
            row_text += pad_char * pad + s

            if len(row_text) > max_len:
                max_len = len(row_text)
            i += 1

        if isinstance(spacing, str):
            row_text += spacing  # line spacer

        # if len(row) > 500:
        #    print(el.page_num, el.index, 'long row', len(row), repr(row.strip()[:40]))
        #    row = row[:200]

        if not row_text.strip():
            empty_rows += 1
            if empty_rows > 5:
                continue
        else:
            empty_rows = 0

        rows.append(Row(row_text, row_objs, page=blocks[0].page))

    # print(blocks[0].page_num, 'max_x', round(max_x), 'max_len', max_len, 'spacing=', spacing)

    return rows
