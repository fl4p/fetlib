"""The parts-list download guard (dslib/discovery/download_parts_list).

The class it exists for: download_parts_list used to check os.path.isfile and
nothing else, so whatever Chromium saved under the requested name became the
parts list. On 2026-08-08 an 8 MB onsemi anti-bot page was sitting in
parts-lists/onsemi/low-medium-voltage-mosfets-2026-08.csv, and because the file
EXISTED every later run skipped the download and died on it identically. A
failed download had persisted itself as data.

Two directions matter and both are pinned here:
  * a bad download must never be accepted, and must never be LEFT BEHIND (that
    is what turns a transient block into a permanent one);
  * a manufacturer must never be silently dropped -- a part that was never
    discovered is indistinguishable from a part that lost on merit -- so the
    fallback to an earlier export is announced, and the no-fallback case raises.
"""
import asyncio
import os
import unittest.mock as mock

import pytest

from dslib.discovery import download_parts_list, parts_list_content_error

CSV = b'"Product","Vds"\n"AOT412","40"\n'
HTML = b'<!DOCTYPE HTML>\n<html lang="en">\n<head><title>Just a moment</title>\n'
XLSX = b'PK\x03\x04' + b'\x00' * 64


# --------------------------------------------------------------------------
# the content check itself, calibrated in both directions
# --------------------------------------------------------------------------

@pytest.mark.parametrize('content,ext,expect_error', [
    (CSV, 'csv', False),
    (b'\xef\xbb\xbf"Product","Status"\n', 'csv', False),   # BOM, as the AO export ships
    (HTML, 'csv', True),
    (b'<html><body>blocked', 'csv', True),
    (b'<?xml version="1.0"?><err/>', 'csv', True),
    (b'', 'csv', True),
    (b'   \n\t\n', 'csv', True),
    (XLSX, 'xlsx', False),
    (HTML, 'xlsx', True),
    (b'not a zip at all', 'xlsx', True),
])
def test_content_error_direction(tmp_path, content, ext, expect_error):
    fn = tmp_path / ('x.' + ext)
    fn.write_bytes(content)
    err = parts_list_content_error(str(fn), ext)
    assert bool(err) is expect_error, (content[:20], ext, err)


def test_a_missing_file_is_an_error_not_a_pass():
    """Absence of evidence must not encode absence of the problem."""
    assert parts_list_content_error('/nonexistent/nope.csv', 'csv')


# --------------------------------------------------------------------------
# download_parts_list end to end
# --------------------------------------------------------------------------

def _run(mfr='testmfr', prefix='mosfet', ext='csv'):
    return asyncio.run(download_parts_list(
        mfr, url='https://example.invalid/list', fn_ext=ext, prefix=prefix))


def _stub(writes=None, raises=None):
    """Stand in for download_with_chromium: write `writes`, or raise."""
    async def _dl(url, filename, **kw):
        if raises is not None:
            raise raises
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'wb') as f:
            f.write(writes)
    return mock.patch('dslib.fetch.download_with_chromium', _dl)


def _prior(tmp_path, name, content):
    """Create an earlier export; returns the repo-RELATIVE path the code uses."""
    d = tmp_path / 'parts-lists' / 'testmfr'
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(content)
    return os.path.join('parts-lists', 'testmfr', name)


def test_a_good_download_is_returned_and_kept(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with _stub(writes=CSV):
        fn = _run()
    assert os.path.isfile(fn) and open(fn, 'rb').read() == CSV


def test_a_bad_download_is_deleted_so_the_block_cannot_become_permanent(tmp_path, monkeypatch):
    """The actual 2026-08-08 failure: leaving the challenge page behind made
    every subsequent run skip the download and fail the same way."""
    monkeypatch.chdir(tmp_path)
    good = _prior(tmp_path, 'mosfet-2026-07.csv', CSV)
    with _stub(writes=HTML):
        with pytest.warns(UserWarning, match='FALLING BACK'):
            fn = _run()
    assert fn == good, 'must fall back to the earlier valid export'
    written = tmp_path / 'parts-lists' / 'testmfr'
    leftovers = [p.name for p in written.iterdir() if p.name != 'mosfet-2026-07.csv']
    assert not leftovers, 'the rejected download must not be left on disk: %s' % leftovers


def test_a_download_that_raises_also_falls_back(tmp_path, monkeypatch):
    """nexperia's export button timed out and took all 27 manufacturers with it."""
    monkeypatch.chdir(tmp_path)
    good = _prior(tmp_path, 'mosfet-2026-07.csv', CSV)
    with _stub(raises=TimeoutError('selector never appeared')):
        with pytest.warns(UserWarning, match='FALLING BACK'):
            assert _run() == good


def test_the_fallback_skips_earlier_exports_that_are_themselves_corrupt(tmp_path, monkeypatch):
    """Newest-first is not enough: a poisoned newer file must be passed over."""
    monkeypatch.chdir(tmp_path)
    good = _prior(tmp_path, 'mosfet-2026-05.csv', CSV)
    _prior(tmp_path, 'mosfet-2026-07.csv', HTML)   # newer, but garbage
    with _stub(writes=HTML):
        with pytest.warns(UserWarning, match='FALLING BACK'):
            assert _run() == good


def test_no_usable_export_raises_rather_than_skipping_the_manufacturer(tmp_path, monkeypatch):
    """Returning None/'' here would drop a whole manufacturer from the corpus,
    and a part that was never discovered looks exactly like one that lost."""
    monkeypatch.chdir(tmp_path)
    with _stub(writes=HTML):
        with pytest.raises(RuntimeError, match='no earlier export'):
            _run()


def test_a_previously_saved_bad_file_is_caught_without_any_download(tmp_path, monkeypatch):
    """os.path.isfile proves the file exists, not that it works."""
    monkeypatch.chdir(tmp_path)
    import datetime
    cur = datetime.datetime.now().strftime('mosfet-%Y-%m.csv')
    _prior(tmp_path, cur, HTML)
    good = _prior(tmp_path, 'mosfet-2020-01.csv', CSV)

    async def _never(url, filename, **kw):
        raise AssertionError('must not re-download: the file already existed')

    with mock.patch('dslib.fetch.download_with_chromium', _never):
        with pytest.warns(UserWarning, match='FALLING BACK'):
            assert _run() == good


def test_xlsx_downloads_are_validated_as_containers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with _stub(writes=XLSX):
        assert os.path.isfile(_run(ext='xlsx'))
    monkeypatch.chdir(tmp_path)
    with _stub(writes=HTML):
        with pytest.raises(RuntimeError):
            _run(prefix='other', ext='xlsx')
