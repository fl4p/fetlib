import pathlib
import subprocess
import traceback
import unicodedata
from io import BytesIO
from typing import Mapping, Optional, Any, List, Dict

import pymupdf
from pdfminer.cmapdb import UnicodeMap, CMapParser, FileUnicodeMap
from pdfminer.encodingdb import EncodingDB
from pdfminer.pdffont import PDFSimpleFont, PDFFont, FontWidthDict, LITERAL_STANDARD_ENCODING, CFFFont
from pdfminer.pdftypes import stream_value, list_value, resolve1
from pdfminer.psparser import literal_name

from dslib.cache import mem_cache, disk_cache


def pdfminer_fix_custom_glyphs_encoding_monkeypatch():
    def PDFSimpleFont__init__2(
            self,
            descriptor: Mapping[str, Any],
            widths: FontWidthDict,
            spec: Mapping[str, Any],
    ) -> None:
        # Font encoding is specified either by a name of
        # built-in encoding or a dictionary that describes
        # the differences.
        if "Encoding" in spec:
            encoding = resolve1(spec["Encoding"])
        else:
            encoding = LITERAL_STANDARD_ENCODING
        if isinstance(encoding, dict):
            name = literal_name(encoding.get("BaseEncoding", LITERAL_STANDARD_ENCODING))
            diff = list_value(encoding.get("Differences", []))
            self.cid2glyph = diff # this is want we need
            self.cid2unicode = EncodingDB.get_encoding(name, diff)
        else:
            self.cid2unicode = EncodingDB.get_encoding(literal_name(encoding))
        self.unicode_map: Optional[UnicodeMap] = None
        if "ToUnicode" in spec:
            strm = stream_value(spec["ToUnicode"])
            self.unicode_map = FileUnicodeMap()
            CMapParser(self.unicode_map, BytesIO(strm.get_data())).run()
        PDFFont.__init__(self, descriptor, widths)
        return

    PDFSimpleFont.__init__ = PDFSimpleFont__init__2

    #import pdfminer.encodingdb
    #_name2unicode = pdfminer.encodingdb.name2unicode

    #def name2unicode_new(s):
    #    return _name2unicode(s)


def convert_cff(in_path, out_path):
    cmd = ["/Volumes/FontForge/FontForge.app/Contents/Resources/opt/local/bin/fontforge",
           "-lang=ff", "-c", "Open($1); Generate($2)", in_path, out_path]
    print(' '.join(cmd))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


@mem_cache(ttl='5min')
def unicode_names():
    return {unicodedata.name(chr(i), '').upper(): i for i in range(2 ** 16)}


@mem_cache(ttl='5min')
@disk_cache(ttl='99d')
def find_good_unicodes_for_name(name) -> List[int]:
    try:
        return [ord(unicodedata.lookup(name))]
    except LookupError:
        from difflib import SequenceMatcher
        def similar(a, b):
            return SequenceMatcher(None, a.replace(' ', ''), b).ratio()

        print('looking for a good unicode name match for', repr(name), '..')

        name = name.upper().replace(' ', '')
        names_ration = dict()
        for n, u in unicode_names().items():
            r = similar(n, name)
            if r > 0.66:
                names_ration[n] = r

        ranked = sorted(names_ration.items(), key=lambda x: x[1], reverse=True)
        print('found unicode', ranked[0], 'for', name)
        unames = unicode_names()
        return list(unames[r[0]] for r in ranked)


