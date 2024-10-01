#!python

import argparse
import asyncio
import glob
import os
import random
import sys
import traceback
from typing import Literal

import pathlib
import pymupdf

from dslib.pdf2txt import normalize_text, whitespaces_to_space
from dslib.pdf2txt.parse import extract_text


# from dslib.pdf2txt.parse import extract_text


def open_file_with_default_app(filepath):
    import subprocess, os, platform
    if platform.system() == 'Darwin':  # macOS
        subprocess.call(('open', filepath))
    elif platform.system() == 'Windows':  # Windows
        os.startfile(filepath)
    else:  # linux variants
        subprocess.call(('xdg-open', filepath))


def unique_stable(l, pop_none=False):
    d = dict(zip(l, l))
    if pop_none:
        d.pop(None, None)
    return list(d.keys())


async def main():
    parser = argparse.ArgumentParser(description='')

    parser.add_argument('command', choices=(
        'open',
        'ascii',
        'rasterize', 'html', 'html-pm',
        'parse',
        'power'), default='power')
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

    if args.datasheet_file == 'random':
        files = glob.glob("datasheets/**/*.pdf", recursive=True)
        random.shuffle(files)
        ds_path = files[0]
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

    if args.command == 'open':
        open_file_with_default_app(ds_path)

    elif args.command == 'ascii':
        from dslib.pdf.ascii import pdf_to_ascii
        sort_vert = True
        grouping: Literal['block', 'line', 'word'] = 'line'
        # line_overlap =.2 # higher will produce more lines
        overwrite = False
        spacing = 30 * 2
        try:
            html_path = pdf_to_ascii(ds_path, sort_vert=sort_vert, grouping=grouping, spacing=spacing, overwrite=overwrite)
            if html_path:
                open_file_with_default_app(html_path)
        except Exception as e:
            print(traceback.format_exc())
            print(ds_path)
            return 1

    elif args.command == 'rasterize':
        raise NotImplementedError()
        #import pdfminer.pdfdocument
        #pdfminer.pdfdocument.choplist(ds_path)
    elif args.command == 'html':

        from dslib.pdf.to_html import pdf_to_html
        html_path = pdf_to_html(ds_path, merge_lines=False)
        open_file_with_default_app(html_path)

    elif args.command == 'html-pm':
        out_path = 'out/html/' + os.path.basename(ds_path).split('.')[0] + '.html'
        with open(ds_path, "rb") as fp:
            import pathlib
            pathlib.Path(out_path).parent.mkdir(exist_ok=True, parents=True)
            with open(out_path, "wb") as fpo:
                import pdfminer.high_level
                pdfminer.high_level.extract_text_to_fp(fp,fpo, output_type='html',layoutmode='exact')
            open_file_with_default_app(out_path)

    pdf = pymupdf.open(ds_path)
    print('File Size:         %.0fk' % (os.path.getsize(ds_path) / 1024))

    if False:
        fonts = unique_stable(sum((pdf.get_page_fonts(pno) for pno in range(len(pdf))), []))
        print('Fonts:   ', ' - no embedded fonts found - ' if not fonts else '')
        for font in fonts:
            print(font)

    for k, v in pdf.metadata.items():
        print('%-20s:' % k, v)
    # print(pdf.get_xml_metadata())
    #

    #print(pdf.xref_xml_metadata())
    text = normalize_text(extract_text(ds_path))
    print('Extracted', len(text), 'characters of text:', whitespaces_to_space(text)[:80], '..')

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
    text = extract_text(ds_path)

    print('Extracted', len(text), 'characters of text')

    print(text)


asyncio.run(main())
