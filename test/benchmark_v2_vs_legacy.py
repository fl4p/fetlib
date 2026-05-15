import dslib.v2
import dslib.pdf.parse
from test_v2_pdf_parse import SAMPLES




for f,ref,rtol in SAMPLES:

    a = dslib.v2.parse_datasheet('../'+f)
    b = dslib.pdf.parse.parse_datasheet('../'+f)

    if a.show_diff(b):
        print('ref=', ref)

