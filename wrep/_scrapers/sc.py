from __future__ import annotations

import json
from itertools import chain
from typing import ClassVar, Iterator

from .. import utils
from ..tools import files, matx, pdfs
from ..tools.dom import bs
from .base import Scraper

__all__ = ['SC']

class SC(Scraper):
    base_url: ClassVar = 'https://scworks.org'
    latest_url: ClassVar = '/employer/employer-programs/risk-closing/layoff-notification-reports'
    headers_species: ClassVar = {
        **{
            r: ['Company', 'Location', 'Layoff/Closure Date', 'Positions', 'Closure or Layoff', 'NAICS Code']
            for r in [range(2020), range(2021, 2022)]
        },
        range(2020, 2021): ['Company', 'Location', 'Closure or Layoff', 'Positions', 'Layoff/Closure Date', 'NAICS Code'],
        None: ['Company', 'County', 'Notice Date', 'Layoff/Closure Date', 'Impacted', 'Layoff/Closure', 'Address']
    }
    extra_headers: ClassVar = ['year', 'url']

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)
        index = self.build_index()
        now = utils.now()
        for key, (year, url) in index.items():
            is_recent = year >= now.year - 1
            await self.download(key, url, missing_only=not is_recent)

    async def clean(self) -> None:
        self.cache.delete('latest.html', 'index.json')

    def statobjs(self):
        yield self.cache/'index.json'
        yield from sorted(self.cache.glob('*.pdf'), reverse=True)

    def build_index(self) -> dict[str, tuple[int, str]]:
        index: dict[str, tuple[int, str]] = {}
        for a in bs(self.cache/'latest.html').find_all('a'):
            href = a.get('href', '')
            if href.endswith('2024_0.pdf'):
                # Duplicate data
                continue
            if href.endswith('.pdf'):
                year = int(href.split('/')[-1][:4])
                key = f'{year}.pdf'
                url = self.absurl(href)
                index[key] = (year, url)
        index = {key: index[key] for key in sorted(index)}
        self.cache.write_json('index.json', index, indent=2)
        return index

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        index: dict[int, tuple[str, str]] = self.cache.read_json('index.json')
        for key, (year, url) in index.items():
            headers = self.get_header_species(year) + self.extra_headers
            extra = [str(year), url]
            it = self.read_table(key)
            next(it)
            for row in it:
                yield dict(zip(headers, row + extra))

    def get_header_species(self, year: int) -> list[str]:
        year = int(year)
        for key, headers in self.headers_species.items():
            if key and year in key:
                return headers
        return self.headers_species[None]

    def read_table(self, key: str) -> Iterator[list[str]]:
        file = self.cache/key
        cached = self.extract_cache/f'{key}.json'
        with files.jsoncache(file, cached) as saved:
            if not saved:
                with pdfs.open(file) as pdf:
                    saved = [page.extract_tables() for page in pdf.pages]
                with cached.open('w') as f:
                    json.dump(saved, f, indent=2)
        it = chain.from_iterable(saved)
        it = map(self.process_table, it)
        it = filter(None, it)
        it = matx.merge_tables(it)
        it = (list(map(self.clean_cell, row)) for row in it)
        yield from it

    def process_table(self, table: list[list[str|None]]) -> list[list]:
        self.remove_extra_header(table)
        if self.table_is_sparse(table) or self.table_is_summary(table):
            return []
        table = matx.nonsparse_rows(table)
        table = matx.nonempty_columns(table)
        matx.align_columns(table)
        return table

    def clean_cell(self, text: str|None) -> str:
        text = text or ''
        text = text.replace('\n', ' ').strip()
        text = self.rewrites.get(text, text)
        return text

    def table_is_sparse(self, table: list[list]) -> bool:
        return not any(utils.morethan(1, row) for row in table)

    def table_is_summary(self, table: list[list]) -> bool:
        return bool(table) and table[0][:2] == ['County', 'Impacted']

    def remove_extra_header(self, table: list[list]) -> None:
        if table and not utils.morethan(1, table[0]):
            del table[0]

    rewrites: ClassVar = {
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
        'Co9u/n2t9ie/s2023': '9/29/2023',
    }
