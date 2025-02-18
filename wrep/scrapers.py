from __future__ import annotations

import asyncio
import csv
import dataclasses
import hashlib
import json
import re
import shutil
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime
from html import unescape as _u
from itertools import chain, filterfalse
from pathlib import Path
from re import compile as _r
from typing import (TYPE_CHECKING, Any, ClassVar, Generator, Iterable,
                    Iterator, Self)
from urllib.parse import parse_qs, unquote_plus, urlparse

import openpyxl
import openpyxl.worksheet
import openpyxl.worksheet.worksheet
import pdfplumber
import requests
from bs4 import BeautifulSoup as Soup
from bs4.element import PageElement, ResultSet, Tag
from openpyxl.worksheet.worksheet import Worksheet
from requests.adapters import HTTPAdapter, Retry
from requests.exceptions import HTTPError
from starlette.datastructures import URL
from typing_extensions import Buffer

import warn.cache
import warn.runner
import warn.utils

from . import SaveType, Stage, settings, utils
from .backends import webdrivers
from .models import ScraperOpts

scrapers: dict[str, type[Scraper]] = {}

class Scraper:
    state: str
    base_url: str|None = None
    user_agent = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0'
    request_delay = 0
    ssl_verify = True
    retry = dict(total=3, backoff_factor=2)

    def __init__(self, *, opts: ScraperOpts|dict|None = None):
        self.opts = ScraperOpts.model_validate(opts or {})
        self.runner = Runner(self.state)
        self.session = requests.session()
        retry = Retry(**self.retry)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.session.headers['User-Agent'] = self.user_agent
        self.cache = Cache(self.state, Stage.Scrape)
        self.extract_cache = Cache(self.state, Stage.Extract)
        self.artifacts = Artifacts(self.state)
        self.metrics = defaultdict(int)
        self.logger = utils.get_logger(f'scrapers.{self.state}')

    async def clean(self) -> None:
        self.runner.file.unlink(missing_ok=True)

    async def scrape(self) -> None:
        self.runner.scrape()

    async def stat(self) -> dict[str, Any]:
        return hashstat(self.statobjs())

    def statobjs(self) -> Iterable[Any]:
        yield from self.runner.statobjs()

    @contextmanager
    def extract(self) -> Generator[Iterable[dict[str, str]]]:
        with self.runner.file.open() as file:
            yield csv.DictReader(file, restkey='__')

    async def extract_clean(self) -> None:
        self.extract_cache.nuke()

    async def fetch(self, key: str, url: str, **kw) -> str:
        rep = await self.request('GET', url, **kw)
        try:
            text = rep.content.decode()
        except UnicodeDecodeError:
            text = rep.text
        self.cache.write(key, text)
        return text

    async def download(self, key: str, url: str, encoding: str|None = None, missing_only: bool = False, **kw) -> requests.Response|None:
        # Adapted from: https://github.com/biglocalnews/warn-scraper/blob/main/warn/cache.py
        dest = self.cache.topath(key)
        if missing_only and dest.exists():
            return
        self.logger.debug(f'Downloading {url} to {dest}')
        dest.parent.mkdir(parents=True, exist_ok=True)
        with await self.request('GET', url, stream=True, **kw) as rep:
            rep.encoding = encoding or rep.encoding or 'utf-8'
            with dest.open('wb') as f:
                for chunk in rep.iter_content(chunk_size=8192):
                    f.write(chunk)
                    self.metrics['request_bytes'] += len(chunk)
        await asyncio.sleep(0)
        return rep

    async def request(self, method: str, url: str, *, check: bool = True, **kw) -> requests.Response:
        if self.request_delay and self.metrics['request_count']:
            await asyncio.sleep(self.request_delay)
        url = self.absurl(url)
        kw.setdefault('verify', self.ssl_verify)
        self.metrics['request_count'] += 1
        try:
            rep = self.session.request(method, url, **kw)
            if check:
                rep.raise_for_status()
        except Exception as err:
            if isinstance(err, HTTPError) and err.response is not None:
                status = err.response.status_code
            else:
                status = None
            self.logger.error(f'Failed to get {url=} {status=}')
            raise
        self.metrics['request_count'] += 1
        if not kw.get('stream'):
            self.metrics['request_bytes'] += len(rep.content)
            await asyncio.sleep(0)
        return rep

    def absurl(self, url: str) -> str:
        return absurl(self.base_url, url)

    def __init_subclass__(cls) -> None:
        cls.retry = Scraper.retry | cls.retry
        if len(name := cls.__name__.upper()) == 2:
            cls.state = name
            scrapers[cls.state] = cls

class AK(Scraper):
    base_url = 'https://jobs.alaska.gov'
    latest_url = '/RR/WARN_notices.htm'

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)

    async def clean(self):
        self.cache.delete('latest.html')

    def statobjs(self):
        if (file := self.cache/'latest.html').exists():
            yield bs(file).find('table')

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        doc = bs(self.cache/'latest.html')
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
            yield ' '.join(td.text.split())

    def parse_url(self, tr: Soup) -> str:
        td = tr.find('td')
        if td.text.strip() == 'Company':
            # header row
            return 'url'
        a = td.find('a')
        if a:
            return self.absurl(a['href'])
        return ''

class CA(Scraper):
    base_url = 'https://edd.ca.gov'
    latest_url = '/Jobs_and_Training/Layoff_Services_WARN.htm'
    hrefpat = _r(r'warn[-_]?report', re.I)

    async def scrape(self) -> None:
        page = bs(await self.fetch('latest.html', self.latest_url))
        index = []
        for link in page.find_all('a'):
            href = str(link.get('href', ''))
            if self.hrefpat.search(href):
                key = Path(urlparse(href).path).name
                await self.download(key, href, missing_only=key.endswith('.pdf'))
                self.artifacts.add(key)
                index.append((key, self.absurl(href)))
        index.sort()
        self.cache.write_json('index.json', dict(index), indent=2)

    async def clean(self):
        self.cache.delete('latest.html', 'index.json')

    def statobjs(self):
        yield from self.list_record_files()
        yield self.cache/'index.json'

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
        return sorted(self.cache.glob('*.pdf', '*.xlsx'))

    def load_index(self) -> dict[str, str]:
        return self.cache.read_json('index.json')

class CO(Scraper):

    async def scrape(self):
        self.runner.scrape()
        await asyncio.sleep(0)
        with self.runner.file.open() as file:
            # upstream scraper uses set() for header, which is unordered & breaks hashing.
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

    def statobjs(self):
        yield self.cache.topath('normalized.csv')

    @contextmanager
    def extract(self) -> Generator[Iterable[dict[str, str]]]:
        with self.cache.open('normalized.csv') as file:
            yield csv.DictReader(file, restkey='__')