class EmbeddedPdfFont():
    def __init__(self, xref, ext, typ, basefont, name, enc):
        self.xref = xref
        self.ext = ext
        self.typ = typ
        self.basefont = basefont
        self.name = name
        self.enc = enc

        self.name2gid = {}
        self.gid2code = {}

        self.gid2code_2 = {}
        self.name2code_2 = {}

    @property
    def path(self):
        assert self.ext != 'n/a', 'this font is not extractable'
        return self.basefont + '.' + self.ext

    def css_import(self):
        css_formats = dict(ttf='truetype', cff='opentype', otf='opentype')
        return f" @font-face {{ font-family: '{self.basefont}'; src: url('{self.path}') format('{css_formats[self.ext]}'); }}\n"

    def decode_name(self, glyph_name):
        u = self.name2code_2[glyph_name]
        return u
        gid = self.name2gid[glyph_name]
        c = self.gid2code[gid]
        return c

    def probe_font(font):

        if font.ext == 'cff':
            with open(font.path, 'rb') as f:
                cff = CFFFont(font.basefont, f)
                assert cff
                font.name2gid = {name.decode('utf-8') if isinstance(name, bytes) else name: gid for name, gid in cff.name2gid.items()}
                font.gid2code = dict(cff.gid2code)
        try:
            from fontTools import ttLib
            tt = ttLib.TTFont(font.path, checkChecksums=2, lazy=False)
            tt.getGlyphOrder()
            tt.save(font.path)
            tt.close()
        except Exception as e:
            print(font, 'probing font file failed', e, '; trying to convert the file to .otf ...')
            try:
                converted_path = font.basefont + '.otf'  # .otf= opentype(CFF)
                convert_cff(in_path=font.path, out_path=converted_path)
                assert os.path.isfile(converted_path)

                from fontTools import ttLib
                tt = ttLib.TTFont(converted_path, checkChecksums=2, lazy=False)
                best_cmap_inv = dict(((i[1], i[0]) for i in tt.getBestCmap().items()))

                for t in tt.get('cmap').tables:
                    tv = set(t.cmap.values())
                    tk = set(t.cmap.keys())
                    for gn in tt.getGlyphOrder():
                        if gn in tv or gn == '.notdef':
                            continue
                        u = EmbeddedPdfFont.glyph_unicode(tk, gn, best_cmap_inv)

                        if t.format == 0 and u > 255:
                            # ascii
                            continue

                        if u != 0:
                            t.cmap[u] = gn
                            print(font, 'add cmap for glyph %s#%d at code point %u (0x%02x) [%s] %s' % (
                                repr(gn), tt.getGlyphID(gn), u, u, unicodedata.name(chr(u)), repr(chr(u))))

                        else:
                            print(font, 'cant find unicode for glyph name %s' % repr(gn))

                    for u, gn in t.cmap.items():
                        gi = tt.getGlyphID(gn)
                        # https://github.com/fonttools/fonttools/blob/0c38f86da9d440ee1ebfc80d7d0660c14b668a09/Doc/source/ttLib/tables/_c_i_d_g.rst#L4
                        # need cidg table or gcid
                        # https://github.com/fonttools/fonttools/blob/0c38f86da9d440ee1ebfc80d7d0660c14b668a09/Lib/fontTools/ttLib/tables/C_F_F_.py#L21
                        # tt.tables.get('CFF ').haveGlyphNames() == False > CID-keyed font
                        # https://fontforge.org/docs/ui/mainviews/fontview.html#fontview-cid
                        # https://fontforge.org/docs/ui/menus/cidmenu.html
                        # in ttLib GID == CID: https://github.com/fonttools/fonttools/discussions/2720
                        # https://github.com/adobe-type-tools/afdko/
                        font.gid2code_2[gi] = u
                        font.name2code_2[gn] = u

                print(font, 'conversion successful', converted_path, len(tt.getGlyphNames()), 'glyphs', tt.getGlyphNames()[:5])
                tt.save(converted_path)
                tt.close()
                font.ext = 'otf'
            except:
                print(traceback.format_exc())
                os.remove(font.path)

    def __str__(self):
        return f'{self.basefont} {self.ext} {self.typ} {self.name} {self.enc}'

    @staticmethod
    def glyph_unicode(table_keys, glyph_name: str, best_cmap_inv: Dict[str, int]):
        if glyph_name[0] == 'C' and glyph_name[1:].isnumeric():
            u = int(glyph_name[1:], 10)
            assert u not in table_keys
            return u

        if glyph_name in best_cmap_inv:
            u = best_cmap_inv[glyph_name]
            assert u not in table_keys
            return u

        for u in find_good_unicodes_for_name(glyph_name):
            if u not in table_keys:
                return u

        print('cant find unicode for glyph name %s' % repr(glyph_name))
        return 0


class PdfFonts():
    def css(self):
        css = ''
        for font in self.fonts:
            css += font.css_import()
        return css

    def cid_map(self):
        cid_map = {}
        for font in self.fonts:
            cid_map[font.name] = font.cid2unicode
            cid_map[font.basefont] = cid_map[font.name]
        return cid_map

    def __init__(self, pdf_path, force_extraction=False):

        self.cid2unicode = {}

        # see https://pymupdf.readthedocs.io/en/latest/vars.html#fontextensions
        # adn https://pymupdf.readthedocs.io/en/latest/document.html#Document.get_page_fonts
        # https://stackoverflow.com/questions/13511554/using-a-cff-type1c-type2-font-in-java
        " CFF uses to perfectly convert cubic Bezier curves (used in Type2)"
        # https://stackoverflow.com/questions/32796220/how-to-convert-otf-to-ttf-with-postscript-outlines-using-fontforge-scripting
        # https://stackoverflow.com/questions/33413632/extracting-text-from-a-pdf-with-cid-fonts

        pdf = pymupdf.open(pdf_path)
        emb_fonts = sorted(set(sum((pdf.get_page_fonts(pno) for pno in range(len(pdf))), [])))


        font_objs = []
        for (xref, ext, typ, basefont, name_, enc) in emb_fonts:
            if '/' in ext:
                # https://pymupdf.readthedocs.io/en/latest/vars.html#fontextensions
                print('not extractable font', xref, ext, typ, basefont, name_)
                continue

            font = EmbeddedPdfFont(xref, ext, typ, basefont, name_, enc)

            if not os.path.isfile(font.path) or force_extraction:
                extr = pdf.extract_font(xref)
                pathlib.Path(font.path).write_bytes(extr[3])

            font.probe_font()
            font_objs.append(font)

        self.fonts = font_objs
