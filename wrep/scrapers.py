from __future__ import annotations

import asyncio
import csv
import dataclasses
import hashlib
import json
import re
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime
from html import unescape as _u
from importlib import import_module
from itertools import chain, filterfalse
from pathlib import Path
from re import compile as _r
from typing import Any, ClassVar, Generator, Iterable, Iterator
from urllib.parse import parse_qs, unquote_plus, urlparse

import requests
from requests.adapters import HTTPAdapter, Retry
from requests.exceptions import HTTPError
from starlette.datastructures import URL
from typing_extensions import Buffer

from . import Stage, settings, utils
from .backends import webdrivers
from .models import ScraperOpts, StateCode
from .tools import dom, matx, pdfs, xlsx
from .tools.dom import Soup, bs
from .tools.files import (ArtifactStore, FileCache, clean_filename, excachectx,
                          jsoncache)
from .utils import wrapcontext

scrapers: dict[str, type[Scraper]] = {}

class Scraper:
    state: ClassVar[StateCode]
    base_url: ClassVar[str|None] = None
    user_agent: ClassVar[str] = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0'
    request_delay: ClassVar[float] = 0.0
    ssl_verify: ClassVar[bool] = True
    retry: ClassVar[dict] = dict(total=3, backoff_factor=2)

    def __init__(self, *, opts: ScraperOpts|dict|None = None):
        self.opts = ScraperOpts.model_validate(opts or {})
        self.runner = Runner(self.state)
        self.session = requests.session()
        retry = Retry(**self.retry)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.session.headers['User-Agent'] = self.user_agent
        self.cache = FileCache(settings.BUILD_DIR/Stage.Scrape/self.state.lower())
        self.extract_cache = FileCache(settings.BUILD_DIR/Stage.Extract/self.state.lower())
        self.artifacts = ArtifactStore(
            settings.ARTIFACTS_DIR/self.state.lower(),
            self.cache.dir)
        self.metrics = defaultdict(int)
        self.logger = utils.get_logger(f'scrapers.{self.state}')

    async def clean(self) -> None:
        self.runner.file.unlink(missing_ok=True)

    async def scrape(self) -> None:
        self.runner.scrape()

    async def stat(self) -> dict[str, Any]:
        return hashstat(self.statobjs())

    def statobjs(self) -> Iterable[Any]:
        yield self.runner.file

    @contextmanager
    def extract(self) -> Generator[Iterable[dict[str, str|None]]]:
        def rest(row: dict):
            # Backwards-compatibility
            if '__' in row:
                row['__'] = json.dumps(row['__'])
            return row
        with self.runner.file.open() as file:
            it = csv.DictReader(file, restkey='__')
            yield map(rest, it)

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
        dest = self.cache/key
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
        index = self.build_index()
        for url, key in index.items():
            await self.download(key, url, missing_only=True)
            self.artifacts.add(key)

    async def clean(self):
        self.cache.delete('latest.html', 'index.json')

    def statobjs(self):
        if (file := self.cache/'latest.html').exists():
            yield bs(file).find('table')
        yield self.cache/'index.json'

    def build_index(self) -> dict[str, str]:
        'Mapping from url to cache key'
        items: deque[tuple[str, str]] = deque()
        table = bs(self.cache/'latest.html').find('table')
        for a in table.find_all('a'):
            href = a.get('href')
            if href and href.endswith('.pdf'):
                url = self.absurl(href)
                urlid = uuid.uuid5(settings.NAMESPACE, url).hex[:6]
                filename = clean_filename(f'{Path(href).stem}-{urlid}.pdf')
                key = f'records/{filename}'
                items.append((url, key))
        index = dict(sorted(items))
        self.cache.write_json('index.json', index, indent=2)
        return index

    @wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:

        def parseurl(tr: Soup) -> str:
            td = tr.find('td')
            if td.text.strip() == 'Company':
                # header row
                return 'url'
            a = td.find('a')
            if a:
                return self.absurl(a['href'])
            return ''

        def readtr(tr: Soup) -> Iterator[str]:
            for td in tr.find_all('td'):
                yield ' '.join(td.text.split())

        def readtable(table: Soup):
            for tr in table.find_all('tr'):
                url = parseurl(tr)
                values = [*readtr(tr), url]
                if len(values) > 2 and values[0]:
                    if url in index:
                        values.append(json.dumps({index[url]: url}))
                    yield values

        index: dict[str, str] = self.cache.read_json('index.json')
        doc = bs(self.cache/'latest.html')
        it = readtable(doc.find('table'))
        headers = next(it)
        headers.append('artifacts_json')
        for values in it:
            yield dict(zip(headers, values))

