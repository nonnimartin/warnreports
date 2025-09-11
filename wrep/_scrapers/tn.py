from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from contextlib import contextmanager
from io import TextIOWrapper
from itertools import chain
from pathlib import Path
from re import compile as _r
from typing import Any, ClassVar, Generator, Iterable, Iterator

from starlette.datastructures import URL

from ..tools import dom, strs
from .base import Scraper

__all__ = ['TN']

class TN(Scraper):
    base_url = 'https://www.tn.gov'
    latest_url = '/workforce/general-resources/major-publications0/major-publications-redirect/reports.html'
    # Archived historical data
    historical_url: ClassVar = 'https://archive.warnreports.org/s/TN/tn_historical.csv'
    # Extra retries for common SSLEOFError
    retry: ClassVar[dict] = dict(total=30, backoff_factor=0.1, backoff_max=10)
    noticeid_rewrites: ClassVar[list[strs.SrchRepl]] = [
        # Strip non-digit characters
        (_r(r'[^\d]'), ''),
        # Typo: missing leading 2
        (_r(r'^(0\d{7})$'), r'2\1'),
        # Typo: missing a 0 in the middle
        (_r(r'^(20\d{2}0{3})([1-9])$'), lambda m: '0'.join(m.groups())),
        # Require at least 9 digits
        (_r(r'^\d{,8}$'), '')]

    async def scrape(self) -> None:
        await self.download('tn_historical.csv', self.historical_url, missing_only=True)
        await self.download('latest.html', self.latest_url)
        for subidx in self.build_index().values():
            for key, url in subidx.items():
                await self.download(key, url, missing_only=True)
                self.artifacts.add(key)

    def statobjs(self) -> Iterator[Any]:
        yield self.cache/'tn_historical.csv'
        yield self.cache/'index.json'
        if (file := self.cache/'latest').exists():
            yield from dom.bs(file).select('div.tn-datatable table')

    @contextmanager
    def extract(self) -> Generator[Iterable[dict[str, str]]]:
        index: dict[str, dict[str, str]] = self.cache.read_json('index.json')
        # Minimal headers from HTML table
        headers = [
            'Notice Date',
            'Company',
            'County',
            'No. Of Employees',
            'Effective Date',
            'Notice ID']
        done: set[str] = set()
        todo: set[str] = set(index)
        fps: list[TextIOWrapper] = []

        def augment(row: dict[str, str]) -> dict[str, str]:
            "Normalize noticeid and associate artifacts"
            noticeid = row['Notice ID'] = strs.rewrite_all(
                row['Notice ID'],
                self.noticeid_rewrites)
            if noticeid in index:
                todo.discard(noticeid)
                row.update(artifacts_json=json.dumps(index[noticeid]))
            return row

        def readfile(file: Path) -> Iterator[dict[str, str]]:
            if file.suffix == '.csv':
                func = readcsv
            elif file.suffix == '.html':
                func = readhtml
            else:
                raise ValueError(f'No reader for {file=}')
            yield from func(file)

        def readcsv(file: Path) -> Iterator[dict[str, str]]:
            "Read historical CSV file"
            with file.open(newline='') as fp:
                fps.append(fp)
                for row in map(augment, csv.DictReader(fp)):
                    # Keep consistent key ordering
                    row = dict((header, row[header]) for header in headers)|row
                    if row['Notice ID']:
                        # Mark as done so duplicates in historical HTML can be skipped
                        done.add(row['Notice ID'])
                    yield row

        def readhtml(file: Path) -> Iterator[dict[str, str]]:
            "Read current HTML file"
            doc = dom.bs(file)
            # Old notices are in <p> elements
            for p in reversed(doc.select('div.tn-rte > p')):
                defs = p.get_text(separator=' ', strip=True).split('|')
                if len(defs) != len(headers):
                    self.logger.warning(f'Unparsed <p>: {defs=}')
                    continue
                values = [' '.join(x.split(':', 1)[1].split()) for x in defs]
                row = augment(dict(zip(headers, values)))
                if row['Notice ID'] in done:
                    # The notice ID was already covered by the historical CSV, skip duplicate
                    self.logger.debug(f'Skipping done Notice ID {row['Notice ID']}')
                else:
                    yield row
            # Newer/current notices are in HTML table
            trs = doc.select('div.tn-datatable table tr')[1:]
            for tr in reversed(trs):
                tds = tr.find_all('td')
                if len(tds) != len(headers):
                    if tds and '@tn.gov' not in tr.get_text():
                        self.logger.warning(f'Unparsed <tr>: {tr}')
                    continue
                values = [td.get_text(strip=True) for td in tds]
                yield augment(dict(zip(headers, values)))

        keys = ['tn_historical.csv', 'latest.html']
        it = map(readfile, map(self.cache.topath, keys))
        try:
            yield chain.from_iterable(it)
            for noticeid in todo:
                self.logger.warning(f'Unassociated artifacts {noticeid=}')
        finally:
            while fps:
                fps.pop().close()
    
    def build_index(self) -> dict[str, dict[str, str]]:
        "Mapping of {noticeid: {cachekey: url}} extracted from HTML"
        items: deque[tuple[str, str, str]] = deque()

        def add(noticeid: str, href: str) -> None:
            url = self.absurl(href)
            noticeid = strs.rewrite_all(noticeid, self.noticeid_rewrites)
            if not (noticeid and url.endswith('.pdf')):
                if not href.startswith('mailto:'):
                    self.logger.warning(f'No index item for {href=}')
                return
            filename = f'{noticeid}-{Path(URL(url).path).name}'
            filename = strs.clean_filename(filename, fail=True)
            cachekey = f'records/{filename}'
            items.append((noticeid, cachekey, url))

        doc = dom.bs(self.cache/'latest.html')
        for tr in doc.select('div.tn-datatable table tr'):
            tds = tr.find_all('td')
            if not tds:
                continue
            add(tds[-1].get_text(), tr.a['href'])
        for p in doc.select('div.tn-rte > p'):
            noticeid = p.get_text(strip=True).rsplit('#', 1)[-1]
            if not (link := p.a):
                continue
            add(noticeid, link['href'])
        index: dict[str, dict[str, str]] = defaultdict(dict)
        for noticeid, cachekey, url in sorted(items):
            index[noticeid][cachekey] = url
        self.cache.write_json('index.json', index, indent=2)
        return dict(index)

    # async def _scrape(self):
    #     from warn.scrapers import tn
    #     from warn import utils as wutils
    #     class fakeutils:
    #         @staticmethod
    #         def get_url(url: str):
    #             rep = self.session.get(url)
    #             rep.raise_for_status()
    #             return rep
    #         @staticmethod
    #         def __getattr__(name):
    #             return getattr(wutils, name)
    #     tn.utils = fakeutils()
    #     try:
    #         await super().scrape()
    #     finally:
    #         tn.utils = wutils