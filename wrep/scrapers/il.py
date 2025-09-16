from __future__ import annotations

import json
from typing import Any, ClassVar, Iterator

from .. import utils
from ..tools import xlsx
from .base import Scraper

__all__ = ['IL']

class IL(Scraper):
    source_url: ClassVar = 'https://apps.illinoisworknet.com/iebs/api/public/export'

    async def scrape(self) -> None:
        await self.download('export.xlsx', self.source_url, params=self.source_params())

    def statobjs(self) -> Iterator[Any]:
        file = self.cache/'export.xlsx'
        if file.exists():
            for row in xlsx.extract_workbook(file):
                row.pop('NAICS Codes', None)
                yield json.dumps(row)

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        yield from xlsx.extract_workbook(self.cache/'export.xlsx')

    def source_params(self):
        return [
            ('search', ''),
            ('layoffTypes', ''),
            ('trade', '0'),
            ('dateReportedStart', 'Invalid Date'),
            ('dateReportedEnd', 'Invalid Date'),
            ('statuses', '4'),
            ('reasons', ''),
            ('eventCauses', ''),
            ('naicsCodes', '1'),
            ('naicIndustries', ''),
            ('naics', ''),
            ('unionsInvolved', '0'),
            ('geolocation', '1'),
            ('cities', ''),
            ('counties', ''),
            ('lwias', ''),
            ('includeAdditionalLwias', 'false'),
            ('edrs', ''),
            ('lat', '0'),
            ('lng', '0'),
            ('distance', '.5'),
            ('memberType', '1'),
            ('users', ''),
            ('accessList', ''),
            ('bookmarked', 'false')]