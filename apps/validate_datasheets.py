#!/usr/bin/env python3
"""Validate every datasheet PDF and emit an HTML report.

For each ``datasheets/<mfr>/<mpn>.pdf`` (skipping derivative outputs whose
name contains ``.pdf.``):

1. Extract text with ``dslib.pdf.parse.extract_text(try_ocr=False,
   auto_decrypt=True)``.
2. Run ``validate_datasheet_text(mfr, mpn, text, return_reason=True)``.
3. Whenever the validator returns a *string* (i.e. invalid: ``no-text``,
   ``mpn-not-found``, or an exception name), record it.

Writes ``out/validation.html`` with one section per manufacturer linking to
the PDFs that failed validation.
"""

from __future__ import annotations

import argparse
import html
import os
import pathlib
import sys
from typing import Dict, Optional

from dslib.pdf.parse import extract_text, validate_datasheet_text
from dslib.pdf.pipeline import pdf2pdf
from dslib.util import open_file_with_default_app, run_parallel


# ---------- per-PDF job -----------------------------------------------------

def _validate_one(pdf_path: str) -> Optional[str]:
    """Returns the reason if invalid (or 'error: …' on exception); None if valid."""
    mfr = pathlib.Path(pdf_path).parent.name
    mpn = pathlib.Path(pdf_path).stem
    try:
        text, _meta = extract_text(pdf_path, try_ocr=False, auto_decrypt=True)
    except Exception as e:
        return f'error: {type(e).__name__}: {e}'
    try:
        result = validate_datasheet_text(mfr, mpn, text, return_reason=True)
        if result != True and 'no-text' not in result and '.fixenc.' not in pdf_path:
            out_path = pdf_path + '.fixenc.pdf'
            pdf2pdf(pdf_path, out_path, 'fix_font_enc')
            text, _meta = extract_text(out_path, try_ocr=False, auto_decrypt=True)
            result = validate_datasheet_text(mfr, mpn, text, return_reason=True)
            if result == True:
                result = 'pdf-fixed'
                print(pdf_path, 'PDF fixed!')
    except Exception as e:
        return f'validator-error: {type(e).__name__}: {e}'
    return result if isinstance(result, str) else None


def _find_pdfs(root: str) -> list[str]:
    """Yield original-PDF paths (excludes derivatives whose name contains `.pdf.`)."""
    paths = []
    for p in pathlib.Path(root).rglob('*.pdf'):
        if '.pdf.' in p.name:
            continue
        paths.append(str(p))
    return sorted(paths)


# ---------- HTML report -----------------------------------------------------

_HTML_HEAD = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Datasheet validation</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 1200px; margin: 2em auto; padding: 0 1em; color: #222; }
  h1 { margin-bottom: 0.2em; }
  h2 { margin-top: 1.6em; border-bottom: 1px solid #ddd; padding-bottom: 0.2em; }
  table { border-collapse: collapse; width: 100%; }
  td, th { padding: 4px 10px; text-align: left; border-bottom: 1px solid #eee;
           font-size: 13px; }
  th { background: #fafafa; }
  td.reason { font-family: ui-monospace, "SF Mono", Menlo, monospace;
              color: #b00; white-space: pre; }
  td.reason.err { color: #777; }
  tr:hover { background: #f7f7f7; }
  .summary { color: #666; margin: 1em 0; }
  a { color: #06c; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .totals span { margin-right: 1.5em; font-family: ui-monospace, monospace; }
</style>
</head><body>
"""


def _render_html(results: Dict[str, Optional[str]], out_path: str) -> None:
    bad = sorted((p, r) for p, r in results.items() if r is not None)
    n_total = len(results)

    by_mfr: Dict[str, list] = {}
    reason_counts: Dict[str, int] = {}
    for path, reason in bad:
        mfr = pathlib.Path(path).parent.name
        by_mfr.setdefault(mfr, []).append((path, reason))
        key = reason.split(':', 1)[0] if reason.startswith(('error:', 'validator-error:')) \
            else reason
        reason_counts[key] = reason_counts.get(key, 0) + 1

    out_dir = os.path.dirname(os.path.abspath(out_path))
    parts = [_HTML_HEAD,
             '<h1>Datasheet validation</h1>',
             f'<p class="summary">{len(bad)} of {n_total} PDFs failed validation.</p>',
             '<p class="totals">'
             + ''.join(f'<span><b>{html.escape(k)}</b>: {v}</span>'
                       for k, v in sorted(reason_counts.items(), key=lambda kv: -kv[1]))
             + '</p>']

    for mfr in sorted(by_mfr):
        items = by_mfr[mfr]
        parts.append(f'<h2>{html.escape(mfr)} <small>({len(items)})</small></h2>')
        parts.append('<table>')
        parts.append('<tr><th style="width:50%">MPN</th><th>Reason</th></tr>')
        for path, reason in sorted(items):
            mpn = pathlib.Path(path).stem
            rel = os.path.relpath(os.path.abspath(path), out_dir)
            klass = 'reason err' if reason.startswith(('error:', 'validator-error:')) \
                else 'reason'
            parts.append(
                f'<tr><td><a href="{html.escape(rel)}">{html.escape(mpn)}</a></td>'
                f'<td class="{klass}">{html.escape(reason)}</td></tr>')
        parts.append('</table>')

    parts.append('</body></html>')
    pathlib.Path(out_path).write_text('\n'.join(parts), encoding='utf-8')


# ---------- entry point -----------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--root', default='datasheets',
                    help='directory containing <mfr>/<mpn>.pdf (default: datasheets)')
    ap.add_argument('--out', default='out/validation.html',
                    help='output HTML path (default: out/validation.html)')
    ap.add_argument('-j', '--jobs', type=int, default=256,
                    help='max parallel workers (default: 256, capped by CPU count)')
    ap.add_argument('--backend', default='multiprocessing',
                    choices=['multiprocessing', 'threading'])
    ap.add_argument('--limit', type=int, default=0,
                    help='only validate the first N PDFs (0 = all, for smoke testing)')
    args = ap.parse_args(argv)

    paths = _find_pdfs(args.root)
    if args.limit:
        paths = paths[:args.limit]
    print(f'Validating {len(paths)} PDFs from {args.root}/ …', file=sys.stderr)

    jobs = {p: (_validate_one, p) for p in paths}
    results = run_parallel(jobs, max_concurrency=args.jobs, backend=args.backend)

    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    _render_html(results, args.out)

    n_bad = sum(1 for r in results.values() if r is not None)
    print(f'\n{n_bad} of {len(results)} failed validation', file=sys.stderr)
    print(f'wrote {args.out}', file=sys.stderr)
    open_file_with_default_app(args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
