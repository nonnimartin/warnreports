from __future__ import annotations

import asyncio
import csv
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path
from typing import Any, Generator, Iterable, Iterator
from urllib.parse import urlparse

import openpyxl
import pdfplumber
import requests
from bs4 import BeautifulSoup as Soup

import warn.cache
import warn.runner
import warn.utils

from . import settings, utils

scrapers: dict[str, type[Scraper]] = {}
logger = utils.get_logger('scrapers')

class Scraper:

    state: str
    base_url: str|None = None
    request_delay = 0

    def __init__(self):
        self.runner = Runner(self.state)
        self.session = requests.session()
        self.cache = Cache(self.state)
        self.request_count = 0

    async def clean(self) -> None:
        self.runner.file.unlink(missing_ok=True)

    async def scrape(self) -> None:
        self.runner.scrape()

    async def stat(self) -> dict[str, Any]:
        return self.runner.stat()

    @contextmanager
    def extract(self) -> Generator[Iterable[dict[str, str]]]:
        with self.runner.file.open() as file:
            yield csv.DictReader(file, restkey='__')

    async def fetch(self, url: str, **kw) -> str:
        rep = await self.req_get(url, **kw)
        return rep.content.decode()

    async def cache_fetch(self, key: str, url: str, **kw) -> str:
        text = await self.fetch(url, **kw)
        self.cache.write(key, text)
        return text

    async def cache_download(self, key: str, url: str, encoding: str|None = None, **kw) -> requests.Response:
        # Adapted from: https://github.com/biglocalnews/warn-scraper/blob/main/warn/cache.py
        dest = self.cache.topath(key)
        logger.debug(f'Downloading {url} to {dest}')
        dest.parent.mkdir(parents=True, exist_ok=True)
        with await self.req_get(url, stream=True, **kw) as rep:
            rep.encoding = encoding or rep.encoding or 'utf-8'
            with dest.open('wb') as f:
                for chunk in rep.iter_content(chunk_size=8192):
                    f.write(chunk)
        await asyncio.sleep(0)
        return rep

    async def req_get(self, url: str, **kw) -> requests.Response:
        if self.request_delay and self.request_count:
            logger.debug(f'request delay: {self.request_delay}s')
            await asyncio.sleep(self.request_delay)
        url = self.absurl(url)
        kw.setdefault('session', self.session)
        rep = warn.utils.get_url(url, **kw)
        self.request_count += 1
        rep.raise_for_status()
        if not kw.get('stream'):
            await asyncio.sleep(0)
        return rep

    def absurl(self, url: str) -> str:
        if not url.startswith('http://') and not url.startswith('https://') and self.base_url:
            url = self.base_url.rstrip('/') + '/' + url.lstrip('/')
        return url

    def __init_subclass__(cls, state: str|None = None) -> None:
        if state:
            cls.state = state.upper()
            scrapers[cls.state] = cls

class AK(Scraper, state='AK'):
    base_url = 'https://jobs.alaska.gov'
    index_url = '/RR/WARN_notices.htm'
    space_pat = re.compile(r'[\s\n]+')

    async def scrape(self) -> None:
        await self.cache_download('latest.html', self.index_url)

    async def clean(self):
        self.cache.delete('latest.html')

    async def stat(self):
        try:
            page = bs(self.cache.read('latest.html'))
        except FileNotFoundError:
            strings = []
        else:
            strings = [page.find('table').text]
        return dict(
            hash=utils.hashstrings(strings),
            size=sum(map(len, strings)))

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        doc = bs(self.cache.read('latest.html'))
        it = self.read_table(doc.find('table'))
        headers = next(it)
        yield (dict(zip(headers, values)) for values in it)

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

