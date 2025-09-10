from __future__ import annotations

import csv
import dataclasses
import json
import re
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from functools import cached_property as lazy
from itertools import batched, chain, filterfalse
from pathlib import Path
from re import compile as _r
from typing import Any, ClassVar, Generator, Iterable, Iterator
from urllib.parse import unquote_plus

from starlette.datastructures import URL

from . import settings, utils
from ._scrapers.base import AugmentArtifactsScraper, Scraper, scrapers
from .backends import webdrivers
from .tools import files, strs, xlsx
from .tools.dom import Soup, bs


class AK(Scraper):
    base_url: ClassVar = 'https://jobs.alaska.gov'
    latest_url: ClassVar = '/RR/WARN_notices.htm'

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)
        index = self.build_index()
        for url, key in index.items():
            await self.download(key, url, missing_only=True)
            self.artifacts.add(key)

    def statobjs(self) -> Iterator[Any]:
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
                filename = strs.clean_filename(f'{Path(href).stem}-{urlid}.pdf')
                key = f'records/{filename}'
                items.append((url, key))
        index = dict(sorted(items))
        self.cache.write_json('index.json', index, indent=2)
        return index

    @utils.wrapcontext
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

        def readtable(table: Soup) -> Iterator[list[str]]:
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
    base_url: ClassVar = 'https://edd.ca.gov'
    latest_url: ClassVar = '/Jobs_and_Training/Layoff_Services_WARN.htm'
    hrefpat: ClassVar = _r(r'warn[-_]?report', re.I)

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)
        index = self.build_index()
        for key, url in index.items():
            await self.download(key, url, missing_only=key.endswith('.pdf'))
            self.artifacts.add(key)

    def statobjs(self) -> Iterator[Any]:
        yield from sorted(self.cache.glob('*.pdf', '*.xlsx'))
        yield self.cache/'index.json'

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        index: dict[str, str] = self.cache.read_json('index.json')

        def clean(data: dict[str, str]):
            return dict(zip(data, map(str, data.values())))

        for key, url in index.items():
            file = self.cache/key
            cached = self.extract_cache/f'{key}.json'
            with files.jsoncache(file, cached) as saved:
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
                key = Path(URL(href).path).name
                url = self.absurl(href)
                items.append((key, url))
        index = dict(sorted(items))
        self.cache.write_json('index.json', index, indent=2)
        return index

from ._scrapers.co import CO as CO


class CT(AugmentArtifactsScraper):
    base_url: ClassVar = 'https://www.ctdol.state.ct.us/progsupt/bussrvce/warnreports'

    def build_index(self) -> dict[str, dict[str, str]]:
        """
        Extracts artifact data from downloaded html files and returns mapping
        of {rowkey: {cachekey: URL}},
        """
        minyear = 2019
        uri_rewrites = [
            (_r(r'^https?://webdev/progsupt/bussrvce/warnreports/'), ''),
        ]
        rowkey_rewrites = [
            (_r(r'(MountainSportsLLCUpdatedNotice){2}'), r'\1'),
        ]

        def parsetable(year: int, table: Soup) -> Iterator[tuple[str, str, str]]:
            "Yields (row_key, cache_key, url) for an html table"
            tbody = table.find('tbody')
            for tr in tbody.find_all('tr'):
                tds = tr.find_all('td')
                if len(tds) < 2:
                    continue
                for td in tds:
                    a = td.find('a')
                    if a is None:
                        continue
                    info = getkeyurl(year, a.get('href', ''))
                    if info:
                        rowkey = self.rowkey(td.text for td in tds)
                        rowkey = strs.rewrite_all(rowkey, rowkey_rewrites)
                        yield rowkey, *info
                        break

        def getkeyurl(year: int, uri: str) -> tuple[str, str]|None:
            "Check the raw 'download' value, and if valid, return a clean cache key and download URL"
            if not uri.endswith('.pdf'):
                return
            uri = strs.rewrite_all(uri, uri_rewrites)
            url = self.absurl(uri)
            clean = Path(URL(url).path).name
            clean = unquote_plus(clean)
            clean = strs.clean_filename(clean)
            if not clean:
                return
            cachekey = f'records/{year}_{clean}'
            return cachekey, url

        # Sequence of (rowkey, cachekey, URL)
        items: deque[tuple[str, str, str]] = deque()
        for file in sorted(self.cache.glob('*.html'), reverse=True):
            year = int(file.name[:4])
            if year < minyear:
                continue
            for table in bs(file, 'html5lib').find_all('table'):
                if (td := table.find('td')) and td.text.strip() == 'WARN Date':
                    items.extend(parsetable(year, table))
                    break
            else:
                raise ValueError(f'Cannot find table {file=}')
        # Mapping of {rowkey: {cachekey: URL}}
        return self.write_index_items(items)

