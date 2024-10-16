import unicodedata
import warnings
from collections import defaultdict
from typing import List, Dict, Sequence, Iterable, Tuple, Union, Literal

import pdfminer
import pymupdf
from pdfminer.layout import LAParams, LTTextBox, LTTextLine, LTAnno, LTImage, LTCurve, LTChar, \
    LTTextLineHorizontal, LTPage, LTFigure
from pdfminer.pdffont import PDFType1Font, PDFCIDFont
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.utils import get_bound, Matrix, MATRIX_IDENTITY

from dslib.pdf.fonts import get_font_default_enc, is_symbol_font, EmbeddedPdfFont


def bbox_union(bbox1, bbox2=None) -> 'Bbox':
    if bbox2 is None:
        return bbox_union_list(bbox1)

    ret = (
        min(bbox1[0], bbox2[0]),
        min(bbox1[1], bbox2[1]),
        max(bbox1[2], bbox2[2]),
        max(bbox1[3], bbox2[3]),
    )
    return Bbox(ret)


def bbox_union_list(bbox: Iterable[tuple]) -> 'Bbox':
    assert isinstance(bbox, list)
    ret = (
        min(b[0] for b in bbox),
        min(b[1] for b in bbox),
        max(b[2] for b in bbox),
        max(b[3] for b in bbox),
    )
    return Bbox(ret)


def has_custom_embed_enc(c, fontname, fonts_enc):
    if (fontname in fonts_enc) and hasattr(fonts_enc[fontname], 'cid2glyph') and fonts_enc[fontname].cid2glyph:
        u = ord(c)
        m = fonts_enc[fontname].cid2glyph
        if u < len(m) and m[u] != u:
            return True
    return False


class Bbox():

    def __repr__(self):
        r2 = lambda x : round(x, 2)
        return f'Bbox({r2(self.x1)},{r2(self.y1)},{r2(self.x2)},{r2(self.y2)})'
    def __init__(self, x1: Union[float, Tuple[float, float, float, float], List[float], 'Bbox'], y1: float = None,
                 x2: float = None, y2: float = None):

        if isinstance(x1, (tuple, list)):
            assert y1 is None and y2 is None and x2 is None
            self.__init__(*x1)
            return

        if isinstance(x1, (Bbox)):
            self.__init__(*x1.t)
            return

        self.x1 = x1
        self.y1: float = y1
        self.x2: float = x2
        self.y2: float = y2
        self.t = (self.x1, self.y1, self.x2, self.y2)
        self.area = self.width * self.height

    def __getitem__(self, item):
        if isinstance(item, str) and item in {'x1', 'y1', 'x2', 'y2'}:
            return self.__dict__[item]
        assert isinstance(item, int), repr(item)
        return (self.x1, self.y1, self.x2, self.y2)[item]

    @property
    def width(self):
        return self.x2 - self.x1

    @property
    def height(self):
        return self.y2 - self.y1

    def __bool__(self):
        return self.width > 0 or self.height > 0

    def h_overlap(self, b2):
        # TODO simplify
        if b2[0] <= self[2] and self[0] <= b2[2]:
            return min(abs(self[0] - b2[2]), abs(self[2] - b2[0]))
        else:
            return 0

    def v_overlap(self, b2):
        # TODO simplify
        if b2[1] <= self[3] and self[1] <= b2[3]:
            return min(abs(self[1] - b2[3]), abs(self[3] - b2[1]))
        else:
            return 0.

    def w_min(b1, b2):
        return min(b1[2] - b1[0], b2[2] - b2[0])

    def h_overlap_rel(b1, b2):
        w = b1.w_min(b2)
        if w == 0:
            return 0
        return b1.h_overlap(b2) / w

    def union(self, bbox):
        return bbox_union(self, bbox)

    def pad(self, left: float, right: float, top: float, bottom: float):
        return Bbox(self.x1 - left, self.y1 - bottom, self.x2 + right, self.y2 + top)

    def overlap_area(self, cell):
        return self.h_overlap(cell) * self.v_overlap(cell)

    def v_overlap_rel(b1, b2):
        h = min(b1.height, b2.height)
        return b1.v_overlap(b2) / h if h else 0

    def __eq__(self, other):
        assert isinstance(other, Bbox)
        return self.t == other.t

    def __hash__(self):
        return hash(self.t)