class CA(Scraper, state='CA'):
    base_url = 'https://edd.ca.gov'
    index_url = '/Jobs_and_Training/Layoff_Services_WARN.htm'
    hrefpat = re.compile(r'warn[-_]?report', re.I)

    async def scrape(self) -> None:
        page = bs(await self.cache_fetch('latest.html', self.index_url))
        index = []
        for link in page.find_all('a'):
            href = str(link.get('href', ''))
            if self.hrefpat.search(href):
                key = Path(urlparse(href).path).name
                if not key.endswith('.pdf') or not self.cache.exists(key):
                    await self.cache_download(key, href)
                index.append(key)
        index.sort()
        self.cache.write_json('index.json', index, indent=2)

    async def clean(self):
        self.cache.delete('latest.html', 'index.json')

    async def stat(self):
        files = self.list_record_files()
        files += [self.cache.topath('index.json')]
        return dict(
            hash=utils.hashfiles(files, missing_ok=True),
            size=sum(file.stat().st_size for file in files if file.exists()))

    @contextmanager
    def extract(self):
        files = map(self.cache.topath, self.load_index())
        yield chain.from_iterable(map(self.read_record_file, files))

    def read_record_file(self, file: Path) -> Iterator[dict[str, str]]:
        from warn.scrapers import ca
        if file.name.endswith('.pdf'):
            records = ca._extract_pdf_data(file)
        else:
            records = ca._extract_excel_data(file)
        return map(self.clean_record, records)

    def clean_record(self, record: dict[str, Any]) -> dict[str, str]:
        return {k: str(v) for k, v in record.items()}

    def list_record_files(self) -> list[Path]:
        files = self.cache.files('.', '*.pdf')
        files += self.cache.files('.', '*.xlsx')
        return sorted(map(Path, files))

    def load_index(self) -> list[str]:
        return self.cache.read_json('index.json')

class CO(Scraper, state='CO'):

    async def scrape(self):
        self.runner.scrape()
        with self.runner.file.open() as file:
            headers = sorted(next(csv.reader(file)))
        with self.runner.file.open() as file:
            reader = csv.DictReader(file)
            with self.cache.open('normalized.csv', 'w') as file:
                writer = csv.DictWriter(file, fieldnames=headers)
                writer.writeheader()
                writer.writerows(reader)
        self.runner.file.unlink()

    async def clean(self):
        self.cache.delete('normalized.csv')

    async def stat(self):
        file = self.cache.topath('normalized.csv')
        return dict(
            hash=utils.hashfile(file, missing_ok=True),
            size=file.stat().st_size if file.exists() else 0)

    @contextmanager
    def extract(self) -> Generator[Iterable[dict[str, str]]]:
        with self.cache.open('normalized.csv') as file:
            yield csv.DictReader(file, restkey='__')

class DE(Scraper, state='DE'):
    base_url = 'https://joblink.delaware.gov'
    index_url = '/search/warn_lookups?commit=Search&page=1&q%5Bs%5D=notice_on+desc'
    request_delay = 1
    index_headers = ['Employer', 'City', 'ZIP', 'LWIB Area', 'Notice Date', 'WARN Type', 'URL']
    record_headers = ['Company Name', 'Address', 'Notice Date', 'Number of Employees Affected']

    async def scrape(self) -> None:
        index: list[dict[str, str]] = []
        async for table in self.fetch_index_tables():
            tbody = table.find('tbody')
            for tr in tbody.find_all('tr'):
                row = dict.fromkeys(self.index_headers, '')
                for key, td in zip(self.index_headers[:-1], tr.find_all('td')):
                    row[key] = td.text.strip()
                href = str(tr.find('td').find('a')['href'])
                record_num = str(int(href.rsplit('/')[-1].removesuffix('.html')))
                key = f'records/{record_num}.html'
                if not self.cache.exists(key):
                    await self.cache_download(key, href)
                row['URL'] = href
                row['record_num'] = record_num
                index.append(row)
        self.cache.write_json('index.json', index, indent=2)

    async def fetch_index_tables(self):
        page = 1
        url = self.index_url
        while url:
            key = f'pages/{page}.html'
            doc = bs(await self.cache_fetch(key, url))
            table = doc.find('table')
            if table:
                yield table
            nextlink = doc.find('a', {'class': 'next_page', 'rel': 'next'})
            url = nextlink['href'] if nextlink else None
            page += 1

    async def clean(self):
        self.cache.delete('index.json')
        for path in self.list_page_files():
            path.unlink()

    @contextmanager
    def extract(self):
        yield self.read_records()

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

    def load_index(self) -> list[dict[str, str]]:
        return self.cache.read_json('index.json')

    def list_page_files(self) -> list[Path]:
        files = self.cache.files('pages', '*.html')
        files.sort(reverse=True)
        return list(map(Path, files))

    def list_record_files(self) -> list[Path]:
        files = self.cache.files('records', '*.html')
        files.sort(reverse=True)
        return list(map(Path, files))

    async def stat(self):
        files = [self.cache.topath('index.json')]
        files += self.list_record_files()
        return dict(
            hash=utils.hashfiles(files, missing_ok=True),
            size=sum(file.stat().st_size for file in files if file.exists()))

