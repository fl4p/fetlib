import re

# see https://symbl.cc/en/unicode-table/#latin-1-supplement


#re.compile('[^ -~]') # basis latin print
#re.compile('[^ -ɏ]') # latin suppl,exA,exB
no_print_latin = re.compile('[^ -~ -ɏ]')

def normalize_dash(s:str)->str:
    s = s.replace(' ', ' ')
    s = s.replace('‐', '-')  # utf8 b'\xe2\x80\x90'
    s = s.replace('‑', '-')  # utf8 b'\xe2\x80\x91'
    s = s.replace('−', '-')  # utf8 b'\xe2\x80\x92'
    s = s.replace('–', '-')  # utf8 b'\xe2\x80\x93'
    s = s.replace('—', '-')

    s = s.replace('', '-') # toshiba

    s = s.replace('ƒ', 'f')# datasheets/ti/CSD19531Q5A.pdf
    s = s.replace('“', '"')
    s = s.replace('”', '"')
    s = s.replace('’', '\'')

    # s = no_print_ascii.sub('', s)

    return s

def ocr_post_subs(s:str)->str:
    return ','.join(map(lambda s: s.strip(' /'), s.replace('{', '|').replace('/', '|').split('|')))
def strip_no_print_latin(s:str)->str:
    return no_print_latin.sub('', s)