class DE(Scraper):
    base_url: ClassVar = 'https://joblink.delaware.gov'
    latest_url: ClassVar = '/search/warn_lookups?commit=Search&page=1&q%5Bs%5D=notice_on+desc'
    request_delay: ClassVar = 0.5
    index_headers: ClassVar = ['Employer', 'City', 'ZIP', 'LWIB Area', 'Notice Date', 'WARN Type']

    async def scrape(self) -> None:

        async def fetch_tables():
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

        numpat = _r(r'.*/(\d+)$')
        index: list[dict[str, str]] = []
        async for table in fetch_tables():
            for tr in table.tbody.find_all('tr'):
                row = {
                    key: td.text.strip() for key, td in
                    zip(self.index_headers, tr.find_all('td'))}
                href = str(tr.td.a['href'])
                record_num = str(int(numpat.match(href)[1]))
                key = f'records/{record_num}.html'
                await self.download(key, href, missing_only=True)
                row['URL'] = self.absurl(href)
                row['record_num'] = record_num
                index.append(row)
        index.sort(key=lambda x: int(x['record_num']), reverse=True)
        self.cache.write_json('index.json', index, indent=2)

    def statobjs(self) -> Iterator[Any]:
        yield self.cache/'index.json'
        yield from sorted(self.cache.glob('records/*.html'), reverse=True)

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        index: list[dict[str, str]] = self.cache.read_json('index.json')
        for row in index:
            record_num = row['record_num']
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

class FL(AugmentArtifactsScraper):
    base_url: ClassVar = 'https://reactwarn.floridajobs.org'
    request_delay: ClassVar = 0.5
    user_agent: ClassVar = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36')

    def build_index(self) -> dict[str, dict[str, str]]:
        "Build the artifacts index {rowkey: {cachekey: url}}"
        minyear = 2020
        uri_rewrites = [
            (_r(r'[^a-zA-Z\d_]'), '-'),
            (_r(r'([-_])+'), r'\1'),
            (_r(r'[A-Z]-MYDOCUMENTS'), ''),
        ]
        uri_fmt = '/WarnList/DownloadAzureFile?file={}'

        def parse_table(year: int, table: Soup) -> Iterator[tuple[str, str, str]]:
            "Yields (values_key, cache_key, url) for an html table"
            tbody = table.find('tbody')
            for tr in tbody.find_all('tr'):
                tds = tr.find_all('td')
                last = tds.pop()
                if last.find('input', id='download'):
                    if (el := last.find('input', type='hidden')):
                        if (info := getkeyurl(year, el['value'])):
                            rowkey = self.rowkey(td.text for td in tds)
                            yield rowkey, *info

        def getkeyurl(year: int, uri: str) -> tuple[str, str]|None:
            "Check the raw 'download' value, and if valid, return a clean cache key and download URL"
            if not uri.endswith('.pdf'):
                return
            clean = unquote_plus(uri)
            if clean.startswith('\\'):
                return
            clean = clean.removesuffix('.pdf')
            clean = strs.rewrite_all(clean, uri_rewrites)
            clean = clean.strip('_-')
            if not clean:
                return
            name = f'{year}_{clean}.pdf'
            cache_key = f'records/{name}'
            url = self.absurl(uri_fmt.format(uri))
            return cache_key, url

        # Sequence of (rowkey, cachekey, URL)
        items: deque[tuple[str, str, str]] = deque()
        for file in sorted(self.cache.glob('*_page_*.html'), reverse=True):
            year = int(file.name[:4])
            if year < minyear:
                continue
            table = bs(file, 'html5lib').find('table')
            items.extend(parse_table(year, table))
        # Mapping of {rowkey: {cachekey: URL}}
        return self.write_index_items(items)

