from __future__ import annotations

import asyncio
import csv
import json
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
from re import compile as _r
from typing import ClassVar, Generator, Iterable, Iterator
from urllib.parse import parse_qs

from starlette.datastructures import URL

from .. import utils
from ..tools import files, strs, xlsx
from ..tools.dom import bs
from .base import Scraper

__all__ = ['CO']

class CO(Scraper):
    sheets_urlmap: ClassVar[dict[str, str]] = {
        'https://drive.google.com/open?id=1M-jYA2cSbehhp1pbpcAa900PtjAgktCHbU556cSjzc4':
            'https://docs.google.com/spreadsheets/d/1M-jYA2cSbehhp1pbpcAa900PtjAgktCHbU556cSjzc4'}
    rowkey_maxlen: ClassVar[int] = 1024
    artifacts_minyear: ClassVar[int] = 2020

    async def scrape(self) -> None:
        self.runner.scrape()
        await asyncio.sleep(0)
        # Rewrite CSV
        with self.runner.file.open() as file:
            # upstream scraper uses set() for header, which is unordered & breaks hashing.
            headers = sorted(next(csv.reader(file)))
        with self.runner.file.open() as file:
            reader = csv.DictReader(file)
            with self.cache.open('normalized.csv', 'w') as file:
                writer = csv.DictWriter(file, fieldnames=headers)
                writer.writeheader()
                writer.writerows(reader)
        self.runner.file.unlink()
        # Download xlsx files for building artifacts index
        doc = bs(self.cache/'main/source.html')
        currtext = 'View Real Time Warns'
        links = (
            doc.find('a', text=currtext),
            *doc.find(class_='ckeditor-accordion').find_all('a'))
        now = utils.now()
        params = dict(format='xlsx')
        for a in links:
            # Normalize whitespace & null bytes
            text = ' '.join(a.text.split())
            if text == currtext:
                year = now.year
                key = f'current.xlsx'
            else:
                year = int(text.split()[1])
                key = f'{year}.xlsx'
            if year < self.artifacts_minyear:
                # No need to download xlsx that won't contain artifacts data
                continue
            url = a['href'].split('edit')[0].rstrip('/')
            url = self.sheets_urlmap.get(url, url)
            url = f'{url}/export'
            is_recent = year >= now.year
            # Redownload prior year util July
            is_recent = is_recent or year == now.year - 1 and now.month <= 6
            await self.download(key, url, params=params, missing_only=not is_recent)
        # Download artifacts
        index = await self.build_index()
        for subidx in index.values():
            for key, url in subidx.items():
                await self.download(key, url, missing_only=True)
                self.artifacts.add(key)

    async def clean(self) -> None:
        self.cache.delete('*.json', '*.csv', '*.xlsx', 'main/*.html', glob=True)

    def statobjs(self):
        yield self.cache/'normalized.csv'
        yield self.cache/'index.json'

    @contextmanager
    def extract(self) -> Generator[Iterable[dict[str, str]]]:
        index: dict[str, dict[str, str]] = self.cache.read_json('index.json')
        todo = set(index)

        def makerow(row: dict[str, str]) -> dict[str, str]:
            key = self.rowkey(row)
            if key:
                row['row_key'] = key
                if key in index:
                    row['artifacts_json'] = json.dumps(index[key])
                    todo.discard(key)
            return row

        with self.cache.open('normalized.csv') as file:
            yield map(makerow, csv.DictReader(file))
            for key in todo:
                self.logger.warning(f'Unassociated artifacts {key=}')

    def rowkey(self, row: dict[str, str]) -> str|None:
        """
        Get artifacts row key from either a CSV row or xlsx file.

        Given how the upstream runner processes the data, there is no simple,
        uniform way to exactly match each row in the CSV to exaclty one row in
        the xlsx files. Here we use just the company name and the first of
        notice_date/received_date to form the row key.

        In cases where there are multiple rows with the same row key, the
        corresponding artifacts will be associated with all rows. This is
        preferred over the alternatives of either missing associations by
        complicating the row key, or dropping artifacts by overwriting
        duplicate rowkey values.
        """
        notice_date = row.get('notice_date', row.get('received_date'))
        parsed_date = utils.parse_date(notice_date)
        company = row.get('company', '').replace('-', '').replace(' ', '')
        if not (parsed_date and company):
            return
        datestr = parsed_date.strftime(f'%Y-%m-%d')
        keystr = f'{company}-{datestr}'
        return strs.clean_filename(keystr[:self.rowkey_maxlen], stem=True)
    
    async def build_index(self) -> dict[str, dict[str, str]]:
        """
        Extracts artifact data from downloaded xlsx files and returns mapping
        of row key to mapping of cache key to URL.
        """
        field_sources: dict[str, list[str]] = dict(
            company=['company', 'company name'],
            received_date=['received_date', 'received'],
            notice_date=['notice_date', 'warn date'],
            url=['warn letter', ''])
        skipurl_searchpat = _r(r'|'.join([
            '1Vt0x-2oxV0NJuIJbdQScctVxdFKb7Rk4',
            '1ogPXaZ2LYg0zRMkYscrkkv0HxdZielri',
            '1uhBFt0cZe7poL3s4yW2gJlkjtcp0ndg5']))

        def extract_workbook(file: Path) -> Iterator[dict[str, str]]:
            'Extract artifact info data from xslx workbook file'
            # Use read_only=False to generate cells with hyperlink attribute
            ws = xlsx.load_workbook(file, read_only=False).worksheets[0]
            it = (tuple(map(cellstr, cells)) for cells in ws.iter_rows())
            headers = tuple(map(str.lower, next(it)))
            for header in field_sources['company']:
                if header in headers:
                    break
            else:
                raise ValueError(f'Cannot find headers {file=}')
            for values in it:
                # Load in reverse order, so duplicate headers favor the first
                # occurrence. Example case is first empty string header for
                # the URL in 2021, followed by additional empty headers for
                # junk columns.
                row = dict(zip(*(map(reversed, (headers, values)))))
                info: dict[str, str] = {}
                for field, sources in field_sources.items():
                    for header in sources:
                        if row.get(header):
                            info[field] = row[header]
                            break
                rowkey = self.rowkey(info)
                if rowkey and info.get('url', '').startswith('https://'):
                    cachekey, url = getkeyurl(rowkey, info['url'])
                    info.update(cachekey=cachekey, url=url, rowkey=rowkey)
                    yield info

        def cellstr(cell: xlsx.Cell) -> str:
            'Get the hyperlink target or string value for an xlsx data cell'
            return xlsx.cellurl(cell) or xlsx.cellstr(cell).strip()

        def getkeyurl(rowkey: str, url: str) -> tuple[str, str]:
            """
            Get the cache key and PDF download URL for the given row key and
            URL as found. Google Drive/Docs URLs are converted to download
            or export URLs.
            """
            # Handle Google Drive/Docs URLs
            fileid, isdoc = None, False
            if url.startswith((
                'https://drive.google.com/open',
                'https://drive.google.com/uc',
                'https://docs.google.com/document/u/0/export')):
                fileid = parse_qs(URL(url).query)['id'][0]
            elif url.startswith('https://drive.google.com/file/d/'):
                fileid = URL(url).path.rsplit('/')[-2]
            elif url.startswith('https://docs.google.com/document/d/'):
                fileid = URL(url).path.rsplit('/')[-2]
                isdoc = True
            if fileid:
                if isdoc:
                    # Export doc as PDF
                    url = str(
                        URL('https://docs.google.com/document/u/0/export')
                        .include_query_params(format='pdf', id=fileid))
                else:
                    url = str(
                        URL('https://drive.google.com/uc')
                        .include_query_params(export='download', id=fileid))
                urlid = fileid
            else:
                # In case there is no Google file ID, use a hash of the URL
                urlid = strs.struuid(url).hex[:16]
            cachekey = f'records/{rowkey}-{urlid}.pdf'
            return cachekey, url

        # Sequence of (rowkey, cachekey, URL)
        items: deque[tuple[str, str, str]] = deque()
        for file in sorted(self.cache.glob('*.xlsx'), reverse=True):
            cached = Path(f'{file}.json')
            with files.jsoncache(file, cached) as infos:
                if infos is None:
                    infos = list(extract_workbook(file))
                    with cached.open('w') as fp:
                        json.dump(infos, fp, indent=2)
            for info in infos:
                rowkey = info['rowkey']
                url = info['url']
                if skipurl_searchpat.search(url):
                    self.logger.debug(f'Skip {url=} {rowkey=}')
                    continue
                items.append((rowkey, info['cachekey'], url))
        # Mapping of {rowkey: {cachekey: URL}}
        index: dict[str, dict[str, str]] = defaultdict(dict)
        for rowkey, cachekey, url in sorted(items):
            index[rowkey][cachekey] = url
        self.cache.write_json('index.json', index, indent=2)
        return dict(index)
