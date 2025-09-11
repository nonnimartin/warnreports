from __future__ import annotations

from datetime import datetime
from html import unescape as _u
from re import compile as _r
from typing import ClassVar, Iterator

from .. import utils
from ..tools import files
from ..tools.dom import Soup, bs
from .base import Scraper

__all__ = ['PA']

class PA(Scraper):
    base_url: ClassVar = 'https://www.pa.gov'
    latest_url: ClassVar = '/agencies/dli/programs-services/workforce-development-home/warn-requirements/warn-notices.html'
    pat_ol: ClassVar = _r(r'^[1-9][0-9]*\.\s')

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        # No warn-scraper implementation
        del self.runner

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)

    def statobjs(self):
        if (file := self.cache/'latest.html').exists():
            yield self.find_main_div(bs(file))

    @utils.wrapcontext
    def extract(self) -> Iterator[dict[str, str]]:
        file = self.cache/'latest.html'
        scrape_time = files.mtime(file)
        maindiv = self.find_main_div(bs(file))
        extra = dict(url=self.absurl(self.latest_url), scrape_time=scrape_time.isoformat())
        for yeardiv in self.find_year_divs(maindiv):
            h2s = yeardiv.find_all('h2')
            year = int(h2s.pop(0).text.strip())
            if not 2000 <= year <= utils.now().year + 1:
                raise ValueError(f'Invalid {year=}')
            extra.pop('reported_month', None)
            if h2s:
                # For 2024 & 2025, month headings are in <h2> elements,
                # and company names are in <h3> elements.
                for h2 in h2s:
                    text = h2.text.strip()
                    # raises ValueError
                    datetime.strptime(text, '%B')
                    extra['reported_month'] = f'{text} {year}'
                    cur = h2.find_next('div', {'class': 'cmp-accordion__panel'})
                    for h3 in cur.find_all('h3'):
                        yield self.parse_record(h3) | extra
            else:
                # For 2023, month headings and company names are both in
                # <h3> elements.
                h3s = yeardiv.find_all('h3')
                for h3 in h3s:
                    text = h3.text.strip()
                    try:
                        datetime.strptime(text, '%B')
                    except ValueError:
                        if 'reported_month' not in extra:
                            raise
                    else:
                        extra['reported_month'] = f'{text} {year}'
                        continue
                    yield self.parse_record(h3) | extra

    def find_main_div(self, doc: Soup) -> Soup:
        return (doc
            .find('section', {'class': 'agencypage-content'})
            .find('div')
            .find('div'))

    def find_year_divs(self, maindiv: Soup) -> Iterator[Soup]:
        for child in maindiv.children:
            if child.name == 'div' and 'panelcontainer' in child['class']:
                yield child

    def parse_record(self, h3: Soup) -> dict[str, str]:
        row = dict(company=_u(h3.text.strip()))
        text = h3.find_next_sibling('div').text
        text = text.replace('\u200b', '')
        lines = text.splitlines()
        lines: list[str] = list(filter(None, map(str.rstrip, lines)))
        curheader = None
        unparsed = []
        for i, line in enumerate(lines):
            clean = ' '.join(line.split()).strip()
            if i == 0:
                row['location'] = clean
                continue
            parts = clean.split(':', 1)
            if curheader and (
                line.startswith('\xa0') or
                self.pat_ol.match(clean) or
                parts[0] != parts[0].upper()
            ):
                if row[curheader]:
                    row[curheader] += '\n'
                row[curheader] += clean
                continue
            if not clean:
                continue
            if ':' not in clean:
                if not curheader:
                    row['location'] += '\n' + clean
                else:
                    unparsed.append(clean)
                continue
            curheader = parts[0].strip()
            row[curheader] = parts[1].strip()
        if unparsed:
            row['unparsed'] = '\n'.join(unparsed)
        row['raw'] = '\n'.join(lines)
        return row