class CA(Scraper):
    base_url = 'https://edd.ca.gov'
    latest_url = '/Jobs_and_Training/Layoff_Services_WARN.htm'
    hrefpat = _r(r'warn[-_]?report', re.I)

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)
        index = self.build_index()
        for key, url in index.items():
            await self.download(key, url, missing_only=key.endswith('.pdf'))
            self.artifacts.add(key)

    async def clean(self):
        self.cache.delete('latest.html', 'index.json')

    def statobjs(self):
        yield from sorted(self.cache.glob('*.pdf', '*.xlsx'))
        yield self.cache/'index.json'

    @wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        index: dict[str, str] = self.cache.read_json('index.json')
        def clean(data: dict[str, str]):
            return dict(zip(data, map(str, data.values())))
        for key, url in index.items():
            file = self.cache/key
            cached = self.extract_cache/f'{key}.json'
            with jsoncache(file, cached) as saved:
                if not saved:
                    from warn.scrapers import ca
                    if file.suffix == '.pdf':
                        saved = ca._extract_pdf_data(file)
                    else:
                        saved = ca._extract_excel_data(file)
                    with cached.open('w') as f:
                        json.dump(saved, f, indent=2)
            extra = dict(artifacts_json=json.dumps({key: url}))
            for data in map(clean, saved):
                yield data|extra

    def build_index(self) -> dict[str, str]:
        'Build downloads index {cache_key: url}'
        page = bs(self.cache/'latest.html')
        items: deque[tuple[str, str]] = deque()
        for link in page.find_all('a'):
            href = str(link.get('href', ''))
            if self.hrefpat.search(href):
                key = Path(urlparse(href).path).name
                url = self.absurl(href)
                items.append((key, url))
        index = dict(sorted(items))
        self.cache.write_json('index.json', index, indent=2)
        return index

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
            yield csv.DictReader(file)

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

    @wrapcontext
    def extract(self):
        "Yield augmented records from CSV rows"
        index: dict[str, list[str]] = self.cache.read_json('artifacts.json')
        with self.runner.file.open() as file:
            it = csv.reader(file)
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

    @wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
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
        index = self.build_index()
        for key, url in index.values():
            await self.download(key, url, missing_only=True)
            self.artifacts.add(key)

    async def clean(self):
        await super().clean()
        self.cache.delete('artifacts.json')

    def statobjs(self):
        yield from super().statobjs()
        yield self.cache/'artifacts.json'

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
            values_key = self.values_key(values)
            if values_key in index:
                key, url = index[values_key]
                row.update(
                    download=url,
                    artifacts_json=json.dumps({key: url}))
            yield row

    def build_index(self) -> dict[str, tuple[str, str]]:
        "Build the artifacts index {values_key: (cache_key, url)}"
        index: dict[str, tuple[str, str]] = {}
        for file in sorted(self.cache.glob('*_page_*.html'), reverse=True):
            year = int(file.name[:4])
            table = bs(file, 'html5lib').find('table')
            index.update(self.parse_downloads_table(year, table))
        self.cache.write_json('artifacts.json', index, indent=2)
        return index

    def values_key(self, values: Iterable[str]) -> str:
        "Values hash key from CSV row for artifact index"
        return ''.join(''.join(values).split())

    def parse_downloads_table(self, year: int, table: Soup) -> Iterator[tuple[str, tuple[str, str]]]:
        "Yields (values_key, (cache_key, url)) for an html table"
        tbody = table.find('tbody')
        for tr in tbody.find_all('tr'):
            tds = tr.find_all('td')
            last = tds.pop()
            if last.find('input', id='download'):
                if (el := last.find('input', type='hidden')):
                    if (info := self.artifact_info(year, el['value'])):
                        values_key = self.values_key(td.text for td in tds)
                        yield values_key, info

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
        await self.download('latest.html', self.latest_url)
        payload = dict(self.payload, nonce=self.extract_nonce())
        rep = await self.request('POST', self.api_url, data=payload)
        try:
            body = rep.json()
        except requests.exceptions.JSONDecodeError:
            self.logger.error(f'{rep.status_code} {rep.url} {payload=} content={rep.content}')
            raise
        self.cache.write_json('latest.json', body, indent=2)
        index = self.build_index()
        if self.needs_scrape():
            await asyncio.sleep(0)
            self.runner.scrape()
        artifacts = {}
        for notice_id in index:
            infos = dict(self.extract_artifact_infos(notice_id))
            if infos:
                artifacts[notice_id] = infos
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
        yield from sorted(self.cache.glob('*.format3'), reverse=True)

    def build_index(self) -> dict[str, tuple[str, str]]:
        body: dict = self.cache.read_json('latest.json')
        index: dict[str, tuple[str, str]] = {}
        for listing in body['data']:
            a = bs(listing[0], 'html5lib').find('a')
            notice_id = a.text
            url = self.absurl(a['href'])
            datestr = listing[2]
            index[notice_id] = (url, datestr)
        self.cache.write_json('index.json', index, indent=2)
        return index

    def needs_scrape(self) -> bool:
        index = self.cache.read_json('index.json')
        source = self.runner.file
        keys = (f'{key}.format3' for key in index)
        return not (
            source.exists() and
            source.stat().st_size and
            self.cache.exists('index.json') and
            all(map(self.cache.exists, keys)))

    def extract_artifact_infos(self, notice_id: str) -> Iterator[tuple[str, str]]:
        doc = bs(self.cache/f'{notice_id}.format3')
        for a in doc.find_all('a', {'data-type': 'pdf'}):
            filename = self.artifact_filename(a['href'])
            if filename:
                cachekey = f'records/{notice_id}-{filename}'
                yield cachekey, self.absurl(a['href'])

    def extract_nonce(self) -> str|None:
        doc = bs(self.cache/'latest.html', 'html5lib')
        script = doc.find(
            'script',
            text=lambda text: text and 'window.gvDTglobals.push' in text)
        match = re.search(r'"nonce":"([^"]+)"', str(script))
        if match:
            return match.group(1)

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

    @contextmanager
    def extract(self):
        index: dict = self.cache.read_json('index.json')
        artifacts = self.cache.read_json('artifacts.json')
        def readrecords(it: Iterable[list[str]]):
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
        with self.runner.file.open() as file:
            yield readrecords(csv.reader(file))

