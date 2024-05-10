from __future__ import annotations

import csv
import functools
import json
import re
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import timezone
from importlib import import_module
from itertools import chain
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import pdfplumber
import requests
from bs4 import BeautifulSoup as Soup

import warn.cache
import warn.runner
import warn.utils

from . import settings, utils
from .utils import Stage

scrapers: dict[str, type[Scraper]] = {}
logger = utils.get_logger('scrapers')

class Scraper(ABC):

    state: str
    base_url: str|None = None
    public_url: str|None = None
    request_delay = 0

    def __init__(self):
        stage = Stage.Extract
        stage_dir = settings.BUILD_DIR/stage
        self.file = stage_dir/f'{self.state.lower()}.csv'
        self.runner = warn.runner.Runner(stage_dir, stage_dir/'cache')
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

    def fetch(self, url: str, **kw) -> str:
        return self.get_url(url, **kw).content.decode()

    def get_url(self, url: str, **kw) -> requests.Response:
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

    def stats(self) -> dict[str, Any]:
        return dict(
            hash=utils.hashfile(self.file),
            size=self.file.stat().st_size)

    @contextmanager
    def reader(self):
        with self.file.open() as file:
            yield csv.DictReader(file, restkey='__')

    @contextmanager
    def ctx_rewrite(self):
        newfile = Path(f'{self.file}.rewrite')
        with self.file.open() as reader:
            with newfile.open('w') as writer:
                yield csv.reader(reader), csv.writer(writer)
        newfile.rename(self.file)

    def __init_subclass__(cls, state: str|None = None) -> None:
        if state:
            cls.state = state.upper()
            scrapers[cls.state] = cls

class CommonScraper(Scraper):
    headers: Sequence[str] = ()
    index_url: str

    def get_headers(self) -> Sequence[str]:
        return self.headers

    @abstractmethod
    def read_records(self) -> Iterable[dict[str, str]]: ...

    def write_csv(self) -> None:
        with self.file.open('w') as file:
            writer = csv.DictWriter(file, fieldnames=self.get_headers())
            writer.writeheader()
            writer.writerows(self.read_records())

    def scrape_index(self) -> None:
        self.cache.write('latest.html', self.fetch(self.index_url))

class AK(CommonScraper, state='AK'):
    base_url = 'https://jobs.alaska.gov'
    index_url = f'{base_url}/RR/WARN_notices.htm'
    public_url = index_url
    headers = ['Company', 'Location', 'Notice Date', 'Layoff Date', 'Employees Affected', 'Notes', 'url']
    space_pat = re.compile(r'[\s\n]+')

    def scrape(self) -> None:
        self.scrape_index()
        self.write_csv()

    def read_records(self) -> Iterator[dict[str, str]]:
        doc = bs(self.cache.read('latest.html'))
        it = self.read_table(doc.find('table'))
        headers = next(it)
        for values in it:
            yield dict(zip(headers, values))

    def read_table(self, table: Soup) -> Iterator[list[str]]:
        for tr in table.find_all('tr'):
            values = [*self.read_tr(tr), self.parse_url(tr)]
            if len(values) > 2 and values[0]:
                yield values

    def read_tr(self, tr: Soup) -> Iterator[str]:
        for td in tr.find_all('td'):
            yield self.space_pat.sub(' ', td.text).strip()

    def parse_url(self, tr: Soup) -> str:
        td = tr.find('td')
        if td.text.strip() == 'Company':
            return 'url'
        a = td.find('a')
        if a:
            return self.base_url + a['href']
        return ''

