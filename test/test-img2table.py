from io import BytesIO

import pymupdf
from img2table.document import Image, PDF
from img2table.ocr import TesseractOCR
import cv2
import numpy as np
from PIL import Image as PILImage

from img2table.document import Image
from img2table.ocr.base import OCRInstance




def main():
    pdf = PDF("../datasheets/littelfuse/IXTQ180N10T.pdf", pages=[1], detect_rotation=False, pdf_text_extraction=True)
    #img = Image("../datasheets/_samples/IXTQ180N10T_p2_400dpi.png")
    #img = Image("../datasheets/_samples/IXTQ180N10T_p2_400dpi.png")
    #img = Image("../datasheets/_samples/BSB028N06NN3GXUMA2_p3.png")


    img = pdf
    doc = img

    tesseract = TesseractOCR()

    # Extract tables with Tesseract and PaddleOCR
    tables = doc.extract_tables(ocr=tesseract,
                                borderless_tables=True,
                                implicit_rows=False,
                                implicit_columns=True,
                                min_confidence=50, # higher values: crops off borderless cells
                                )

    tables = tables[1]

    # draw borders of borderless tables on bordered_img
    bordered_img = list(img.images)[0].copy()
    for tb in tables:

        cv2.rectangle(bordered_img, (tb.bbox.x1-1, tb.bbox.y1), (tb.bbox.x2-1, tb.bbox.y2+1),
            (0, 0, 0), 1)
        for row in tb.content.values():
            for cell in row:
                cv2.rectangle(bordered_img, (cell.bbox.x1, cell.bbox.y1), (cell.bbox.x2, cell.bbox.y2),
                              (0, 0, 0), 1)

    bio = BytesIO()
    PILImage.fromarray(bordered_img).save(bio, format='PNG')
    PILImage.fromarray(bordered_img).show('bordered')

    if 0:
        mudoc = pymupdf.open("PNG", bio)[0]

        tset = {
            # lines_strict is more robust but needs a table frame
            "vertical_strategy": "lines",  # (text,lines)
            "horizontal_strategy": "lines",
            "snap_tolerance": 1, # this causes offset issues
            "join_tolerance": 2,
            "edge_min_length": 2,
            "min_words_vertical": 1,
            "min_words_horizontal": 2,
            "intersection_tolerance": 2,
            "text_tolerance": 2,
        }

        tabs = mudoc.find_tables(**tset)  # locate and extract any tables on page
        #print('pymupdf found', len(tabs), 'tables')
        for cell in tabs.cells:
            mudoc.draw_rect(cell, width=1, dashes="[3 4] 0", color=(1,0,0))
        pix = mudoc.get_pixmap(dpi=300)
        pixmap_to_pil(pix).show(title='img2tableBorders+pymupdf')


    #exit(0)

    img2 = Image(bio)
    tables2 = img2.extract_tables(ocr=tesseract,
                                borderless_tables=False,
                                implicit_rows=False,
                                implicit_columns=False,
                                  min_confidence=60
                                )

    disp_img = display_borderless_tables(img2, tables2)
    PILImage.fromarray(disp_img).show()

    #tables[0].df
    # coding: utf-8




def display_borderless_tables(img: Image, extracted_tables) -> np.ndarray:

    # Create image displaying extracted tables
    display_image = list(img.images)[0].copy()
    for tb in extracted_tables:
        for row in tb.content.values():
            for cell in row:
                cv2.rectangle(display_image, (cell.bbox.x1, cell.bbox.y1), (cell.bbox.x2, cell.bbox.y2),
                              (255, 0, 0), 2)

    # Create white separator image
    width = min(display_image.shape[1] // 10, 100)
    #white_img = cv2.cvtColor(255 * np.ones((display_image.shape[0], width), dtype=np.uint8), cv2.COLOR_GRAY2RGB)

    final_image = display_image

    # Stack images
    #final_image = np.hstack([
        #list(img.images)[0].copy(),
         #                    white_img,
    #                         display_image])

    return final_image


def _etc():
    rects = []
    for table in tables[1]:
        for id_row, row in enumerate(table.content.values()):
            for id_col, cell in enumerate(row):
                rects.append(cell.bbox)
                #value = cell.value

    pdf.pages

    from img2table.document import PDF


    ocr = TesseractOCR(n_threads=1, lang="eng")

    # Instantiation of document, either an image or a PDF
    doc = Image(src)

    # Table extraction
    extracted_tables = doc.extract_tables(ocr=ocr,
                                          implicit_rows=False,
                                          implicit_columns=False,
                                          borderless_tables=False,
                                          min_confidence=50)
    for id_row, row in enumerate(table.content.values()):
        for id_col, cell in enumerate(row):
            x1 = cell.bbox.x1
            y1 = cell.bbox.y1
            x2 = cell.bbox.x2
            y2 = cell.bbox.y2
            value = cell.value


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


main()