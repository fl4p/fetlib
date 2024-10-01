import re
import unicodedata

import unidecode

from dslib.pdf2txt import strip_no_print_latin, normalize_dash, normalize_text, patch_unidecode


def test_strip_no_print_latin():
    assert strip_no_print_latin("\n \t") == "\n \t"


    ohm = "\u2126" # u2126'OHM SIGN', unidecode to 'ohm'
    assert unicodedata.normalize("NFKD", ohm) != ohm

    omega = unicodedata.normalize("NFKD", ohm)
    assert omega == 'Ω' # u03a9'GREEK CAPITAL LETTER OMEGA', unidecode() = 'O'
    assert unicodedata.normalize("NFKD", omega) == omega

    assert strip_no_print_latin(omega) == omega
    assert strip_no_print_latin(ohm) == ohm


    assert unicodedata.normalize("NFKD", 'ƒ') == 'ƒ'
    assert strip_no_print_latin('ƒ')

    assert unidecode.unidecode(omega, errors='preserve') == omega # patched !
    assert unidecode.unidecode(ohm, errors='preserve') == 'ohm'

    assert unicodedata.normalize("NFKD", 'μ') == 'μ' # 'GREEK SMALL LETTER MU'
    assert strip_no_print_latin('μ') == 'μ'
    assert unidecode.unidecode('μ', errors='preserve') == 'μ'

    assert strip_no_print_latin('≈') == '≈'


def test_unidecode():
    # assert unidecode.unidecode('°') == 'deg'
    patch_unidecode()
    assert unidecode.unidecode('°') == '°'
    assert unidecode.unidecode('≈') == '≈'

def test_normalize_dash_and_new():
    s = '°!"§$%&/())))=?`*\'_:;'
    s += 'ƒ‐ ‑ − – —'
    s += '-+\s=≈/a-z0-9.,;:μΩ°(){}"\'<>'
    assert normalize_dash(s) == normalize_text(s)

def test_normalize_text():
    s = '≈μ°'
    assert normalize_text(s) == s