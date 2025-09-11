from __future__ import annotations

import json
from collections import deque
from itertools import chain
from pathlib import Path
from typing import Any, ClassVar, Iterator
from urllib.parse import urlparse

from .. import utils
from ..tools import files, matx, pdfs
from ..tools.dom import bs
from .base import Scraper

__all__ = ['SC']

class SC(Scraper):
    base_url: ClassVar = 'https://scworks.org'
    latest_url: ClassVar = '/employer/employer-programs/risk-closing/layoff-notification-reports'

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)
        now = utils.now()
        for key, url in self.build_index().items():
            year = int(Path(key).stem)
            is_recent = year >= now.year or year == now.year -1 and now.month <= 6
            await self.download(key, url, missing_only=not is_recent)

    def statobjs(self) -> Iterator[Any]:
        yield self.cache/'index.json'
        yield from sorted(self.cache.glob('*.pdf'), reverse=True)

    def build_index(self) -> dict[str, str]:
        items: deque[tuple[str, str]] = deque()
        for a in bs(self.cache/'latest.html').find_all('a'):
            href = a.get('href', '')
            if not href.endswith('.pdf'):
                continue
            if href.endswith('2024_0.pdf'):
                # Duplicate data
                continue
            url = self.absurl(href)
            year = int(Path(urlparse(url).path).stem[:4])
            items.append((f'{year}.pdf', url))
        index = dict(sorted(items))
        self.cache.write_json('index.json', index, indent=2)
        return index

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        headers_species = {
            # Any year before 2022, except 2020
            **{
                r: [
                    'Company',
                    'Location',
                    'Layoff/Closure Date',
                    'Positions',
                    'Closure or Layoff',
                    'NAICS Code']
                for r in [range(2020), range(2021, 2022)]},
            # Special case for 2020
            range(2020, 2021): [
                'Company',
                'Location',
                'Closure or Layoff',
                'Positions',
                'Layoff/Closure Date',
                'NAICS Code'],
            # Default
            None: [
                'Company',
                'County',
                'Notice Date',
                'Layoff/Closure Date',
                'Impacted',
                'Layoff/Closure',
                'Address']}
        extra_headers = ['year', 'url']
        cell_rewrites = {
            'Caraustar Industrial &': 'Caraustar Industrial & Consumer Products Group',
            'roup7,/ 5In/2c0.23': '7/5/2023',
            'CYoonrskumer Products G': 'York',
            'PBS Radiology Busine': 'PBS Radiology Business Experts',
            'sSs uEmxpteerrts': 'Sumter',
            'iGcsr,e eInncv i(l"leRyder")': 'Greenville',
            'eCrvhiacrele IsIt o("nLegacy")': 'Charleston',
            'LCLhCar,l eds/bto/an Yelloh': 'Charleston',
            'LLLexCi,n dg/tbo/na Yelloh': 'Lexington',
            'tSivtaet eSwerivdiec e- sM, LuLltiCple': 'Statewide - Multiple Counties',
            'Co9u/n1t5ie/s2023': '9/15/2023',
            'Statewide - Multiple': 'Statewide - Multiple Counties',
            'Co9u/n2t9ie/s2023': '9/29/2023'}
        index: dict[str, str] = self.cache.read_json('index.json')

        def readpdf(file: Path) -> Iterator[dict[str, str]]:
            key = self.cache.tokey(file)
            cached = self.extract_cache/f'{key}.json'
            with files.jsoncache(file, cached) as tables:
                if not tables:
                    with pdfs.open(file) as pdf:
                        tables = [page.extract_tables() for page in pdf.pages]
                    with cached.open('w') as f:
                        json.dump(tables, f, indent=2)
            it = chain.from_iterable(tables)
            it = map(cleantable, it)
            it = filter(None, it)
            it = matx.merge_tables(it)
            it = (list(map(cleancell, row)) for row in it)
            next(it)
            year = int(file.stem)
            headers = getheaders(year)
            extra = [str(year), index[key]]
            for values in it:
                yield dict(zip(headers, values + extra))

        def cleantable[T](table: list[list[T]]) -> list[list[T]]:
            # Remove extra header
            if table and not utils.morethan(1, table[0]):
                del table[0]
            # Skip sparse table
            if not any(utils.morethan(1, row) for row in table):
                return []
            # Skip summary table
            if table[0][:2] == ['County', 'Impacted']:
                return []
            table = matx.nonsparse_rows(table)
            table = matx.nonempty_columns(table)
            matx.align_columns(table)
            return table

        def cleancell(text: str|None) -> str:
            text = text or ''
            text = text.replace('\n', ' ').strip()
            text = cell_rewrites.get(text, text)
            return text

        def getheaders(year: int) -> list[str]:
            year = int(year)
            for key, headers in headers_species.items():
                if key and year in key:
                    break
            else:
                headers = headers_species[None]
            return headers + extra_headers

        for key in index:
            yield from readpdf(self.cache/key)