class IL(Scraper):
    source_url = 'https://apps.illinoisworknet.com/iebs/api/public/export'
    source_params = [
        ('search', ''),
        ('layoffTypes', ''),
        ('trade', '0'),
        ('dateReportedStart', 'Invalid Date'),
        ('dateReportedEnd', 'Invalid Date'),
        ('statuses', '4'),
        ('reasons', ''),
        ('eventCauses', ''),
        ('naicsCodes', '1'),
        ('naicIndustries', ''),
        ('naics', ''),
        ('unionsInvolved', '0'),
        ('geolocation', '1'),
        ('cities', ''),
        ('counties', ''),
        ('lwias', ''),
        ('includeAdditionalLwias', 'false'),
        ('edrs', ''),
        ('lat', '0'),
        ('lng', '0'),
        ('distance', '.5'),
        ('memberType', '1'),
        ('users', ''),
        ('accessList', ''),
        ('bookmarked', 'false')]

    async def scrape(self):
        await self.download('export.xlsx', self.source_url, params=self.source_params)

    def statobjs(self):
        file = self.cache/'export.xlsx'
        if file.exists():
            for row in xlsx.extract_workbook(file):
                row.pop('NAICS Codes', None)
                yield json.dumps(row)

    async def clean(self):
        self.cache.delete('export.xlsx')

    @contextmanager
    def extract(self):
        yield xlsx.extract_workbook(self.cache/'export.xlsx')

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

    @wrapcontext
    def extract(self):

        def readtable(table: Soup) -> Iterator[list[str]]:
            tags = ['td', 'th']
            for tr in table.find_all('tr'):
                tds = tr.find_all(tags)
                if not tds:
                    continue
                last = tds.pop()
                values = [td.text.strip() for td in tds]
                values.append(parseurl(last))
                yield values

        def parseurl(cell: Soup) -> str:
            if cell.name == 'th':
                # header row
                return 'url'
            a = cell.find('a')
            if a:
                return self.absurl(a['href'])
            return cell.text.strip()

        doc = bs(self.cache/'latest.html')
        for i, table in enumerate(doc.find_all('table')):
            it = readtable(table)
            if i == 0:
                headers = next(it)
            for values in it:
                yield dict(zip(headers, values))

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
        with self.runner.file.open() as f:
            yield map(extend, csv.DictReader(f))

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
            cache: FileCache

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
        await self.download('latest.html', self.latest_url)
        index = self.build_index()
        now = utils.now()
        recent = (now.year, now.year - 1)
        for key, url in index.items():
            is_recent = (
                'historical' not in url and
                any(str(y) in key for y in recent))
            await self.download(key, url, missing_only=not is_recent)

    def statobjs(self):
        yield from sorted(self.cache.glob('*.pdf'))

    async def clean(self):
        self.cache.delete('*.pdf', '*.html', '*.csv', '*.json', glob=True)

    @contextmanager
    def extract(self):
        from warn.scrapers import la
        index: dict[str, str] = self.cache.read_json('index.json')
        headers: list[str] = []
        def readfile(key: str):
            url = index[key]
            file = self.cache/key
            cached = self.extract_cache/f'{key}.json'
            with jsoncache(file, cached) as rows:
                if not rows:
                    rows: list[list[str]] = la._process_pdf(file)
                    with cached.open('w') as f:
                        json.dump(rows, f, indent=2)
            if not headers:
                headers.extend(next(filter(la._is_clean_header, rows)))
                headers.append('url')
            for values in filterfalse(la._is_header, rows):
                values.append(url)
                yield dict(zip(headers, values))
        yield chain.from_iterable(map(readfile, index))

    def build_index(self) -> dict[str, str]:
        'Build downloads index {cache_key: url}'
        items: deque[tuple[str, str]] = deque()
        page = bs(self.cache/'latest.html')
        for a in page.find_all('a'):
            href = a.get('href', '')
            if 'WARN Notices' in a.text and href.endswith('.pdf'):
                key = href.split('/')[-1]
                url = self.absurl(href)
                items.append((key, url))
        for url in self.historical_urls:
            key = url.split('/')[-1]
            items.append((key, url))
        index = dict(sorted(items, reverse=True))
        self.cache.write_json('index.json', index, indent=2)
        return index

