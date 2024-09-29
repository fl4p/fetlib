import warnings
from typing import List, Dict

import pdfminer
import pymupdf
from pdfminer.layout import LAParams, LTTextBox, LTTextLine
from pdfminer.pdffont import PDFType1Font
from pdfminer.utils import get_bound, Rect

from test.dslib.pdf.fonts import EmbeddedPdfFont


class Word:
    def __init__(self, index, bbox, s):
        self.index = index
        self.bbox = bbox
        self.s = s

    def __repr__(self):
        return f"Word({tuple(map(round, self.bbox))}, {self.s})"

    def __str__(self):
        return self.s


def bbox_union(bbox1, bbox2):
    ref = get_bound([
        (bbox1[0], bbox1[1]),
        (bbox1[2], bbox1[3]),
        (bbox2[0], bbox2[1]),
        (bbox2[2], bbox2[3]),
    ])
    ret = (
        min(bbox1[0], bbox2[0]),
        min(bbox1[1], bbox2[1]),
        max(bbox1[2], bbox2[2]),
        max(bbox1[3], bbox2[3]),
    )
    assert ref == ret
    return ret


class Line:
    def __init__(self, index, words: List[Word]):
        self.index = index
        self.words = words
        self.bbox = get_bound(
            [(w.bbox[0], w.bbox[1]) for w in words]
            + [(w.bbox[2], w.bbox[3]) for w in words])

        self._dirty = False

    def __repr__(self):
        return f"Line({self.words})"

    def __str__(self):
        return ' '.join(map(str, self.words))

    def __iter__(self):
        return iter(self.words)

    def __iadd__(self, other):
        # assert other.bbox[0] >  self.bbox[2], (str(other), str(self))
        if other.bbox[0] < self.bbox[2]:
            self._dirty = True
        self.words += other.words
        self.bbox = bbox_union(self.bbox, other.bbox)
        return self

    def clean(self):
        if self._dirty:
            self.words.sort(key=lambda w: w.bbox[0])
            self._dirty = False


class Block:
    def __init__(self, page_num, block_num, bbox, lines: List[Line]):
        self.page_num = page_num
        self.index = block_num
        self.bbox: Rect = bbox
        self.lines = lines

    def __repr__(self):
        return f"Block({self.page_num}, {self.index}, {self.bbox}, {self.lines})"

    def __str__(self):
        return '\n'.join(map(str, self.lines))

    def __iter__(self):
        return iter(self.lines)

    def __iadd__(self, other: 'Block'):
        assert self.page_num == other.page_num
        self.bbox = bbox_union(self.bbox, other.bbox)
        self.lines += other.lines
        self._dirty = True
        return self

    def clean(self):
        pass


def pdf_blocks_pymupdf(pdf_path) -> List[Block]:
    all_blocks = []

    pdf = pymupdf.open(pdf_path)
    for pg in pdf.pages():
        tpg = pg.get_textpage()
        blocks = tpg.extractDICT()["blocks"]
        for block in blocks:
            all_blocks.append(block)

    return all_blocks


