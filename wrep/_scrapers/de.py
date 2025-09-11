from __future__ import annotations

from re import compile as _r
from typing import Any, ClassVar, Iterator

from .. import utils
from ..tools import dom
from .base import Scraper

__all__ = ['DE']

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
                doc = dom.bs(await self.fetch(key, url))
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
                    key: td.get_text(strip=True) for key, td in
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
            page = dom.bs(self.cache/key)
            section = page.find(id='primaryContent')
            div = section.find('div', {'class': 'definition-list'})
            record = {}
            for h3 in div.find_all('h3'):
                record[h3.text.strip()] = h3.find_next('p').text.strip()
            for key, value in row.items():
                if not record.get(key):
                    record[key] = value
            yield record
