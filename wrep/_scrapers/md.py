from __future__ import annotations

from itertools import chain
from pathlib import Path
from typing import Any, ClassVar, Iterator

from .. import utils
from ..tools import dom
from .base import Scraper

__all__ = ['MD']

class MD(Scraper):
    base_url: ClassVar = 'https://www.dllr.state.md.us/employment'
    latest_url: ClassVar = '/warn.shtml'
    retry: ClassVar = dict(total=10)

    async def scrape(self) -> None:
        page = dom.bs(await self.fetch('latest.html', self.latest_url))
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

        def readtr(tr: dom.Soup) -> list[str]:
            return [' '.join(td.text.split()) for td in tr.find_all('td')]

        def readtable(table: dom.Soup) -> Iterator[list[str]]:
            return filter(any, map(readtr, table.find_all('tr')))

        it = map(readtable, self.get_tables())
        it = chain.from_iterable(it)
        headers = next(it)
        for values in it:
            yield dict(zip(headers, values))

    def get_tables(self) -> Iterator[dom.Soup]:
        for file in self.list_page_files():
            yield dom.bs(file, 'html5lib').find('table')

    def list_page_files(self) -> list[Path]:
        return sorted(self.cache.glob('*.html'), reverse=True)
