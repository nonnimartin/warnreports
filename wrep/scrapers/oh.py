from __future__ import annotations

import csv
import json
from collections import defaultdict
from contextlib import contextmanager
from itertools import chain, islice
from re import compile as _r
from typing import Any, Iterator

from ..tools import strs
from ..tools.dom import bs
from .base import Scraper

__all__ = ['OH']

class OH(Scraper):
    base_url = 'https://jfs.ohio.gov'
    latest_url = (
        '/wps/portal/gov/jfs/job-services-and-unemployment/job-services'
        '/job-programs-and-services/submit-a-warn-notice'
        '/current-public-notices-of-layoffs-and-closures-sa'
        '/current-public-notices-of-layoffs-and-closures')
    request_delay = 1
    atext_pat = _r(r'^\s*(\d{4}) Public Notices')
    legacy_header_map = {
        'DateReceived': 'Date Received',
        'Potential NumberAffected': 'Potential Number Affected',
        'LayoffDate(s)': 'Layoff Date(s)',
        'PhoneNumber': 'Phone Number'}
    artifact404 = {
        'https://jfs.ohio.gov/static/warn/pdf/Things-Remembered.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Golden-Svcs-LLC.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Crothall-Healthcare.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Omaze.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Norcold-LLC-Gettysburg.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Norcold-LLC-Sidney.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/McLaren-St--Luke-s-Hospital.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Starry-Inc.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/OhioHealth.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Toppan-Merrill.pdf',
        'https://jfs.ohio.gov/static/warn/pdf/Specialized-Bicycle-Components-Inc.pdf',
    }
    rewrites = dict(
        artifact=[
            (_r(r' '), '+'),
            (_r(r'-\.pdf$'), '.pdf'),
            (_r(r'David-s-Bridal'), 'Davids-Bridal'),
        ],
        notice_id=[
            (_r(r'-+'), '-'),
            (_r(r'\*'), ''),
        ]
    )
    # Archived historical data
    historical_url = 'https://archive.warnreports.org/s/OH/oh_historical.csv'
    archived_sources = {
        # 2025-02 The 2024 link disappeared from the website for a while, so we
        #         keep archived sources as a fallback.
        '2020.html': 'https://archive.warnreports.org/s/OH/2020.html',
        '2021.html': 'https://archive.warnreports.org/s/OH/2021.html',
        '2022.html': 'https://archive.warnreports.org/s/OH/2022.html',
        '2023.html': 'https://archive.warnreports.org/s/OH/2023.html',
        '2024.html': 'https://archive.warnreports.org/s/OH/2024.html',
    }

    async def scrape(self):
        await self.download('latest.html', self.latest_url)
        sources = self.build_sources()
        for key, url in sources.items():
            await self.download(key, url, missing_only=True)
            self.extract_json(key)
        index = self.build_index()
        for items in map(dict.items, index.values()):
            for key, url in items:
                await self.download(key, url, missing_only=True)
                self.artifacts.add(key)
        await self.download('oh_historical.csv', self.historical_url, missing_only=True)

    def statobjs(self):
        yield from sorted(self.cache.glob('*.json', 'oh_historical.csv'))

    def build_sources(self) -> dict[str, str]:
        'Yearly html pages {key: url}'
        items: list[tuple[str, str]] = []
        items.extend(self.archived_sources.items())
        items.append(('latest.html', self.absurl(self.latest_url)))
        for a in bs(self.cache/'latest.html').select('nav a'):
            if not (match := self.atext_pat.match(a.text)):
                continue
            key = f'{match.group(1)}.html'
            url = self.absurl(a['href'])
            items.append((key, url))
        sources = dict(sorted(items))
        self.cache.write_json('sources.json', sources, indent=2)
        return sources

    def extract_json(self, key: str) -> dict[str, Any]:
        page = bs(self.cache/key)
        div = page.find('div', {'id': 'js-placeholder-json-data'})
        body = json.loads(div.decode_contents().strip())
        self.cache.write_json(f'{key}.json', body, indent=2)
        return body

    def build_index(self) -> dict[str, dict[str, str]]:
        'Build mapping of notice_id to artifacts dict (key: url)'
        def rewriteurl(url: str) -> str:
            return strs.rewrite(url, self.rewrites['artifact'])
        # Mapping from notice_id to urls
        builder: dict[str, set[str]] = defaultdict(set)
        sourcekeys: list[str] = list(self.cache.read_json('sources.json'))
        for key in sourcekeys:
            rows: list[list[str]] = self.cache.read_json(f'{key}.json')['data']
            headers = rows[1]
            for values in filter(any, rows[2:]):
                data = dict(zip(headers, values))
                url = rewriteurl(self.absurl(data['URL']))
                if (
                    not (url and url.endswith('.pdf')) or
                    url in self.artifact404
                ):
                    continue
                it = data['Notice ID'].split(' and ')
                it = map(self.normalize_notice_id, it)
                it = filter(None, it)
                for notice_id in it:
                    builder[notice_id].add(url)
        # Final index
        index: dict[str, dict[str, str]] = {}
        for notice_id in sorted(builder):
            index[notice_id] = {}
            urls = sorted(builder[notice_id])
            for i, url in enumerate(urls, start=1):
                name = notice_id
                if len(urls) > 1:
                    name = f'{name}_{i}'
                key = f'records/{name}.pdf'
                index[notice_id][key] = url
        self.cache.write_json('index.json', index, indent=2)
        return index

    def normalize_notice_id(self, value: str) -> str:
        return strs.rewrite(value, self.rewrites['notice_id']).strip()

    @contextmanager
    def extract(self):
        index: dict[str, dict[str, str]] = self.cache.read_json('index.json')
        sources: dict[str, str] = self.cache.read_json('sources.json')

        def readfile(key: str):
            url = sources[key]
            rows: list[list[str]] = self.cache.read_json(f'{key}.json')['data']
            headers = list(rows[1])
            while not headers[-1]:
                headers.pop()
            for values in filter(any, islice(rows, 2, None)):
                base = dict(zip(headers, values))
                if self.archived_sources.get(key) != url:
                    # Don't include the archived source
                    base['URL'] = url
                it = base['Notice ID'].split(' and ')
                it = map(self.normalize_notice_id, it)
                for notice_id in it:
                    data = dict(base)
                    data['Notice ID'] = notice_id
                    if notice_id in index:
                        data['artifacts_json'] = json.dumps(index[notice_id])
                    yield data

        def readhistorical(reader: Iterator[list[str]]):
            headers = [
                self.legacy_header_map.get(header, header)
                for header in next(reader)]
            for values in reader:
                data = dict(zip(headers, values))
                # Ignore duplicates of current data
                if (notice_id := data.get('Notice ID')) and notice_id not in index:
                    yield data

        it = chain.from_iterable(map(readfile, sources))
        with self.cache.open('oh_historical.csv') as file:
            yield chain(it, readhistorical(csv.reader(file)))
