from __future__ import annotations

from typing import Any, ClassVar, Iterator

from .. import utils
from .base import Scraper
from ..tools import dom

__all__ = ['IN']

class IN(Scraper):
    base_url: ClassVar = 'https://www.in.gov'
    latest_url: ClassVar = '/dwd/warn-notices/current-warn-notices/'

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)

    def statobjs(self) -> Iterator[Any]:
        if (file := self.cache/'latest.html').exists():
            yield from dom.bs(file).find_all('table')

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:

        def readtable(table: dom.Soup) -> Iterator[list[str]]:
            tags = ['td', 'th']
            for tr in table.find_all('tr'):
                tds = tr.find_all(tags)
                if not tds:
                    continue
                last = tds.pop()
                values = [td.text.strip() for td in tds]
                values.append(parseurl(last))
                yield values

        def parseurl(cell: dom.Soup) -> str:
            if cell.name == 'th':
                # header row
                return 'url'
            a = cell.find('a')
            if a:
                return self.absurl(a['href'])
            return cell.text.strip()

        doc = dom.bs(self.cache/'latest.html')
        for i, table in enumerate(doc.find_all('table')):
            it = readtable(table)
            if i == 0:
                headers = next(it)
            for values in it:
                yield dict(zip(headers, values))