from ._scrapers.ga import GA as GA


class IL(Scraper):
    source_url: ClassVar = 'https://apps.illinoisworknet.com/iebs/api/public/export'
    source_params: ClassVar = [
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

    async def scrape(self) -> None:
        await self.download('export.xlsx', self.source_url, params=self.source_params)

    def statobjs(self) -> Iterator[Any]:
        file = self.cache/'export.xlsx'
        if file.exists():
            for row in xlsx.extract_workbook(file):
                row.pop('NAICS Codes', None)
                yield json.dumps(row)

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        yield xlsx.extract_workbook(self.cache/'export.xlsx')

class IN(Scraper):
    base_url: ClassVar = 'https://www.in.gov'
    latest_url: ClassVar = '/dwd/warn-notices/current-warn-notices/'

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)

    def statobjs(self) -> Iterator[Any]:
        if (file := self.cache/'latest.html').exists():
            yield from bs(file).find_all('table')

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:

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

from ._scrapers.ky import KY as KY


class LA(Scraper):
    base_url: ClassVar = 'https://www.laworks.net'
    latest_url: ClassVar = f'/Downloads/Downloads_WFD.asp'
    # PDFs no longer available for download after site redesign.
    historical_urls: ClassVar = [
        f'https://archive.warnreports.org/s/LA/historical/WarnNotices{y}.pdf'
        for y in range(2007, 2024)]

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)
        index = self.build_index()
        now = utils.now()
        recent = (now.year, now.year - 1)
        for key, url in index.items():
            is_recent = (
                'historical' not in url and
                any(str(y) in key for y in recent))
            await self.download(key, url, missing_only=not is_recent)

    def statobjs(self) -> Iterator[Any]:
        yield from sorted(self.cache.glob('*.pdf'))

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        from warn.scrapers import la
        index: dict[str, str] = self.cache.read_json('index.json')
        headers: list[str] = []

        def readfile(key: str):
            url = index[key]
            file = self.cache/key
            cached = self.extract_cache/f'{key}.json'
            with files.jsoncache(file, cached) as rows:
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
    base_url: ClassVar = 'https://www.dllr.state.md.us/employment'
    latest_url: ClassVar = '/warn.shtml'
    retry: ClassVar = dict(total=10)

    async def scrape(self) -> None:
        page = bs(await self.fetch('latest.html', self.latest_url))
        for a in page.find_all('a', {'class': 'sub'}):
            href = a['href'].lstrip('/')
            key = f'{href}.html'
            url = f'/{href}'
            year = int(href[4:8])
            is_recent = year >= utils.now().year - 1
            await self.download(key, url, missing_only=not is_recent)

    def statobjs(self) -> Iterator[Any]:
        yield from self.get_tables()

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:

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

    def statobjs(self) -> Iterator[Any]:
        yield from self.cache.glob('*.csv')