class CT(Scraper):
    base_url = 'https://www.ctdol.state.ct.us/progsupt/bussrvce/warnreports'
    artifact_uri_subs = [
        (_r(r'^https?://webdev/progsupt/bussrvce/warnreports/'), ''),
    ]
    artifacts_min_year = 2019

    async def scrape(self) -> None:
        self.runner.scrape()
        index = dict(self.build_artifacts_index())
        self.cache.write_json('artifacts.json', index, indent=2)
        for key, url in index.values():
            await self.download(key, url, missing_only=True)
            self.artifacts.add(key)

    async def clean(self):
        await super().clean()
        self.cache.delete('artifacts.json')

    def statobjs(self):
        yield from super().statobjs()
        yield self.cache.topath('artifacts.json')

    @contextmanager
    def extract(self):
        with self.runner.file.open() as file:
            yield self.read_records(csv.reader(file))

    def read_records(self, it: Iterable[list[str]]) -> Iterator[dict[str, str]]:
        "Yield augmented records from CSV rows"
        index: dict[str, list[str]] = self.cache.read_json('artifacts.json')
        headers = next(it)
        for values in it:
            row = dict(zip(headers, values))
            row_key = self.row_key(values)
            if row_key in index:
                key, url = index[row_key]
                row.update(
                    download=url,
                    artifacts_json=json.dumps({key: url}))
            yield row

    def row_key(self, values: Iterable[str]) -> str:
        "Values hash key from CSV row for artifact index"
        return ''.join(''.join(values).split())

    def build_artifacts_index(self) -> Iterator[tuple[str, tuple[str, str]]]:
        "Build the artifacts index from the downloaded page files"
        for file in sorted(self.cache.glob('*.html'), reverse=True):
            year = int(file.name[:4])
            if year < self.artifacts_min_year:
                continue
            doc = bs(file.read_text(), 'html5lib')
            tables = doc.find_all('table')
            for table in tables:
                yield from self.parse_downloads_table(year, table)

    def parse_downloads_table(self, year: int, table: Soup) -> Iterator[tuple[str, tuple[str, str]]]:
        "Yields (row_key, (cache_key, url)) for an html table"
        tbody = table.find('tbody')
        for tr in tbody.find_all('tr'):
            tds = tr.find_all('td')
            for td in tds:
                if td.a is not None:
                    info = self.artifact_info(year, td.a.get('href', ''))
                    if info:
                        row_key = self.row_key(td.text for td in tds)
                        yield row_key, info
                        break

    def artifact_info(self, year: int, uri: str) -> tuple[str, str]|None:
        "Check the raw 'download' value, and if valid, return a clean cache key and download URL"
        if year < self.artifacts_min_year or not uri.endswith('.pdf'):
            return
        uri = utils.rewrite_all(uri, self.artifact_uri_subs)
        url = self.absurl(uri)
        clean = Path(urlparse(url).path).name
        clean = unquote_plus(clean)
        clean = clean_filename(clean)
        if not clean:
            return
        cache_key = f'records/{year}_{clean}'
        return cache_key, url

class DE(Scraper):
    base_url = 'https://joblink.delaware.gov'
    latest_url = '/search/warn_lookups?commit=Search&page=1&q%5Bs%5D=notice_on+desc'
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
                await self.download(key, href, missing_only=True)
                row['URL'] = href
                row['record_num'] = record_num
                index.append(row)
        self.cache.write_json('index.json', index, indent=2)

    async def fetch_index_tables(self):
        page = 1
        url = self.latest_url
        while url:
            key = f'pages/{page}.html'
            doc = bs(await self.fetch(key, url))
            table = doc.find('table')
            if table:
                yield table
            nextlink = doc.find('a', {'class': 'next_page', 'rel': 'next'})
            url = nextlink['href'] if nextlink else None
            page += 1

    async def clean(self):
        self.cache.delete('index.json', '*.html', glob=True)

    def statobjs(self):
        yield self.cache/'index.json'
        yield from self.list_record_files()

    @contextmanager
    def extract(self):
        yield self.read_records()

    def read_records(self) -> Iterator[dict[str, str]]:
        for row in self.load_index():
            record_num = row.pop('record_num')
            key = f'records/{record_num}.html'
            page = bs(self.cache/key)
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
        return sorted(self.cache.glob('*.html'), reverse=True)

    def list_record_files(self) -> list[Path]:
        return sorted(self.cache.glob('records/*.html'), reverse=True)

class FL(Scraper):
    base_url = 'https://reactwarn.floridajobs.org'
    artifact_url_fmt = '/WarnList/DownloadAzureFile?file={}'
    request_delay = 1
    user_agent = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36')
    key_clean_subs = (
        (_r(r'[^a-zA-Z\d_]'), '-'),
        (_r(r'([-_])+'), r'\1'),
        (_r(r'[A-Z]-MYDOCUMENTS'), ''))

    async def scrape(self) -> None:
        self.runner.scrape()
        index = dict(self.build_artifacts_index())
        self.cache.write_json('artifacts.json', index, indent=2)
        for key, url in index.values():
            await self.download(key, url, missing_only=True)
            self.artifacts.add(key)

    async def clean(self):
        await super().clean()
        self.cache.delete('artifacts.json')

    def statobjs(self):
        yield from super().statobjs()
        yield self.cache.topath('artifacts.json')

    @contextmanager
    def extract(self):
        with self.runner.file.open() as file:
            yield self.read_records(csv.reader(file))

    def read_records(self, it: Iterable[list[str]]) -> Iterator[dict[str, str]]:
        "Yield augmented records from CSV rows"
        index: dict[str, list[str]] = self.cache.read_json('artifacts.json')
        headers = next(it)
        for values in it:
            row = dict(zip(headers, values))
            row_key = self.row_key(values)
            if row_key in index:
                key, url = index[row_key]
                row.update(
                    download=url,
                    artifacts_json=json.dumps({key: url}))
            yield row

    def build_artifacts_index(self) -> Iterator[tuple[str, tuple[str, str]]]:
        "Build the artifacts index from the downloaded page files"
        for file in sorted(self.cache.glob('*_page_*.html'), reverse=True):
            year = int(file.name[:4])
            doc = bs(file.read_text(), 'html5lib')
            table = doc.find('table')
            yield from self.parse_downloads_table(year, table)

    def row_key(self, values: Iterable[str]) -> str:
        "Values hash key from CSV row for artifact index"
        return ''.join(''.join(values).split())

    def parse_downloads_table(self, year: int, table: Soup) -> Iterator[tuple[str, tuple[str, str]]]:
        "Yields (row_key, (cache_key, url)) for an html table"
        tbody = table.find('tbody')
        for tr in tbody.find_all('tr'):
            tds = tr.find_all('td')
            last = tds.pop()
            if last.find('input', id='download'):
                if (el := last.find('input', type='hidden')):
                    if (info := self.artifact_info(year, el['value'])):
                        row_key = self.row_key(td.text for td in tds)
                        yield row_key, info

    def artifact_info(self, year: int, uri: str) -> tuple[str, str]|None:
        "Check the raw 'download' value, and if valid, return a clean cache key and download URL"
        if year < 2020 or not uri.endswith('.pdf'):
            return
        clean = unquote_plus(uri)
        if clean.startswith('\\'):
            return
        clean = clean.removesuffix('.pdf')
        clean = utils.rewrite_all(clean, self.key_clean_subs)
        clean = clean.strip('_-')
        if not clean:
            return
        name = f'{year}_{clean}.pdf'
        cache_key = f'records/{name}'
        url = self.absurl(self.artifact_url_fmt.format(uri))
        return cache_key, url

