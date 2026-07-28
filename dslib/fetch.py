import asyncio
import math
import os.path
import re
import traceback
from functools import partial
from os.path import expanduser
from typing import Union, List, Dict

import requests
from playwright.async_api import async_playwright, Page, BrowserContext, Error as PlaywrightError, \
    TimeoutError as PlaywrightTimeoutError

import dslib.discovery.onsemi
from dslib.cache import acquire_file_lock


def get_datasheet_url(mfr, mpn):
    if mfr == 'mcc':
        req = requests.get('https://www.mccsemi.com/products/search/' + mpn)
        reg = re.compile(
            r'<a target="_blank" href="?(https://www.mccsemi.com/pdf/products/' + mpn[:6] + '[-()a-z0-9]+.pdf)"?',
            re.IGNORECASE)
        m = reg.search(req.text)
        if m:
            return m.group(1)

    if mfr == 'onsemi':
        return [
            f"https://www.onsemi.com/download/data-sheet/pdf/{mpn}-d.pdf",
            ]

    if mfr == 'ti':
        return f'https://www.ti.com/lit/ds/symlink/{mpn.lower()}.pdf'

    if mfr == 'ao':
        return [
            f'https://www.aosmd.com/sites/default/files/res/datasheets/{mpn}.pdf',
            f'https://www.aosmd.com/sites/default/files/res/datasheets/{mpn}_0.pdf',
            f'https://www.aosmd.com/sites/default/files/res/datasheets/{mpn}_1.pdf',
            ]

    if mfr == 'st':
        return [
            '~/Downloads/'+mpn.lower()+'.pdf',
        ]

    # asyncio.get_event_loop().run_until_complete(download_with_chromium(
    #    'https://www.mouser.de/c/?q=' + mpn, datasheet_path,
    #    click='a#pdp-datasheet_0,a#lnkDataSheet_1',
    # ))


async def fetch_datasheet(ds_url, datasheet_path, mfr, mpn):
    ds_url_alt = None
    if isinstance(ds_url, float) and math.isnan(ds_url):
        ds_url = None
    ds_url = ds_url and ds_url.strip('- ')
    ds_url = ds_url or get_datasheet_url(mfr, mpn)


    if mfr == 'ti':
        ds_url_alt = ds_url
        ds_url = get_datasheet_url(mfr, mpn)

    if mfr == 'ao':
        ds_url_alt = ds_url
        ds_url = get_datasheet_url(mfr, mpn)

    if mfr == 'onsemi':
        #import dslib.discovery.parts_discovery
        if not requests.head(ds_url).ok:
            ds_url = dslib.discovery.onsemi.onsemi_ds_url(mpn)
        # ds_url_alt = ds_url.replace('fdb','fdp')
        # ds_url_alt = lambda : dslib.parts_discovery.onsemi_ds_url(mpn)

    if mfr == 'st':
        #ds_url_alt = ds_url
        ds_url = get_datasheet_url(mfr, mpn)

    if not ds_url or str(ds_url) == 'nan':
        print('SKIP', datasheet_path, 'no url', ds_url)
        return None

    if ('infineon-technologies/fundamentals-of-power-semiconductors' in ds_url or 'MCCProductCatalog.pdf' in ds_url):
        print(mfr, 'skip url to', ds_url)
        return None

    if isinstance(ds_url, str):
        ds_url = [ds_url]

    print('downloading', ds_url, datasheet_path)
    dp = os.path.dirname(datasheet_path)
    os.path.isdir(dp) or os.makedirs(dp)
    for du in [*ds_url, ds_url_alt]:
        if not du:
            continue

        try:
            if callable(du):
                du = du()

            if du.startswith('//'):
                du = 'https:' + du

            if not du.startswith('http'):
                if os.path.isfile(expanduser(du)):
                    import shutil
                    shutil.copyfile(expanduser(du), datasheet_path)
                    return
                else:
                    continue

            try:
                req = requests.get(du, timeout=6)
                if req.status_code == 200 and req.headers['Content-Type'].split(';')[0].lower() == 'application/pdf' and len(
                        req.content) > 10e3 and req.content.startswith(b"%PDF"):
                    with open(datasheet_path, 'wb') as f:
                        f.write(req.content)
                    return
                if req.status_code == 404:
                    continue
            except Exception as e:
                if 'not found' in str(e).lower():
                    continue
                pass

            t = download_with_chromium(du, datasheet_path)
            await t
            # asyncio.get_event_loop().run_until_complete(download_with_chromium(du, datasheet_path))
            # asyncio.run(download_with_chromium(du, datasheet_path))
        except Exception as e:
            print(traceback.format_exc())
            print('ERROR', du, e)


def download(url, filename):
    request = requests.get(url, timeout=3, stream=True, headers={'User-agent': 'Mozilla/5.0'})
    with open(filename, 'wb') as fh:
        for chunk in request.iter_content(1024 * 1024):
            fh.write(chunk)


_playwrights: Dict[int, object] = {}
browser_contexts: Dict[int, BrowserContext] = {}
browser_pages: Dict[int, Page] = {}


