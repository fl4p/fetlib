from io import BytesIO

import cv2
import numpy as np
import pdfplumber
from pdfplumber.table import TableFinder


import pymupdf

if 1:

    def pixmap_to_pil(pixmap):
        """Write to image file using Pillow.

        Args are passed to Pillow's Image.save method, see their documentation.
        Use instead of save when other output formats are desired.
        """
        try:
            from PIL import Image
        except ImportError:
            print("PIL/Pillow not installed")
            raise


        cspace = pixmap.colorspace
        if cspace is None:
            mode = "L"
        elif cspace.n == 1:
            mode = "L" if pixmap.alpha == 0 else "LA"
        elif cspace.n == 3:
            mode = "RGB" if pixmap.alpha == 0 else "RGBA"
        else:
            mode = "CMYK"

        return Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)

    page = pymupdf.open("../datasheets/infineon/IRF150DM115XTMA1.pdf")[3]
    #page = pymupdf.open("../datasheets/onsemi/FDMS86368-F085.pdf")[1]

    page = pymupdf.open("../datasheets/littelfuse/IXTQ180N10T.pdf")[1]

    tset = {
        # lines_strict is more robust but needs a table frame
        "vertical_strategy": "text",  # (text,lines)
        "horizontal_strategy": "lines",
        #"explicit_vertical_lines": [],
        #"explicit_horizontal_lines": [],
        "snap_tolerance": 2, # this causes offset issues
        "join_tolerance": 2,
        "edge_min_length": 2,
        "min_words_vertical": 1,
        "min_words_horizontal": 2,
        "intersection_tolerance": 2,
        "text_tolerance": 2,
    }

    #page.draw_line((59,150),(59,800),color=(0,0,0),width=1)

    tabs = page.find_tables(**tset)  # locate and extract any tables on page
    print('found', tabs.cells)

    for cell in tabs.cells:
        page.draw_rect(cell, width=1, dashes="[3 4] 0", color=(1,0,0))
    pix = page.get_pixmap(dpi=300)
    pixmap_to_pil(pix).show()





tset = {
    "vertical_strategy": "lines_strict", # text
    "horizontal_strategy": "lines",
    "snap_tolerance": 0.5,
    "snap_x_tolerance": 3,
    "snap_y_tolerance": 3,
    "join_tolerance": 3,
    "join_x_tolerance": 3,
    "join_y_tolerance": 3,
    "edge_min_length": 3,
    "min_words_vertical": 3,
    "min_words_horizontal": 1,
    "intersection_tolerance": 3,
    "intersection_x_tolerance": 3,
    "intersection_y_tolerance": 3,
    "text_tolerance": 3,
    "text_x_tolerance": 3,
    "text_y_tolerance": 3, }

#with pdfplumber.open("../datasheets/vishay/SIR680ADP-T1-RE3.pdf") as pdf:
#    p0 = pdf.pages[1]
#    im = p0.to_image(resolution=200)
#    im.debug_tablefinder(tset)
#    im.show()

import pymupdf
#doc = pymupdf.open("datasheets/infineon/IRF150DM115XTMA1.pdf") # open a document

with pdfplumber.open("../datasheets/infineon/IRF150DM115XTMA1.pdf") as pdf:
    p0 = pdf.pages[3]
    im = p0.to_image(resolution=200)

    # tf = TableFinder(p0)

    im.debug_tablefinder(tset)
    im.show()



    #buf = BytesIO()
    #im.save(buf, format="PNG", colors= )


    #dilated = cv2.dilate(im, np.ones((3, 3)))


''