class MD(Scraper):
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

    @wrapcontext
    def extract(self):
        def readtr(tr: Soup) -> list[str]:
            return [' '.join(td.text.split()) for td in tr.find_all('td')]
        def readtable(table: Soup) -> Iterator[list[str]]:
            return filter(any, map(readtr, table.find_all('tr')))
        it = map(readtable, self.get_tables())
        it = chain.from_iterable(it)
        headers = next(it)
        for values in it:
            yield dict(zip(headers, values))

    def get_tables(self) -> Iterator[Soup]:
        for file in self.list_page_files():
            yield bs(file, 'html5lib').find('table')

    def list_page_files(self) -> list[Path]:
        return sorted(self.cache.glob('*.html'), reverse=True)

class ME(Scraper):

    async def scrape(self) -> None:
        # CSV files appear to get corrupted sometimes, resulting in missing data, which breaks
        # hashing. Clearing the CSV seems to help.
        self.cache.delete('*.csv', glob=True)
        await super().scrape()

    async def clean(self) -> None:
        self.cache.delete('*.csv', glob=True)

    def statobjs(self):
        yield from self.cache.glob('*.csv')

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
        years = range(self.start_year, utils.now().year + 1)
        keys = [f'pages/{y}.html' for y in years]
        if settings.SELENIUM_ENABLED:
            func = self.driver_scrape
            urls = [self.absurl(f'/{y}') for y in years]
        else:
            func = self.archive_scrape
            urls = [f'{self.archive_url}/{key}' for key in keys]
        index = dict(zip(years, zip(keys, urls)))
        await func(index)

    async def driver_scrape(self, index: dict[int, tuple[str, str]]) -> None:
        def find_content():
            return driver.find_element('css selector', 'div.view-warn-notices')
        wait = utils.Wait(timeout=10)
        now = utils.utcnow()
        async with webdrivers.selenium() as driver:
            for year, (key, url) in index.items():
                is_recent = year >= now.year - 1
                if not is_recent and self.cache.exists(key):
                    continue
                driver.get(url)
                try:
                    await wait.until(find_content)
                except TimeoutError:
                    self.logger.warning(f'Failed to find content for {url=}')
                    return
                self.logger.info(f'Scraped {key}')
                self.cache.write(key, driver.page_source)

    async def archive_scrape(self, index: dict[int, tuple[str, str]]) -> None:
        now = utils.utcnow()
        for year, (key, url) in index.items():
            is_recent = year >= now.year - 1
            rep = await self.download(key, url, missing_only=not is_recent)
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

    def list_page_files(self) -> list[Path]:
        return sorted(self.cache.glob('pages/*.html'), reverse=True)

    @wrapcontext
    def extract(self) -> Iterable[dict[str, str]]:
        def readtr(tr: Soup) -> Iterator[str]:
            for td in tr.find_all('td'):
                yield td.text.strip()
        for file in self.list_page_files():
            table = bs(file).find('table')
            year = int(file.name.removesuffix('.html'))
            url = self.absurl(str(year))
            it = iter(table.find_all('tr'))
            width = len(next(it).find_all(['td', 'th']))
            headers = self.headers_species[width]
            for tr in it:
                values = [*readtr(tr), url]
                if utils.morethan(2, values):
                    yield dict(zip(headers, values))

