from __future__ import annotations

import json
from collections import deque
from contextlib import contextmanager
from itertools import chain, filterfalse
from typing import Any, ClassVar, Generator, Iterator

from .. import utils
from ..tools import dom, files
from .base import Scraper

__all__ = ['LA']

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
        page = dom.bs(self.cache/'latest.html')
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
