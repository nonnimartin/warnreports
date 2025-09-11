from __future__ import annotations

import json
from pathlib import Path
from re import compile as _r
from typing import Any, ClassVar, Iterator

from starlette.datastructures import URL

from .. import utils
from ..tools import dom, files, xlsx
from .base import Scraper

__all__ = ['TX']

class TX(Scraper):
    base_url: ClassVar = 'https://www.twc.texas.gov'
    latest_url: ClassVar = '/data-reports/warn-notice'
    href_pat: ClassVar = _r(r'^/sites/default/files/oei/docs/warn-act-listings-')
    year_pat: ClassVar = _r(r'.*-(\d{4})-')
    archive_url: ClassVar = 'https://archive.warnreports.org/s/TX/tx_historical.xlsx'
    ssl_verify: ClassVar = False

    async def scrape(self) -> None:
        page = dom.bs(await self.fetch('latest.html', self.latest_url))
        for a in page.find_all('a', href=self.href_pat):
            href = a['href']
            key = Path(URL(self.absurl(href)).path).name
            year = int(self.year_pat.match(key)[1])
            is_recent = year >= utils.now().year - 1
            await self.download(key, href, missing_only=not is_recent)
            self.artifacts.add(key)
        key = self.archive_url.split('/')[-1]
        await self.download(key, self.archive_url, missing_only=True)

    def statobjs(self) -> Iterator[Any]:
        yield from sorted(self.cache.glob('*.xlsx'), reverse=True)

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        for file in sorted(self.cache.glob('*.xlsx'), reverse=True):
            extra = {}
            if self.year_pat.match(file.name):
                extra.update(artifact_url=self.absurl(file.name))
            cached = self.extract_cache/f'{file.name}.json'
            with files.jsoncache(file, cached) as saved:
                if not saved:
                    saved = list(xlsx.extract_workbook(file))
                    with cached.open('w') as f:
                        json.dump(saved, f)
            for data in saved:
                yield data|extra