class GA(Scraper):
    base_url = 'https://www.tcsg.edu'
    latest_url = '/warn-public-view/'
    request_delay = 1
    api_url = f'/wp-admin/admin-ajax.php'
    user_agent = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36')
    extra_headers = ['entry_url', 'submitted_date', 'artifacts_json']

    async def scrape(self):
        text = await self.fetch('latest.html', self.latest_url)
        doc = bs(text, 'html5lib')
        payload = dict(self.payload, nonce=self.extract_nonce(doc))
        rep = await self.request('POST', self.api_url, data=payload)
        try:
            body = rep.json()
        except requests.exceptions.JSONDecodeError:
            self.logger.error(f'{rep.status_code} {rep.url} {payload=} content={rep.content}')
            raise
        index = {}
        for listing in body['data']:
            a = bs(listing[0], 'html5lib').find('a')
            index[a.text] = [a['href'], listing[2]]
        self.cache.write_json('index.json', index, indent=2)
        if self.needs_scrape():
            await asyncio.sleep(0)
            self.runner.scrape()
        artifacts = {}
        for idkey in index:
            infos = dict(self.extract_artifact_infos(idkey))
            if infos:
                artifacts[idkey] = infos
        self.cache.write_json('artifacts.json', artifacts, indent=2)
        it = chain.from_iterable(map(dict.items, artifacts.values()))
        for cachekey, url in it:
            await self.download(cachekey, url, missing_only=True)
            self.artifacts.add(cachekey)

    async def clean(self):
        await super().clean()
        self.cache.delete('latest.html', '*.json', glob=True)

    def statobjs(self):
        yield from self.cache.glob('*.json')
        yield from self.list_record_files()

    @contextmanager
    def extract(self):
        with self.runner.file.open() as file:
            yield self.read_records(csv.reader(file))

    def read_records(self, it: Iterable[list[str]]) -> Iterator[dict[str, str]]:
        index: dict = self.cache.read_json('index.json')
        artifacts = self.cache.read_json('artifacts.json')
        headers = next(it) + self.extra_headers
        fillrow = [''] * len(self.extra_headers)
        for values in it:
            idkey = values[0]
            fill = list(fillrow)
            if idkey in index:
                fill[:2] = index[idkey]
            if idkey in artifacts:
                fill[2] = json.dumps(artifacts[idkey])
            values.extend(fill)
            yield dict(zip(headers, values))

    def extract_artifact_infos(self, idkey: str) -> Iterator[tuple[str, str]]:
        doc = bs(self.cache/f'{idkey}.format3')
        for a in doc.find_all('a', {'data-type': 'pdf'}):
            filename = self.artifact_filename(a['href'])
            if filename:
                cachekey = f'records/{idkey}-{filename}'
                yield cachekey, self.absurl(a['href'])

    def needs_scrape(self) -> bool:
        index = self.cache.read_json('index.json')
        source = self.runner.file
        keys = (f'{key}.format3' for key in index)
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
        return sorted(self.cache.glob('*.format3'), reverse=True)

    def artifact_filename(self, href: str) -> str|None:
        vals = parse_qs(urlparse(href).query).get('gf-download')
        if vals and vals[0].endswith('.pdf'):
            return clean_filename(vals[0])

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

class IL(Scraper):
    # Scrape time: ~20s
    # Extract time: ~7s
    source_url = 'https://apps.illinoisworknet.com/iebs/api/public/export?search=&layoffTypes=&trade=0&dateReportedStart=Invalid%20Date&dateReportedEnd=Invalid%20Date&statuses=4&reasons=&eventCauses=&naicsCodes=1&naicIndustries=&naics=&unionsInvolved=0&geolocation=1&cities=&counties=&lwias=&includeAdditionalLwias=false&edrs=&lat=0&lng=0&distance=.5&memberType=1&users=&accessList=&bookmarked=false'

    async def scrape(self):
        await self.download('export.xlsx', self.source_url)

    def statobjs(self):
        file = self.cache/'export.xlsx'
        if file.exists():
            for row in extract_xlsx(file):
                row.pop('NAICS Codes', None)
                yield json.dumps(row)

    async def clean(self):
        self.cache.delete('export.xlsx')

    @contextmanager
    def extract(self):
        yield extract_xlsx(self.cache/'export.xlsx')

class IN(Scraper):
    # Scrape time: < 2s
    # Extract time: < 2s
    base_url = 'https://www.in.gov'
    latest_url = '/dwd/warn-notices/current-warn-notices/'

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)

    async def clean(self) -> None:
        self.cache.delete('latest.html')

    def statobjs(self):
        if (file := self.cache/'latest.html').exists():
            yield from bs(file).find_all('table')

    @contextmanager
    def extract(self):
        yield self.read_records()

    def read_records(self):
        doc = bs(self.cache/'latest.html')
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
            # header row
            return 'url'
        a = cell.find('a')
        if a:
            return self.absurl(a['href'])
        return cell.text.strip()

