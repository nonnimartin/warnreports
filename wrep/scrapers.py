from __future__ import annotations

import csv
import functools
import glob
import itertools
import json
import re
import time
from importlib import import_module
from pathlib import Path
from typing import Iterable, Iterator, Mapping

import requests
from bs4 import BeautifulSoup

import warn.cache
import warn.runner
import warn.utils

from . import utils
from .utils import Stage

scrapers: dict[str, type[Scraper]] = {}
logger = utils.get_logger('scrapers')

class Scraper:

    state: str
    base_url: str|None = None
    public_url: str|None = None
    request_delay = 0

    def __init__(self):
        stage = Stage.Extract
        self.file = stage.file(self.state)
        self.runner = warn.runner.Runner(stage.dir, stage.dir/'cache')
        self.cache = warn.cache.Cache(self.runner.cache_dir/self.state.lower())
        self.session = requests.session()
        self.request_count = 0
        self._scraper = get_scraper_module(self.state)
        if self._scraper and not self.public_url:
            src = getattr(self._scraper, '__source__', None)
            if isinstance(src, Mapping) and 'url' in src:
                self.public_url = src['url']

    def clean(self) -> None:
        self.file.unlink(missing_ok=True)

    def scrape(self) -> None:
        self.runner.scrape(self.state)

    def get_url(self, url: str, **kw):
        if not url.startswith('http://') and not url.startswith('https://') and self.base_url:
            url = self.base_url.rstrip('/') + '/' + url.lstrip('/')
        if self.request_delay and self.request_count:
            logger.debug(f'request delay: {self.request_delay}s')
            time.sleep(self.request_delay)
        kw.setdefault('session', self.session)
        rep = warn.utils.get_url(url, **kw)
        self.request_count += 1
        rep.raise_for_status()
        return rep

    def fetch(self, url: str, **kw) -> str:
        return self.get_url(url, **kw).content.decode()

    def __init_subclass__(cls, state: str|None = None) -> None:
        if state:
            cls.state = state.upper()
            scrapers[cls.state] = cls


class AK(Scraper, state='AK'):

    base_url = 'https://jobs.alaska.gov'
    scrape_url = f'{base_url}/RR/WARN_notices.htm'
    public_url = scrape_url

    def scrape(self):
        key = 'latest.html'
        content = self.get_url(self.scrape_url).content.decode()
        self.cache.write(key, content)
        doc = BeautifulSoup(content, 'html.parser')
        table = doc.find('table')
        with self.file.open('w') as file:
            writer = csv.writer(file)
            writer.writerows(self.read_table(table))

    def read_table(self, table: BeautifulSoup) -> Iterator[list[str]]:
        tags = ['td']
        pat = re.compile(r'[\s\n]+')
        for tr in table.find_all('tr'):
            tds = tr.find_all(tags)
            if len(tds) < 2:
                continue
            values = [pat.sub(' ', td.text).strip() for td in tds]
            if not values[0]:
                continue
            values.append(self.parse_url(tds[0]))
            yield values

    def parse_url(self, td: BeautifulSoup) -> str:
        if td.text.strip() == 'Company':
            return 'url'
        a = td.find('a')
        if a:
            return self.base_url + a['href']
        return ''

