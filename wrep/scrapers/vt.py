from __future__ import annotations

from typing import ClassVar

from .base import JobCenterSiteProxy, Scraper

__all__ = ['VT']

class VT(Scraper):
    site_url: ClassVar[str] = 'https://www.vermontjoblink.com/search/warn_lookups'
    stop_year: ClassVar[int] = 2003

    async def scrape(self) -> None:
        await JobCenterSiteProxy(self, self.site_url, self.stop_year).run()
