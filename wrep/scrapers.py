from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterator

import requests
from bs4 import BeautifulSoup

import warn.runner
import warn.utils

from . import utils
from .utils import Stage

scrapers: dict[str, type[Scraper]] = {}
logger = utils.get_logger('scrapers')

class Scraper:

    def __init__(self, state: str) -> None:
        self.state = state.upper()
        self.file = Stage.Extract.file(self.state)

    def clean(self) -> None:
        self.file.unlink(missing_ok=True)

    def scrape(self) -> None:
        scraper = warn.runner.Runner(Stage.Extract.dir, Stage.Extract.dir/'cache')
        scraper.scrape(self.state)

    def __init_subclass__(cls, state: str|None = None) -> None:
        if state:
            scrapers[state.upper()] = cls


class AK(Scraper, state='AK'):

    base_url = 'https://jobs.alaska.gov'
    scrape_url = f'{base_url}/RR/WARN_notices.htm'

    def scrape(self):
        rep = warn.utils.get_url(self.scrape_url)
        rep.encoding = 'utf-8'
        soup = BeautifulSoup(rep.text, 'html.parser')
        trs = soup.find('table').find_all('tr')
        with self.file.open('w') as file:
            writer = csv.writer(file)
            for i, tr in enumerate(trs):
                url = '' if i > 0 else 'url'
                row = []
                for j, td in enumerate(tr.find_all('td')):
                    if i > 1 and j == 0:
                        a = td.find('a')
                        if a:
                            url = self.base_url + a['href']
                    text = re.sub(r'[\s\n]+', ' ', td.text).strip()
                    row.append(text)
                if len(row) < 2 or not row[0]:
                    continue
                row.append(url)
                writer.writerow(row)

class GA(Scraper, state='GA'):
    base_url = 'https://www.tcsg.edu'
    public_url = f'{base_url}/warn-public-view/'
    api_url = f'{base_url}/wp-admin/admin-ajax.php'
    user_agent = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36')

    extra_columns = ['entry_url', 'submitted_date']

    def scrape(self):
        super().scrape()
        self.augment()

    def augment(self):
        logger.info('Augmenting scraped data')
        entries = dict(self.fetch_entries())
        fillrow = [''] * len(self.extra_columns)
        newfile = Path(f'{self.file}.new')
        with newfile.open('w') as file:
            writer = csv.writer(file)
            with self.file.open() as file:
                reader = csv.reader(file)
                writer.writerow(next(reader) + self.extra_columns)
                for values in reader:
                    extra = entries.get(values[0]) or fillrow
                    writer.writerow(values + extra)
        newfile.rename(self.file)

    def fetch_entries(self) -> Iterator[tuple[str, list[str]]]:
        logger.info('Fetching entries')
        self.session = requests.session()
        self.session.headers = {'User-Agent': self.user_agent}
        rep = self.session.post(self.api_url, data=self.get_api_payload())
        rep.raise_for_status()
        for listing in rep.json()['data']:
            a = BeautifulSoup(listing[0], 'html5lib').find('a')
            yield a.text, [a['href'], listing[2]]

    def get_api_payload(self):
        rep = warn.utils.get_url(self.public_url, session=self.session)
        rep.raise_for_status()
        soup = BeautifulSoup(rep.text, 'html5lib')
        return dict(self.payload, nonce=self.extract_nonce(soup))

    def extract_nonce(self, soup: BeautifulSoup) -> str|None:
        script = str(
            soup.find(
                'script',
                text=lambda text: text and 'window.gvDTglobals.push' in text))
        match = re.search(r'"nonce":"([^"]+)"', script)
        if match:
            return match.group(1)

    payload = dict(
        draw=1,
        columns=[
            dict(
                data=i,
                name=name,
                searchable=True,
                orderable=True,
                search={})
            for i, name in enumerate(['gv_96', 'gv_4', 'gv_date_created', 'gv_97'])],
        order=[dict(column=0, dir='asc')],
        start=0,
        length=-1,
        search={},
        action='gv_datatables_data',
        view_id=77460,
        post_id=77462,
        getData=[],
        hideUntilSearched=0,
        setUrlOnSearch=True,
        shortcode_atts=dict(id=77460))
