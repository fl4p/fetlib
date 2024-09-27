import os
import traceback

from dslib.ocr import img2table_text
from dslib.pdf2txt.parse import extract_text, validate_datasheet_text, extract_fields_from_text
from dslib.pdf2txt.pipeline import pdf2pdf


def brute_force_ocr():
    ds_path = os.path.realpath(
        '../datasheets/infineon/IRF6644TRPBF.pdf'
        # '../datasheets/infineon/BSC050N10NS5ATMA1.pdf'
        # '../../datasheets/infineon/IRF150DM115XTMA1.pdf',
        # '../../datasheets/infineon/BSZ150N10LS3GATMA1.pdf',
        # '../../datasheets/nxp/PSMN3R3-80BS,118.pdf',
    )
    mfr = ds_path.split('/')[-2]
    mpn = ds_path.split('/')[-1].split('.')[0]

    needed_symbols = {'Qrr'}

    pre_process_methods = (
        'ocrmypdf_r250',

        'ocrmypdf_r400',
        'r400_ocrmypdf',

        'ocrmypdf_r600',
        'r600_ocrmypdf',

        # 'ocrmypdf_r800', # poor
        # 'r800_ocrmypdf', # poor
        # 'img2table',

        'ocrmypdf_redo',
    )

    ds_by_method = {}

    txt = img2table_text(ds_path, rasterize_dpi=400)
    ds_by_method['img2table_400'] = extract_fields_from_text(txt, mfr, ds_path, quiet=False)

    try:
        txt = img2table_text(ds_path, rasterize_dpi=600)
        ds_by_method['img2table_600'] = extract_fields_from_text(txt, mfr, ds_path, quiet=False)
    except:
        print(traceback.format_exc())

    for method in pre_process_methods:
        f2 = ds_path + '.' + method + '.pdf'
        try:
            pdf2pdf(ds_path, f2, method=method)
            txt = extract_text(f2)
            if not txt:
                print(method, 'no text extracted', f2)
                continue
            if not validate_datasheet_text(mfr, mpn, txt):
                print(method, 'text validation failed', len(txt))
                # continue
            ds = extract_fields_from_text(txt, mfr, ds_path, quiet=True)
            if not ds:
                print(method, 'no fields extracted', "\n" * 3, '-' * 12, txt, '-' * 12, "\n" * 3, )

            ds.print()

            ds_by_method[method] = ds
            miss = needed_symbols - set(ds.keys())
            if miss:
                print('got', len(ds), 'with', method, 'missing', miss)
            else:
                print('found all', needed_symbols, 'with', method)
                # return

        except Exception as e:
            raise
            continue

    from dslib.manual_fields import reference_data
    ref = reference_data(mfr, mpn) or ds_by_method['ocrmypdf_r400']

    diff_by_method = {method: ref.show_diff(ds_by_method[method], title=method) for method in ds_by_method.keys()}

    print('summary:')
    for m, ds in sorted(ds_by_method.items(), key=lambda i: diff_by_method[i[0]]):
        print('%30s' % m, 'diff', diff_by_method[m], 'found', len(ds), set(ds.keys()))

    ref.print()
    print(repr(ref))

    if not reference_data(mfr, mpn):
        print('WARNING: no reference data for', mfr, mpn)

    # assert not miss, miss


brute_force_ocr()