class MO(Scraper):
    start_year: ClassVar = 2019
    base_url: ClassVar = 'https://jobs.mo.gov/warn'
    archive_url: ClassVar = 'https://archive.warnreports.org/s/MO'
    headers_species: ClassVar = {
        10: ['Received', 'Title', 'Industry', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'Notes', 'url'],
        9: ['Received', 'Title', 'Industry', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'url'],
        8: ['Received', 'Title', 'Location(s)', 'County', 'Region', 'Type', 'Layoff date(s)', '# affected', 'url'],
    }

    async def scrape(self) -> None:
        now = utils.utcnow()

        def isrecent(year: int) -> bool:
            return year >= now.year or year == now.year - 1 and now.month <= 6

        years = range(self.start_year, now.year + 1)
        keys = map('pages/{}.html'.format, years)
        if settings.SELENIUM_ENABLED:

            def find_content():
                return driver.find_element('css selector', 'div.view-warn-notices')

            wait = utils.Wait(timeout=10)
            async with webdrivers.selenium() as driver:
                for year, key in zip(years, keys):
                    if not isrecent(year) and self.cache.exists(key):
                        continue
                    url = self.absurl(f'/{year}')
                    driver.get(url)
                    try:
                        await wait.until(find_content)
                    except TimeoutError:
                        self.logger.warning(f'Failed to find content for {url=}')
                        return
                    self.logger.info(f'Scraped {key}')
                    self.cache.write(key, driver.page_source)
        else:
            for year, key in zip(years, keys):
                url = strs.absurl(self.archive_url, key)
                rep = await self.download(key, url, missing_only=not isrecent(year))
                if year == now.year:
                    dt = utils.parse_date(rep.headers.get('Last-Modified'))
                    if not dt:
                        self.logger.warning(f'Cannot parse last-modified header')
                    elif dt < utils.utcnow(days=-7):
                        self.logger.warning(
                            f'Current year page more than 7 days old {url=}. '
                            f'Refresh from {self.absurl(f'/{year}')}')

    def statobjs(self) -> Iterator[Any]:
        for file in self.list_page_files():
            yield bs(file).find('table')

    @utils.wrapcontext
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

    def list_page_files(self) -> list[Path]:
        return sorted(self.cache.glob('pages/*.html'), reverse=True)

class NJ(Scraper):
    base_url: ClassVar = 'https://www.nj.gov/labor'
    latest_url: ClassVar = '/assets/PDFs/WARN/WARN_Notice_Archive.xlsx'
    retry: ClassVar = dict(total=5)

    async def scrape(self) -> None:
        await self.download('latest.xlsx', self.latest_url)

    def statobjs(self) -> Iterator[Any]:
        yield self.cache/'latest.xlsx'

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        file = self.cache/'latest.xlsx'
        scrape_time = files.mtime(file).isoformat()
        wb = xlsx.load_workbook(file)
        for ws in wb.worksheets:
            extra = dict(scrape_time=scrape_time, worksheet_name=ws.title)
            for data in xlsx.extract_worksheet(ws):
                data.update(extra)
                yield data

from ._scrapers.ny import NY as NY
from ._scrapers.oh import OH as OH


class OK(Scraper):
    latest_url: ClassVar = 'https://www.employoklahoma.gov/Participants/s/warnnotices'
    # Archived historical data
    historical_url: ClassVar = 'https://archive.warnreports.org/s/OK/ok_historical.csv'
    # Historical data is better, so prefer it for Jan 2024 and earlier
    historical_cutoff: ClassVar = datetime.strptime('2024-01-31', '%Y-%m-%d')

    async def scrape(self) -> None:
        await self.download('historical.csv', self.historical_url, missing_only=True)
        if settings.SELENIUM_ENABLED:
            async with webdrivers.selenium() as driver:
                await self.DriverHelper(self, driver).run()

    def statobjs(self) -> Iterator[Any]:
        yield self.cache/'latest.csv'
        yield self.cache/'historical.csv'

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        def isnew(data: dict[str, str]) -> bool:
            return self.historical_cutoff < utils.parse_date(data['Notice Date'])
        with self.cache.open('historical.csv') as file:
            it = csv.DictReader(file)
            if self.cache.exists('latest.csv'):
                with self.cache.open('latest.csv') as file:
                    yield chain(filter(isnew, csv.DictReader(file)), it)
            else:
                self.logger.warning(
                    f'Missing latest.csv, including historical data only. '
                    f'Latest data requires selenium, check setting SELENIUM_ENABLED')
                yield it

    @dataclasses.dataclass
    class DriverHelper:
        scraper: OK
        driver: webdrivers.Chrome

        async def run(self) -> None:
            self.driver.get(self.scraper.latest_url)
            await utils.Wait(timeout=10).until(self.loaded)
            self.ordertable()
            with self.scraper.cache.open('latest.csv', 'w') as file:
                writer = csv.writer(file)
                writer.writerow(self.header)
                writer.writerows(self.rows())

        @lazy
        def header(self) -> list[str]:
            "Lazy fetch the column headers"
            ths = self.findall('//thead//th[@role="columnheader"]')
            return [th.text.splitlines()[1] for th in ths]

        def rows(self) -> Generator[tuple[str, ...]]:
            "Yield the data rows"
            button = self.find('//button[text()="Next"]')
            while True:
                it = self.findall('//tbody//lightning-primitive-cell-factory')
                it = (c.text for c in it)
                yield from batched(it, len(self.header))
                if not button.is_enabled():
                    break
                button.click()

        def findall(self, q: str) -> list[webdrivers.WebElement]:
            return self.driver.find_elements('xpath', f'//*[@role="main"]{q}')

        def find(self, q: str) -> webdrivers.WebElement:
            return self.driver.find_element('xpath', f'//*[@role="main"]{q}')

        def loaded(self) -> list[webdrivers.WebElement]:
            return self.findall('//lightning-primitive-cell-factory')

        def ordertable(self) -> None:
            "Sort the table by notice date descending"
            a = self.find('//thead//th[@aria-label="Notice Date"]//a[@role="button"]')
            a.click()
            a.click()