async def get_browser_page():
    evl_id = id(asyncio.get_event_loop())

    if evl_id not in browser_contexts:
        assert not browser_contexts
        userDataDir = os.path.realpath(os.path.dirname(__file__) + '/chromium-user-data-dir')
        os.path.exists(userDataDir) or os.makedirs(userDataDir)

        pw = await async_playwright().start()
        _playwrights[evl_id] = pw

        browser_contexts[evl_id] = await pw.chromium.launch_persistent_context(
            userDataDir,
            channel='chrome',  # use the real, up-to-date installed Chrome instead of Playwright's bundled Chromium
            headless=False,
            ignore_https_errors=True,
            accept_downloads=True,
            timeout=120000,
        )

        def on_close(evl_id):
            browser_contexts.pop(evl_id, None)
            browser_pages.pop(evl_id, None)

        browser_contexts[evl_id].on('close', partial(on_close, evl_id))

    ctx = browser_contexts[evl_id]

    if evl_id not in browser_pages or browser_pages[evl_id].is_closed():
        browser_pages[evl_id] = ctx.pages[0] if ctx.pages else await ctx.new_page()

    return browser_pages[evl_id]


async def close_browser():
    browser_pages.clear()

    for k in list(browser_contexts.keys()):
        ctx = browser_contexts.pop(k)
        try:
            await ctx.close()
        except:
            pass

    for k in list(_playwrights.keys()):
        pw = _playwrights.pop(k)
        try:
            await pw.stop()
        except:
            pass



"""
https://stackoverflow.com/questions/50804931/how-to-download-a-pdf-that-opens-in-a-new-tab-in-puppeteer

"""

_chromium_lock = asyncio.Lock()


async def download_with_chromium(url, filename, click: Union[str, List[str]] = '#open-button', eval=None, close=False,
                                 nav_timeout=90000):
    with acquire_file_lock(os.path.dirname(__file__) + '/chromium.lock', kill_holder=False, max_time=120):
        if isinstance(click, str):
            click = [click]

        print(url, 'downloading to', filename)

        page = await get_browser_page()

        # a direct link straight to a file (e.g. a PDF datasheet) - page.goto() would hand it to
        # Chrome's built-in PDF viewer, which renders it inline instead of downloading it, so no
        # 'download' event ever fires and there's no button to click. page.request is a plain
        # HTTP client bound to the browser context (same TLS fingerprint, bypasses some WAFs that
        # block requests/aiohttp) with no rendering involved, so it isn't affected by that at all.
        try:
            direct_resp = await page.request.get(url, timeout=nav_timeout)
            content_type = (direct_resp.headers.get('content-type') or '').lower()
            if direct_resp.ok and ('pdf' in content_type or 'octet-stream' in content_type):
                body = await direct_resp.body()
                dp = os.path.dirname(filename)
                os.path.isdir(dp) or os.makedirs(dp)
                with open(filename, 'wb') as f:
                    f.write(body)
                print('got direct response body', filename)
                return
        except PlaywrightError:
            pass  # not directly fetchable this way; fall through to the normal page-based flow

        downloads = []
        page.on('download', lambda d: downloads.append(d))

        try:
            try:
                # 'commit' (just the response starting), not the default 'load': some sites
                # never fire 'load' or even 'domcontentloaded' promptly (slow trackers/ads/fonts
                # keep them pending) even though the page is visually ready and interactive well
                # before that. We always separately wait_for_selector() below anyway, so goto()
                # itself doesn't need any particular load state.
                await page.goto(url, timeout=nav_timeout, wait_until='commit')
            except PlaywrightTimeoutError:
                raise
            except PlaywrightError:
                # navigation aborted, probably because it's a direct download (caught via the 'download' event above)
                pass

            if eval:
                await page.evaluate(eval)

            for c in click:
                if downloads:
                    break

                try:
                    await page.wait_for_selector(c, timeout=60000)
                except PlaywrightTimeoutError:
                    raise TimeoutError(f'selector {c!r} never appeared on {url}')

                await asyncio.sleep(1)

                sel = c + ' a' if await page.query_selector(c + ' a') else c

                try:
                    await page.click(sel)
                except PlaywrightError:
                    sel_js = sel.replace("'", "\\'")
                    await page.evaluate(f""" document.querySelector('{sel_js}').click() """)

                if len(click) > 1:
                    await asyncio.sleep(2)

            for i in range(1, 100):
                if downloads:
                    break
                await asyncio.sleep(.3)

            if not downloads:
                raise TimeoutError(f'no downloaded file found for {url}')

            dp = os.path.dirname(filename)
            os.path.isdir(dp) or os.makedirs(dp)
            await downloads[0].save_as(filename)
            print('got download', filename)
        finally:
            if close and page:
                if close == 'page':
                    await page.close()
                else:
                    await page.context.close()



async def get_text_with_chromium(url, close=False):
    with acquire_file_lock(os.path.dirname(__file__) + '/chromium.lock', kill_holder=False, max_time=120):

        page = None
        try:
            page = await get_browser_page()
            resp = await page.goto(url, wait_until='commit')
            if resp is not None and resp.status in {404}:
                print(url, 'NOT FOUND')
                return

            return await resp.text()

        finally:
            if close and page:
                if close == 'page':
                    await page.close()
                else:
                    await page.context.close()

if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(
        # download2('https://assets.nexperia.com/documents/data-sheet/BUK763R8-80E.pdf', 'test.pdf')
        download_with_chromium(
            # 'https://rocelec.widen.net/view/pdf/rkduem07mj/ONSM-S-A0003590078-1.pdf?t.download=true&u=5oefqw',
            # 'https://rocelec.widen.net/view/pdf/rkduem07mj/ONSM-S-A0003590078-1.pdf?t.download=true&u=5oefqw',
            'https://rocelec.widen.net/view/pdf/rkduem07mj/ONSM-S-A0003590078-1.pdf?t.download=true&u=5oefqw ',
            'test.pdf')
    )