class DE(CommonScraper, state='DE'):
    base_url = 'https://joblink.delaware.gov'
    index_url_template = '/search/warn_lookups?commit=Search&page={page}&q%5Bs%5D=notice_on+desc'
    request_delay = 1
    index_headers = ['Employer', 'City', 'ZIP', 'LWIB Area', 'Notice Date', 'WARN Type', 'URL']
    record_headers = ['Company Name', 'Address', 'Notice Date', 'Number of Employees Affected']
    headers = list(utils.unique(chain(record_headers, index_headers)))

    def scrape(self) -> None:
        self.scrape_index()
        self.download_pages()
        self.write_csv()

    def scrape_index(self) -> None:
        index: list[dict[str, str]] = []
        for table in self.fetch_index_tables():
            tbody = table.find('tbody')
            for tr in tbody.find_all('tr'):
                row = dict.fromkeys(self.index_headers, '')
                for key, td in zip(self.index_headers[:-1], tr.find_all('td')):
                    row[key] = td.text.strip()
                href = tr.find('td').find('a')['href']
                row['URL'] = href
                row['record_num'] = str(int(href.rsplit('/')[-1].removesuffix('.html')))
                index.append(row)
        self.cache.write('index.json', json.dumps(index, indent=2))

    def download_pages(self) -> None:
        for row in self.load_index():
            record_num = row.pop('record_num')
            key = f'records/{record_num}.html'
            if not self.cache.exists(key):
                self.cache.write(key, self.fetch(row['URL']))

    def read_records(self) -> Iterator[dict[str, str]]:
        for row in self.load_index():
            record_num = row.pop('record_num')
            key = f'records/{record_num}.html'
            page = bs(self.cache.read(key))
            section = page.find(id='primaryContent')
            div = section.find('div', {'class': 'definition-list'})
            record = {}
            for h3 in div.find_all('h3'):
                record[h3.text.strip()] = h3.find_next('p').text.strip()
            for key, value in row.items():
                if not record.get(key):
                    record[key] = value
            yield record

    def fetch_index_tables(self) -> Iterator[Soup]:
        page = 1
        while True:
            key = f'pages/{page}.html'
            url = self.index_url_template.format(page=page)
            text = self.fetch(url)
            doc = bs(text)
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

class GA(Scraper, state='GA'):
    base_url = 'https://www.tcsg.edu'
    public_url = f'{base_url}/warn-public-view/'
    api_url = f'{base_url}/wp-admin/admin-ajax.php'
    user_agent = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36')

    extra_headers = ['entry_url', 'submitted_date']

    def scrape(self):
        super().scrape()
        self.augment()

    def augment(self):
        logger.debug('Augmenting scraped data')
        entries = dict(self.fetch_entries())
        fillrow = [''] * len(self.extra_headers)
        with self.ctx_rewrite() as (reader, writer):
            writer.writerow(next(reader) + self.extra_headers)
            for values in reader:
                extra = entries.get(values[0]) or fillrow
                writer.writerow(values + extra)

    def fetch_entries(self) -> Iterator[tuple[str, list[str]]]:
        logger.debug('Fetching entries')
        self.session.headers = {'User-Agent': self.user_agent}
        rep = self.session.post(self.api_url, data=self.get_api_payload())
        rep.raise_for_status()
        for listing in rep.json()['data']:
            a = bs(listing[0], 'html5lib').find('a')
            yield a.text, [a['href'], listing[2]]

    def get_api_payload(self):
        rep = self.get_url(self.public_url)
        rep.raise_for_status()
        doc = bs(rep.text, 'html5lib')
        return dict(self.payload, nonce=self.extract_nonce(doc))

    def extract_nonce(self, doc: Soup) -> str|None:
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

class IN(CommonScraper, state='IN'):
    base_url = 'https://www.in.gov'
    index_url = f'{base_url}/dwd/warn-notices/current-warn-notices/'
    public_url = index_url
    headers = [
        'Company',
        'City',
        'Affected Workers',
        'Notice Date',
        'LO/CL Date',
        'NAICS',
        'Description of Work/Industry',
        'Notice Type',
        'url']

    def scrape(self) -> None:
        self.scrape_index()
        self.write_csv()

    def read_records(self):
        doc = bs(self.cache.read('latest.html'))
        for i, table in enumerate(doc.find_all('table')):
            it = self.read_table(table)
            if i == 0:
                headers = next(it)
            for values in it:
                yield dict(zip(headers, values))

    def read_table(self, table: Soup) -> Iterator[list[str]]:
        tags = ['td', 'th']
        for tr in table.find_all('tr'):
            tds = tr.find_all(tags)
            if not tds:
                continue
            last = tds.pop()
            values = [td.text.strip() for td in tds]
            values.append(self.parse_url(last))
            yield values

    def parse_url(self, cell: Soup) -> str:
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

    def augment(self) -> None:
        lookup = dict(self.fetch_lookup())
        with self.ctx_rewrite() as (reader, writer):
            writer.writerow(next(reader) + ['download'])
            for values in reader:
                key = self.row_key(values)
                values.append(lookup.get(key, ''))
                writer.writerow(values)

    def fetch_lookup(self) -> Iterator[tuple[str, str]]:
        for file in self.cache.files('.', '*_page_*.html'):
            with open(file) as f:
                doc = bs(f, 'html5lib')
            table = doc.find('table')
            yield from self.parse_lookup_table(table)

    def parse_lookup_table(self, table: Soup) -> Iterator[tuple[str, str]]:
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

