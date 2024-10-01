import unicodedata
import warnings
from collections import defaultdict
from typing import List, Dict, Sequence

import pdfminer
import pymupdf
from pdfminer.layout import LAParams, LTTextBox, LTTextLine, LTAnno, LTImage, LTCurve, LTChar, \
    LTTextLineHorizontal, LTLine
from pdfminer.pdffont import PDFType1Font, PDFCIDFont
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.utils import get_bound, Rect, Matrix, MATRIX_IDENTITY

from dslib.pdf.fonts import get_font_default_enc


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
    def __init__(self, page_num, block_num, bbox, lines: List[Line], page):
        self.page_num = page_num
        self.index = block_num
        self.bbox: Rect = bbox
        self.lines = lines
        self.page = page

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


def is_symbol_font(basefont: str, font: 'EmbeddedPdfFont', font_pdf: pdfminer.pdffont.PDFFont = None) -> bool:
    if 'Symbol' in basefont:
        return True

    if 'Wingdings' in basefont or 'Webdings' in basefont or 'Dingbats' in basefont or 'Emoji' in basefont:
        return True

    if font and font.gid2code:
        return True

    if 'Arial' in basefont:
        return False

    if 'EUDC' in basefont:
        return True

    return False


def remove_whitespaces(obj: object):
    try:
        iter(obj)
    except:
        return  # raise
    for sub in obj:
        remove_whitespaces(sub)


class PDFPageInterpreter_NOWS(PDFPageInterpreter):

    # TODO write test for this
    def render_contents(
            self,
            resources: Dict[object, object],
            streams: Sequence[object],
            ctm: Matrix = MATRIX_IDENTITY,
    ) -> None:
        r = super().render_contents(resources, streams, ctm)
        for obj in list(self.device.cur_item):
            if isinstance(obj, LTChar):
                c = obj.get_text()
                if c.isspace():
                    self.device.cur_item._objs.remove(obj)
            elif isinstance(obj, LTAnno):
                self.device.cur_item._objs.remove(obj)
        return r


