from __future__ import annotations

from typing import Any, ClassVar, Iterator

from .. import utils
from ..tools import dom, files
from .base import Scraper

__all__ = ['']

class UT(Scraper):
    base_url: ClassVar = 'https://jobs.utah.gov'
    latest_url: ClassVar = '/employer/business/warnnotices.html'

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)

    def statobjs(self) -> Iterator[Any]:
        if (file := self.cache/'latest.html').exists():
            yield from dom.bs(file).find_all('table')

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        file = self.cache/'latest.html'
        extra = dict(scrape_time=files.mtime(file).isoformat())
        for table in dom.bs(file).find_all('table'):
            it = (
                [td.get_text(strip=True) for td in tr.find_all(('td', 'th'))]
                for tr in table.find_all('tr'))
            headers = next(it)
            for values in it:
                yield dict(zip(headers, values))|extra
