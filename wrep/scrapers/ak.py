from __future__ import annotations

import json
import uuid
from collections import deque
from pathlib import Path
from typing import Any, ClassVar, Iterator

from .. import settings, utils
from ..tools import dom, strs
from .base import Scraper

__all__ = ['AK']

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
            yield dom.bs(file).find('table')
        yield self.cache/'index.json'

    def build_index(self) -> dict[str, str]:
        'Mapping from url to cache key'
        items: deque[tuple[str, str]] = deque()
        table = dom.bs(self.cache/'latest.html').find('table')
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
        index: dict[str, str] = self.cache.read_json('index.json')
        todo = set(index)

        def parseurl(tr: dom.Soup) -> str:
            td = tr.find('td')
            if td.get_text(strip=True) == 'Company':
                # header row
                return 'url'
            a = td.find('a')
            if a:
                return self.absurl(a['href'])
            return ''

        def readtr(tr: dom.Soup) -> Iterator[str]:
            for td in tr.find_all('td'):
                yield ' '.join(td.get_text().split())

        def readtable(table: dom.Soup) -> Iterator[list[str]]:
            for tr in table.find_all('tr'):
                url = parseurl(tr)
                values = [*readtr(tr), url]
                if len(values) > 2 and values[0]:
                    if url in index:
                        values.append(json.dumps({index[url]: url}))
                        todo.discard(url)
                    yield values

        doc = dom.bs(self.cache/'latest.html')
        it = readtable(doc.find('table'))
        headers = next(it)
        headers.append('artifacts_json')
        for values in it:
            yield dict(zip(headers, values))
        for url in todo:
            self.logger.warning(f'Unassociated artifact {url=}')