class NJ(Scraper):
    base_url = 'https://www.nj.gov/labor'
    latest_url = '/assets/PDFs/WARN/WARN_Notice_Archive.xlsx'
    retry = dict(total=5)

    async def scrape(self):
        await self.download('latest.xlsx', self.latest_url)

    def statobjs(self):
        yield self.cache.topath('latest.xlsx')

    async def clean(self):
        self.cache.delete('latest.xlsx')

    @wrapcontext
    def extract(self):
        file = self.cache/'latest.xlsx'
        scrape_time = utils.file_mtime(file).isoformat()
        wb = xlsx.load_workbook(file)
        for ws in wb.worksheets:
            extra = dict(scrape_time=scrape_time, worksheet_name=ws.title)
            for data in xlsx.extract_worksheet(ws):
                data.update(extra)
                yield data

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
        index = self.build_index()
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

    def build_index(self) -> dict[str, str]:
        "Build the artifacts index from the downloaded page files {cache_key: url}"
        items: deque[tuple[str, str]] = deque()
        for key in ('latest.html', *self.past_urls):
            if not key.endswith('.html'):
                continue
            file = self.cache/key
            table = self.find_table(bs(file))
            for a in table.select('tbody > tr > td:nth-of-type(1) > a'):
                items.append(self.parse_record_key_url(a['href']))
        index = dict(items)
        self.cache.write_json('artifacts.json', index, indent=2)
        return index

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

    def read_record_file(self, key: str) -> Iterator[dict[str, str]]:
        "Call either read_html_file() or read_xlsx_file() depending on the file extenstion"
        file = self.cache/key
        return getattr(self, f'read_{file.suffix[1:]}_file')(key)

    def read_xlsx_file(self, key: str) -> Iterator[dict[str, str]]:
        "Extract records from historical xlsx file"
        file = self.cache/key
        cached = self.extract_cache/f'{key}.json'
        with jsoncache(file, cached) as saved:
            if not saved:
                saved = list(xlsx.extract_workbook(file))
                with cached.open('w') as f:
                    json.dump(saved, f, indent=2)
        yield from saved    

    def read_html_file(self, key: str) -> Iterator[dict[str, str]]:
        "Extract records from HTML page"
        file = self.cache/key
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

    def read_record_pdf(self, key: str) -> Iterator[tuple[str, str]]:
        "Extract extra data from an individual record PDF download"
        text = self.extract_pdf_text(key)
        for line in text.splitlines():
            item = line.split(': ', 1)
            if len(item) == 1:
                continue
            key, value = item
            key = self.pdf_keytrans.get(key, key)
            yield key, value

    def extract_pdf_text(self, key: str) -> str:
        "Cache extracted text to file for performance"
        file = self.cache/key
        cached = self.extract_cache/f'{key}.txt'
        with excachectx(file, cached) as saved:
            if saved:
                return saved.read_text()
            with pdfs.open(file) as pdf:
                text = '\n'.join(page.extract_text() for page in pdf.pages)
            cached.write_text(text)
        return text