def pdf_blocks_pdfminer_six(pdf_path, laparams: LAParams, fonts: Dict[str, EmbeddedPdfFont]) -> List[Block]:
    fp = open(pdf_path, 'rb')
    from pdfminer.pdfinterp import PDFResourceManager
    rsrcmgr = PDFResourceManager()
    from pdfminer.converter import PDFPageAggregator
    device = PDFPageAggregator(rsrcmgr, laparams=laparams)
    from pdfminer.pdfinterp import PDFPageInterpreter
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    from pdfminer.pdfpage import PDFPage
    pages = PDFPage.get_pages(fp)

    # interpreter.fontmap

    blocks = []
    page_no = 0
    page_block_cnt = 0

    INF = pdfminer.utils.INF

    for page in pages:
        interpreter.process_page(page)

        fonts_enc = {f.fontname: f for f in interpreter.fontmap.values()}

        def decode_cid_char(cid, fontname):
            if fontname not in fonts_enc:
                raise ValueError(fontname)

            gn = ''
            u = 0
            font = fonts_enc[fontname]
            if isinstance(font, PDFType1Font):
                if hasattr(font, 'cid2glyph'):
                    glyph = font.cid2glyph[cid - 1]
                    gn = glyph.name
                    u = fonts[fontname].decode_name(glyph.name)
                    c = font.cid2unicode[u] # or just chr ?
                else:
                    print('font has no cid2glyph')
                    raise NotImplementedError()
            else:
                raise NotImplementedError()

            c = f'<span style="font-family:\'{ch.fontname}\'" data-cid={cid} data-u={u} data-gn="{gn}">{c.replace("<","&lt;")}</span>'

            return c
            # TODO render the CID with the given font, maybe find the name?
            # or use OCR to translate to unicode tech symbol? Ohm, mu , etc.
            # ref: https://www.helpandmanual.com/help/hm_working_pdf_cid.html

        layout = device.get_result()
        for lobj in layout:
            if isinstance(lobj, LTTextBox):

                lines: List[Line] = []

                for line in lobj:
                    line: LTTextLine
                    words: List[Word] = []
                    word_text = ''
                    word_pts = []

                    assert line._objs[-1].get_text() == '\n'
                    eol = False

                    for ch in line._objs:
                        c = ch.get_text()


                        if len(c) != 1:
                            # import pdfminer.converter
                            # see converter.py @ handle_undefined_char
                            #
                            assert c.startswith('(cid:') and c.endswith(')'), c
                            cid = int(c[5:-1])
                            c = decode_cid_char(cid, ch.fontname)

                        if c in {'\x02'}:  # infineon
                            c = '<\\x2>'

                        # assert len(c) == 1, repr(c)
                        assert c not in {'\t', '\r'}, "char is %s" % repr(c)
                        assert not c.isspace() or c in {' ', '\n'}, "char is %s" % repr(c)
                        if not (c.isprintable() or c.isspace()):
                            # print(repr(c), repr(line.get_text()), ch.fontname)
                            if ch.fontname and 'symbol' in ch.fontname.lower():
                                c = hex(ord(c)).replace('0x', '\\u')
                            else:
                                raise ValueError()

                        if c in {'\x02'}:
                            warnings.warn('char %s in %s' % (c, repr(line.get_text())))

                        if c == ' ' or c == '\n':
                            if c == '\n':
                                assert not eol
                                eol = True
                            if word_text:
                                words.append(Word((lobj.index, len(lines), len(words)), get_bound(word_pts), word_text))
                                word_text = ''
                                word_pts.clear()
                            else:
                                pass
                                # raise ValueError('empty word?')
                        else:
                            if ch.fontname == 'unknown':
                                print('warning', page.pageid, lobj.index, 'unknown font for char', c)

                            assert c.isprintable()
                            if max(ch.bbox) >= INF or min(ch.bbox) <= -INF:
                                print(c, 'has infinite bbox')
                            word_pts.append((ch.bbox[0], ch.bbox[1]))
                            word_pts.append((ch.bbox[2], ch.bbox[3]))
                            word_text += c
                    if words:
                        lines.append(Line((lobj.index, len(lines)), words))

                # TODO
                assert lobj.index == page_block_cnt
                blocks.append(Block(page_no, lobj.index, lobj.bbox, lines))
                page_block_cnt += 1

        page_no += 1
        page_block_cnt = 0

    return blocks


def vertical_sort(elements):
    """
    Sorts elements vertically by (y0,x0,index).


    :param elements:
    :return:
    """
    # elements = sorted(elements, key=lambda el: (el.index, round(el.bbox[1],1), round(el.bbox[0],1), el.index))  # sort blocks by bbox.y0
    elements.sort(key=lambda el: (
        -round(el.bbox[1], 0),  # top -> bottom
        el.bbox[0],  # left -> right
        el.index))  # sort blocks by bbox.y0


def vertical_merge(elements):
    """
    Merges elements with similar y0
    :param elements:
    :return:
    """
    m_el: Line = elements[0]
    y_max = elements[0].bbox[1]
    assert y_max > 0
    y_max += 100  # reg

    i = 1
    while i < len(elements):
        el = elements[i]
        dy = m_el.bbox[1] - el.bbox[1]
        if abs(dy) < y_max / 400:  # param: merge line threshold
            # same line
            m_el += elements.pop(i)
        else:
            m_el.clean()
            m_el = el
            i += 1