class Char:

    def __init__(self, c: str, fontname):
        self.c = c
        self.fontname = fontname
        self.cid = 0
        self.gn = None  # glyph name
        self.u = None  # unicode
        self.span_font = None  # need a font for display (CID and fonts with custom enc and diff enc)

    def decode(self, line, fonts: Dict[str, 'EmbeddedPdfFont'], fonts_enc):
        c = self.c

        if 2 <= len(c) <= 3 and ('fi' in c or 'ff' in c):
            # for some reason, pdfminer occasionally bundles 'ffi' or 'fi' into single chars?
            # EPC2021.pdf
            return c

        if len(c) not in {1, 2}:
            # import pdfminer.converter
            # see converter.py @ handle_undefined_char
            #

            assert c.startswith('(cid:') and c.endswith(')'), (c, repr(line.get_text()))
            cid = int(c[5:-1])
            assert cid > 0
            self.cid = cid
            c = self.decode_cid_char(cid, fonts, fonts_enc)  # this can update.self.fontname
            # now we should use a font span

        fontname = self.fontname  # decode_cid_char() can unset fontname
        font_custom_enc = has_custom_embed_enc(c, fontname, fonts_enc)

        if not font_custom_enc and try_decode_to_unicode(c, fontname):
            c = try_decode_to_unicode(c, fontname)
            self.fontname = None
            self.span_font = None

        else:

            if fontname and '+Z' in fontname:
                self.span_font = fontname
                # assert e

            if c in {'\x02', '\x00'}:  # infineon
                c = ' '  # <\\x2>' # TODO

            if not (c.isprintable() or c.isspace()):
                if fontname and is_symbol_font(fontname, fonts[fontname], fonts_enc[fontname]):
                    # c = hex(ord(c)).replace('0x', '\\u')
                    if isinstance(fonts_enc[fontname], PDFCIDFont):
                        # TODO for some reason need to un-do the CID resolution
                        u2cid = {v: k for k, v in fonts_enc[fontname].unicode_map.cid2unichr.items()}
                        c = chr(u2cid[c]) if u2cid[c] else c
                    c = c
                else:
                    print('in line %r' % line.get_text())
                    # raise ValueError('not printable %r (%d, 0x%02x, %s) with font %s in line %r' % (
                    #    c, ord(c), ord(c), unicodedata.name(c, '?'), fontname, line.get_text()))

        # assert len(c) == 1, repr(c)
        assert c not in {'\t', '\r'}, "char is %s" % repr(c)
        assert not c.isspace() or c in {' ', '\n', '\xa0'}, "char is space %r %s within %r" % (
            c, unicodedata.name(c, '?'), line.get_text())

        if c in {'\x02'}:
            warnings.warn('char %s in %s' % (c, repr(line.get_text())))

        return c

    def decode_cid_char(self, cid, fonts, fonts_enc):
        fontname = self.fontname

        if fontname not in fonts_enc:
            raise ValueError(fontname)

        font = fonts_enc[fontname]
        if isinstance(font, PDFType1Font):
            if hasattr(font, 'cid2glyph'):
                glyph = font.cid2glyph[cid - 1]
                self.gn = glyph.name
                u = fonts[fontname].decode_name(glyph.name)
                self.u = u
                # gid2code_2[5]
                if u in font.cid2unicode:
                    c = font.cid2unicode[u]  # or just chr ?
                else:
                    c = chr(u)
                    # c = fonts[fontname].gid2code_2[u] # TODO is this
            elif cid < 256 and chr(cid).isprintable():
                c = chr(cid)
            else:
                print('font has no cid2glyph')
                raise NotImplementedError()
        elif isinstance(font, PDFCIDFont) and font.unicode_map:
            c = font.unicode_map.cid2unichr[cid]
        else:
            if cid <= 20:
                warnings.warn('char %s in %s' % (cid, fontname))
                c = chr(cid)
            else:
                warnings.warn(
                    "decode_cid_char(%s) not implemented for this font %s type %s" % (cid, fontname, type(font)))
                c = chr(cid)

        uc = not has_custom_embed_enc(c, fontname, fonts_enc) and try_decode_to_unicode(c, fontname)
        if uc:
            # yay this way we dont need that font for displays !
            self.fontname = None
            return uc

        if is_symbol_font(fontname, fonts[fontname], fonts_enc):
            self.span_font = fonts[fontname].basefont if fontname in fonts else fontname

        return c

    def html_span(self, c):
        assert self.span_font
        kwargs = dict(cid=self.cid, u=self.u, gn=self.gn)
        data_attr = ' '.join(f'data-{k}="{v}"' for k, v in kwargs.items() if v is not None)
        return f'<span style="font-family:\'{self.span_font}\'" {data_attr}>{c.replace("<", "&lt;")}</span>'

    def get(self):
        return self.c


