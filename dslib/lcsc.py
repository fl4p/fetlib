import glob
import os

#from html.parser import HTMLParser
from pyquery import PyQuery

from dslib import mfr_tag
from dslib.fetch import fetch_datasheet


def read_lcsc_search_results(html_glob_path):

    files = sorted(glob.glob(html_glob_path))

    for filename in files:
        with open(filename, 'r') as f:
            pq = PyQuery(f.read())
        for tr in pq('tr'):
            trq = pq(tr)

            links = list(pq(a) for a in trq.find('a.hoverUnderline[target="_blank"][href^="https://www.lcsc.com/product-detail"]'))
            if not links:
                print('skip row')
                continue
            mpn = links[0].text()
            lcsc_num = links[1].text()

            mnf_links = list(pq(a) for a in
                         trq.find('a.hoverUnderline[target="_blank"][href^="https://www.lcsc.com/brand-detail"]'))
            assert len(mnf_links) == 1
            mfr =  mfr_tag(mnf_links[0].text())
            ds_url =  trq.find('a.datasheet').attr('href')

            if ds_url == 'https://www.lcsc.com/':
                ds_url = None

            print(mfr, mpn, lcsc_num, ds_url)

            if ds_url:
                ds_url = ds_url.replace('https://www.lcsc.com/datasheet/lcsc_datasheet_',
                                        'https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/')

                datasheet_path = os.path.join('../datasheets', mfr, mpn + '.pdf')
                fetch_datasheet(ds_url, datasheet_path, mfr=mfr, mpn=mpn)


if __name__ == '__main__':
    read_lcsc_search_results('../search-results/lcsc/80v 26a 10mohm p*.html')