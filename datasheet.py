#!python

import argparse
import asyncio
import glob
import os
import random
import sys
import traceback
from typing import Literal

import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)

from dslib.field import conditions_to_str
from dslib.pdf.pdf2txt import normalize_text, whitespaces_to_space
from dslib.pdf.parse import extract_text, parse_datasheet
from dslib.util import open_file_with_default_app, unique_stable


async def main():
    parser = argparse.ArgumentParser(description='')

    parser.add_argument('command', choices=(
        'open',
        'ascii',
        'rasterize',
        'html',  # text only with bbox, using pdf_blocks_pdfminer_six
        'html-pm',  # dfminer.high_level.extract_text_to_fp
        'parse',  # parses the datasheet and prints all fields
        'read-sheet-debug',  # runs the spatial query and places annotations
        'power' # power loss computation
    ), default='power')
    parser.add_argument('datasheet_file')

    parser.add_argument('--dcdc-file')
    parser.add_argument('-q')
    parser.add_argument('-tab-strat')
    parser.add_argument('-j', default=8)  # parallel jobs
    parser.add_argument('--rg-total', default=6)  # total gate resistance
    parser.add_argument('--vpl-fallback', default=4.5)
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--no-ocr', action='store_true')
    parser.add_argument('--clean', action='store_true')

    args = parser.parse_args(sys.argv[1:])

    if args.no_cache:
        print('cache disabled')
        from dslib.cache import disk_cache_disable
        disk_cache_disable(True)

    if args.datasheet_file == 'random':
        files = glob.glob("datasheets/**/*.pdf", recursive=True)
        random.shuffle(files)
        ds_path = next(filter(lambda fn: fn.count('.pdf') < 2, files))
        # ds_path = files[0]
        print(ds_path)
    else:
        ds_path = os.path.abspath(args.datasheet_file)

        if not os.path.isfile(ds_path):
            import configparser
            config = configparser.ConfigParser()
            config.read('.dspicks', 'utf-8')
            if args.datasheet_file == 'dspick':
                p = next(iter(config['dspicks'].values()))
            else:
                p = config['dspicks'].get(args.datasheet_file, None)
            if p:
                ds_path = os.path.abspath(p)

    print('Selected', ds_path)

    pdf = pymupdf.open(ds_path)
    print('File Size:         %.0fk' % (os.path.getsize(ds_path) / 1024))
    for k, v in pdf.metadata.items():
        print('%-20s:' % k, v)

    if args.command == 'open':
        open_file_with_default_app(ds_path)
    elif args.command == 'power':
        ds = parse_datasheet(ds_path)
        ds.print(show_cond=True, show_sources=True)
        mf = ds.get_mosfet_specs()

        from dslib.spec_models import DcDcLoadParams
        from dslib.mosfet import GateDrive
        dc = DcDcLoadParams.default()

        gd = GateDrive(rg_total=args.rg_total, Von=10, fallback_V_pl=args.vpl_fallback)

        from dclib.powerloss import dcdc_buck_hs, dcdc_buck_ls
        print('')
        print('DCDC = %s' % dc)
        print('GDrv = %s' % gd)
        p_hs = dcdc_buck_hs(dc, mf, gd=gd)
        p_ls = dcdc_buck_ls(dc, mf, gd=gd)
        print('P_HS = %6.2f W    ' % p_hs.buck_hs(), conditions_to_str(dict(p_hs.items())))
        print('P_LS = %6.2f W    ' % p_ls.buck_ls(), conditions_to_str(dict(p_ls.items())))

        return 0

    elif args.command == 'ascii':
        from dslib.pdf.ascii import pdf_to_ascii
        sort_vert = True
        grouping: Literal['block', 'line', 'word'] = 'line'
        # line_overlap =.2 # higher will produce more lines
        overwrite = False
        spacing = 30 * 2
        try:
            html_path = pdf_to_ascii(ds_path, sort_vert=sort_vert, grouping=grouping, spacing=spacing,
                                     overwrite=overwrite)
            if html_path:
                open_file_with_default_app(html_path)
        except Exception as e:
            print(traceback.format_exc())
            print(ds_path)
            return 1

    elif args.command == 'rasterize':
        raise NotImplementedError()
        # import pdfminer.pdfdocument
        # pdfminer.pdfdocument.choplist(ds_path)
    elif args.command == 'html':

        from dslib.pdf.to_html import pdf_to_html
        html_path = pdf_to_html(ds_path, merge_lines=True)
        open_file_with_default_app(html_path)

    elif args.command == 'parse':
        ds = parse_datasheet(ds_path)
        ds.print(True, True)
        print(ds.get_mosfet_specs())
    elif args.command == 'read-sheet-debug':
        from dslib.pdf.sheet import read_sheet_debug
        read_sheet_debug(ds_path).print(True, True)
    elif args.command == 'html-pm':
        out_path = 'out/html/' + os.path.basename(ds_path).split('.')[0] + '.html'
        with open(ds_path, "rb") as fp:
            import pathlib
            pathlib.Path(out_path).parent.mkdir(exist_ok=True, parents=True)
            with open(out_path, "wb") as fpo:
                import pdfminer.high_level
                pdfminer.high_level.extract_text_to_fp(fp, fpo, output_type='html', layoutmode='exact')
            open_file_with_default_app(out_path)

    if False:
        fonts = unique_stable(sum((pdf.get_page_fonts(pno) for pno in range(len(pdf))), []))
        print('Fonts:   ', ' - no embedded fonts found - ' if not fonts else '')
        for font in fonts:
            print(font)

    # print(pdf.get_xml_metadata())
    #

    # print(pdf.xref_xml_metadata())
    text = normalize_text(extract_text(ds_path)[0])
    print('Extracted', len(text), 'characters of text:', whitespaces_to_space(text)[:80], '..')
    print(ds_path)

    return

    import pymupdf4llm
    md_text = pymupdf4llm.to_markdown(ds_path, table_strategy=args.tab_strat or "lines_strict", )
    print(md_text)
    import pathlib
    md_path = os.path.basename(ds_path).replace('.pdf', '.md')
    pathlib.Path(md_path).write_bytes(md_text.encode())
    open_file_with_default_app(md_path)

    return 0

    ds_path = 'datasheets/nxp/PSMN3R3-80BS,118.pdf'
    ds_path = 'datasheets/toshiba/TK46E08N1.pdf'  # column wise text

    print('Analysing', ds_path)
    text, _ = extract_text(ds_path)

    print('Extracted', len(text), 'characters of text')

    print(text)


asyncio.run(main())