class Word:
    Delimiter = ' '

    def __init__(self, index, bbox, s: str):
        self.index = index
        self.bbox = Bbox(bbox)
        self.s = s
        self.line_offset = 0

    def __repr__(self):
        round2 = lambda x: round(x, 1)
        return f"Word({self.index},{tuple(map(round2, self.bbox.t))},{repr(self.s)})"

    def __str__(self):
        return self.s

    @property
    def mean_char_width(self):
        return round(self.bbox.width / len(self.s), 2)


class Line:
    def __init__(self, index, words: List[Word]):
        self.index = index
        self.words = words
        self.bbox = get_bound(
            [(w.bbox[0], w.bbox[1]) for w in words]
            + [(w.bbox[2], w.bbox[3]) for w in words])

        self._dirty = False

    def __repr__(self):
        return f"Line({self.index},{self.words})"

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


class Block():
    def __init__(self, index: int, bbox, page: 'Page'):
        self.index = index
        self.bbox = Bbox(bbox)
        self.page = page


class GraphicBlock(Block):
    def __init__(self, index, bbox, page: 'Page', type: Literal['vector', 'image']):
        super().__init__(index, bbox, page)
        self.type = type
        self.text = None


class TextBlock(Block):
    def __init__(self, block_num: int, bbox, lines: List[Line], page: 'Page'):
        super().__init__(block_num, bbox, page)
        self.lines = lines

    def __repr__(self):
        return f"Block({self.page.page_num}, {self.index}, {self.bbox}, {self.lines})"

    def __str__(self):
        return '\n'.join(map(str, self.lines))

    def __iter__(self):
        return iter(self.lines)

    def __iadd__(self, other: 'TextBlock'):
        assert self.page_num == other.page_num
        self.bbox = bbox_union(self.bbox, other.bbox)
        self.lines += other.lines
        self._dirty = True
        return self

    def clean(self):
        pass


class Page():
    def __init__(self, page_num, mediabox, cropbox):
        self.page_num = page_num
        # self.blocks = blocks
        self.mediabox = Bbox(mediabox)
        self.cropbox = Bbox(cropbox)

    @property
    def bbox(self) -> Bbox:
        return self.cropbox or self.mediabox


def pdf_blocks_pymupdf(pdf_path) -> List[TextBlock]:
    # pymupdf has no control over block/line/word agg params
    all_blocks = []

    pdf = pymupdf.open(pdf_path)
    for pg in pdf.pages():
        tpg = pg.get_textpage()
        blocks = tpg.extractDICT()["blocks"]
        for block in blocks:
            all_blocks.append(block)

    return all_blocks


class PDFPageInterpreter_NO_WS(PDFPageInterpreter):

    # TODO write test for this
    # noinspection PyUnresolvedReferences
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


def try_decode_to_unicode(c, fontname):
    if fontname is None:
        return None
    enc = get_font_default_enc(fontname)
    if enc:
        o = ord(c)
        u = enc.get(o)
        if u:
            return chr(u)
        elif ord(c) > 0xf000:
            u = enc.get(o - 0xf000)
            if u:
                return chr(u)