class FL(Scraper, state='FL'):

    async def scrape(self) -> None:
        self.runner.scrape()

    @contextmanager
    def extract(self):
        with self.runner.file.open() as file:
            yield self.read_records(csv.reader(file))

    def read_records(self, it: Iterable[list[str]]) -> Iterator[dict[str, str]]:
        lookup = dict(self.fetch_lookup())
        headers = next(it) + ['download']
        for values in it:
            key = self.row_key(values)
            values.append(lookup.get(key, ''))
            yield dict(zip(headers, values))

    def fetch_lookup(self):
        for file in self.cache.files('.', '*_page_*.html'):
            doc = bs(Path(file).read_text(), 'html5lib')
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

class GA(Scraper, state='GA'):
    base_url = 'https://www.tcsg.edu'
    index_url = '/warn-public-view/'
    api_url = f'{base_url}/wp-admin/admin-ajax.php'
    user_agent = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36')
    extra_headers = ['entry_url', 'submitted_date']

    async def scrape(self):
        text = await self.cache_fetch('latest.html', self.index_url)
        doc = bs(text, 'html5lib')
        payload = dict(self.payload, nonce=self.extract_nonce(doc))
        self.session.headers = {'User-Agent': self.user_agent}
        rep = self.session.post(self.api_url, data=payload)
        rep.raise_for_status()
        index = {}
        for listing in rep.json()['data']:
            a = bs(listing[0], 'html5lib').find('a')
            index[a.text] = [a['href'], listing[2]]
        self.cache.write_json('index.json', index, indent=2)
        if self.needs_scrape():
            self.runner.scrape()

    async def clean(self):
        await super().clean()
        self.cache.delete('latest.html', 'index.json')

    async def stat(self):
        files = [self.cache.topath('index.json')]
        files += self.list_record_files()
        return dict(
            hash=utils.hashfiles(files, missing_ok=True),
            size=sum(file.stat().st_size for file in files if file.exists()))

    @contextmanager
    def extract(self):
        with self.runner.file.open() as file:
            yield self.read_records(csv.reader(file))

    def read_records(self, it: Iterable[list[str]]) -> Iterator[dict[str, str]]:
        index = self.load_index()
        fillrow = [''] * len(self.extra_headers)
        headers = next(it) + self.extra_headers
        for values in it:
            values += index.get(values[0]) or fillrow
            yield dict(zip(headers, values))

    def load_index(self) -> dict[str, tuple[str, str]]:
        index: dict = self.cache.read_json('index.json')
        return {key: tuple(item) for key, item in index.items()}

    def needs_scrape(self):
        source = self.runner.file
        keys = (f'{key}.format3' for key in self.load_index())
        return not (
            source.exists() and
            source.stat().st_size and
            self.cache.exists('index.json') and
            all(map(self.cache.exists, keys)))

    def extract_nonce(self, doc: Soup) -> str|None:
        script = doc.find(
            'script',
            text=lambda text: text and 'window.gvDTglobals.push' in text)
        match = re.search(r'"nonce":"([^"]+)"', str(script))
        if match:
            return match.group(1)

    def list_record_files(self) -> list[Path]:
        files = self.cache.files('.', '*.format3')
        files.sort(reverse=True)
        return list(map(Path, files))

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
    index_url = '/dwd/warn-notices/current-warn-notices/'

    async def scrape(self) -> None:
        await self.cache_download('latest.html', self.index_url)

    async def clean(self) -> None:
        self.cache.delete('latest.html')

    @contextmanager
    def extract(self):
        yield self.read_records()

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

    async def stat(self):
        try:
            page = bs(self.cache.read('latest.html'))
        except FileNotFoundError:
            strings = []
        else:
            strings = [table.text for table in page.find_all('table')]
        return dict(
            hash=utils.hashstrings(strings),
            size=sum(map(len, strings)))

