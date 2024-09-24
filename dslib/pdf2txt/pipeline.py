import os
import pathlib
from typing import Literal, Union

import PIL
from ocrmypdf import hookimpl

from dslib.cache import disk_cache


@disk_cache(ttl='14d', file_dependencies=[0], out_files=[1])
def convertapi(in_path, out_path, method: Literal['ocr', 'pdf', 'rasterize'] = 'ocr'):
    assert method != 'rasterize', 'use rasterize_pdf() instead'
    import convertapi
    convertapi.api_credentials = 'secret_kbFZouJhsYxqPFYm'
    print('calling convertapi', method.upper(), in_path, round(os.stat(in_path).st_size * 1e-6, 2), 'MB')
    not os.path.isfile(out_path) or os.remove(out_path)
    convertapi.convert(method, {
        'File': in_path
    }, from_format='pdf').save_files(out_path)
    assert os.path.isfile(out_path)


# @disk_cache(ttl='99d', file_dependencies=[0], out_files=[1], salt='v200')
def rasterize_pdf(in_path, out_path, dpi=400):
    # this breaks "encryption" e.g. FDP047N10.pdf
    from pdf2image import convert_from_path
    images = convert_from_path(in_path)
    assert images
    images[0].save(
        out_path, "PDF", resolution=float(dpi), save_all=True, append_images=images[1:]
    )
    assert os.path.isfile(out_path)


@hookimpl
def rasterize_pdf_page(
        input_file,
        output_file,
        raster_device,
        raster_dpi,
        pageno,
        page_dpi,
        rotation,
        filter_vector,
        stop_on_soft_error,
):
    raise NotImplemented()

@hookimpl
def add_options(parser):
    print('')
    pass

@disk_cache(ttl='14d',
            file_dependencies=[0, 'tesseract-stuff/tesseract.cfg', 'tesseract-stuff/mosfet.user-words'],
            out_files=[1],
            salt='v03')
def ocrmypdf(in_path, out_path, rasterize:Union[bool, int], try_decrypt=True):
    # custom wordlist
    # https://github.com/tesseract-ocr/test/blob/main/testing/eng.unicharset
    # https://vprivalov.medium.com/tesseract-ocr-tips-custom-dictionary-to-improve-ocr-d2b9cd17850b
    import subprocess
    not os.path.isfile(out_path) or os.remove(out_path)

    cfg_file = ('tesseract-stuff/tesseract.cfg')  # os.path.realpath
    assert os.path.isfile(cfg_file)

    uw_file = 'tesseract-stuff/mosfet.user-words'
    assert os.path.isfile(uw_file)

    # TESSDATA_PREFIX

    #if rasterize:
    #    rasterize_pdf(in_path, in_path + '.r.pdf')
    #    in_path = in_path + '.r.pdf'
    import ocrmypdf as ocrmypdf_

    #import PIL.Image
    #PIL.Image.MAX_IMAGE_PIXELS *= 2
    print('ocrmypdf', in_path)

    try:
        ocrmypdf_.ocr(
            in_path, out_path,
                 language='eng',
                 #image_dpi=
                 output_type='pdf',
                 # image_dpi=400, # for input images only !
                 redo_ocr=not rasterize,
                 oversample=int(rasterize) if not isinstance(rasterize, bool) else None,
                 force_ocr=bool(rasterize),
                 tesseract_config=cfg_file,
                 #tesseract_thresholding=''
                 user_words=pathlib.Path(uw_file), #user_patterns=
                 progress_bar=True,
                 max_image_mpixels=500, # 250 default
                 #pages='1,2-4',
                 plugins='ocrmypdf_plugins.py',
                 )
    except Exception as e:
        if try_decrypt and ('is encrypted' in str(e) or isinstance(e, ocrmypdf_.EncryptedPdfError)):
            dec_path = in_path + '.decrypted.pdf'
            pdf2pdf(in_path, dec_path, method='qpdf_decrypt')
            return ocrmypdf(dec_path, out_path, rasterize=rasterize, try_decrypt=False)
        else:
            raise

    assert os.path.isfile(out_path)
    return

    cmd = list(filter(bool, ['ocrmypdf',
                             '--force-ocr' if rasterize else '',  # rasterize all pages
                             *(['--oversample', str(rasterize)] if not isinstance(rasterize, bool) else []),
                             '--output-type', 'pdf',
                             '-l', 'eng',
                             # '--tesseract-oem', '3',  # 0=legacy, 1=LSTM 2=both 3=auto https://github.com/tesseract-ocr/tessdoc/blob/main/Command-Line-Usage.md
                             '--tesseract-config', cfg_file,
                             '--user-words', uw_file,
                             # --user-patterns
                             in_path,
                             out_path]))
    print(' '.join(cmd))
    subprocess.run(cmd, check=True)
    assert os.path.isfile(out_path)


