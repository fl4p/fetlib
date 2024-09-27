import os

import pix2text
from pix2text import Pix2Text
from pix2text.element import Element
from pix2text.layout_parser import ElementType

# see https://stackoverflow.com/questions/72416726/how-to-move-pytorch-model-to-gpu-on-apple-m1-chips
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'
p2t = Pix2Text.from_config()

doc = p2t.recognize_pdf(
    #'../datasheets/_samples/BSC050N10NS5ATMA1_crop.pdf'
    '../datasheets/infineon/BSB028N06NN3GXUMA2.pdf'
    , page_numbers=[2], resized_shape=2048)

md = ''
for pg in doc.pages:
    for el in pg.elements:
        if el.type == ElementType.TABLE:
            print('\n')
            print('table', el.id, el.box)
            assert len(el.meta['html']) == 1, el.meta['html']
            print(el.meta['html'][0])
            print('\n')

            md += f"\n\n{el.meta['html'][0]}\n\n{el.meta['markdown'][0]}"

with open('_pix2text.md', 'w') as f:
    f.write(md)
print('written _pix2text.md')
exit(0)

doc = p2t.recognize_pdf('../datasheets/EPC/EPC2306.pdf', page_numbers=[1], resized_shape=2048)
table = doc.pages[0].elements[9]
print(table.meta['html'][0])
