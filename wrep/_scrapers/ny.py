from __future__ import annotations

import json
from collections import deque
from contextlib import contextmanager
from itertools import chain
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from ..tools import files, pdfs, xlsx
from ..tools.dom import Soup, bs
from .base import Scraper

__all__ = ['NY']

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
        url = self.absurl(href.strip())
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
        with files.jsoncache(file, cached) as saved:
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
        with files.cachectx(file, cached) as saved:
            if saved:
                return saved.read_text()
            with pdfs.open(file) as pdf:
                text = '\n'.join(page.extract_text() for page in pdf.pages)
            cached.write_text(text)
        return text