class DE(Scraper, state='DE'):
    base_url = 'https://joblink.delaware.gov'
    index_url_template = '/search/warn_lookups?commit=Search&page={page}&q%5Bs%5D=notice_on+desc'
    request_delay = 1
    index_headers = ['Employer', 'City', 'ZIP', 'LWIB Area', 'Notice Date', 'WARN Type', 'URL']
    record_headers = ['Company Name', 'Address', 'Notice Date', 'Number of Employees Affected']

    def scrape(self):
        self.scrape_index()
        self.download_record_pages()
        self.write_csv()

    def scrape_index(self):
        index: list[dict[str, str]] = []
        for table in self.fetch_index_tables():
            tbody = table.find('tbody')
            for tr in tbody.find_all('tr'):
                row = dict.fromkeys(self.index_headers, '')
                for key, td in zip(self.index_headers[:-1], tr.find_all('td')):
                    row[key] = td.text.strip()
                row['URL'] = tr.find('td').find('a')['href']
                index.append(row)
        self.cache.write('index.json', json.dumps(index, indent=2))

    def download_record_pages(self):
        for row in self.load_index():
            url = row['URL']
            record_num = self.parse_record_number_from_path(url)
            key = self.get_record_number_cache_key(record_num)
            if self.cache.exists(key):
                logger.debug(f'Using cache {key}')
                continue
            self.cache.write(key, self.fetch(url))

    def read_records(self) -> Iterator[dict[str, str]]:
        for row in self.load_index():
            url = row['URL']
            record_num = self.parse_record_number_from_path(url)
            key = self.get_record_number_cache_key(record_num)
            page = BeautifulSoup(self.cache.read(key), 'html.parser')
            section = page.find(id='primaryContent')
            div = section.find('div', {'class': 'definition-list'})
            record = {}
            for h3 in div.find_all('h3'):
                record[h3.text.strip()] = h3.find_next('p').text.strip()
            for key, value in row.items():
                if not record.get(key):
                    record[key] = value
            yield record

    def write_csv(self):
        headers = list(self.get_headers())
        with self.file.open('w') as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()
            writer.writerows(self.read_records())

    def fetch_index_tables(self) -> Iterator[BeautifulSoup]:
        page = 1
        while True:
            key = f'pages/{page}.html'
            url = self.index_url_template.format(page=page)
            text = self.fetch(url)
            doc = BeautifulSoup(text, 'html.parser')
            table = doc.find('table')
            if not table:
                break
            if 'no matches for your search results' in text:
                logger.debug(f'No matches for {page=}')
                break
            self.cache.write(key, text)
            yield table
            page += 1

    def load_index(self) -> list[dict[str, str]]:
        return json.loads(self.cache.read('index.json'))

    def get_record_number_cache_key(self, record_num: int) -> str:
        return f'records/{record_num}.html'

    def parse_record_number_from_path(self, href: str) -> int:
        return int(href.rsplit('/')[-1].removesuffix('.html'))

    @classmethod
    def get_headers(cls):
        done = set()
        for value in (cls.record_headers + cls.index_headers):
            if value not in done:
                yield value
            done.add(value)


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
        self.session.headers = {'User-Agent': self.user_agent}
        rep = self.session.post(self.api_url, data=self.get_api_payload())
        rep.raise_for_status()
        for listing in rep.json()['data']:
            a = BeautifulSoup(listing[0], 'html5lib').find('a')
            yield a.text, [a['href'], listing[2]]

    def get_api_payload(self):
        rep = self.get_url(self.public_url)
        rep.raise_for_status()
        doc = BeautifulSoup(rep.text, 'html5lib')
        return dict(self.payload, nonce=self.extract_nonce(doc))

    def extract_nonce(self, doc: BeautifulSoup) -> str|None:
        script = doc.find(
            'script',
            text=lambda text: text and 'window.gvDTglobals.push' in text)
        match = re.search(r'"nonce":"([^"]+)"', str(script))
        if match:
            return match.group(1)

    payload = dict(
        columns=[
            dict(data=i, name=name, searchable=True, orderable=True, search={})
            for i, name in enumerate(['gv_96', 'gv_4', 'gv_date_created', 'gv_97'])],
        order=[dict(column=0, dir='asc')],
        draw=1,
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

class IN(Scraper, state='IN'):
    base_url = 'https://www.in.gov'
    scrape_url = f'{base_url}/dwd/warn-notices/current-warn-notices/'
    public_url = scrape_url

    def scrape(self) -> None:
        key = 'latest.html'
        content = self.get_url(self.scrape_url).content.decode()
        self.cache.write(key, content)
        doc = BeautifulSoup(content, 'html.parser')
        with self.file.open('w') as file:
            writer = csv.writer(file)
            for table in doc.find_all('table'):
                writer.writerows(self.read_table(table))

    def read_table(self, table: BeautifulSoup) -> Iterator[list[str]]:
        tags = ['td', 'th']
        for tr in table.find_all('tr'):
            tds = tr.find_all(tags)
            if not tds:
                continue
            last = tds.pop()
            values = [td.text.strip() for td in tds]
            values.append(self.parse_url(last))
            yield values

    def parse_url(self, cell: BeautifulSoup) -> str:
        if cell.name == 'th':
            return 'url'
        a = cell.find('a')
        if a:
            return self.base_url + a['href']
        return cell.text.strip()

class FL(Scraper, state='FL'):

    def scrape(self) -> None:
        super().scrape()
        self.augment()

    def augment(self):
        lookup = dict(self.fetch_lookup())
        newfile = Path(f'{self.file}.new')
        with newfile.open('w') as file:
            writer = csv.writer(file)
            with self.file.open() as file:
                reader = csv.reader(file)
                writer.writerow(next(reader) + ['download'])
                for values in reader:
                    key = self.row_key(values)
                    values.append(lookup.get(key, ''))
                    writer.writerow(values)
        newfile.rename(self.file)

    def fetch_lookup(self):
        for file in glob.glob(f'{self.cache.path}/*_page_*.html'):
            with open(file) as f:
                doc = BeautifulSoup(f, 'html5lib')
            table = doc.find('table')
            tbody = table.find('tbody')
            for tr in tbody.find_all('tr'):
                tds = tr.find_all('td')
                last = tds.pop()
                if last.find('input', id='download'):
                    el = last.find('input', type='hidden')
                    if el:
                        key = self.row_key(td.text for td in tds)
                        yield key, el['value']

    def row_key(self, values: Iterable[str]) -> str:
        return ''.join(re.sub(r'\s', '', value) for value in values)

warn_scraper_names = warn.utils.get_all_scrapers()

@functools.cache
def get_scraper_module(state: str):
    state = state.lower()
    if state in warn_scraper_names:
        return import_module(f'warn.scrapers.{state}')

def create_scraper(state: str):
    class DefaultScraper(Scraper):
        pass
    DefaultScraper.state = state
    return DefaultScraper

for state in map(str.upper, warn_scraper_names):
    if state not in scrapers:
        scrapers[state] = create_scraper(state)
del(state)

class Command(utils.BaseCommand):

    @classmethod
    def add_arguments(cls, parser: utils.ArgumentParser) -> None:
        parser.add_argument('states', nargs='*', choices=scrapers)
        parser.add_argument('--limit', '-l', type=int, default=10)
    
    def run(self):
        states = self.opts.states or scrapers
        for state in states:
            scraper = scrapers[state]()
            with utils.csvdicts(scraper.file) as reader:
                it = itertools.islice(reader, self.opts.limit)
                fixed = dict(state=state)
                rows = [fixed | row for row in it]
                print(json.dumps(rows, indent=2, default=utils.json_default))

if __name__ == '__main__':
    try:
        Command.main()
    except BrokenPipeError:
        pass