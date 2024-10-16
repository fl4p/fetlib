import os
from typing import List, Dict

import PIL.Image
import cv2
import numpy as np

from dslib.cache import disk_cache
from dslib.pdf.to_html import Annotation
from dslib.pdf2txt import normalize_text, whitespaces_to_space


def draw_annotations(image: PIL.Image.Image, page_annotations: List[Annotation]):
    rgb = np.array(image)  # .convert('RGB')
    # Convert RGB to BGR
    # bgr = rgb[:, :, ::-1].copy()

    pb = page_annotations[0].page_bbox

    sc = rgb.shape[0] / pb[3]
    rint = lambda f: int(round(sc * f))

    for a in page_annotations:
        p0 = (rint(a.bbox[0]) - 1, rint(pb[3] - a.bbox[3]) - 1)
        s = normalize_text(a.name)
        s = whitespaces_to_space(s)
        cv2.rectangle(rgb, p0, (rint(a.bbox[2]) + 1, rint(pb[3] - a.bbox[1]) + 1), a.color, a.thickness)
        cv2.putText(rgb, s, (p0[0] + 4, p0[1] + 22), cv2.FONT_HERSHEY_PLAIN, 1.6, a.color, a.thickness)

    return PIL.Image.fromarray(rgb)


@disk_cache(ttl='99d', file_dependencies=True)
def pdf_rasterize(pdf_path, dpi):
    from pdf2image import convert_from_path
    images = convert_from_path(pdf_path, dpi=dpi, fmt='png')  # rm dpi?
    return images


def pdf_raster_annot(pdf_path, dpi, annotations: Dict[int, List[Annotation]]):
    images = pdf_rasterize(pdf_path, dpi)
    assert images

    images2 = []

    for pn, page_annotations in annotations.items():
        print('draw annotations on page', pn, len(page_annotations))
        images2.append(draw_annotations(images[pn], page_annotations))

    images = images2

    out_path = pdf_path + '.annot.pdf'
    images[0].save(
        out_path, "PDF", resolution=float(dpi), save_all=True, append_images=images[1:]
    )
    assert os.path.isfile(out_path)
    return out_path


def display_borderless_tables(img: 'Image', extracted_tables) -> np.ndarray:
    # Create image displaying extracted tables
    display_image = img.copy()  # list(img.images)[0].copy()
    for tb in extracted_tables:
        for row in tb.content.values():
            for cell in row:
                cv2.rectangle(display_image, (cell.bbox.x1, cell.bbox.y1), (cell.bbox.x2, cell.bbox.y2),
                              (255, 0, 0), 2)

    # Create white separator image
    width = min(display_image.shape[1] // 10, 100)
    # white_img = cv2.cvtColor(255 * np.ones((display_image.shape[0], width), dtype=np.uint8), cv2.COLOR_GRAY2RGB)

    final_image = display_image

    # Stack images
    # final_image = np.hstack([
    # list(img.images)[0].copy(),
    #                    white_img,
    #                         display_image])

    return final_image