class KY(Scraper):

    async def scrape(self) -> None:
        self.runner.scrape()
        index = self.load_index()
        if settings.SELENIUM_ENABLED:
            await self.ArtifactDownloader(self, index).run()
        for key in index.values():
            if self.cache.exists(key):
                self.artifacts.add(key)

    async def clean(self) -> None:
        await super().clean()
        self.cache.delete('download/*', glob=True)

    def statobjs(self):
        yield self.runner.file
        yield self.cache/'artifacts.json'

    @contextmanager
    def extract(self):
        index = self.load_index()
        def extend(row: dict) -> dict:
            if (key := index.get(url := row['Notice URL'])):
                if self.cache.exists(key):
                    row.update(artifacts_json=json.dumps({key: url}))
            return row
        with super().extract() as it:
            yield map(extend, it)

    def load_index(self) -> dict[str, str]:
        if self.cache.exists('artifacts.json'):
            return self.cache.read_json('artifacts.json')
        return {}

    @dataclasses.dataclass
    class ArtifactDownloader:
        scraper: KY
        index: dict[str, str]
        broken_links: ClassVar = {
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005grO4/Vc6tHw.pgfZltA4R7RPb6MS7UY060XBDCzz3WNj9vVg',
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005NnQa/qEmJQv7aNct3EcgWUyr2QdpPW4csItqqtY1R7UFUEoM',
            'https://kydev.my.salesforce.com/sfc/p/#t00000004X3h/a/8y000005NnQa/qEmJQv7aNct3EcgWUyr2QdpPW4csItqqtY1R7UFUEoM',
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/t0000000WdMn/g2M_onZ71eICyV5MHAmrcI9xj.DWop9fES47Qz6TOY0',
            'https://kydev.my.salesforce.com/sfc/p/#t00000004X3h/a/t0000000WdMn/g2M_onZ71eICyV5MHAmrcI9xj.DWop9fES47Qz6TOY0',
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000004t96n/5P7Er8jyZDBXBGs92hEZzvmN8hJRRiUjVC3V9bSY5Z0',
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005Lkhh/16ZxfoY4UYNVp8NSCL2i.Im.Q7k0xxjpNn_725NxzFQ',
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005AaYZ/nOhlGCeHWJakUVLtYFLpq2QXY.WDel0jlYO6gs7mer8',
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005Aajf/_s09zrUsBYJdgPCh.PqdjhGXOuSG1CnCX_R06f6cUpw',
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005Aabo/V_hfVFWEIfnIQH57FqfbR9BdouHsTK6yDVavS3W.yC4',
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005Aaxr/KwrVbJWv9bt4iW0MMP6gybrw6S28RfEL_VJ2mbxlYXI',
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000004qHeU/0nnBdn1OOgCrcBTm_OtK6KFJkSq1YTPT7tRoYjrnotg',
            'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000004aMmU/2LSDXkaovRtmd5nUogcW..Erku6gsF1YNYPlI_KxcHY',
            'https://kydev.my.salesforce.com'}

        @property
        def logger(self) -> utils.logging.Logger:
            return self.scraper.logger

        async def run(self) -> None:
            with self.scraper.runner.file.open() as f:
                todos = deque(self.find_todos(csv.DictReader(f)))
            if todos:
                self.logger.info(f'Found {len(todos)} artifact urls to scrape')
            else:
                self.logger.info(f'No artifact urls to scrape')
                return
            self.scraper.cache.mkdir('records')
            num_workers = min(self.scraper.opts.selenium_max_procs, len(todos))
            self.logger.info(f'Creating {num_workers} selenium workers')
            try:
                async with asyncio.TaskGroup() as group:
                    for i in range(num_workers):
                        name = f'worker-{i}'
                        coro = self.start_worker(todos, name)
                        group.create_task(coro, name=name)
            finally:
                self.save_index()

        def find_todos(self, rows: Iterable[dict[str, str]]) -> Iterator[tuple[str, str]]:
            for row in rows:
                url = row['Notice URL']
                recvd = row.get('Date Received')
                if not (url and recvd):
                    continue
                if url in self.broken_links:
                    self.logger.debug(f'Ignoring {url=}')
                    continue
                if url in self.index:
                    key = self.index[url]
                    if self.scraper.cache.exists(key):
                        self.logger.debug(f'Skipping {key} already exists')
                        continue
                dateid = str(recvd).split()[0]
                urlid = uuid.uuid5(settings.NAMESPACE, url).hex[:6]
                prefix = clean_filename(f'{dateid}-{urlid}')
                yield (url, prefix)

        async def start_worker(self, queue: deque[tuple[str, str]], name: str) -> None:
            cache = self.scraper.cache.subcache(f'download/{name}')
            cache.mkdir()
            prefs = {
                'download.default_directory': cache.path,
                'download.prompt_for_download': False,
                'download.directory_upgrade': True}
            async with webdrivers.selenium(prefs=prefs) as driver:
                helper = self.WorkerHelper(self, driver, cache)
                while queue:
                    url, prefix = queue.popleft()
                    cache.delete('*', glob=True)
                    await helper.run(url, prefix)
            cache.nuke()

        def save_index(self) -> None:
            self.scraper.cache.write_json('artifacts.json', self.index, indent=2)

        def add_entry(self, url: str, key: str) -> None:
            self.index[url] = key
            self.save_index()

        @dataclasses.dataclass
        class WorkerHelper:
            downloader: KY.ArtifactDownloader
            driver: webdrivers.Chrome
            cache: Cache

            @property
            def scraper(self) -> KY:
                return self.downloader.scraper

            @property
            def index(self) -> dict[str, str]:
                return self.downloader.index

            @property
            def logger(self) -> utils.logging.Logger:
                return self.downloader.logger

            def find_title(self) -> str:
                return self.get_title(self.driver.page_source)

            def find_fileinfos(self) -> list[webdrivers.WebElement]:
                return self.driver.find_elements('xpath',
                    "//*[contains(text(), 'Word document') or "
                    "contains(text(), 'Adobe PDF')]")

            def find_buttons(self) -> list[webdrivers.WebElement]:
                return self.driver.find_elements('css selector', 'button.downloadbutton')

            def find_downloads(self) -> list[Path]:
                files = list(self.cache.glob('*'))
                for file in files:
                    if file.name.endswith('.crdownload'):
                        return []
                return files

            async def run(self, url: str, prefix: str) -> None:
                self.driver.get(url)
                wait = utils.Wait(timeout=10)
                try:
                    element = (await wait.until(self.find_fileinfos))[0]
                    doc_type = element.get_attribute('innerHTML')
                except TimeoutError:
                    self.logger.warning(f'No file info found at {url=}')
                    return
                except Exception:
                    self.logger.warning(f'Failed to fetch {url=}', exc_info=True)
                    return
                wait = utils.Wait(timeout=5)
                try:
                    title = await wait.until(self.find_title)
                except TimeoutError:
                    if url in self.index:
                        key = self.index[key]
                        self.logger.warning(f'Using stored key {key} for {url=}')
                    else:
                        self.logger.warning(f'Skipping empty title for {url=}')
                        return
                else:
                    # Construct file name
                    ext = self.get_extension(doc_type)
                    name = clean_filename(f'{prefix}-{title}.{ext}')
                    key = f'records/{name}'
                    # Save to index
                    self.downloader.add_entry(url, key)
                await self.download(url, key)

            async def download(self, url: str, key: str) -> None:
                dest = self.scraper.cache/key
                if dest.exists():
                    self.logger.info(f'Skipping download {key} already downloaded')
                    return
                wait = utils.Wait(timeout=5)
                try:
                    button = (await wait.until(self.find_buttons))[0]
                except TimeoutError:
                    self.logger.warning(f'No download button found for {key} {url=}')
                    return
                self.logger.info(f'Clicking download button for {key}')
                wait = utils.Wait(timeout=5, ignored=[Exception], oper=id)
                try:
                    await wait.until(button.click)
                except TimeoutError:
                    self.logger.warning(f'Click to download failed for {url=}', exc_info=True)
                    return
                wait = utils.Wait(timeout=10)
                try:
                    downloads = await wait.until(self.find_downloads)
                except TimeoutError:
                    self.logger.warning(f'Downloads did not complete for {key} {url=}')
                    return
                if len(downloads) > 1:
                    self.logger.warning(f'Multiple downloads found for {url=} {downloads}')
                    return
                self.logger.info(f'Moving download to {key}')
                downloads.pop().rename(dest)

            @staticmethod
            def get_title(text: str) -> str:
                start_str = 'Page 1 of '
                start_index = text.find(start_str)
                if start_index == -1:
                    return ''
                start_index += len(start_str)
                end_index = text.find('"', start_index)
                if end_index == -1:
                    return ''
                filename = text[start_index:end_index].split(', ')[1]
                return filename

            @staticmethod
            def get_extension(file_type: str) -> str:
                if file_type == 'Adobe PDF':
                    return 'pdf'
                return 'docx'

class LA(Scraper):
    base_url = 'https://www.laworks.net'
    latest_url = f'/Downloads/Downloads_WFD.asp'
    # PDFs no longer available for download after site redesign.
    historical_urls = [
        f'https://archive.warnreports.org/s/LA/historical/WarnNotices{y}.pdf'
        for y in range(2007, 2024)]

    async def scrape(self):
        index = {}
        page = bs(await self.fetch('latest.html', self.latest_url))
        recent = (utils.now().year, utils.now().year - 1)
        for a in page.find_all('a'):
            url = a.get('href', '')
            if 'WARN Notices' in a.text and url.endswith('.pdf'):
                key = url.split('/')[-1]
                is_recent = any(str(y) in key for y in recent)
                await self.download(key, url, missing_only=not is_recent)
                index[key] = self.absurl(url)
        for url in self.historical_urls:
            key = url.split('/')[-1]
            await self.download(key, url, missing_only=True)
            if key not in index:
                index[key] = url
        index = {key: index[key] for key in sorted(index, reverse=True)}
        self.cache.write_json('index.json', index, indent=2)

    def statobjs(self):
        yield from self.cache.glob('*.pdf')

    async def clean(self):
        self.cache.delete('*.pdf', '*.html', '*.csv', '*.json', glob=True)

    @contextmanager
    def extract(self):
        from warn.scrapers import la
        index = self.cache.read_json('index.json')
        headers: list[str] = []
        def readfile(key: str):
            url = index[key]
            rows: list[list[str]] = la._process_pdf(self.cache.topath(key))
            if not headers:
                headers.extend(next(filter(la._is_clean_header, rows)))
                headers.append('url')
            for values in filterfalse(la._is_header, rows):
                values.append(url)
                yield dict(zip(headers, values))
        yield chain.from_iterable(map(readfile, index))