class NY(Scraper, state='NY'):
    base_url = 'https://dol.ny.gov'
    index_url = '/warn-notices'
    past_urls = {
        '2023.html': '/2023-warn-notices',
        '2022.html': '/2022-warn-notices',
        '2021.html': '/warn-notices-2021',
        'ny_historical.xlsx': 'http://warn-public.s3-website-us-west-2.amazonaws.com/s/NY/ny_historical.xlsx'}

    async def scrape(self) -> None:
        await self.cache_download('latest.html', self.index_url)
        for key, url in self.past_urls.items():
            if not self.cache.exists(key):
                await self.cache_download(key, url)

    async def clean(self):
        self.cache.delete('latest.html', *self.past_urls)

    async def stat(self):
        objs = list(map(self.cache.topath, self.past_urls))
        size = sum(obj.stat().st_size for obj in objs if obj.exists())
        if self.cache.exists('latest.html'):
            table = self.find_table(bs(self.cache.read('latest.html')))
            text = table.text
            objs.append(text)
            size += len(text)
        return dict(hash=utils.hashobjects(objs, missing_ok=True), size=size)

    @contextmanager
    def extract(self):
        keys = ('latest.html', *self.past_urls)
        files = map(self.cache.topath, keys)
        tables = map(self.read_record_file, files)
        yield chain.from_iterable(tables)

    def read_record_file(self, file: Path) -> Iterator[dict[str, str]]:
        if file.name.endswith('.xlsx'):
            func = self.read_xlsx_file
        else:
            func = self.read_html_file
        yield from func(file)

    def read_xlsx_file(self, file: Path) -> Iterator[dict[str, str]]:
        worksheet = openpyxl.load_workbook(file, read_only=True).worksheets[0]
        it = ([cell.value for cell in row] for row in worksheet.rows)
        headers = next(it)
        for values in it:
            row = {}
            for k, v in zip(headers, values):
                if not (k or v):
                    continue
                if v is None:
                    v = ''
                elif isinstance(v, datetime):
                    v = v.strftime(f'%Y-%m-%d')
                else:
                    v = str(v)
                row[k] = v
            yield row

    def read_html_file(self, file: Path) -> Iterator[dict[str, str]]:
        table = self.find_table(bs(file.read_bytes()))
        it = iter(table.find_all('tr'))
        next(it)
        for tr in it:
            tds = tr.find_all('td')
            yield dict(
                company_name=tds[0].a.text,
                notice_url=tds[0].a['href'],
                date_posted=tds[1].text,
                notice_dated=tds[2].text)

    def find_table(self, page: Soup) -> Soup:
         return page.find('div', {'class': 'landing-paragraphs'}).find('table')

class SC(Scraper, state='SC'):
    base_url = 'https://scworks.org'
    index_url = f'{base_url}/employer/employer-programs/risk-closing/layoff-notification-reports'
    headers_species = {
        **{
            r: ['Company', 'Location', 'Layoff/Closure Date', 'Positions', 'Closure or Layoff', 'NAICS Code']
            for r in [range(2020), range(2021, 2022)]
        },
        range(2020, 2021): ['Company', 'Location', 'Closure or Layoff', 'Positions', 'Layoff/Closure Date', 'NAICS Code'],
        None: ['Company', 'County', 'Notice Date', 'Layoff/Closure Date', 'Impacted', 'Layoff/Closure', 'Address']
    }
    extra_headers = ['year', 'url']
    realign_most = 0.9

    async def scrape(self) -> None:
        index: list[tuple[int, str]] = []
        text = await self.cache_fetch('latest.html', self.index_url)
        page = bs(text)
        for a in page.find_all('a'):
            href = str(a.get('href', ''))
            if href.endswith('.pdf'):
                year = int(href.split('/')[-1][:4])
                index.append((year, href))
                key = f'{year}.pdf'
                if not self.cache.exists(key) or year >= utils.now().year - 1:
                    await self.cache_download(key, href)
        index.sort()
        self.cache.write_json('index.json', index, indent=2)

    async def clean(self) -> None:
        self.cache.delete('latest.html', 'index.json')

    async def stat(self):
        files = [self.cache.topath('index.json')]
        files += self.list_record_files()
        return dict(
            hash=utils.hashfiles(files, missing_ok=True),
            size=sum(file.stat().st_size for file in files if file.exists()))

    @contextmanager
    def extract(self):
        yield self.read_records()

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
            it = [page.extract_tables() for page in pdf.pages]
        it = (table for tables in it for table in tables)
        it = map(self.process_table, it)
        it = filter(None, it)
        it = self.merge_tables(it)
        it = (list(map(self.clean_cell, row)) for row in it)
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
        return list(map(tuple, self.cache.read_json('index.json')))

    def list_record_files(self) -> list[Path]:
        files = self.cache.files('.', '*.pdf')
        files.sort(reverse=True)
        return list(map(Path, files))

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

