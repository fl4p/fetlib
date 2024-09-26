from io import BytesIO

import PIL.Image
import cv2
import numpy as np
import pdfplumber
from pdfplumber.table import TableFinder


import pymupdf

from test.util import pixmap_to_pil


def main():
    #page:pymupdf.Page = pymupdf.open("../datasheets/infineon/IRF150DM115XTMA1.pdf")[3]
    #page = pymupdf.open("../datasheets/onsemi/FDMS86368-F085.pdf")[1]
    #page = pymupdf.open("../datasheets/littelfuse/IXTQ180N10T.pdf")[1]

    #draw_tables_pymupdf("../datasheets/infineon/IRF150DM115XTMA1.pdf", page=4).show('pymupdf')

    #draw_tables_img2table("../datasheets/infineon/IRF150DM115XTMA1.pdf", page=4).show()
    #
    #draw_tables_img2table("../datasheets/littelfuse/IXTQ180N10T.pdf", page=2).show()
    # draw_tables_img2table("../datasheets/onsemi/FDMS86368-F085.pdf", page=2).show()
    #draw_tables_img2table("../datasheets/nxp/PSMN4R4-80BS,118.pdf", page=6).show()
    #draw_tables_img2table("../datasheets/infineon/IPP180N10N3GXKSA1.pdf", page=3).show()

    # draw_tables_img2table("../datasheets/littelfuse/IXFP180N10T2.pdf", page=2).show()


    exit(0)

#def pdf_tables_add_grid_to_borderless(pdf_path, out_path):

def pdf_page_to_image(pdf_path, page, dpi=400):
    page = pymupdf.open(pdf_path)[page - 1]
    pix = page.get_pixmap(dpi=dpi)
    return pixmap_to_pil(pix)

def draw_tables_pymupdf(pdf_path, page):
    page = pymupdf.open(pdf_path)[page-1]

    tset = {
        # lines_strict is more robust but needs a table frame
        "vertical_strategy": "lines_strict",  # (text,lines)
        "horizontal_strategy": "lines",
        #"explicit_vertical_lines": [],
        #"explicit_horizontal_lines": [],
        "snap_tolerance": 1, # this causes offset issues
        #"join_tolerance": 2,
        #"edge_min_length": 2,
        #"min_words_vertical": 1,
        #"min_words_horizontal": 2,
        #"intersection_tolerance": 2,
        #"text_tolerance": 2,
    }

    tabs = page.find_tables(**tset)
    for cell in tabs.cells:
        page.draw_rect(cell, width=1, dashes="[3 4] 0", color=(1,0,0))
    pix = page.get_pixmap(dpi=300)
    img = pixmap_to_pil(pix)
    #img.show()
    return img


def thicken(img):
    kernel = np.zeros((3, 3), np.uint8)
    kernel[:,int(kernel.shape[1]/2)] = 1
    kernel[int(kernel.shape[0] / 2), :] = 1
    #draw_img = 255 - cv2.dilate(255-draw_img, kernel, iterations=1)
    img = cv2.erode(img, kernel, iterations=1)
    return img

def draw_tables_img2table(pdf_path, page):
    from img2table.document import Image, PDF
    from img2table.document import Image
    from img2table.ocr.base import OCRInstance

    buf = BytesIO()
    img_pil = pdf_page_to_image(pdf_path,page,dpi=400)
    img_pil.save(buf, format='PNG')
    img = Image(buf)


    #from img2table.ocr import TesseractOCR
    #tesseract = TesseractOCR()

    buf = BytesIO()
    #thick = thicken(list(img.images)[0])
    thick = list(img.images)[0].copy()
    PIL.Image.fromarray(thick).save(buf, format='PNG')
    img = Image(buf)


    # Extract tables with Tesseract and PaddleOCR
    tables = img.extract_tables(#ocr=tesseract,
                                borderless_tables=True,
                                implicit_rows=True,
                                implicit_columns=True,
                                #min_confidence=80,
                                )

    draw_img = list(img.images)[0].copy()

    #draw_img = thicken(draw_img)

    page = pymupdf.open(pdf_path)[page - 1]

    px2pg = page.rect[2] / draw_img.shape[1]

    for tb in tables:
        for row in tb.content.values():
            for cell in row:
                cv2.rectangle(draw_img, (cell.bbox.x1, cell.bbox.y1), (cell.bbox.x2, cell.bbox.y2),
                              (255, 0, 0), 2)

                page.draw_rect(
                    tuple(np.array((float(cell.bbox.x1), float(cell.bbox.y1), float(cell.bbox.x2), float(cell.bbox.y2)))*px2pg),
                               width=1,
                    #dashes="[3 4] 0",
                    color=(0, 0, 0))

    tset = {
        # lines_strict is more robust but needs a table frame
        "vertical_strategy": "lines_strict",  # (text,lines)
        "horizontal_strategy": "lines",
        "snap_tolerance": 2, # this causes offset issues
    }
    tabs = page.find_tables(**tset)
    for cell in tabs.cells:
        page.draw_rect(tuple(cell), width=1, dashes="[3 4] 0", color=(1,.8,0))

    pix = page.get_pixmap(dpi=300)
    img = pixmap_to_pil(pix)
    # img.show()
    return img


    #return PIL.Image.fromarray(draw_img)




main()
if 0:


    page:pymupdf.Page = pymupdf.open("../datasheets/infineon/IRF150DM115XTMA1.pdf")[3]
    #page = pymupdf.open("../datasheets/onsemi/FDMS86368-F085.pdf")[1]
    page = pymupdf.open("../datasheets/littelfuse/IXTQ180N10T.pdf")[1]





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