class MD(Scraper):
    # Scrape time: 3s
    # Extract time: 2s
    base_url = 'https://www.dllr.state.md.us/employment'
    latest_url = '/warn.shtml'
    retry = dict(total=10)

    async def scrape(self):
        page = bs(await self.fetch('latest.html', self.latest_url))
        for a in page.find_all('a', {'class': 'sub'}):
            href = a['href'].lstrip('/')
            key = f'{href}.html'
            url = f'/{href}'
            year = int(href[4:8])
            is_recent = year >= utils.now().year - 1
            await self.download(key, url, missing_only=not is_recent)

    async def clean(self):
        self.cache.delete('*.html', glob=True)

    def statobjs(self):
        yield from self.get_tables()

    @contextmanager
    def extract(self):
        it = chain.from_iterable(map(self.read_table, self.get_tables()))
        headers = next(it)
        yield (dict(zip(headers, values)) for values in it)

    def read_table(self, table: Soup) -> Iterator[list[str]]:
        it = map(self.read_tr, table.find_all('tr'))
        return filter(any, map(list, it))

    def read_tr(self, tr: Soup) -> Iterator[str]:
        for td in tr.find_all('td'):
            yield ' '.join(td.text.split())

    def get_tables(self) -> Iterator[Soup]:
        for file in self.list_page_files():
            yield bs(file, 'html5lib').find('table')

    def list_page_files(self) -> list[Path]:
        return sorted(self.cache.glob('*.html'), reverse=True)

class MO(Scraper):
    start_year = 2019
    base_url = 'https://jobs.mo.gov/warn'
    archive_url = 'https://archive.warnreports.org/s/MO'
    headers_species = {
        10: ['Received', 'Title', 'Industry', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'Notes', 'url'],
        9: ['Received', 'Title', 'Industry', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'url'],
        8: ['Received', 'Title', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'url'],
    }

    async def scrape(self) -> None:
        now = utils.utcnow()
        for year in range(self.start_year, now.year + 1):
            key = f'pages/{year}.html'
            url = f'{self.archive_url}/{key}'
            is_recent = year >= now.year - 1
            try:
                rep = await self.download(key, url, missing_only=not is_recent)
            except HTTPError:
                if year == now.year and now.month < 2:
                    # Don't fail for current year if it is January
                    self.logger.warning(f'Current year download failed, skipping {url=}')
                    continue
                raise
            if year == now.year:
                dt = utils.parse_date(rep.headers.get('Last-Modified'))
                if not dt:
                    self.logger.warning(f'Cannot parse last-modified header')
                elif dt < utils.utcnow(days=-7):
                    self.logger.warning(
                        f'Current year page more than 7 days old {url=}. '
                        f'Refresh from {self.absurl(f'/{year}')}')

    async def clean(self) -> None:
        self.cache.delete('pages/*.html', glob=True)

    def statobjs(self):
        for file in self.list_page_files():
            yield bs(file).find('table')

    @contextmanager
    def extract(self):
        yield self.read_records()

    def read_records(self) -> Iterable[dict[str, str]]:
        for file in self.list_page_files():
            table = bs(file).find('table')
            year = int(file.name.removesuffix('.html'))
            url = self.absurl(str(year))
            it = iter(table.find_all('tr'))
            headers = self.get_header_species(next(it))
            for tr in it:
                values = [*self.read_tr(tr), url]
                if utils.morethan(2, values):
                    yield dict(zip(headers, values))

    def get_header_species(self, head: Soup) -> list[str]:
        return self.headers_species[len(head.find_all(['td', 'th']))]

    def read_tr(self, tr: Soup) -> Iterator[str]:
        for td in tr.find_all('td'):
            yield td.text.strip()

    def list_page_files(self) -> list[Path]:
        return sorted(self.cache.glob('pages/*.html'), reverse=True)

class NJ(Scraper):
    base_url = 'https://www.nj.gov/labor'
    latest_url = '/assets/PDFs/WARN/WARN_Notice_Archive.xlsx'

    async def scrape(self):
        await self.download('latest.xlsx', self.latest_url)

    def statobjs(self):
        yield self.cache.topath('latest.xlsx')

    async def clean(self):
        self.cache.delete('latest.xlsx')

    @contextmanager
    def extract(self):
        file = self.cache.topath('latest.xlsx')
        extra = dict(scrape_time=utils.file_mtime(file).isoformat())
        wb = openpyxl.load_workbook(file, read_only=True)
        it = chain.from_iterable(map(self.extract_xlsx_worksheet, wb.worksheets))
        yield (row|extra for row in it)

    def extract_xlsx_worksheet(self, ws: openpyxl.worksheet.worksheet.Worksheet):
        extra = dict(worksheet_name=ws.title)
        it = extract_xlsx_worksheet(ws)
        return (row|extra for row in it)

class NY(Scraper):
    base_url = 'https://dol.ny.gov'
    latest_url = '/warn-notices'
    past_urls = {
        '2024.html': '/2024-warn-notices',
        '2023.html': '/2023-warn-notices',
        '2022.html': '/2022-warn-notices',
        '2021.html': '/warn-notices-2021',
        'ny_historical.xlsx': 'https://archive.warnreports.org/s/NY/ny_historical.xlsx'}
    pdf_keytrans = {
        'L ayoff End Date': 'Layoff End Date',
    }
    artifact_map = {
        'https://dol.ny.gov/system/files/documents/2022/10/starry-inc.-2022-0043-10-20-2022.pdf':
            'https://dol.ny.gov/system/files/documents/2024/05/warn-nyc-starry-inc.-10.20.2022.pdf'
    }
    request_delay = 1

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)
        for key, url in self.past_urls.items():
            await self.download(key, url, missing_only=True)
        index = dict(self.build_artifacts_index())
        self.cache.write_json('artifacts.json', index, indent=2)
        for key, url in index.items():
            await self.download(key, url, missing_only=True)
            self.artifacts.add(key)

    async def clean(self):
        self.cache.delete('latest.html', 'artifacts.json', *self.past_urls)

    def statobjs(self):
        yield from map(self.cache.topath, self.past_urls)
        if (file := self.cache/'latest.html').exists():
            yield self.find_table(bs(file))

    @contextmanager
    def extract(self):
        keys = ('latest.html', *self.past_urls)
        yield chain.from_iterable(map(self.read_record_file, keys))

    def read_record_file(self, file: Path|str) -> Iterator[dict[str, str]]:
        "Call either read_html_file() or read_xlsx_file() depending on the file extenstion"
        file = self.cache/file
        return getattr(self, f'read_{file.name[-4:]}_file')(file)

    def read_xlsx_file(self, file: Path|str) -> Iterator[dict[str, str]]:
        "Extract records from historical xlsx file"
        return extract_xlsx(self.cache/file)

    def read_html_file(self, file: Path|str) -> Iterator[dict[str, str]]:
        "Extract records from HTML page"
        file = self.cache/file
        table = self.find_table(bs(file))
        it = iter(table.find_all('tr'))
        next(it)
        for tr in it:
            record = {}
            tds = tr.find_all('td')
            a = tds[0].a
            key, url = self.parse_record_key_url(a['href'])
            if self.cache.exists(key):
                record.update(self.read_record_pdf(key))
                record.update(artifacts_json=json.dumps({key: url}))
            record.update(
                company_name=a.text,
                notice_url=url,
                date_posted=tds[1].text,
                notice_dated=tds[2].text)
            yield record

    def find_table(self, page: Soup) -> Soup:
         "Find main table in HTML page"
         return page.find('div', {'class': 'landing-paragraphs'}).find('table')

    def parse_record_key_url(self, href: str) -> tuple[str, str]:
        "Return an artifact key and download URL from the href value"
        url = self.absurl(href)
        url = self.artifact_map.get(url, url)
        filename = Path(urlparse(url).path).name
        key = f'records/{filename}'
        if not filename.endswith('.pdf'):
            key = f'{key}.pdf'
        return key, url

    def build_artifacts_index(self) -> Iterator[tuple[str, str]]:
        "Build the artifacts index from the downloaded page files"
        for key in ('latest.html', *self.past_urls):
            if not key.endswith('.html'):
                continue
            file = self.cache/key
            table = self.find_table(bs(file))
            for a in table.select('tbody > tr > td:nth-of-type(1) > a'):
                yield self.parse_record_key_url(a['href'])

    def read_record_pdf(self, file: Path|str) -> Iterator[tuple[str, str]]:
        "Extract extra data from an individual record PDF download"
        text = self.extract_pdf_text(file)
        for line in text.splitlines():
            item = line.split(': ', 1)
            if len(item) == 1:
                continue
            key, value = item
            key = self.pdf_keytrans.get(key, key)
            yield key, value

    def extract_pdf_text(self, file: Path|str) -> str:
        "Cache extracted text to file for performance"
        file = self.cache/file
        textkey = f'{self.cache.tokey(file)}.txt'
        if not self.extract_cache.exists(textkey):
            with pdfplumber.open(file) as pdf:
                text = '\n'.join(page.extract_text() for page in pdf.pages)
            self.extract_cache.write(textkey, text)
        return self.extract_cache.read(textkey)