def raster_ocr(in_path, out_path, method: Literal['convertapi', 'ocrmypdf']):
    # TODO add http://www.tobias-elze.de/pdfsandwich/
    if method == 'ocrmypdf':
        return ocrmypdf(in_path, out_path, rasterize=True)
    elif method == 'convertapi':
        rasterize_pdf(in_path, out_path + '.r.pdf')
        return convertapi(out_path + '.r.pdf', out_path, 'ocr')
    else:
        raise ValueError(method)


# @disk_cache(ttl='99d', file_dependencies=[0], out_files=[1], salt='v02')
def pdf2pdf(in_path, out_path, method):
    # import fitz
    # import shutil
    # shutil.copy(in_path, out_path)
    # with fitz.open(in_path) as pdf:
    #    pdf.bake()
    #    pdf.save(out_path, garbage=1, clean=True, incremental=False)

    # macos Preview print2pdf fixes:
    # - IRF7779L2TRPBF

    # page = 1
    # for image in images:
    #    out_path = in_path + '_images/page_%02d.png'
    #    image.save(out_path % page)
    #    page = page + 1

    def cups():
        # macports
        # https://www.cups-pdf.de/

        # /opt/local/var/spool/cups-pdf/${USER}/
        # return subprocess.run(['lp', '-d', 'CUPS_PDF' 'test.txt'])

        ret = subprocess.run(['cupsfilter', in_path], capture_output=True)
        with open(out_path, 'wb') as f:
            f.write(ret.stdout)

    def r400_ocrmypdf():
        rasterize_pdf(in_path, in_path + '.r.pdf')
        return ocrmypdf(in_path + '.r.pdf', out_path, rasterize=False)

    def qpdf_decrypt():
        subprocess.run(['qpdf', '--decrypt', in_path, out_path], check=True)

    # TODO https://stackoverflow.com/a/4297984
    import subprocess
    #os.path.isfile(out_path) and os.remove(out_path) # dont delete, inner function might use disk_cache

    return dict(
        nop=lambda: None,
        sips=lambda: subprocess.run(['sips', '-s', 'format', 'pdf', in_path, '--out', out_path], check=True),
        gs=lambda: subprocess.run(['gs', '-sDEVICE=pdfwrite',
                                   '-dPDFSETTINGS=/printer',  # /screen /default
                                   '-dPDFA=2',  # 1,2,3
                                   '-o', out_path, in_path], check=True), # TODO try decrypt
        cups=cups,

        # ocrmypdf=lambda: raster_ocr(in_path, out_path, 'ocrmypdf'),
        ocrmypdf_r400=lambda: ocrmypdf(in_path, out_path, rasterize=400),
        r400_ocrmypdf=r400_ocrmypdf,
        ocrmypdf_redo=lambda: ocrmypdf(in_path, out_path, rasterize=False),

        convertapi_ocr=lambda: raster_ocr(in_path, out_path, 'convertapi'),
        qpdf_decrypt=qpdf_decrypt,
    )[method]()