class OH(Scraper):
    base_url = 'https://jfs.ohio.gov'
    latest_url = (
        '/wps/portal/gov/jfs/job-services-and-unemployment/job-services'
        '/job-programs-and-services/submit-a-warn-notice'
        '/current-public-notices-of-layoffs-and-closures-sa'
        '/current-public-notices-of-layoffs-and-closures')
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
    # Archived historical data
    historical_url = 'https://archive.warnreports.org/s/OH/oh_historical.csv'
    archived_sources = {
        # 2025-02 The 2024 link disappeared from the website for a while, so we
        #         keep archived sources as a fallback.
        '2020.html': 'https://archive.warnreports.org/s/OH/2020.html',
        '2021.html': 'https://archive.warnreports.org/s/OH/2021.html',
        '2022.html': 'https://archive.warnreports.org/s/OH/2022.html',
        '2023.html': 'https://archive.warnreports.org/s/OH/2023.html',
        '2024.html': 'https://archive.warnreports.org/s/OH/2024.html',
    }

    async def scrape(self):
        await self.download('latest.html', self.latest_url)
        sources = self.build_sources()
        for key, url in sources.items():
            await self.download(key, url, missing_only=True)
            self.extract_json(key)
        index = self.build_index()
        for items in map(dict.items, index.values()):
            for key, url in items:
                await self.download(key, url, missing_only=True)
                self.artifacts.add(key)
        await self.download('oh_historical.csv', self.historical_url, missing_only=True)

    async def clean(self):
        self.cache.delete('*.html', '*.json', '*.csv', glob=True)

    def statobjs(self):
        yield from sorted(self.cache.glob('*.json', 'oh_historical.csv'))

    def build_sources(self) -> dict[str, str]:
        'Yearly html pages {key: url}'
        items: list[tuple[str, str]] = []
        items.extend(self.archived_sources.items())
        items.append(('latest.html', self.absurl(self.latest_url)))
        for a in bs(self.cache/'latest.html').select('nav a'):
            if not (match := self.atext_pat.match(a.text)):
                continue
            key = f'{match.group(1)}.html'
            url = self.absurl(a['href'])
            items.append((key, url))
        sources = dict(sorted(items))
        self.cache.write_json('sources.json', sources, indent=2)
        return sources

    def extract_json(self, key: str) -> dict[str, Any]:
        page = bs(self.cache/key)
        div = page.find('div', {'id': 'js-placeholder-json-data'})
        body = json.loads(div.decode_contents().strip())
        self.cache.write_json(f'{key}.json', body, indent=2)
        return body

    def build_index(self) -> dict[str, dict[str, str]]:
        'Build mapping of notice_id to artifacts dict (key: url)'
        def rewriteurl(url: str) -> str:
            return utils.rewrite_all(url, self.rewrites['artifact'])
        # Mapping from notice_id to urls
        builder: dict[str, set[str]] = defaultdict(set)
        sourcekeys: list[str] = list(self.cache.read_json('sources.json'))
        for key in sourcekeys:
            rows: list[list[str]] = self.cache.read_json(f'{key}.json')['data']
            headers = rows[1]
            for values in filter(any, rows[2:]):
                data = dict(zip(headers, values))
                url = rewriteurl(self.absurl(data['URL']))
                if (
                    not (url and url.endswith('.pdf')) or
                    url in self.artifact404
                ):
                    continue
                it = data['Notice ID'].split(' and ')
                it = map(self.normalize_notice_id, it)
                it = filter(None, it)
                for notice_id in it:
                    builder[notice_id].add(url)
        # Final index
        index: dict[str, dict[str, str]] = {}
        for notice_id in sorted(builder):
            index[notice_id] = {}
            urls = sorted(builder[notice_id])
            for i, url in enumerate(urls, start=1):
                name = notice_id
                if len(urls) > 1:
                    name = f'{name}_{i}'
                key = f'records/{name}.pdf'
                index[notice_id][key] = url
        self.cache.write_json('index.json', index, indent=2)
        return index

    def normalize_notice_id(self, value: str) -> str:
        return utils.rewrite_all(value, self.rewrites['notice_id']).strip()

    @contextmanager
    def extract(self):
        index: dict[str, dict[str, str]] = self.cache.read_json('index.json')
        sources: dict[str, str] = self.cache.read_json('sources.json')

        def readfile(key: str):
            url = sources[key]
            rows: list[list[str]] = self.cache.read_json(f'{key}.json')['data']
            headers = rows[1][:9]
            for values in filter(any, rows[2:]):
                base = dict(zip(headers, values))
                if self.archived_sources.get(key) != url:
                    # Don't include the archived source
                    base['URL'] = url
                it = base['Notice ID'].split(' and ')
                it = map(self.normalize_notice_id, it)
                for notice_id in it:
                    data = dict(base)
                    data['Notice ID'] = notice_id
                    if notice_id in index:
                        data['artifacts_json'] = json.dumps(index[notice_id])
                    yield data

        def readhistorical(reader: Iterator[list[str]]):
            headers = [
                self.legacy_header_map.get(header, header)
                for header in next(reader)]
            for values in reader:
                data = dict(zip(headers, values))
                # Ignore duplicates of current data
                if (notice_id := data.get('Notice ID')) and notice_id not in index:
                    yield data

        it = chain.from_iterable(map(readfile, sources))
        with self.cache.open('oh_historical.csv') as file:
            yield chain(it, readhistorical(csv.reader(file)))
    