class OH(Scraper):
    base_url = 'https://jfs.ohio.gov'
    archive_url = 'https://archive.warnreports.org/s/OH/oh_historical.csv'
    latest_url = '/wps/portal/gov/jfs/job-services-and-unemployment/job-services/job-programs-and-services/submit-a-warn-notice/current-public-notices-of-layoffs-and-closures-sa/current-public-notices-of-layoffs-and-closures'
    request_delay = 1
    atext_pat = _r(r'^\s*(\d{4}) Public Notices')
    legacy_header_map = {
        'DateReceived': 'Date Received',
        'Potential NumberAffected': 'Potential Number Affected',
        'LayoffDate(s)': 'Layoff Date(s)',
        'PhoneNumber': 'Phone Number'}
    artifact404 = {
        'https://jfs.ohio.gov/static/warn/pdf/Things-Remembered.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Golden-Svcs-LLC.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Crothall-Healthcare.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Omaze.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Norcold-LLC-Gettysburg.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Norcold-LLC-Sidney.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/McLaren-St--Luke-s-Hospital.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Starry-Inc.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/OhioHealth.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Toppan-Merrill.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Specialized-Bicycle-Components-Inc.pdf',
    }
    rewrites = dict(
        artifact=[
            (_r(r' '), '+'),
            (_r(r'-\.pdf$'), '.pdf'),
            (_r(r'David-s-Bridal'), 'Davids-Bridal'),
        ],
        notice_id=[
            (_r(r'-+'), '-'),
            (_r(r'\*'), ''),
        ]
    )

    async def scrape(self):
        await self.download('oh_historical.csv', self.archive_url, missing_only=True)
        sources: deque[tuple[str, str]] = deque()
        page = bs(await self.fetch(key := 'latest.html', self.latest_url))
        self.cache.write_json(f'{key}.json', self.extract_json(page), indent=2)
        sources.append((f'{key}.json', self.absurl(self.latest_url)))
        for a in page.select('nav a'):
            if not (match := self.atext_pat.match(a.text)):
                continue
            key = f'{match.group(1)}.html'
            await self.download(key, a['href'], missing_only=True)
            if not self.cache.exists(f'{key}.json'):
                self.cache.write_json(
                    f'{key}.json',
                    self.extract_json(bs(self.cache.read(key))),
                    indent=2)
            sources.append((f'{key}.json', self.absurl(a['href'])))
        self.cache.write_json('sources.json', dict(sorted(sources)), indent=2)
        self.cache.write_json('index.json', index := self.build_index(), indent=2)
        for key, url in chain.from_iterable(map(dict.items, index.values())):
            await self.download(key, url, missing_only=True)
            self.artifacts.add(key)

    async def clean(self):
        self.cache.delete('*.html', '*.json', '*.csv', glob=True)

    def statobjs(self):
        yield from sorted(self.cache.glob('*.json', 'oh_historical.csv'))

    @contextmanager
    def extract(self):
        index = self.cache.read_json('index.json')
        sources = self.cache.read_json('sources.json')
        files = sorted(self.cache.glob('*.html.json'), reverse=True)
        with self.cache.open('oh_historical.csv') as file:
            yield chain(
                chain.from_iterable(
                    self.read_data_file(file, index, sources[file.name]) for file in files),
                self.read_historical(csv.reader(file), index))

    def read_data_file(self, file: Path, index: dict[str, dict[str, str]], source: str) -> Iterator[dict[str, str]]:
        with file.open() as f:
            data = json.load(f)['data']
        it = iter(data)
        next(it)
        headers = next(it)[:9]
        for values in filter(any, it):
            raw = dict(zip(headers, values))
            raw['URL'] = source
            ids = raw['Notice ID'].split(' and ')
            for notice_id in map(self.normalize_notice_id, ids):
                row = dict(raw)
                row['Notice ID'] = notice_id
                if notice_id in index:
                    row['artifacts_json'] = json.dumps(index[notice_id])
                yield row

    def read_historical(self, data: Iterable[list[str]], index: dict[str, dict[str, str]]) -> Iterator[dict[str, str]]:
        it = iter(data)
        headers = [self.legacy_header_map.get(header, header) for header in next(it)]
        for values in it:
            row = dict(zip(headers, values))
            if (notice_id := row.get('Notice ID')) and notice_id not in index:
                yield row

    def extract_json(self, page: Soup) -> dict[str, Any]:
        div = page.find('div', {'id': 'js-placeholder-json-data'})
        return json.loads(div.decode_contents().strip())

    def normalize_notice_id(self, value: str) -> str:
        return utils.rewrite_all(value, self.rewrites['notice_id']).strip()

    def build_index(self) -> dict[str, list[str]]:
        items: deque[tuple[str, str]] = deque()
        for file in self.cache.glob('*.html.json'):
            with file.open() as f:
                data: list[list[str]] = json.load(f)['data']
            it = iter(data)
            next(it)
            headers = next(it)
            k_id = headers.index('Notice ID')
            k_url = headers.index('URL')
            for values in filter(any, it):
                url = self.absurl(values[k_url])
                url = utils.rewrite_all(url, self.rewrites['artifact'])
                if not url.endswith('.pdf'):
                    continue
                if url in self.artifact404:
                    continue
                ids = values[k_id].split(' and ')
                ids = filter(None, map(self.normalize_notice_id, ids))
                for id in ids:
                    if id and url:
                        items.append((id, url))
        index = defaultdict(list)
        for key, value in sorted(items):
            index[key].append(value)
        for notice_id, values in index.items():
            if len(values) > 1:
                values = sorted(set(values))
            artifacts = {}
            for i, url in enumerate(values, start=1):
                if len(values) == 1:
                    key = f'records/{notice_id}.pdf'
                else:
                    key = f'records/{notice_id}_{i}.pdf'
                artifacts[key] = url
            index[notice_id] = artifacts
        return dict(index)

