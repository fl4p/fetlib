import re

from dslib.cache import disk_cache


@disk_cache(ttl='99d', file_dependencies=[0], salt='v01', hash_func_code=True)
def img2table_tables(pdf_path, pages=None, rasterize_dpi=None):

    if rasterize_dpi is not None:
        dpi = rasterize_dpi
        int_file = pdf_path + f'.r{int(dpi)}.pdf'
        from dslib.pdf2txt.pipeline import rasterize_pdf
        rasterize_pdf(pdf_path, int_file, dpi=dpi, fitz_method=False)
        pdf_path = int_file

    print('img2table_tables', pdf_path)


    from img2table.document import PDF
    pdf = PDF(src=pdf_path, pages=pages)

    from img2table.ocr import TesseractOCR
    tessdata_dir = '/usr/local/share/tessdata'
    tesseract_ocr = TesseractOCR(n_threads=4, lang="eng", tessdata_dir=tessdata_dir)

    print(pdf_path, 'extracting tables..')
    extracted_tables = pdf.extract_tables(
        ocr=tesseract_ocr,
        implicit_rows=True,
        implicit_columns=True,
        borderless_tables=True,
        min_confidence=50,
    )

    return extracted_tables


@disk_cache(ttl='99d', file_dependencies=[0], salt='v01', hash_func_code=True)
def img2table_text(pdf_path, pages=None, rasterize_dpi=None):
    extracted_tables = img2table_tables(pdf_path, pages, rasterize_dpi=rasterize_dpi)

    text = ''
    for page, tables in extracted_tables.items():
        for idx, table in enumerate(tables):
            for i, row in table.content.items():
                csv = '\n'.join(str(cell.value or '') for cell in row)
                text += csv + '\n'

    text = re.compile('\n+').sub('\n', text)

    return text