class OK(Scraper):
    warn_url = 'https://www.employoklahoma.gov/Participants/s/warnnotices'
    
    async def scrape(self) -> None:
        if settings.SELENIUM_ENABLED:
            async with webdrivers.selenium() as driver:
                await self.WorkerHelper(self, driver).run()
        else:
            self.runner.scrape()

    @dataclasses.dataclass
    class WorkerHelper:
        scraper: OK
        driver: webdrivers.Chrome
        url: ClassVar = 'https://www.employoklahoma.gov/Participants/s/warnnotices'
        
        @property
        def cache(self) -> FileCache:
            return self.scraper.cache
        
        @property
        def logger(self) -> utils.logging.Logger:
            return self.scraper.logger
        
        def yield_rows(self) -> Iterable[list[str]]:
            yield_headers = True
            while True:
                element = self.driver.find_element('css selector', '.body')
                header_elements = element.find_elements('xpath', "//th[@role = 'columnheader']")
                headers = [header.text.split('\n')[1] for header in header_elements]
                headers_len = len(headers)
                next_button = element.find_element('xpath', '//button[text()="Next"]')
                cells = element.find_elements('tag name', 'lightning-primitive-cell-factory')
                cells = [(i.text) for i in cells]
                # Group cells into rows by header length
                if yield_headers:
                    yield headers
                    yield_headers = False
                yield from (cells[x:x+headers_len] for x in range(0, len(cells), headers_len))
                if not next_button.is_enabled():
                    break
                else:
                    next_button.click()

        def is_loaded(self) -> list[webdrivers.WebElement]:
            body = self.driver.find_elements('css selector', '.body')[0]
            return body.find_elements('tag name', 'lightning-primitive-cell-factory')

        async def run(self) -> None:
            self.driver.get(self.url)
            wait = utils.Wait(timeout=10)
            await wait.until(self.is_loaded)
            with self.scraper.runner.file.open('w') as file:
                writer = csv.writer(file)
                writer.writerows(self.yield_rows())

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

    @wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
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

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)
        index = self.build_index()
        now = utils.now()
        for key, (year, url) in index.items():
            is_recent = year >= now.year - 1
            await self.download(key, url, missing_only=not is_recent)

    async def clean(self) -> None:
        self.cache.delete('latest.html', 'index.json')

    def statobjs(self):
        yield self.cache/'index.json'
        yield from sorted(self.cache.glob('*.pdf'), reverse=True)

    def build_index(self) -> dict[str, tuple[int, str]]:
        index: dict[str, tuple[int, str]] = {}
        for a in bs(self.cache/'latest.html').find_all('a'):
            href = a.get('href', '')
            if href.endswith('2024_0.pdf'):
                # Duplicate data
                continue
            if href.endswith('.pdf'):
                year = int(href.split('/')[-1][:4])
                key = f'{year}.pdf'
                url = self.absurl(href)
                index[key] = (year, url)
        index = {key: index[key] for key in sorted(index)}
        self.cache.write_json('index.json', index, indent=2)
        return index

    @wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        index: dict[int, tuple[str, str]] = self.cache.read_json('index.json')
        for key, (year, url) in index.items():
            headers = self.get_header_species(year) + self.extra_headers
            extra = [str(year), url]
            it = self.read_table(key)
            next(it)
            for row in it:
                yield dict(zip(headers, row + extra))

    def get_header_species(self, year: int) -> list[str]:
        year = int(year)
        for key, headers in self.headers_species.items():
            if key and year in key:
                return headers
        return self.headers_species[None]

    def read_table(self, key: str) -> Iterator[list[str]]:
        file = self.cache/key
        cached = self.extract_cache/f'{key}.json'
        with jsoncache(file, cached) as saved:
            if not saved:
                with pdfs.open(file) as pdf:
                    saved = [page.extract_tables() for page in pdf.pages]
                with cached.open('w') as f:
                    json.dump(saved, f, indent=2)
        it = chain.from_iterable(saved)
        it = map(self.process_table, it)
        it = filter(None, it)
        it = matx.merge_tables(it)
        it = (list(map(self.clean_cell, row)) for row in it)
        yield from it

    def process_table(self, table: list[list[str|None]]) -> list[list]:
        self.remove_extra_header(table)
        if self.table_is_sparse(table) or self.table_is_summary(table):
            return []
        table = matx.nonsparse_rows(table)
        table = matx.nonempty_columns(table)
        matx.align_columns(table)
        return table

    def clean_cell(self, text: str|None) -> str:
        text = text or ''
        text = text.replace('\n', ' ').strip()
        text = self.rewrites.get(text, text)
        return text

    def table_is_sparse(self, table: list[list]) -> bool:
        return not any(utils.morethan(1, row) for row in table)

    def table_is_summary(self, table: list[list]) -> bool:
        return bool(table) and table[0][:2] == ['County', 'Impacted']

    def remove_extra_header(self, table: list[list]) -> None:
        if table and not utils.morethan(1, table[0]):
            del table[0]

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

    def list_record_files(self) -> list[Path]:
        return sorted(self.cache.glob('*.xlsx'), reverse=True)

    @wrapcontext
    def extract(self):
        for file in self.list_record_files():
            extra = {}
            if self.year_pat.match(file.name):
                extra.update(artifact_url=self.absurl(file.name))
            cached = self.extract_cache/f'{file.name}.json'
            with jsoncache(file, cached) as saved:
                if not saved:
                    saved = list(xlsx.extract_workbook(file))
                    with cached.open('w') as f:
                        json.dump(saved, f)
            for data in saved:
                yield data|extra

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

    @wrapcontext
    def extract(self):
        file = self.cache/'latest.html'
        extra = dict(scrape_time=utils.file_mtime(file).isoformat())
        for table in bs(file).find_all('table'):
            it = (
                [td.text.strip() for td in tr.find_all(('td', 'th'))]
                for tr in table.find_all('tr'))
            headers = next(it)
            for values in it:
                yield dict(zip(headers, values))|extra

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

