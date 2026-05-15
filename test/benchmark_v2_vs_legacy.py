import dslib.v2
import dslib.pdf.parse
from test_v2_pdf_parse import SAMPLES




for f,ref,rtol in SAMPLES:

    dslib.v2.parse_datasheet('../'+f)
    dslib.pdf.parse.parse_datasheet('../'+f)

