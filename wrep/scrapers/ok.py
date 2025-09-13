from __future__ import annotations

import csv
import dataclasses
from contextlib import contextmanager
from datetime import datetime
from functools import cached_property as lazy
from itertools import batched, chain
from typing import Any, ClassVar, Generator, Iterator

from .. import settings, utils
from ..backends import webdrivers
from .base import Scraper

__all__ = ['OK']

class OK(Scraper):
    latest_url: ClassVar = 'https://www.employoklahoma.gov/Participants/s/warnnotices'
    # Archived historical data
    historical_url: ClassVar = 'https://archive.warnreports.org/s/OK/ok_historical.csv'
    # Historical data is better, so prefer it for Jan 2024 and earlier
    historical_cutoff: ClassVar = datetime.strptime('2024-01-31', '%Y-%m-%d')

    async def scrape(self) -> None:
        await self.download('historical.csv', self.historical_url, missing_only=True)
        if settings.SELENIUM_ENABLED:
            args = [f'--user-agent={self.user_agent}']
            async with webdrivers.selenium(args=args, logger=self.logger) as driver:
                await DriverHelper(self, driver).run()
                count, size = webdrivers.getmetrics(driver)
                self.metrics['request_count'] += count
                self.metrics['request_bytes'] += size

    def statobjs(self) -> Iterator[Any]:
        yield self.cache/'latest.csv'
        yield self.cache/'historical.csv'

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        def isnew(data: dict[str, str]) -> bool:
            return self.historical_cutoff < utils.parse_date(data['Notice Date'])
        with self.cache.open('historical.csv') as file:
            it = csv.DictReader(file)
            if self.cache.exists('latest.csv'):
                with self.cache.open('latest.csv') as file:
                    yield chain(filter(isnew, csv.DictReader(file)), it)
            else:
                self.logger.warning(
                    f'Missing latest.csv, including historical data only. '
                    f'Latest data requires selenium, check setting SELENIUM_ENABLED')
                yield it

@dataclasses.dataclass
class DriverHelper:
    scraper: OK
    driver: webdrivers.Chrome

    async def run(self) -> None:
        self.driver.get(self.scraper.latest_url)
        await utils.Wait(timeout=10).until(self.loaded)
        self.ordertable()
        with self.scraper.cache.open('latest.csv', 'w') as file:
            writer = csv.writer(file)
            writer.writerow(self.header)
            writer.writerows(self.rows())

    @lazy
    def header(self) -> list[str]:
        "Lazy fetch the column headers"
        ths = self.findall('//thead//th[@role="columnheader"]')
        return [th.text.splitlines()[1] for th in ths]

    def rows(self) -> Generator[tuple[str, ...]]:
        "Yield the data rows"
        button = self.find('//button[text()="Next"]')
        while True:
            it = self.findall('//tbody//lightning-primitive-cell-factory')
            it = (c.text for c in it)
            yield from batched(it, len(self.header))
            if not button.is_enabled():
                break
            button.click()

    def findall(self, q: str) -> list[webdrivers.WebElement]:
        return self.driver.find_elements('xpath', f'//*[@role="main"]{q}')

    def find(self, q: str) -> webdrivers.WebElement:
        return self.driver.find_element('xpath', f'//*[@role="main"]{q}')

    def loaded(self) -> list[webdrivers.WebElement]:
        return self.findall('//lightning-primitive-cell-factory')

    def ordertable(self) -> None:
        "Sort the table by notice date descending"
        a = self.find('//thead//th[@aria-label="Notice Date"]//a[@role="button"]')
        a.click()
        a.click()
