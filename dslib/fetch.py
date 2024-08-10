import asyncio
import glob
import os.path
import time

import requests
from pyppeteer.errors import PageError


def fetch_datasheet(ds_url, datasheet_path, mfr, mpn):
    ds_url_alt = None

    if ds_url.startswith('//'):
        ds_url = 'https:' + ds_url

    if mfr == 'ti':
        ds_url_alt = ds_url
        ds_url = f'https://www.ti.com/lit/ds/symlink/{mpn.lower()}.pdf'

    if not os.path.exists(datasheet_path):
        if 'infineon-technologies/fundamentals-of-power-semiconductors' in ds_url:
            print(mfr, 'skip url to', ds_url)
            return None

        if ds_url == '-':
            # asyncio.get_event_loop().run_until_complete(download_with_chromium(
            #    'https://www.mouser.de/c/?q=' + mpn, datasheet_path,
            #    click='a#pdp-datasheet_0,a#lnkDataSheet_1',
            # ))

            print('SKIP', datasheet_path, ds_url)
            return None

        else:

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


async def get_browser_page():
    global browser_page
    if browser_page is None or browser_page.isClosed():
        userDataDir = os.path.realpath(os.path.dirname(__file__) + '/chromium-user-data-dir')
        os.path.exists(userDataDir) or os.makedirs(userDataDir)
        browser = await pyppeteer.launch(dict(headless=False, userDataDir=userDataDir))
        browser_page = await browser.newPage()
    return browser_page


"""
https://stackoverflow.com/questions/50804931/how-to-download-a-pdf-that-opens-in-a-new-tab-in-puppeteer

"""


async def download_with_chromium(url, filename, click='#open-button'):

    def _check_dl():
        dl_files = glob.glob(dl_path + '/*.[pP][dD][fF]')
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

            for i in range(1, 100):
                if _check_dl():
                    return

                try:
                    await page.waitFor(click, timeout=200)
                except:
                    pass

            await page.waitFor(click, timeout=300)

            try:
                await page.click(click + ' a')
            except:
                await page.click(click)

        except PageError as e:
            # print('page error, probably direct download')
            pass

        for i in range(1, 100):
            if _check_dl():
                return
            time.sleep(.1)
        print('no downloaded file found')
    finally:
        os.rmdir(dl_path)





if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(
        # download2('https://assets.nexperia.com/documents/data-sheet/BUK763R8-80E.pdf', 'test.pdf')
        download_with_chromium(
            # 'https://rocelec.widen.net/view/pdf/rkduem07mj/ONSM-S-A0003590078-1.pdf?t.download=true&u=5oefqw',
            # 'https://rocelec.widen.net/view/pdf/rkduem07mj/ONSM-S-A0003590078-1.pdf?t.download=true&u=5oefqw',
            'https://rocelec.widen.net/view/pdf/rkduem07mj/ONSM-S-A0003590078-1.pdf?t.download=true&u=5oefqw ',
            'test.pdf')
    )