class MO(Scraper, state='MO'):
    start_year = 2019
    base_url = 'https://jobs.mo.gov/warn'
    archive_url = 'http://warn-public.s3-website-us-west-2.amazonaws.com/s/MO'
    headers_species = {
        10: ['Received', 'Title', 'Industry', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'Notes', 'url'],
        9: ['Received', 'Title', 'Industry', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'url'],
        8: ['Received', 'Title', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'url'],
    }

    async def scrape(self) -> None:
        now = utils.now()
        for year in range(self.start_year, now.year + 1):
            key = f'pages/{year}.html'
            if self.cache.exists(key) and year < now.year - 1:
                continue
            url = f'{self.archive_url}/{key}'
            rep = await self.cache_download(key, url)
            if year == now.year:
                dt = utils.parse_date(rep.headers.get('Last-Modified'))
                if not dt:
                    logger.warning(f'Cannot parse last-modified header')
                elif dt < utils.now(days=-7, tz=timezone.utc):
                    logger.warning(f'Current year page more than 7 days old {url=}')

    async def clean(self) -> None:
        for path in self.list_page_files():
            path.unlink()

    async def stat(self):
        it = self.list_page_files()
        it = (bs(file.read_bytes()) for file in it)
        strings = [page.find('table').text for page in it]
        return dict(
            hash=utils.hashstrings(strings),
            size=sum(map(len, strings)))

    @contextmanager
    def extract(self):
        yield self.read_records()

    def read_records(self) -> Iterable[dict[str, str]]:
        for path in self.list_page_files():
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

    def list_page_files(self) -> list[Path]:
        files = self.cache.files('pages', '*.html')
        files.sort(reverse=True)
        return list(map(Path, files))

class Cache(warn.cache.Cache):

    def __init__(self, state: str):
        data_dir = settings.BUILD_DIR/'scrape'
        super().__init__(data_dir/state.lower())

    def delete(self, *keys: str):
        for path in map(self.topath, keys):
            path.unlink(missing_ok=True)
    
    def topath(self, key: str):
        return Path(self.path, key)

    def open(self, key: str, *args, **kw):
        return self.topath(key).open(*args, **kw)

    def write_json(self, key: str, obj: Any, **kw):
        with self.open(key, 'w') as file:
            json.dump(obj, file, **kw)

    def read_json(self, key: str, **kw) -> Any:
        with self.open(key) as file:
            return json.load(file, **kw)

class Runner(warn.Runner):

    def __init__(self, state: str):
        self.state = state.upper()
        cache_dir = settings.BUILD_DIR/'scrape'
        data_dir = cache_dir/self.state.lower()
        self.file = data_dir/f'{self.state.lower()}.csv'
        super().__init__(data_dir, cache_dir)

    def scrape(self) -> None:
        super().scrape(self.state.lower())

    def stat(self) -> dict[str, Any]:
        file = self.file
        return dict(
            hash=utils.hashfile(file, missing_ok=True),
            size=file.stat().st_size if file.exists() else 0)

def bs(markup, features='html.parser', **kw):
    return Soup(markup, features, **kw)
    
def create_scraper(state: str) -> type[Scraper]:
    class DefaultScraper(Scraper):
        pass
    DefaultScraper.state = state.upper()
    return DefaultScraper

scrapers.update({
    state: create_scraper(state)
    for state in map(str.upper, warn.utils.get_all_scrapers())
    if state not in scrapers})