class PA(Scraper):
    base_url = 'https://www.pa.gov'
    latest_url = '/agencies/dli/programs-services/workforce-development-home/warn-requirements/warn-notices.html'
    pat_ol = _r(r'^[1-9][0-9]*\.\s')

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        # No warn-scraper implementation
        del self.runner

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)

    async def clean(self) -> None:
        self.cache.delete('latest.html')

    def statobjs(self):
        if (file := self.cache/'latest.html').exists():
            yield self.find_main_div(bs(file))

    @contextmanager
    def extract(self):
        yield self.read_records()

    def read_records(self) -> Iterator[dict[str, str]]:
        file = self.cache/'latest.html'
        scrape_time = utils.file_mtime(file)
        maindiv = self.find_main_div(bs(file))
        extra = dict(url=self.absurl(self.latest_url), scrape_time=scrape_time.isoformat())
        for yeardiv in self.find_year_divs(maindiv):
            h2s = yeardiv.find_all('h2')
            year = int(h2s.pop(0).text.strip())
            if not 2000 <= year <= utils.now().year + 1:
                raise ValueError(f'Invalid {year=}')
            extra.pop('reported_month', None)
            if h2s:
                # For 2024 & 2025, month headings are in <h2> elements,
                # and company names are in <h3> elements.
                for h2 in h2s:
                    text = h2.text.strip()
                    # raises ValueError
                    datetime.strptime(text, '%B')
                    extra['reported_month'] = f'{text} {year}'
                    cur = h2.find_next('div', {'class': 'cmp-accordion__panel'})
                    for h3 in cur.find_all('h3'):
                        yield self.parse_record(h3) | extra
            else:
                # For 2023, month headings and company names are both in
                # <h3> elements.
                h3s = yeardiv.find_all('h3')
                for h3 in h3s:
                    text = h3.text.strip()
                    try:
                        datetime.strptime(text, '%B')
                    except ValueError:
                        if 'reported_month' not in extra:
                            raise
                    else:
                        extra['reported_month'] = f'{text} {year}'
                        continue
                    yield self.parse_record(h3) | extra

    def find_main_div(self, doc: Soup) -> Soup:
        return (doc
            .find('section', {'class': 'agencypage-content'})
            .find('div')
            .find('div'))

    def find_year_divs(self, maindiv: Soup) -> Iterator[Soup]:
        for child in maindiv.children:
            if child.name == 'div' and 'panelcontainer' in child['class']:
                yield child

    def parse_record(self, h3: Soup) -> dict[str, str]:
        row = dict(company=_u(h3.text.strip()))
        text = h3.find_next_sibling('div').text
        text = text.replace('\u200b', '')
        lines = text.splitlines()
        lines: list[str] = list(filter(None, map(str.rstrip, lines)))
        curheader = None
        unparsed = []
        for i, line in enumerate(lines):
            clean = ' '.join(line.split()).strip()
            if i == 0:
                row['location'] = clean
                continue
            parts = clean.split(':', 1)
            if curheader and (
                line.startswith('\xa0') or
                self.pat_ol.match(clean) or
                parts[0] != parts[0].upper()
            ):
                if row[curheader]:
                    row[curheader] += '\n'
                row[curheader] += clean
                continue
            if not clean:
                continue
            if ':' not in clean:
                if not curheader:
                    row['location'] += '\n' + clean
                else:
                    unparsed.append(clean)
                continue
            curheader = parts[0].strip()
            row[curheader] = parts[1].strip()
        if unparsed:
            row['unparsed'] = '\n'.join(unparsed)
        row['raw'] = '\n'.join(lines)
        return row

class SC(Scraper):
    base_url = 'https://scworks.org'
    latest_url = '/employer/employer-programs/risk-closing/layoff-notification-reports'
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
        text = await self.fetch('latest.html', self.latest_url)
        page = bs(text)
        for a in page.find_all('a'):
            href = a.get('href', '')
            if href.endswith('2024_0.pdf'):
                # Duplicate data
                continue
            if href.endswith('.pdf'):
                year = int(href.split('/')[-1][:4])
                index.append((year, href))
                key = f'{year}.pdf'
                is_recent = year >= utils.now().year - 1
                await self.download(key, href, missing_only=not is_recent)
                self.artifacts.add(key)
        index.sort()
        self.cache.write_json('index.json', index, indent=2)

    async def clean(self) -> None:
        self.cache.delete('latest.html', 'index.json')

    def statobjs(self):
        yield self.cache/'index.json'
        yield from self.list_record_files()

    @contextmanager
    def extract(self):
        yield self.read_records()

    def read_records(self) -> Iterator[dict[str, str]]:
        for year, url in self.load_index():
            headers = self.get_header_species(year) + self.extra_headers
            extra = [str(year), url]
            it = self.read_table(self.cache/f'{year}.pdf')
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
        it = chain.from_iterable(it)
        it = map(self.process_table, it)
        it = filter(None, it)
        it = self.merge_tables(it)
        it = (list(map(self.clean_cell, row)) for row in it)
        yield from it

    def process_table(self, table: list[list[str|None]]) -> list[list]:
        self.remove_extra_header(table)
        if self.table_is_sparse(table) or self.table_is_summary(table):
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
        return sorted(self.cache.glob('*.pdf'), reverse=True)

    def table_is_sparse(self, table: list[list]) -> bool:
        return not any(utils.morethan(1, row) for row in table)

    def table_is_summary(self, table: list[list]) -> bool:
        return bool(table) and table[0][:2] == ['County', 'Impacted']

    def remove_extra_header(self, table: list[list]) -> None:
        if table and not utils.morethan(1, table[0]):
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

class TX(Scraper):
    base_url = 'https://www.twc.texas.gov'
    latest_url = '/data-reports/warn-notice'
    href_pat = _r(r'^/sites/default/files/oei/docs/warn-act-listings-')
    year_pat = _r(r'.*-(\d{4})-')
    archive_url = 'https://archive.warnreports.org/s/TX/tx_historical.xlsx'
    ssl_verify = False

    async def scrape(self):
        page = bs(await self.fetch('latest.html', self.latest_url))
        for a in page.find_all('a', href=self.href_pat):
            href = a['href']
            key = Path(URL(self.absurl(href)).path).name
            year = int(self.year_pat.match(key)[1])
            is_recent = year >= utils.now().year - 1
            await self.download(key, href, missing_only=not is_recent)
            self.artifacts.add(key)
        key = self.archive_url.split('/')[-1]
        await self.download(key, self.archive_url, missing_only=True)

    async def clean(self):
        self.cache.delete('latest.html', '*.xlsx', glob=True)

    def statobjs(self):
        yield from self.list_record_files()

    @contextmanager
    def extract(self):
        yield chain.from_iterable(map(self.extract_xlsx, self.list_record_files()))

    def extract_xlsx(self, file: Path) -> Iterator[dict[str, str]]:
        extra = {}
        if self.year_pat.match(file.name):
            extra.update(artifact_url=self.absurl(file.name))
        for row in extract_xlsx(file):
            row.update(extra)
            yield row

    def list_record_files(self) -> list[Path]:
        return sorted(self.cache.glob('*.xlsx'), reverse=True)

class UT(Scraper):
    base_url = 'https://jobs.utah.gov'
    latest_url = '/employer/business/warnnotices.html'

    async def scrape(self):
        await self.download('latest.html', self.latest_url)

    def statobjs(self):
        if (file := self.cache/'latest.html').exists():
            yield from bs(file).find_all('table')

    async def clean(self):
        self.cache.delete('latest.html')

    @contextmanager
    def extract(self):
        file = self.cache/'latest.html'
        extra = dict(scrape_time=utils.file_mtime(file).isoformat())
        tables = bs(file).find_all('table')
        it = chain.from_iterable(map(self.read_table, tables))
        yield (row|extra for row in it)

    def read_table(self, table: Soup) -> Iterator[dict[str, str]]:
        it = (
            [td.text.strip() for td in tr.find_all(('td', 'th'))]
            for tr in table.find_all('tr'))
        headers = next(it)
        for values in it:
            yield dict(zip(headers, values))

