from __future__ import annotations

from typing import ClassVar

from .base import JobCenterSiteProxy, Scraper

__all__ = ['AZ']

class AZ(Scraper):
    site_url: ClassVar[str] = 'https://www.azjobconnection.gov/search/warn_lookups'
    stop_year: ClassVar[int] = 2010

    async def scrape(self) -> None:
        await JobCenterSiteProxy(self, self.site_url, self.stop_year).run()
