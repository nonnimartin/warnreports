from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any, ClassVar

from .. import utils
from ..tools import strs
from .base import PatchUtils as BasePatchUtils
from .base import Scraper

__all__ = ['HI']

class HI(Scraper):
    request_delay: ClassVar = 1.0
    archive_url: ClassVar = 'https://archive.warnreports.org/s/HI'
    archive_years: ClassVar = range(2019, 2024 + 1)

    async def scrape(self) -> None:
        async with asyncio.TaskGroup() as group:
            for year in self.archive_years:
                key = f'{year}.html'
                url = strs.absurl(self.archive_url, key)
                coro = self.download(key, url, missing_only=True, delay=None)
                group.create_task(coro)
        await super().scrape()

    def get_patches(self) -> dict[str, Any]:
        # Sleep is accounted for by request delay
        def sleep(seconds: float, /) -> None:
            pass
        return super().get_patches()|dict(utils=PatchUtils(self), sleep=sleep)

class PatchUtils(BasePatchUtils):

    def get_url(self, url: str) -> SimpleNamespace:
        scraper = self.scraper
        leaf = url.rstrip('/').rsplit('/', 1)[1]
        try:
            year = int(leaf.split('-', 1)[0])
        except ValueError:
            key = strs.clean_filename(f'{leaf}.html', fail=True)
            usecache = False
        else:
            key = f'{year}.html'
            now = utils.now(tz=scraper.tz)
            isrecent = year >= now.year or year == now.year - 1 and now.month <= 6
            usecache = not isrecent
        self.logger.debug(f'{usecache=} {key=}')
        if usecache and scraper.cache.exists(key):
            self.logger.debug(f'Reading from cache')
            text = scraper.cache.read(key)
        else:
            if scraper.metrics['request_count']:
                time.sleep(scraper.request_delay)
            text = scraper.session.get(url).text
            scraper.cache.write(key, text)
        return SimpleNamespace(text=text)
