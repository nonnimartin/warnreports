from __future__ import annotations

from collections import deque
from pathlib import Path
from re import compile as _r
from typing import ClassVar, Iterator
from urllib.parse import unquote_plus

from starlette.datastructures import URL

from ..tools import dom, strs
from .base import AugmentArtifactsScraper

__all__ = ['CT']

class CT(AugmentArtifactsScraper):
    base_url: ClassVar = 'https://www.ctdol.state.ct.us/progsupt/bussrvce/warnreports'

    def get_patches(self):
        return super().get_patches()|dict(utils=PatchUtils(self))

    def build_index(self) -> dict[str, dict[str, str]]:
        """
        Extracts artifact data from downloaded html files and returns mapping
        of {rowkey: {cachekey: URL}},
        """
        minyear = 2019
        uri_rewrites = [
            (_r(r'^https?://webdev/progsupt/bussrvce/warnreports/'), ''),
        ]
        rowkey_rewrites = [
            (_r(r'(MountainSportsLLCUpdatedNotice){2}'), r'\1'),
        ]

        def parsetable(year: int, table: dom.Soup) -> Iterator[tuple[str, str, str]]:
            "Yields (row_key, cache_key, url) for an html table"
            tbody = table.find('tbody')
            for tr in tbody.find_all('tr'):
                tds = tr.find_all('td')
                if len(tds) < 2:
                    continue
                for td in tds:
                    a = td.find('a')
                    if a is None:
                        continue
                    info = getkeyurl(year, a.get('href', ''))
                    if info:
                        rowkey = self.rowkey(td.text for td in tds)
                        rowkey = strs.rewrite_all(rowkey, rowkey_rewrites)
                        yield rowkey, *info
                        break

        def getkeyurl(year: int, uri: str) -> tuple[str, str]|None:
            "Check the raw 'download' value, and if valid, return a clean cache key and download URL"
            if not uri.endswith('.pdf'):
                return
            uri = strs.rewrite_all(uri, uri_rewrites)
            url = self.absurl(uri)
            clean = Path(URL(url).path).name
            clean = unquote_plus(clean)
            clean = strs.clean_filename(clean)
            if not clean:
                return
            cachekey = f'records/{year}_{clean}'
            return cachekey, url

        # Sequence of (rowkey, cachekey, URL)
        items: deque[tuple[str, str, str]] = deque()
        for file in sorted(self.cache.glob('*.html'), reverse=True):
            year = int(file.name[:4])
            if year < minyear:
                continue
            for table in dom.bs(file, 'html5lib').find_all('table'):
                if (td := table.find('td')) and td.text.strip() == 'WARN Date':
                    items.extend(parsetable(year, table))
                    break
            else:
                raise ValueError(f'Cannot find table {file=}')
        # Mapping of {rowkey: {cachekey: URL}}
        return self.write_index_items(items)

class PatchUtils:

    def __init__(self, scraper: CT) -> None:
        self.get_url = scraper.session.get
        from warn import utils as wutils
        self.delegate = wutils
        self.write_rows_to_csv = self.delegate.write_rows_to_csv

    def __getattr__(self, name: str):
        return self.__dict__.setdefault(name, getattr(self.delegate, name))
