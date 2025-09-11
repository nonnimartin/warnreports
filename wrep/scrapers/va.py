from __future__ import annotations

import csv
from contextlib import contextmanager
from itertools import chain
from typing import Any, ClassVar, Generator, Iterator

from .base import Scraper

__all__ = ['VA']

class VA(Scraper):
    latest_csvurl: ClassVar = 'https://www.virginiaworks.gov/warn_notices.csv'
    bads: ClassVar = {
        # The rows with these Notice Dates have crap values for Impact Date.
        # In some cases it is always the current date, which breaks hashing
        # in a way that is hard to fix in the translator.
        '09/22/2010',
        '11/17/2010',
        '10/26/2012',
        '07/14/2020'}

    async def scrape(self) -> None:
        await self.download('download.csv', self.latest_csvurl)
        with self.cache.open('download.csv') as file:
            reader = csv.DictReader(file)
            first = next(reader)
            with self.cache.open('latest.csv', 'w') as file:
                writer = csv.DictWriter(file, first)
                writer.writeheader()
                for data in chain((first,), reader):
                    if data['Notice Date'] in self.bads:
                        data['Impact Date'] = ''
                    writer.writerow(data)

    def statobjs(self) -> Iterator[Any]:
        yield self.cache/'latest.csv'

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        with self.cache.open('latest.csv') as file:
            yield csv.DictReader(file)