def pdf_blocks_pdfminer_six(pdf_path, laparams: LAParams, fonts: Dict[str, 'EmbeddedPdfFont']) -> Dict[
    int, List[Block]]:
    fp = open(pdf_path, 'rb')
    from pdfminer.pdfinterp import PDFResourceManager
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.pdfpage import PDFPage

    rsrcmgr = PDFResourceManager()
    device = PDFPageAggregator(rsrcmgr, laparams=laparams)
    interpreter = PDFPageInterpreter_NOWS(rsrcmgr, device)
    pages = PDFPage.get_pages(fp)

    # interpreter.fontmap

    blocks = defaultdict(list)
    page_no = 0
    page_block_cnt = 0

    INF = pdfminer.utils.INF

    for page in pages:
        remove_whitespaces(page)
        interpreter.process_page(page)
        # print(page.pageid, page.cropbox, page.mediabox)

        fonts_enc = {f.fontname: f for f in interpreter.fontmap.values()}

        # TODO pdfminer how to access fonts, open discussion
        for fid, f in rsrcmgr._cached_fonts.items():
            if f.fontname not in fonts and hasattr(f, 'basefont') and f.basefont in fonts:
                fonts[f.fontname] = fonts[f.basefont]
            fonts_enc[f.fontname] = f

        def font_span(s, font_family, **kwargs):
            font_family = fonts[font_family].basefont if font_family in fonts else font_family
            data_attr = ' '.join(f'data-{k}="{v}"' for k, v in kwargs.items())
            return f'<span style="font-family:\'{font_family}\'" {data_attr}>{s.replace("<", "&lt;")}</span>'

        def decode_cid_char(cid, fontname):
            if fontname not in fonts_enc:
                raise ValueError(fontname)

            font = fonts_enc[fontname]
            if isinstance(font, PDFType1Font):
                if hasattr(font, 'cid2glyph'):
                    glyph = font.cid2glyph[cid - 1]
                    gn = glyph.name
                    u = fonts[fontname].decode_name(glyph.name)
                    # gid2code_2[5]
                    if u in font.cid2unicode:
                        c = font.cid2unicode[u]  # or just chr ?
                    else:
                        c = chr(u)
                        #c = fonts[fontname].gid2code_2[u] # TODO is this
                else:
                    print('font has no cid2glyph')
                    raise NotImplementedError()
            else:
                raise NotImplementedError(
                    "decoding_cid_char(%s) not implemented for this font type %s" % (cid, type(font)))

            return font_span(c, fontname, cid=cid, u=u, gn=gn)

            # TODO render the CID with the given font, maybe find the name?
            # or use OCR to translate to unicode tech symbol? Ohm, mu , etc.
            # ref: https://www.helpandmanual.com/help/hm_working_pdf_cid.html

        def _traverse(lobj):
            nonlocal page_block_cnt

            if isinstance(lobj, LTTextLineHorizontal):
                lobj = [lobj]

            if isinstance(lobj, (LTTextBox, list)):

                lines: List[Line] = []

                for line in lobj:
                    height = line.bbox[3] - line.bbox[1]
                    if height < 0.1:
                        return

                    line: LTTextLine
                    words: List[Word] = []
                    word_text = ''
                    word_pts = []

                    assert line._objs[-1].get_text() == '\n'
                    eol = False

                    for ch in line._objs:
                        c = ch.get_text()

                        if len(c) not in {1, 2}:
                            # import pdfminer.converter
                            # see converter.py @ handle_undefined_char
                            #
                            assert c.startswith('(cid:') and c.endswith(')'), (c, repr(line.get_text()))
                            cid = int(c[5:-1])
                            c = decode_cid_char(cid, ch.fontname)

                        if c in {'\x02'}:  # infineon
                            c = ' '  # <\\x2>' # TODO

                        # assert len(c) == 1, repr(c)
                        assert c not in {'\t', '\r'}, "char is %s" % repr(c)
                        assert not c.isspace() or c in {' ', '\n'}, "char is %s" % repr(c)

                        if not isinstance(ch, LTAnno) and ch.fontname not in fonts and get_font_default_enc(ch.fontname):
                            enc = get_font_default_enc(ch.fontname)
                            if enc:
                                u = enc.get(ord(c))
                                if u:
                                    c = chr(u)

                        elif not (c.isprintable() or c.isspace()):
                            # print(repr(c), repr(line.get_text()), ch.fontname)
                            if ch.fontname and is_symbol_font(ch.fontname, fonts[ch.fontname], fonts_enc[ch.fontname]):
                                # c = hex(ord(c)).replace('0x', '\\u')
                                if isinstance(fonts_enc[ch.fontname], PDFCIDFont):
                                    # TODO for some reason need to un-do the CID resolution
                                    u2cid = {v: k for k, v in fonts_enc[ch.fontname].unicode_map.cid2unichr.items()}
                                    c = chr(u2cid[c]) if u2cid[c] else c
                                c = c
                            else:
                                print('in line %r' % line.get_text())
                                raise ValueError('not printable %r (%d, 0x%02x, %s) with font %s' % (
                                    c, ord(c), ord(c), unicodedata.name(c, '?'), ch.fontname))

                        if c in {'\x02'}:
                            warnings.warn('char %s in %s' % (c, repr(line.get_text())))

                        if len(c) == 1 and not isinstance(ch, LTAnno):
                            if is_symbol_font(ch.fontname, fonts.get(ch.fontname), fonts_enc.get(ch.fontname)):
                                c = font_span(c, ch.fontname)

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

                            # assert c.isprintable()
                            if max(ch.bbox) >= INF or min(ch.bbox) <= -INF:
                                print(c, 'has infinite bbox')
                            word_pts.append((ch.bbox[0], ch.bbox[1]))
                            word_pts.append((ch.bbox[2], ch.bbox[3]))
                            word_text += c
                    if words:
                        lines.append(Line((lobj.index, len(lines)), words))

                # TODO
                # assert lobj.index == page_block_cnt
                if len(lines):
                    if isinstance(lobj, list):
                        assert len(lobj) == 1
                        # raise NotImplementedError()
                        blocks[page_no].append(Block(page, 9999, lobj[0].bbox, lines, page))
                    else:
                        blocks[page_no].append(Block(page, lobj.index, lobj.bbox, lines, page))
                page_block_cnt += 1
            elif isinstance(lobj, LTImage):
                pass
            elif isinstance(lobj, LTCurve):  # LTRect, LTLine
                pass
            else:
                if isinstance(lobj, LTChar):
                    raise "should not happe"
                for sub in lobj:
                    _traverse(sub)

        layout = device.get_result()
        _traverse(layout)

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


def vertical_merge(elements, ):
    """
    TODO pdfminer: where does it split lines across x-axis?

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
        h = min(m_el.bbox[3]-m_el.bbox[1],el.bbox [3]- el.bbox[1])
        if abs(dy) < h/10: #y_max / 600:  # param: merge line threshold
            # same line
            m_el += elements.pop(i)
        else:
            m_el.clean()
            m_el = el
            i += 1
