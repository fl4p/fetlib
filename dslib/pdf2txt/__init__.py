def normalize_dash(s):
    s = s.replace('‐', '-')  # utf8 b'\xe2\x80\x90'
    s = s.replace('‑', '-')  # utf8 b'\xe2\x80\x91'
    s = s.replace('−', '-')  # utf8 b'\xe2\x80\x92'
    s = s.replace('–', '-')  # utf8 b'\xe2\x80\x93'
    s = s.replace('—', '-')

    s = s.replace('', '-')

    s = s.replace('ƒ', 'f')# datasheets/ti/CSD19531Q5A.pdf
    return s
