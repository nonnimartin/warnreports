from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from re import compile as _r
from typing import Any, ClassVar, Iterator

from starlette.datastructures import URL

from .. import utils
from ..tools import asyn, dom, files, strs
from .base import Scraper

__all__ = ['CA']

class CA(Scraper):
    base_url: ClassVar = 'https://edd.ca.gov'
    latest_url: ClassVar = '/en/Jobs_and_Training/Layoff_Services_WARN'
    archive_url: ClassVar[str] = 'https://archive.warnreports.org/s/CA'

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)

        async def downloader(arg: tuple[str, str]) -> None:
            key, url = arg
            ispdf = key.endswith('.pdf')
            if ispdf:
                url = strs.absurl(self.archive_url, key)
            await self.download(key, url, missing_only=ispdf)
            self.artifacts.add(key)

        await asyn.pooled(self.build_index().items(), downloader, size=10)

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
        page = dom.bs(self.cache/'latest.html')
        items: deque[tuple[str, str]] = deque()
        hrefsearch = _r(r'warn[-_]?report', re.I).search
        for link in page.select('a[href]'):
            href = link['href']
            if hrefsearch(href):
                key = Path(URL(href).path).name
                url = self.absurl(href)
                items.append((key, url))
        index = dict(sorted(items))
        self.cache.write_json('index.json', index, indent=2)
        return index
