from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Iterable, Iterator

from .. import settings, utils
from ..backends import webdrivers
from ..tools import dom, strs
from .base import Scraper

__all__ = ['MO']

class MO(Scraper):
    start_year: ClassVar = 2019
    base_url: ClassVar = 'https://jobs.mo.gov/warn'
    archive_url: ClassVar = 'https://archive.warnreports.org/s/MO'

    async def scrape(self) -> None:
        now = utils.utcnow()

        def isrecent(year: int) -> bool:
            return year >= now.year or year == now.year - 1 and now.month <= 6

        years = range(self.start_year, now.year + 1)
        keys = map('pages/{}.html'.format, years)
        if settings.SELENIUM_ENABLED:

            def find_content():
                return driver.find_element('css selector', 'div.view-warn-notices')

            wait = utils.Wait(timeout=10, callback=find_content)
            args = [f'--user-agent={self.user_agent}']
            async with webdrivers.selenium(args=args, logger=self.logger) as driver:
                for year, key in zip(years, keys):
                    if not isrecent(year) and self.cache.exists(key):
                        continue
                    url = self.absurl(f'/{year}')
                    driver.get(url)
                    try:
                        await wait()
                    except TimeoutError:
                        self.logger.warning(f'Failed to find content for {url=}')
                        return
                    self.logger.info(f'Scraped {key}')
                    self.cache.write(key, driver.page_source)
                count, size = webdrivers.getmetrics(driver)
                self.metrics['request_count'] += count
                self.metrics['request_bytes'] += size
        else:
            for year, key in zip(years, keys):
                url = strs.absurl(self.archive_url, key)
                rep = await self.download(key, url, missing_only=not isrecent(year))
                if year == now.year:
                    dt = utils.parse_date(rep.headers.get('Last-Modified'))
                    if not dt:
                        self.logger.warning(f'Cannot parse last-modified header')
                    elif dt < utils.utcnow(days=-7):
                        self.logger.warning(
                            f'Current year page more than 7 days old {url=}. '
                            f'Refresh from {self.absurl(f'/{year}')}')

    def statobjs(self) -> Iterator[Any]:
        for file in self.list_page_files():
            yield dom.bs(file).find('table')

    @utils.wrapcontext
    def extract(self) -> Iterable[dict[str, str]]:
        headers_species = {
            10: [
                'Received',
                'Title',
                'Industry',
                'Location(s)',
                'County',
                'Region',
                'Type',
                'Layoff date(s)',
                '# affected',
                'Notes',
                'url'],
            9: [
                'Received',
                'Title',
                'Industry',
                'Location(s)',
                'County',
                'Region',
                'Type',
                'Layoff date(s)',
                '# affected',
                'url'],
            8: [
                'Received',
                'Title',
                'Location(s)',
                'County',
                'Region',
                'Type',
                'Layoff date(s)',
                '# affected',
                'url']}

        def readtr(tr: dom.Soup) -> Iterator[str]:
            for td in tr.find_all('td'):
                yield td.get_text(strip=True)

        for file in self.list_page_files():
            table = dom.bs(file).find('table')
            year = int(file.name.removesuffix('.html'))
            url = self.absurl(str(year))
            it = iter(table.find_all('tr'))
            width = len(next(it).find_all(['td', 'th']))
            headers = headers_species[width]
            for tr in it:
                values = [*readtr(tr), url]
                if utils.morethan(2, values):
                    yield dict(zip(headers, values))

    def list_page_files(self) -> list[Path]:
        return sorted(self.cache.glob('pages/*.html'), reverse=True)