class SC(CommonScraper, state='SC'):
    base_url = 'https://scworks.org'
    public_url = f'{base_url}/employer/employer-programs/risk-closing/layoff-notification-reports'
    index_url = public_url
    headers_species = {
        **{
            r: ['Company', 'Location', 'Layoff/Closure Date', 'Positions', 'Closure or Layoff', 'NAICS Code']
            for r in [range(2020), range(2021, 2022)]
        },
        range(2020, 2021): ['Company', 'Location', 'Closure or Layoff', 'Positions', 'Layoff/Closure Date', 'NAICS Code'],
        None: ['Company', 'County', 'Notice Date', 'Layoff/Closure Date', 'Impacted', 'Layoff/Closure', 'Address']
    }
    extra_headers = ['year', 'url']
    headers = list(utils.unique(chain(*reversed(headers_species.values()), extra_headers)))
    realign_most = 0.9

    def scrape(self) -> None:
        self.scrape_index()
        self.download_pdfs()
        self.write_csv()

    def scrape_index(self) -> None:
        super().scrape_index()
        index: list[tuple[int, str]] = []
        page = bs(self.cache.read('latest.html'))
        for a in page.find_all('a'):
            href = str(a.get('href', ''))
            if href.endswith('.pdf'):
                year = int(href.split('/')[-1][:4])
                index.append((year, href))
        index.sort()
        self.cache.write('index.json', json.dumps(index, indent=2))

    def download_pdfs(self) -> None:
        for year, url in self.load_index():
            key = f'{year}.pdf'
            if not self.cache.exists(key) or year >= utils.now().year - 1:
                self.cache.download(key, self.base_url + url)

    def read_records(self) -> Iterator[dict[str, str]]:
        for year, url in self.load_index():
            headers = self.get_header_species(year) + self.extra_headers
            extra = [str(year), url]
            it = self.read_table(Path(self.cache.path, f'{year}.pdf'))
            next(it)
            for row in it:
                yield dict(zip(headers, row + extra))

    def get_header_species(self, year: int) -> list[str]:
        for key, headers in self.headers_species.items():
            if key and year in key:
                return headers
        return self.headers_species[None]

    def read_table(self, path: Path) -> Iterator[list[str]]:
        with pdfplumber.open(path) as pdf:
            it = (page.extract_tables() for page in pdf.pages)
            it = (table for tables in it for table in tables)
            it = map(self.process_table, it)
            it = filter(None, it)
            it = self.merge_tables(it)
            it = (list(map(self.clean_cell, row)) for row in it)
            it = list(it)
            yield from it

    def process_table(self, table: list[list[str|None]]) -> list[list]:
        self.remove_extra_header(table)
        if self.table_is_sparse(table):
            logger.debug(f'skip sparse {table=}')
            return []
        if self.table_is_summary(table):
            logger.debug(f'skip summary {table=}')
            return []
        table = self.filter_sparse_rows(table)
        table = self.filter_empty_columns(table)
        self.realign_columns(table)
        return table

    def merge_tables(self, tables: Iterable[list[list]]) -> Iterator[list]:
        width, head = None, None
        for i, table in enumerate(tables):
            h = table[0]
            w = len(h)
            if i == 0:
                width, head = w, h
            elif width != w:
                raise ValueError(f'Mismatched table widths {width}, {w}')
            elif head == h:
                table = iter(table)
                next(table)
            yield from table

    def clean_cell(self, text: str|None) -> str:
        text = text or ''
        text = text.replace('\n', ' ').strip()
        text = self.rewrites.get(text, text)
        return text

    def load_index(self) -> list[tuple[int, str]]:
        return list(map(tuple, json.loads(self.cache.read('index.json'))))

    def table_is_sparse(self, table: list[list]) -> bool:
        return not any(utils.morethan(1, row) for row in table)

    def table_is_summary(self, table: list[list]) -> bool:
        return bool(table) and table[0][:2] == ['County', 'Impacted']

    def remove_extra_header(self, table: list[list]) -> None:
        if table and not utils.morethan(1, table[0]):
            logger.debug(f'remove extra {table[0]}')
            del table[0]

    def filter_sparse_rows(self, table: list[list]) -> list[list]:
        return [row for row in table if utils.morethan(2, row)]

    def filter_empty_columns(self, table: list[list]) -> list[list]:
        if not table:
            return table
        cols = [
            c for c in range(len(table[0]))
            if any(row[c] for row in table)]
        return [[row[c] for c in cols] for row in table]

    def realign_columns(self, table: list[list]) -> None:
        """
        +---+---+      +---+
        | x |   |      | x |
        +---+---+  =>  +---+
        |   | x |      | x |
        +---+---+      +---+
        """
        L = len(table)
        if L < 2:
            return table
        def most(it):
            return utils.morethan(self.realign_most * L, it)
        c = 0
        while c <= len(table[0]) - 2:
            d = c + 1
            realign = (
                most(row[c] or row[d] for row in table) and
                not any(row[c] and row[d] for row in table))
            if realign:
                for row in table:
                    if not row[c]:
                        del row[c]
                    else:
                        del row[d]
            c += 1

    rewrites = {
        'Caraustar Industrial &': 'Caraustar Industrial & Consumer Products Group',
        'roup7,/ 5In/2c0.23': '7/5/2023',
        'CYoonrskumer Products G': 'York',
        'PBS Radiology Busine': 'PBS Radiology Business Experts',
        'sSs uEmxpteerrts': 'Sumter',
        'iGcsr,e eInncv i(l"leRyder")': 'Greenville',
        'eCrvhiacrele IsIt o("nLegacy")': 'Charleston',
        'LCLhCar,l eds/bto/an Yelloh': 'Charleston',
        'LLLexCi,n dg/tbo/na Yelloh': 'Lexington',
        'tSivtaet eSwerivdiec e- sM, LuLltiCple': 'Statewide - Multiple Counties',
        'Co9u/n1t5ie/s2023': '9/15/2023',
        'Statewide - Multiple': 'Statewide - Multiple Counties',
        'Co9u/n2t9ie/s2023': '9/29/2023',
    }

