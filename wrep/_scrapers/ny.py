from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import date
from io import TextIOWrapper
from itertools import chain
from pathlib import Path
from re import compile as _r
from typing import Any, Generator, Iterator
from urllib.parse import urlparse

from .. import utils
from ..tools import files, pdfs, strs, xlsx
from ..tools.dom import Soup, bs
from .base import Scraper

__all__ = ['NY']

class NY(Scraper):
    base_url = 'https://dol.ny.gov'
    archive_url = 'https://archive.warnreports.org/s/NY'
    archive_filenames = [
        'ny_historical.xlsx',
        '2021.html',
        '2022.html',
        '2023.html',
        '2024.html',
        '2025.html']
    tableau_mindate = date(2025, 3, 28)
    tableau_filenames = ['tableau-2025.csv']

    async def scrape(self) -> None:
        for key in self.tableau_filenames:
            url = strs.absurl(self.archive_url, key)
            await self.download(key, url)
        for key in self.archive_filenames:
            url = strs.absurl(self.archive_url, key)
            await self.download(key, url, missing_only=True)
        # Download artifacts
        for subidx in self.build_index().values():
            for key, url in subidx.items():
                await self.download(key, url, missing_only=True)
                self.artifacts.add(key)

    def statobjs(self) -> Iterator[Any]:
        it = chain(self.archive_filenames, self.tableau_filenames)
        yield from map(self.cache.topath, it)

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        pdfheader_rewrites = [
            ('L ayoff End Date', 'Layoff End Date'),
            ('U nion', 'Union')]
        csvkey_fields = [
            'Date Posted',
            'Date of WARN Notice',
            'Impacted Site County',
            'Business Legal Name',
            'Impacted Site Address',
            'Number of Affected Workers']
        html_headers = [
            'company_name',
            'region',
            'date_posted',
            'notice_dated']
        index: dict[str, dict[str, str]] = self.cache.read_json('index.json')
        fps: list[TextIOWrapper] = []

        def readfile(file: Path) -> Iterator[dict[str, str]]:
            self.logger.debug(f'Reading {file}')
            if file.suffix == '.html':
                func = readhtml
            elif file.suffix == '.xlsx':
                func = readxlsx
            elif file.suffix == '.csv':
                func = readcsv
            else:
                raise ValueError(f'No method to read {file=}')
            yield from func(file)
        
        def readcsv(file: Path) -> Iterator[dict[str, str]]:
            "Extract records from a CSV file downloaded from current Tableau site"
            with file.open(encoding='utf-16', newline='') as fp:
                fps.append(fp)
                it = (
                    list(map(' '.join, map(str.split, values[:9])))
                    for values in csv.reader(fp, delimiter='\t'))
                for headers in it:
                    if headers[0]:
                        break
                else:
                    raise ValueError(f'Cannot find headers {file=}')
                for values in it:
                    row = dict(zip(headers, values))
                    posted = utils.parse_date(row['Date Posted'], fail=True).date()
                    if posted < self.tableau_mindate:
                        continue
                    row['row_key'] = strs.clean_filename(
                        '_'.join(row[key] for key in csvkey_fields),
                        stem=True,
                        fail=True)
                    yield row

        def readxlsx(file: Path) -> Iterator[dict[str, str]]:
            "Extract records from historical xlsx file"
            cached = self.extract_cache/f'{self.cache.tokey(file)}.json'
            with files.jsoncache(file, cached) as saved:
                if not saved:
                    saved = list(xlsx.extract_workbook(file))
                    with cached.open('w') as f:
                        json.dump(saved, f, indent=2)
            yield from saved

        def readhtml(file: Path) -> Iterator[dict[str, str]]:
            "Extract records from legacy HTML page"
            headers = html_headers
            table = self.find_table(bs(file))
            it = iter(table.find_all('tr'))
            next(it)
            for tr in it:
                tds = tr.find_all('td')
                values = [' '.join((td.text or '').split()) for td in tds]
                row = dict(zip(headers, values))
                href = tds[0].a['href']
                if href in index:
                    cachekey, url = next(iter(index[href].items()))
                    if self.cache.exists(cachekey):
                        row.update(pdfitems(self.cache/cachekey))
                        row.update(artifacts_json=json.dumps({cachekey: url}))
                else:
                    url = self.absurl(href)
                row.update(notice_url=url)
                yield row

        def pdfitems(file: Path) -> Iterator[tuple[str, str]]:
            "Extract extra data from a legacy record PDF download artifact"
            cached = self.extract_cache/f'{self.cache.tokey(file)}.txt'
            with files.cachectx(file, cached) as saved:
                if saved:
                    text = saved.read_text()
                else:
                    with pdfs.open(file) as pdf:
                        text = '\n'.join(page.extract_text() for page in pdf.pages)
                    cached.write_text(text)
            for line in text.splitlines():
                item = line.split(': ', 1)
                if len(item) == 1:
                    continue
                header, value = item
                header = strs.rewrite_all(header, pdfheader_rewrites)
                yield header, value

        it = chain(self.archive_filenames, self.tableau_filenames)
        it = map(self.cache.topath, it)
        try:
            yield chain.from_iterable(map(readfile, it))
        finally:
            while fps:
                fps.pop().close()

    def build_index(self) -> dict[str, dict[str, str]]:
        "Build the legacy artifacts index from the downloaded HTML files {cachekey: url}"
        url_rewrites = [
            (
                _r(r'/2022/10/starry-inc\.-2022-0043-10-20-2022\.pdf'),
                '/2024/05/warn-nyc-starry-inc.-10.20.2022.pdf')]

        def hrefkey(href: str) -> str:
            "Return a cache key and download URL from the href value"
            url = self.absurl(href.strip())
            url = strs.rewrite_all(url, url_rewrites)
            filename = Path(urlparse(url).path).name
            key = f'records/{filename}'
            if not filename.endswith('.pdf'):
                key = f'{key}.pdf'
            return key, url

        selector = 'tbody > tr > td:nth-of-type(1) > a'
        items: deque[tuple[str, str, str]] = deque()
        for key in self.archive_filenames:
            if not key.endswith('.html'):
                continue
            file = self.cache/key
            cached = self.cache/f'{key}.hrefs.json'
            with files.jsoncache(file, cached) as hrefs:
                if hrefs is None:
                    links = self.find_table(bs(file)).select(selector)
                    hrefs: list[str] = [a['href'] for a in links]
                    with cached.open('w') as fp:
                        json.dump(hrefs, fp, indent=2)
            items.extend((href, *hrefkey(href)) for href in hrefs)
        index: dict[str, dict[str, str]] = defaultdict(dict)
        for urikey, cachekey, url in sorted(items):
            index[urikey][cachekey] = url
        self.cache.write_json('index.json', index, indent=2)
        return dict(index)

    def find_table(self, page: Soup) -> Soup:
         "Find main table in a legacy HTML page"
         return page.find('div', {'class': 'landing-paragraphs'}).find('table')
