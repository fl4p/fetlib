"""Regenerate the character-language-model corpus used by dslib/pdf/glyph_lm.py.

    python apps/build_glyph_lm_corpus.py [--parts 400] [--out dslib/pdf/glyph_lm_corpus.txt.gz]

Samples text from datasheets that are ALREADY READABLE and writes it gzipped.
The model that consumes it decides between candidate readings of a scrambled
glyph, so what it must know is what MOSFET datasheet English looks like --
'N-channel', 'Rds(on)', 'Qgd', 'mOhm', 'Typ.' -- not what English looks like in
general. A generic corpus would score 'OμtiMOS' and 'OptiMOS' as equally odd.

Two properties are load-bearing and enforced below:

* **Only clean sources.** A PDF whose own text layer is scrambled would train
  the model on gibberish, and the model would then prefer gibberish. Files
  flagged by `has_custom_font_encoding`, and lines that fail a printable-ratio
  check, are dropped.
* **Deterministic selection.** Files are taken in sorted order with a fixed
  stride, never sampled at random, so regenerating the corpus on the same
  datasheet tree reproduces it byte for byte. A model that drifts silently
  between rebuilds would make every accuracy measurement unrepeatable.
"""

import argparse
import gzip
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pymupdf

DEFAULT_OUT = 'dslib/pdf/glyph_lm_corpus.txt.gz'

# Cap on the emitted corpus. Past a few hundred KB the trigram counts stop
# moving -- datasheet English has a small vocabulary -- and the file has to sit
# in the repo, so the extra megabytes buy nothing and cost every clone.
DEFAULT_MAX_BYTES = 400_000

_PRINTABLE = re.compile(r'[ -~°±×÷≤≥≠≈ΩµμÅ•™®©€]')


def _clean_line(ln: str) -> str:
    ln = ln.replace(' ', ' ').strip()
    ln = re.sub(r'\s+', ' ', ln)
    if len(ln) < 8:
        return ''
    good = len(_PRINTABLE.findall(ln))
    # A line that is mostly unprintable is either a broken text layer or a
    # symbol font's output. Either way it is not the English the model is for.
    if good / len(ln) < 0.90:
        return ''
    # Reject lines that are almost all digits/punctuation (table rows). They
    # would teach the model that letters are rare.
    if sum(c.isalpha() for c in ln) / len(ln) < 0.35:
        return ''
    return ln


def iter_pdfs(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            if f.lower().endswith('.pdf'):
                yield os.path.join(dirpath, f)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--datasheets', default='datasheets')
    ap.add_argument('--parts', type=int, default=400,
                    help='how many PDFs to sample text from')
    ap.add_argument('--pages', type=int, default=3,
                    help='pages per PDF (the front pages carry the prose)')
    ap.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES)
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    from dslib.pdf.fix_encoding import has_custom_font_encoding

    all_pdfs = sorted(iter_pdfs(args.datasheets))
    if not all_pdfs:
        print('no PDFs under %s' % args.datasheets, file=sys.stderr)
        return 2
    stride = max(1, len(all_pdfs) // (args.parts * 2))
    picked = all_pdfs[::stride]

    seen_lines = set()
    out_lines = []
    total = 0
    used = 0
    for path in picked:
        if used >= args.parts or total >= args.max_bytes:
            break
        try:
            if has_custom_font_encoding(path):
                continue
        except Exception:
            continue
        try:
            doc = pymupdf.open(path)
        except Exception:
            continue
        got = 0
        try:
            for pno in range(min(args.pages, len(doc))):
                for ln in doc[pno].get_text().splitlines():
                    c = _clean_line(ln)
                    # Deduplicate: boilerplate ("www.infineon.com", the legal
                    # footer) repeats across thousands of files and would
                    # dominate the counts, teaching the model a footer rather
                    # than a datasheet.
                    if not c or c in seen_lines:
                        continue
                    seen_lines.add(c)
                    out_lines.append(c)
                    total += len(c) + 1
                    got += 1
                    if total >= args.max_bytes:
                        break
                if total >= args.max_bytes:
                    break
        except Exception:
            pass
        finally:
            doc.close()
        if got:
            used += 1
        if used % 50 == 0 and got:
            print('  %d files, %d KB' % (used, total // 1024))

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    blob = ('\n'.join(out_lines) + '\n').encode('utf-8')
    # mtime=0: gzip stamps the current time by default, which would make the
    # output differ on every rebuild even when the text is identical, defeating
    # the determinism this script otherwise goes to some trouble for.
    with gzip.GzipFile(args.out, 'wb', mtime=0) as fh:
        fh.write(blob)
    print('wrote %s: %d lines, %d KB raw, %d KB gz, from %d datasheets'
          % (args.out, len(out_lines), len(blob) // 1024,
             os.path.getsize(args.out) // 1024, used))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
