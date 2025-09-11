from __future__ import annotations

from typing import Any, Iterator

from .base import Scraper

__all__ = ['ME']

class ME(Scraper):

    async def scrape(self) -> None:
        # CSV files appear to get corrupted sometimes, resulting in missing data, which breaks
        # hashing. Clearing the CSV seems to help.
        self.cache.delete('*.csv', glob=True)
        await super().scrape()

    def statobjs(self) -> Iterator[Any]:
        yield from self.cache.glob('*.csv')
