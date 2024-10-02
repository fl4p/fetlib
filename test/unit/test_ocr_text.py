from pymupdf import get_tessdata

from dslib.ocr import img2table_text
from dslib.pdf2txt.parse import extract_text
from dslib.pdf2txt.pipeline import rasterize_pdf, ocrmypdf, rasterize_ocrmypdf


def _test_mupdfy():
    import pymupdf

    pdf = pymupdf.open("../../datasheets/infineon/IPP048N12N3GXKSA1.pdf")
    text = ''.join(p.get_text() for p in pdf)

    # from img2table.ocr import TesseractOCR
    # TesseractOCR()

    # https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_textpage_ocr
    tessdata = get_tessdata() or '/usr/local/share/tessdata'
    tp = pdf[1].get_textpage_ocr(dpi=400, full=True, tessdata=tessdata)  # tessdata
    text_mu = tp.extractText()
    assert text_mu

    in_path = "../../datasheets/infineon/IPP048N12N3GXKSA1.pdf"

    rasterize_ocrmypdf(in_path, '_tmp_r400omp.pdf', dpi=400)  # pre-rasterize
    text_r400omp = extract_text('_tmp_r400omp.pdf')

    rasterize_ocrmypdf(in_path, '_tmp_r600omp.pdf', dpi=600)  # pre-rasterize
    text_r600omp = extract_text('_tmp_r600omp.pdf')

    ocrmypdf(in_path, '_tmp_redo.pdf', rasterize=False)  # REDO
    text_redo = extract_text('_tmp_redo.pdf')
    assert text_redo

    ocrmypdf(in_path, '_tmp_omp400.pdf', rasterize=400)  # force
    text_omp400 = extract_text('_tmp_omp400.pdf')

    ocrmypdf(in_path, '_tmp_omp600.pdf', rasterize=600)  # force
    text_omp600 = extract_text('_tmp_omp600.pdf')

    dpi = 400
    int_file = in_path + f'.r{int(dpi)}.pdf'
    rasterize_pdf(in_path, int_file, dpi=dpi)
    text_i2t = img2table_text(int_file, pages=[1])

    print('\n'.join(map(str, dict(
        text=text,
        text_mu=text_mu,
        text_r400omp=text_r400omp,
        # text_redo=text_redo,
        text_omp400=text_omp400,
        text_r600omp=text_r600omp,
        text_omp600=text_omp600,
        text_i2t=text_i2t,
    ).items())))

    # test_ca = extract_text(, try_ocr='force')

    # assert test_ca


if __name__ == '__main__':
    test_mupdfy()