def pdf_blocks_pdfminer_six(pdf_path, laparams: LAParams, fonts: Dict[str, 'EmbeddedPdfFont'], html_spans=False,
                            other_visuals=False) -> \
        Dict[int, List[TextBlock]]:
    fp = open(pdf_path, 'rb')
    from pdfminer.pdfinterp import PDFResourceManager
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.pdfpage import PDFPage

    rsrcmgr = PDFResourceManager()
    device = PDFPageAggregator(rsrcmgr, laparams=laparams)
    interpreter = PDFPageInterpreter_NO_WS(rsrcmgr, device)
    pages = PDFPage.get_pages(fp)

    blocks = defaultdict(list)
    page_no = 0
    page_block_cnt = 0

    inf_ = pdfminer.utils.INF

    for page in pages:
        pg = Page(page_no, page.mediabox, page.cropbox)

        interpreter.process_page(page)
        # print(page.pageid, page.cropbox, page.mediabox)

        fonts_enc = {f.fontname: f for f in interpreter.fontmap.values()}

        # TODO pdfminer how to access fonts, open discussion
        for fid, f in rsrcmgr._cached_fonts.items():
            # noinspection PyUnresolvedReferences
            if f.fontname not in fonts and hasattr(f, 'basefont') and f.basefont in fonts:
                fonts[f.fontname] = fonts[f.basefont]
            fonts_enc[f.fontname] = f

        def _traverse(lobj):
            nonlocal page_block_cnt

            if isinstance(lobj, LTTextLineHorizontal):
                lobj = [lobj]

            if isinstance(lobj, (LTTextBox, list)):

                lines: List[Line] = []

                for line in lobj:
                    height = line.bbox[3] - line.bbox[1]
                    if height < 0.1:  # invisible lines
                        return

                    line: LTTextLine
                    words: List[Word] = []
                    word_text = ''
                    word_pts = []

                    assert line._objs[-1].get_text() == '\n'
                    eol = False

                    for ch in line._objs:
                        c = ch.get_text()

                        if not isinstance(ch, LTAnno):
                            char = Char(c, ch.fontname)
                            c = char.decode(line, fonts, fonts_enc)

                            if html_spans and char.span_font:
                                c = char.html_span(c)

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

                        else:
                            if ch.fontname == 'unknown':
                                print('warning', page.pageid, lobj.index, 'unknown font for char', c)

                            # assert c.isprintable()
                            if max(ch.bbox) >= inf_ or min(ch.bbox) <= -inf_:
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
                        blocks[page_no].append(TextBlock(9999, lobj[0].bbox, lines, pg))
                    else:
                        blocks[page_no].append(TextBlock(lobj.index, lobj.bbox, lines, pg))
                page_block_cnt += 1
            elif isinstance(lobj, LTImage):
                if other_visuals:
                    blocks[page_no].append(GraphicBlock(0, lobj.bbox, pg, 'image'))

            elif isinstance(lobj, LTCurve):  # LTRect, LTLine
                if other_visuals:
                    blocks[page_no].append(GraphicBlock(0, lobj.bbox, pg, 'vector'))
            else:
                assert not isinstance(lobj, LTChar)

                # iterables that dont matter for spatial queries:
                assert isinstance(lobj, (LTPage, LTFigure)), repr(lobj)

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
    if not elements:
        return

    m_el: Line = elements[0]
    y_max = elements[0].bbox[1]
    assert y_max > 0
    y_max += 100  # reg

    i = 1
    while i < len(elements):
        el = elements[i]
        assert el.bbox[1] < el.bbox[3]
        dy = min(m_el.bbox[1] - el.bbox[1], m_el.bbox[3] - el.bbox[3])
        h = min(m_el.bbox[3] - m_el.bbox[1], el.bbox[3] - el.bbox[1])
        if abs(dy / h) < 0.25:  # y_max / 600:  # param: merge line threshold
            # same line
            m_el += elements.pop(i)
        else:
            m_el.clean()
            m_el = el
            i += 1
