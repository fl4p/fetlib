import re
import unicodedata
import warnings

import unidecode

"""

Unicode normalization
see https://unicode.org/reports/tr15/#Normalization_Forms_Table
we want NFKD, as we usually deal with english and a couple of greeks (omega)

unicode table: find a symbol (hex(ord('‐')))
https://symbl.cc/en/unicode-table/#latin-1-supplement
https://github.com/jsvine/pdfplumber?tab=readme-ov-file#loading-a-pdf

"""

no_print_latin_greek = re.compile('[^\s'
                                  ' -~'  # latin
                                  ' -Ͽ'  # .. greek
                                  '℀-⏿'  # letterlike, num, math, .. misc tech
                                  ']')
hyphens = re.compile('[\u2010-\u2015]')  # HYPHEN-HORIZONTAL BAR
# single_quotes = re.compile('[\u2018-\u201B]')
_whitespaces = re.compile('\s+', re.MULTILINE)

CONTROL = re.compile("[\x00-\x08\x0b-\x0c\x0e-\x1f]")


def patch_unidecode():
    preserve = '°μ§\u03a9'  # '\u03a9'='Ω'=greek letter
    unidecode.unidecode(preserve)  # load the tables
    for c in preserve:
        codepoint = ord(c)
        section = codepoint >> 8
        position = codepoint % 256
        chars = list(unidecode.Cache[section])
        chars[position] = c
        unidecode.Cache[section] = tuple(chars)


patch_unidecode()


def normalize_text(s: str):
    s = custom_subs(s)
    s = unicodedata.normalize('NFKD', s)  # Ω->Ω
    s = unidecode.unidecode(s, errors='preserve')  # Ω->O, ’->', ƒ->f
    s = strip_no_print_latin(s)
    return s


horizontal_whitespace = re.compile(r'[^\S\r\n]')

def custom_subs(s: str):
    assert isinstance(s, str), (type(s), s)

    s = hyphens.sub('-', s)  # vs unidecode '\u2015'->'--'

    s = s.replace('\r\n', '\n')
    s = s.replace('\r', '\n')
    s = horizontal_whitespace.sub(' ', s)

    s = s.replace('\x04', '\x03')
    s = s.replace('\0x03', '\x03') # toshiba ETX = end of text
    s = s.replace('\0x04', '\x03')  # utf8 b'\xe2\x80\x93' toshiba # 0x04=END OF TRANSMISSION
    #s = s.replace('\x03', '-')  # should not replace with minus, as it can be confusd with a num sign!

    s = s.replace('', '-')  # toshiba
    s = s.replace('', 'Ω')  # infineon
    s = s.replace('', 'μ') # littlefuse 'IXFX360N15T2'
    s = s.replace('•', '*') # littlefuse 'IXFX360N15T2'
    return s


#@deprecated.deprecated
def normalize_dash(s: str) -> str:
    warnings.warn("deprecated")

    s = s.replace(' ', ' ')
    s = s.replace('‐', '-')  # utf8 b'\xe2\x80\x90'
    s = s.replace('‑', '-')  # utf8 b'\xe2\x80\x91'
    s = s.replace('−', '-')  # utf8 b'\xe2\x80\x92'
    s = s.replace('–', '-')  # utf8 b'\xe2\x80\x93'
    s = s.replace('—', '-')

    s = s.replace('', '-')  # toshiba

    s = s.replace('ƒ', 'f')  # datasheets/ti/CSD19531Q5A.pdf
    s = s.replace('“', '"')
    s = s.replace('”', '"')
    s = s.replace('’', '\'')

    # s = no_print_ascii.sub('', s)

    return s


def ocr_post_subs(s: str) -> str:
    s = s.replace('{', '|').replace('/', '|')
    s = ','.join(map(lambda s: s.strip(' /'), s.split('|')))
    s = ','.join(map(ocr_strip_string, s.split(',')))
    return s

def ocr_strip_string(s):
    return s.strip(' /|_{}\'";=')


def strip_no_print_latin(s: str) -> str:
    return no_print_latin_greek.sub('', s)


def whitespaces_to_space(s: str) -> str:
    return _whitespaces.sub(' ', s)


def whitespaces_remove(s: str) -> str:
    return _whitespaces.sub('', s)