class Runner:

    def __init__(self, state: str):
        self.state = state.upper()
        self.logger = utils.get_logger(f'scrapers.{self.state}')
        self.cache_dir = settings.BUILD_DIR/Stage.Scrape
        self.data_dir = self.cache_dir/self.state.lower()
        self.file = self.data_dir/f'{self.state.lower()}.csv'

    def scrape(self) -> None:
        mod = import_module(f'warn.scrapers.{self.state.lower()}')
        mod.scrape(self.data_dir, self.cache_dir)

def absurl(base_url: str|None, url: str) -> None:
    if base_url and not any(map(url.startswith, ('http://', 'https://'))):
        url = base_url.rstrip('/') + '/' + url.lstrip('/')
    return url

def hashstat(it: Iterable[Path|str|Buffer|dom.PageElement]) -> dict[str, str|int|None]:
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
        elif isinstance(obj, dom.PageElement):
            buf = obj.text.encode()
        else:
            buf = obj
        if buf:
            h.update(buf)
            size += len(buf)
    hash = h.hexdigest() if size else None
    return dict(hash=hash, size=size)

scrapers.update({
    state: type(state, (Scraper,), {})
    for state in (
        x.stem.upper() for x in
        (settings.REPODIR/'warn/scrapers').glob('??.py'))
    if state not in scrapers})
