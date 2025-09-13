from __future__ import annotations

from collections import deque
from re import compile as _r
from typing import Any, ClassVar, Iterator
from urllib.parse import unquote_plus

from ..tools import dom, strs
from .base import AugmentArtifactsScraper, Scraper

__all__ = ['FL']

class FL(AugmentArtifactsScraper):
    base_url: ClassVar = 'https://reactwarn.floridajobs.org'
    request_delay: ClassVar = 0.5
    user_agent: ClassVar = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36')

    class Session(Scraper.Session):

        def request(self, method: str, url: str, *, check = True, **kw):
            # Force verify
            kw['verify'] = self.verify
            # Force https
            url = url.replace('http://', 'https://')
            return super().request(method, url, check=check, **kw)

    def get_patches(self) -> dict[str, Any]:
        'Bug in _scrape_pdf uses os.exists instead of cache.exists'
        def exists(key: str) -> bool:
            return self.cache.exists(key.removeprefix(f'{self.state.lower()}/'))
        return super().get_patches()|dict(exists=exists)

    def build_index(self) -> dict[str, dict[str, str]]:
        "Build the artifacts index {rowkey: {cachekey: url}}"
        minyear = 2020
        uri_rewrites = [
            (_r(r'[^a-zA-Z\d_]'), '-'),
            (_r(r'([-_])+'), r'\1'),
            (_r(r'[A-Z]-MYDOCUMENTS'), ''),
        ]
        uri_fmt = '/WarnList/DownloadAzureFile?file={}'

        def parse_table(year: int, table: dom.Soup) -> Iterator[tuple[str, str, str]]:
            "Yields (rowkey, cachekey, url) for an html table"
            tbody = table.find('tbody')
            for tr in tbody.find_all('tr'):
                tds = tr.find_all('td')
                last = tds.pop()
                if last.find('input', id='download'):
                    if (el := last.find('input', type='hidden')):
                        if (info := getkeyurl(year, el['value'])):
                            rowkey = self.rowkey(td.text for td in tds)
                            yield rowkey, *info

        def getkeyurl(year: int, uri: str) -> tuple[str, str]|None:
            "Check the raw 'download' value, and if valid, return a clean cache key and download URL"
            if not uri.endswith('.pdf'):
                return
            clean = unquote_plus(uri)
            if clean.startswith('\\'):
                return
            clean = clean.removesuffix('.pdf')
            clean = strs.rewrite_all(clean, uri_rewrites)
            clean = clean.strip('_-')
            if not clean:
                return
            name = f'{year}_{clean}.pdf'
            cachekey = f'records/{name}'
            url = self.absurl(uri_fmt.format(uri))
            return cachekey, url

        # Sequence of (rowkey, cachekey, URL)
        items: deque[tuple[str, str, str]] = deque()
        for file in sorted(self.cache.glob('*_page_*.html'), reverse=True):
            year = int(file.name[:4])
            if year < minyear:
                continue
            table = dom.bs(file, 'html5lib').find('table')
            items.extend(parse_table(year, table))
        # Mapping of {rowkey: {cachekey: URL}}
        return self.write_index_items(items)
