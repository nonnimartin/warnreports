from __future__ import annotations

from typing import Any, ClassVar, Iterator

from .. import utils
from ..tools import files, xlsx
from .base import Scraper

__all__ = ['NJ']

class NJ(Scraper):
    base_url: ClassVar = 'https://www.nj.gov/labor'
    latest_url: ClassVar = '/assets/PDFs/WARN/WARN_Notice_Archive.xlsx'
    retry: ClassVar = dict(total=5)

    async def scrape(self) -> None:
        await self.download('latest.xlsx', self.latest_url)

    def statobjs(self) -> Iterator[Any]:
        yield self.cache/'latest.xlsx'

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        file = self.cache/'latest.xlsx'
        scrape_time = files.mtime(file).isoformat()
        wb = xlsx.load_workbook(file)
        for ws in wb.worksheets:
            extra = dict(scrape_time=scrape_time, worksheet_name=ws.title)
            for data in xlsx.extract_worksheet(ws):
                data.update(extra)
                yield data
