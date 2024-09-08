import asyncio
import glob
import math
import os.path
import re
import time
from typing import Union, List

import requests
from pyppeteer.errors import PageError


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
        return f"https://www.onsemi.com/download/data-sheet/pdf/{mpn}-d.pdf"

    if mfr == 'ti':
        return f'https://www.ti.com/lit/ds/symlink/{mpn.lower()}.pdf'

    # asyncio.get_event_loop().run_until_complete(download_with_chromium(
    #    'https://www.mouser.de/c/?q=' + mpn, datasheet_path,
    #    click='a#pdp-datasheet_0,a#lnkDataSheet_1',
    # ))


def fetch_datasheet(ds_url, datasheet_path, mfr, mpn):
    ds_url_alt = None
    if isinstance(ds_url, float) and math.isnan(ds_url):
        ds_url = None
    ds_url = ds_url and ds_url.strip('- ')
    ds_url = ds_url or get_datasheet_url(mfr, mpn)

    if ds_url and ds_url.startswith('//'):
        ds_url = 'https:' + ds_url

    if mfr == 'ti':
        ds_url_alt = ds_url
        ds_url = get_datasheet_url(mfr, mpn)

    if not ds_url:
        print('SKIP', datasheet_path, 'no url', ds_url)
        return None

    if ('infineon-technologies/fundamentals-of-power-semiconductors' in ds_url or 'MCCProductCatalog.pdf' in ds_url):
        print(mfr, 'skip url to', ds_url)
        return None



    print('downloading', ds_url, datasheet_path)
    dp = os.path.dirname(datasheet_path)
    os.path.isdir(dp) or os.makedirs(dp)
    for du in (ds_url, ds_url_alt):
        if not du:
            continue
        try:
            asyncio.get_event_loop().run_until_complete(download_with_chromium(du, datasheet_path))
        except Exception as e:
            print('ERROR', du, e)


def download(url, filename):
    request = requests.get(url, timeout=3, stream=True, headers={'User-agent': 'Mozilla/5.0'})
    with open(filename, 'wb') as fh:
        for chunk in request.iter_content(1024 * 1024):
            fh.write(chunk)


import pyppeteer

browser_page = None
browser = None


async def get_browser_page():
    global browser, browser_page
    if browser is None:
        userDataDir = os.path.realpath(os.path.dirname(__file__) + '/chromium-user-data-dir')
        os.path.exists(userDataDir) or os.makedirs(userDataDir)
        browser = await pyppeteer.launch(dict(headless=False, userDataDir=userDataDir))

        def on_close():
            global browser
            browser = None

        browser.on('close', on_close)

    if browser_page is None or browser_page.isClosed():
        browser_page = await browser.newPage()

    return browser_page


"""
https://stackoverflow.com/questions/50804931/how-to-download-a-pdf-that-opens-in-a-new-tab-in-puppeteer

"""


async def download_with_chromium(url, filename, click: Union[str, List[str]] = '#open-button', close=False):
    file_ext_glob = ''.join(map(lambda c: f'[{c.lower()}{c.upper()}]', filename.split('.')[-1]))

    if isinstance(click, str):
        click = [click]

    def _check_dl():
        dl_files = glob.glob(dl_path + '/*.' + file_ext_glob)
        if len(dl_files) > 0:
            print('got download', dl_files[0])
            os.rename(dl_files[0], filename)
            return True
        return False

    dl_path = os.path.realpath(filename + '_downloads')
    if os.path.exists(dl_path):
        import shutil
        shutil.rmtree(dl_path)
    assert not os.path.exists(dl_path), dl_path
    page = None
    try:
        os.path.isdir(dl_path) or os.makedirs(dl_path)

        print('download folder', dl_path)

        page = await get_browser_page()

        await page._client.send('Page.setDownloadBehavior', {
            'behavior': 'allow',
            'downloadPath': dl_path,
        })

        try:
            resp = await page.goto(url)
            if resp.status in {404}:
                print(url, 'NOT FOUND')
                return

            for c in click:

                for i in range(1, 100):
                    if _check_dl():
                        return

                    try:
                        await page.waitFor(c, timeout=200)
                        break
                    except Exception as e:
                        # print(e)
                        pass

                    # await page.evaluate(""" document.querySelector('a[data-track-name="downloadLink"]').click() """)

                await page.waitFor(c, timeout=300)

                await asyncio.sleep(1)

                try:
                    await page.click(c + ' a')
                except:
                    await page.click(c)

        except PageError as e:
            # print('page error, probably direct download')
            pass

        for i in range(1, 100):
            if _check_dl():
                return
            time.sleep(.3)
        print('no downloaded file found')
    finally:
        os.rmdir(dl_path)
        if close and page:
            if close == 'page':
                await page.close()
            else:
                await page.browser.close()
            # await page.close()


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(
        # download2('https://assets.nexperia.com/documents/data-sheet/BUK763R8-80E.pdf', 'test.pdf')
        download_with_chromium(
            # 'https://rocelec.widen.net/view/pdf/rkduem07mj/ONSM-S-A0003590078-1.pdf?t.download=true&u=5oefqw',
            # 'https://rocelec.widen.net/view/pdf/rkduem07mj/ONSM-S-A0003590078-1.pdf?t.download=true&u=5oefqw',
            'https://rocelec.widen.net/view/pdf/rkduem07mj/ONSM-S-A0003590078-1.pdf?t.download=true&u=5oefqw ',
            'test.pdf')
    )