from ._scrapers.pa import PA as PA
from ._scrapers.sc import SC as SC


class TX(Scraper):
    base_url: ClassVar = 'https://www.twc.texas.gov'
    latest_url: ClassVar = '/data-reports/warn-notice'
    href_pat: ClassVar = _r(r'^/sites/default/files/oei/docs/warn-act-listings-')
    year_pat: ClassVar = _r(r'.*-(\d{4})-')
    archive_url: ClassVar = 'https://archive.warnreports.org/s/TX/tx_historical.xlsx'
    ssl_verify: ClassVar = False

    async def scrape(self) -> None:
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

    def statobjs(self) -> Iterator[Any]:
        yield from self.list_record_files()

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        for file in self.list_record_files():
            extra = {}
            if self.year_pat.match(file.name):
                extra.update(artifact_url=self.absurl(file.name))
            cached = self.extract_cache/f'{file.name}.json'
            with files.jsoncache(file, cached) as saved:
                if not saved:
                    saved = list(xlsx.extract_workbook(file))
                    with cached.open('w') as f:
                        json.dump(saved, f)
            for data in saved:
                yield data|extra

    def list_record_files(self) -> list[Path]:
        return sorted(self.cache.glob('*.xlsx'), reverse=True)

class UT(Scraper):
    base_url: ClassVar = 'https://jobs.utah.gov'
    latest_url: ClassVar = '/employer/business/warnnotices.html'

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)

    def statobjs(self) -> Iterator[Any]:
        if (file := self.cache/'latest.html').exists():
            yield from bs(file).find_all('table')

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        file = self.cache/'latest.html'
        extra = dict(scrape_time=files.mtime(file).isoformat())
        for table in bs(file).find_all('table'):
            it = (
                [td.text.strip() for td in tr.find_all(('td', 'th'))]
                for tr in table.find_all('tr'))
            headers = next(it)
            for values in it:
                yield dict(zip(headers, values))|extra

class VA(Scraper):
    latest_csvurl: ClassVar = 'https://www.virginiaworks.gov/warn_notices.csv'
    bads: ClassVar = {
        # The rows with these Notice Dates have crap values for Impact Date.
        # In some cases it is always the current date, which breaks hashing
        # in a way that is hard to fix in the translator.
        '09/22/2010',
        '11/17/2010',
        '10/26/2012',
        '07/14/2020'}

    async def scrape(self) -> None:
        await self.download('download.csv', self.latest_csvurl)
        with self.cache.open('download.csv') as file:
            reader = csv.DictReader(file)
            first = next(reader)
            with self.cache.open('latest.csv', 'w') as file:
                writer = csv.DictWriter(file, first)
                writer.writeheader()
                for data in chain((first,), reader):
                    if data['Notice Date'] in self.bads:
                        data['Impact Date'] = ''
                    writer.writerow(data)

    def statobjs(self) -> Iterator[Any]:
        yield self.cache/'latest.csv'

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        with self.cache.open('latest.csv') as file:
            yield csv.DictReader(file)

# Create default Scraper classes
scrapers.update({
    state: type(state, (Scraper,), {})
    for state in (
        x.stem.upper() for x in
        (settings.REPODIR/'warn/scrapers').glob('??.py'))
    if state not in scrapers})
