from __future__ import annotations

import csv
import re

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

    baseurl = 'https://jobs.alaska.gov'

    def scrape(self):
        rep = warn.utils.get_url(f'{self.baseurl}/RR/WARN_notices.htm')
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
                            url = self.baseurl + a['href']
                    text = re.sub(r'[\s\n]+', ' ', td.text).strip()
                    row.append(text)
                if len(row) < 2 or not row[0]:
                    continue
                row.append(url)
                writer.writerow(row)