class VA(Scraper):
    # TODO: detail url: https://www.vec.virginia.gov/warn-notice-detail/18595
    base_url = 'https://www.vec.virginia.gov'
    latest_url = '/warn-notices'
    rss_url = '/warn-notices-rss-1'
    """
    the downloadable csv does not have links
    <ul class="pagination">
        <li class="next"><a title="Go to next page" href="/warn-notices?page=2">
    
    NB: there are about 50 pages. you can filter by year. there is a select box that lists them.
    """
    csv_url = 'https://www.virginiaworks.gov/warn_notices.csv'

    async def scrape(self):
        await self.download(self.runner.file, self.csv_url)

class Cache(warn.cache.Cache):

    def __init__(self, state: str, stage: Stage) -> None:
        data_dir = settings.BUILD_DIR/Stage(stage)
        super().__init__(data_dir/state.lower())
        self.dir = Path(self.path)

    def delete(self, *keys: str, glob: bool = False) -> None:
        for key in keys:
            if glob and isinstance(key, str):
                paths = self.glob(key)
            else:
                paths = (self.topath(key),)
            for path in paths:
                path.unlink(missing_ok=True)
    
    def topath(self, key: str) -> Path:
        return Path(self.dir, key)

    def tokey(self, file: Path) -> str:
        return str(self.topath(file).relative_to(self.path))

    def open(self, key: str, *args, **kw):
        return self.topath(key).open(*args, **kw)

    def write_json(self, key: str, obj: Any, **kw) -> None:
        file = self.topath(key)
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open('w') as file:
            json.dump(obj, file, **kw)

    def read_json(self, key: str, **kw) -> Any:
        with self.open(key) as file:
            return json.load(file, **kw)

    def glob(self, *globs) -> Iterator[Path]:
        return chain.from_iterable(
            map(self.topath, self.files('.', glob))
            for glob in globs)

    def nuke(self) -> None:
        if self.dir.exists():
            shutil.rmtree(self.dir)

    def mkdir(self, key: str|None = None) -> None:
        self.topath(key or '.').mkdir(parents=True, exist_ok=True)

    def subcache(self, key: str) -> Self:
        key = self.tokey(key)
        inst = type(self)('XX', 'scrape')
        inst.dir = self.dir/key
        inst.path = str(inst.dir)
        return inst

    def __truediv__(self, other: str|Path) -> Path:
        return self.dir/other

    _path_from_env = str(settings.BUILD_DIR)
    _path_default = str(settings.BUILD_DIR)

class Artifacts:

    def __init__(self, state: str):
        self.state = state.upper()
        self.dir = settings.ARTIFACTS_DIR/state.lower()
        self.src = settings.BUILD_DIR/Stage.Scrape/state.lower()
        self.metrics = defaultdict(int)

    def add(self, key: str, file: Path|None = None) -> tuple[SaveType, int]:
        key = key.strip('/')
        file = file or self.src/key
        dest = self.dir/key
        digfile = Path(f'{dest}.sha1')
        sta = file.stat()
        if dest.exists():
            stb = dest.stat()
            a = (int(sta.st_mtime), sta.st_size)
            b = (int(stb.st_mtime), stb.st_size)
            if a == b:
                save = SaveType.Nochange
            elif a[1] == b[1]:
                with file.open('rb') as f:
                    diga = hashlib.file_digest(f, 'sha1').hexdigest()
                if digfile.exists():
                    digb = digfile.read_text().strip()
                else:
                    with dest.open('rb') as f:
                        digb = hashlib.file_digest(f, 'sha1').hexdigest()
                    digfile.write_text(digb)
                if diga == digb:
                    save = SaveType.Nochange
                else:
                    save = SaveType.Update
            else:
                save = SaveType.Update
        else:
            save = SaveType.Create
            dest.parent.mkdir(parents=True, exist_ok=True)
        if save is not save.Nochange:
            digfile.unlink(missing_ok=True)
            shutil.copyfile(file, dest)
            shutil.copystat(file, dest)
            with dest.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha1').hexdigest()
            digfile.write_text(digest)
            self.metrics['bytes_written'] += sta.st_size
        self.metrics[str(save)] += 1
        self.metrics['total'] += 1
        self.metrics['bytes_total'] += sta.st_size
        return save, sta.st_size

class Runner(warn.Runner):

    def __init__(self, state: str):
        self.state = state.upper()
        cache_dir = settings.BUILD_DIR/Stage.Scrape
        data_dir = cache_dir/self.state.lower()
        self.file = data_dir/f'{self.state.lower()}.csv'
        super().__init__(data_dir, cache_dir)

    def scrape(self) -> None:
        super().scrape(self.state.lower())

    def statobjs(self) -> Iterable[Any]:
        yield self.file

def absurl(base_url: str|None, url: str) -> None:
    if base_url and not any(map(url.startswith, ('http://', 'https://'))):
        url = base_url.rstrip('/') + '/' + url.lstrip('/')
    return url

def bs(markup: Any, features='html.parser', **kw):
    if isinstance(markup, Path):
        markup = markup.read_bytes()
    return Soup(markup, features, **kw)

def extract_xlsx(file: Path) -> Iterator[dict[str, str]]:
    worksheet = openpyxl.load_workbook(file, read_only=True).worksheets[0]
    return extract_xlsx_worksheet(worksheet)

def extract_xlsx_worksheet(ws: Worksheet) -> Iterator[dict[str, str]]:
    it = ([cell.value for cell in row] for row in ws.rows)
    headers = next(it)
    for values in filter(any, it):
        row = {}
        for k, v in filter(any, zip(headers, values)):
            if v is None:
                v = ''
            elif isinstance(v, datetime):
                v = v.strftime(f'%Y-%m-%d')
            else:
                v = str(v)
            row[k] = v
        yield row

def hashstat(it: Iterable[Path|str|Buffer]) -> dict[str, str|int|None]:
    h = hashlib.sha1()
    size = 0
    for obj in it:
        if isinstance(obj, Path):
            try:
                with obj.open('rb') as file:
                    hashlib.file_digest(file, lambda: h)
                size += obj.stat().st_size
            except FileNotFoundError:
                pass
            continue
        if isinstance(obj, str):
            buf = obj.encode()
        elif isinstance(obj, PageElement):
            buf = obj.text.encode()
        else:
            buf = obj
        if buf:
            h.update(buf)
            size += len(buf)
    hash = h.hexdigest() if size else None
    return dict(hash=hash, size=size)

clean_filename_subs = [
    (_r(r'[^a-z\d_]', re.I), '-'),
    (_r(r'([-_])+'), r'\1'),
]
clean_extension_subs = [(rw[0], '') for rw in clean_filename_subs]

def clean_filename[T](value: str, default: T = None) -> str|T:
    parts = value.rsplit('.', 1)
    clean = utils.rewrite_all(parts[0], clean_filename_subs)
    clean = clean.strip('_-')
    if clean:
        if len(parts) == 2:
            ext = utils.rewrite_all(parts[1], clean_extension_subs)
            clean = f'{clean}.{ext}'
        return clean
    return default

scrapers.update({
    state: type(state, (Scraper,), {})
    for state in map(str.upper, warn.utils.get_all_scrapers())
    if state not in scrapers})

if TYPE_CHECKING:
    from typing import overload
    class Soup(Soup):
        @overload
        def find_all(
            self,
            name:str|Any=...,
            attrs: dict[str, Any]=...,
            recursive:bool=True,
            string:str|Any=...,
            limit:int|None=...,
            **kwargs) -> ResultSet[Soup|PageElement|Tag]: ...
