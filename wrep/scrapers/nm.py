from __future__ import annotations

import asyncio
import json
from itertools import islice
from pathlib import Path
from typing import Any, ClassVar, Iterator

from .. import utils
from ..tools import dom, files, pdfs, strs
from .base import Scraper

__all__ = ['NM']

class NM(Scraper):
    base_url: ClassVar = 'https://www.dws.state.nm.us'
    latest_url: ClassVar = '/Rapid-Response'
    archive_url: ClassVar = 'https://archive.warnreports.org/s/NM'
    archive_years: ClassVar = range(2016, 2024 + 1)

    async def scrape(self) -> None:
        async with asyncio.TaskGroup() as group:
            for year in self.archive_years:
                key = f'{year}.pdf'
                url = strs.absurl(self.archive_url, key)
                coro = self.download(key, url, missing_only=True, delay=None)
                group.create_task(coro)
        now = utils.now(tz=self.tz)
        doc = dom.bs(await self.fetch('latest.html', self.latest_url))
        for link in doc.select('a[href]'):
            href = link['href']
            if not ('WARN' in href and href.endswith('.pdf')):
                continue
            year = int(link.get_text(strip=True))
            recent = year >= now.year or year == now.year - 1 and now.month <= 6
            await self.download(f'{year}.pdf', href, missing_only=not recent)

    def statobjs(self) -> Iterator[Any]:
        yield from sorted(self.cache.glob(f'????.pdf'), reverse=True)

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:

        def readpdf(file: Path) -> Iterator[dict[str, str]]:
            cached = self.extract_cache/f'{self.cache.tokey(file)}.json'
            with files.jsoncache(file, cached) as tables:
                if not tables:
                    with pdfs.open(file) as pdf:
                        tables = [page.extract_table() for page in pdf.pages]
                    with cached.open('w') as fp:
                        json.dump(tables, fp, indent=2)
            for i, table in enumerate(tables):
                it = (list(map(cellstr, values)) for values in table)
                if i:
                    it = islice(it, 1, None)
                else:
                    headers = next(it)
                it = filter(any, it)
                for values in it:
                    yield dict(zip(headers, values))

        def cellstr(value: str|None) -> str:
            return ' '.join((value or '').split())

        for file in sorted(self.cache.glob(f'????.pdf'), reverse=True):
            yield from readpdf(file)
