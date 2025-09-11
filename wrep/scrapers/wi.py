from __future__ import annotations

import json
import re
from itertools import chain
from pathlib import Path
from re import compile as _r
from typing import Any, ClassVar, Iterator

from starlette.datastructures import URL

from .. import utils
from ..tools import dom, strs
from .base import Scraper

__all__ = ['WI']

class WI(Scraper):
    base_url: ClassVar = 'https://dwd.wisconsin.gov/dislocatedworker/warn'
    # All data from 2020 and later is downloadable as JSON in one request
    latest_url: ClassVar = str(
        URL('https://sheets.googleapis.com')
        .replace(path='/v4/spreadsheets/1cyZiHZcepBI7ShB3dMcRprUFRG24lbwEnEDRBMhAqsA/values/Originals')
        .replace_query_params(key='AIzaSyBF5bsJ9oCetBmqXL5LQII4G639YaKritw'))
    # Older years use static HTML pages
    legacy_range: ClassVar = range(2016, 2020)

    async def scrape(self) -> None:
        rep = await self.request('GET', self.latest_url)
        self.cache.write_json('latest.json', rep.json(), indent=2)
        for year in self.legacy_range:
            key = f'{year}.legacy.html'
            await self.download(key, self.yearurl(year), missing_only=True)
        for row in self.build_index():
            for key, url in row['artifacts'].items():
                await self.download(key, url, missing_only=True)
                self.artifacts.add(key)

    def statobjs(self) -> Iterator[Any]:
        yield self.cache/'index.json'

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        value_rewrites = [(_r(r'<br.*'), '')]
        rowkey_rewrites = [(_r(r'[^a-z\d]', re.I), '')]
        rowkey_fields = ['PK', 'Company', 'City', 'AffectedWorkers']

        def cleanstr(value: str) -> str:
            clean = strs.unhtml(' '.join(value.split()))
            clean = strs.rewrite_all(clean, value_rewrites)
            return clean

        def getkey(row: dict[str, str]) -> str:
            it = (row[key] for key in rowkey_fields)
            it = (strs.rewrite_all(value, rowkey_rewrites) for value in it)
            return '-'.join(it)

        rows: list[dict[str, str]] = self.cache.read_json('index.json')
        for row in rows:
            artifacts = row.pop('artifacts', None)
            row.update(zip(row, map(cleanstr, row.values())))
            row.update(
                url=self.yearurl(int(row['PK'][:4])),
                row_key=getkey(row))
            if artifacts:
                row['artifacts_json'] = json.dumps(artifacts)
            yield row

    def yearurl(self, year: int) -> str:
        "Get landing page for year"
        year = max(self.legacy_range.start, year)
        if year in self.legacy_range:
            uri = f'/{year}/default.htm'
        else:
            uri = f'/default.htm?{year=}'
        return self.absurl(uri)

    def build_index(self) -> list[dict[str, Any]]:
        html_rewrites = dict(
            LayoffBeginDate=[
                # Missing closing </td> tag
                (_r(r'[^\d/-]'), ''),
            ])

        def readfile(file: Path) -> Iterator[dict[str, str]]:
            if file.suffix == '.json':
                func = readjson
            elif file.suffix == '.html':
                func = readhtml
            else:
                raise ValueError(f'No reader for {file=}')
            yield from func(file)

        def readhtml(file: Path) -> Iterator[dict[str, str]]:
            """
            Read legacy HTML file. Augments with `PK` and `PDF` headers to
            normalize with newer format.
            """
            for h3 in dom.bs(file).find_all('h3', text='New Notices'):
                for tr in h3.find_next_sibling('table').find_all('tr')[1:]:
                    row = {td['headers'][0]: td.text for td in tr.find_all('td')}
                    row.update(PK=tr['id'], PDF=Path(tr.a['href']).stem)
                    for header, rewrites in html_rewrites.items():
                        if header in row:
                            row[header] = strs.rewrite_all(row[header], rewrites)
                    yield row

        def readjson(file: Path) -> Iterator[dict[str, str]]:
            """
            Read newer JSON format downloaded from Google sheet export API.
            """
            with file.open() as fp:
                body = json.load(fp)
            it: Iterator[list[str]] = iter(body['values'])
            headers = next(it)
            for values in it:
                yield dict(zip(headers, values))

        keys = [f'{y}.legacy.html' for y in self.legacy_range] + ['latest.json']
        it = chain.from_iterable(map(readfile, map(self.cache.topath, keys)))
        index = []
        for row in it:
            raw = row['PDF']
            stem = strs.clean_filename(raw, stem=True, fail=True)
            key = f'records/{stem}.pdf'
            year = max(self.legacy_range.start, int(raw[:4]))
            url = self.absurl(f'/{year}/{raw}.pdf')
            row.update(artifacts={key: url})
            index.append(row)
        self.cache.write_json('index.json', index, indent=2)
        return index