class MO(CommonScraper, state='MO'):
    start_year = 2019
    base_url = 'https://jobs.mo.gov/warn'
    archive_url = 'http://warn-public.s3-website-us-west-2.amazonaws.com/s/MO'
    headers_species = {
        10: ['Received', 'Title', 'Industry', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'Notes', 'url'],
        9: ['Received', 'Title', 'Industry', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'url'],
        8: ['Received', 'Title', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'url'],
    }
    headers = list(utils.unique(chain(*headers_species.values())))

    def scrape(self) -> None:
        self.download_pages()
        self.write_csv()

    def download_pages(self) -> None:
        now = utils.now()
        for year in range(self.start_year, now.year + 1):
            key = f'pages/{year}.html'
            if self.cache.exists(key) and year < now.year - 1:
                continue
            url = f'{self.archive_url}/{key}'
            rep = self.get_url(url)
            if year == now.year:
                dt = utils.parse_date(rep.headers.get('Last-Modified'))
                if not dt:
                    logger.warning(f'Cannot parse last-modified header')
                elif dt < utils.now(days=-7, tz=timezone.utc):
                    logger.warning(f'Current year page more than 7 days old {url=}')
            self.cache.write(key, rep.content.decode())

    def read_records(self) -> Iterable[dict[str, str]]:
        for path in map(Path, self.cache.files('pages', '*.html')):
            year = int(path.name.removesuffix('.html'))
            url = f'{self.base_url}/{year}'
            page = bs(path.read_text())
            table = page.find('table')
            head, *trs = table.find_all('tr')
            headers = self.get_header_species(head)
            for tr in trs:
                values = [*self.read_tr(tr), url]
                if utils.morethan(2, values):
                    yield dict(zip(headers, values))

    def get_header_species(self, head: Soup) -> list[str]:
        return self.headers_species[len(head.find_all(['td', 'th']))]

    def read_tr(self, tr: Soup) -> Iterator[str]:
        for td in tr.find_all('td'):
            yield td.text.strip()

def bs(markup, features='html.parser', **kw):
    return Soup(markup, features, **kw)
    
warn_scraper_names = warn.utils.get_all_scrapers()

@functools.cache
def get_scraper_module(state: str):
    state = state.lower()
    if state in warn_scraper_names:
        return import_module(f'warn.scrapers.{state}')

def create_scraper(state: str) -> type[Scraper]:
    class DefaultScraper(Scraper):
        pass
    DefaultScraper.state = state
    return DefaultScraper

for state in map(str.upper, warn_scraper_names):
    if state not in scrapers:
        scrapers[state] = create_scraper(state)
del(state)
