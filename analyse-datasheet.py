import asyncio
import os.path

from discover_parts import discover_mosfets
from dslib.fetch import fetch_datasheet
from dslib.pdf2txt.parse import extract_text
from dslib.spec_models import DcDcSpecs



async def main():

    ds_path = 'datasheets/nxp/PSMN3R3-80BS,118.pdf'
    ds_path = 'datasheets/toshiba/TK46E08N1.pdf' # column wise text

    print('Analysing', ds_path)
    text = extract_text(ds_path)

    print('Extracted', len(text), 'characters of text')

    print(text)




asyncio.run(main())