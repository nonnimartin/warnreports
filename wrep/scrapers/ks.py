from __future__ import annotations

from typing import ClassVar

from .base import JobCenterSiteProxy, Scraper

__all__ = ['KS']

class KS(Scraper):
    site_url: ClassVar[str] = 'https://www.kansasworks.com/search/warn_lookups'
    stop_year: ClassVar[int] = 1998

    async def scrape(self) -> None:
        await JobCenterSiteProxy(self, self.site_url, self.stop_year).run()
