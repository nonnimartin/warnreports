from __future__ import annotations

import asyncio
import csv
import functools
import hashlib
import json
from collections import defaultdict
from contextlib import contextmanager
from importlib import import_module
from itertools import chain
from pathlib import Path
from typing import Any, ClassVar, Generator, Iterable, Iterator, override

import requests
from requests.adapters import HTTPAdapter, Retry
from requests.exceptions import HTTPError
from typing_extensions import Buffer

from .. import Stage, settings, utils
from ..models import ScraperOpts, StateCode, ValidStateCode
from ..ref.tz import zoneinfos
from ..tools import dom, files, strs

__all__ = ['Scraper']

class Scraper:
    'Scraper base class'
    state: ClassVar[StateCode]
    base_url: ClassVar[str|None] = None
    user_agent: ClassVar[str] = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0'
    request_delay: ClassVar[float] = 0.0
    ssl_verify: ClassVar[bool] = True
    retry: ClassVar[dict] = dict(total=10, backoff_factor=0.5, backoff_max=20.0)

    def __init__(self, *, opts: ScraperOpts|dict|None = None) -> None:
        self.opts = ScraperOpts.model_validate(opts or {})
        self.session = requests.session()
        self.session.mount('https://', HTTPAdapter(max_retries=Retry(**self.retry)))
        self.session.headers['User-Agent'] = self.user_agent
        self.cache = files.FileCache(settings.BUILD_DIR/Stage.Scrape/self.state.lower())
        self.extract_cache = files.FileCache(settings.BUILD_DIR/Stage.Extract/self.state.lower())
        self.artifacts = files.ArtifactStore(
            settings.ARTIFACTS_DIR/self.state.lower(),
            self.cache.dir)
        self.metrics = defaultdict(int)
        self.logger = utils.get_logger(f'scrapers.{self.state}')
        self.tz = zoneinfos[self.state]
        self.runner = Runner(self)

    async def clean(self) -> None:
        self.cache.delete(
            '*.csv',
            '*.xlsx',
            '*.pdf',
            '*.json',
            '*.html',
            '*/*.html',
            glob=True)
        await asyncio.sleep(0)

    async def scrape(self) -> None:
        self.runner.scrape()
        await asyncio.sleep(0)

    async def stat(self) -> dict[str, Any]:
        stat = hashstat(self.statobjs())
        await asyncio.sleep(0)
        return stat

    def statobjs(self) -> Iterable[Any]:
        yield self.runner.file

    @contextmanager
    def extract(self) -> Generator[Iterable[dict[str, str|None]]]:
        def rest(row: dict):
            # Backwards-compatibility
            if '__' in row:
                row['__'] = json.dumps(row['__'])
            return row
        with self.runner.file.open() as file:
            it = csv.DictReader(file, restkey='__')
            yield map(rest, it)

    async def extract_clean(self) -> None:
        self.extract_cache.nuke()
        await asyncio.sleep(0)

    async def fetch(self, key: str|Path, url: str, **kw) -> str:
        rep = await self.request('GET', url, **kw)
        try:
            text = rep.content.decode()
        except UnicodeDecodeError:
            text = rep.text
        self.cache.write(key, text)
        return text

    async def download(self, key: str|Path, url: str, *, encoding: str|None = None, missing_only: bool = False, **kw) -> requests.Response|None:
        # Adapted from: https://github.com/biglocalnews/warn-scraper/blob/main/warn/cache.py
        dest = self.cache/key
        if missing_only and dest.exists():
            await asyncio.sleep(0)
            return
        self.logger.debug(f'Downloading {url} to {dest}')
        dest.parent.mkdir(parents=True, exist_ok=True)
        with await self.request('GET', url, stream=True, **kw) as rep:
            if not rep.ok:
                self.logger.warning(f'Download failed status={rep.status_code} url={rep.url}')
                return rep
            rep.encoding = encoding or rep.encoding or 'utf-8'
            with dest.open('wb') as f:
                for chunk in rep.iter_content(chunk_size=8192):
                    f.write(chunk)
                    self.metrics['request_bytes'] += len(chunk)
        await asyncio.sleep(0)
        return rep

    async def request(self, method: str, url: str, *, check: bool = True, **kw) -> requests.Response:
        if self.request_delay and self.metrics['request_count']:
            await asyncio.sleep(self.request_delay)
        url = self.absurl(url)
        kw.setdefault('verify', self.ssl_verify)
        self.metrics['request_count'] += 1
        try:
            rep = self.session.request(method, url, **kw)
            if check:
                rep.raise_for_status()
        except Exception as err:
            if isinstance(err, HTTPError) and err.response is not None:
                status = err.response.status_code
            else:
                status = None
            self.logger.error(f'Failed to get {url=} {status=}')
            raise
        if not kw.get('stream'):
            self.metrics['request_bytes'] += len(rep.content)
            await asyncio.sleep(0)
        return rep

    def absurl(self, url: str) -> str:
        return strs.absurl(self.base_url, url)

    def __init_subclass__(cls) -> None:
        cls.retry = Scraper.retry | cls.retry
        try:
            cls.state = ValidStateCode(cls.__name__)
        except ValueError:
            pass

class AugmentArtifactsScraper(Scraper):
    """
    Scraper class with default functionality for augmenting CSV data with artifacts.
    Subclasses must implement `build_index()`
    """
    index_filename: ClassVar[str] = 'index.json'
    rowkey_trans: ClassVar[dict[int, None]] = dict.fromkeys(map(ord, '-_'))

    async def scrape(self) -> None:
        self.runner.scrape()
        # Download artifacts
        index = self.build_index()
        for key, url in chain.from_iterable(map(dict.items, index.values())):
            await self.download(key, url, missing_only=True)
            self.artifacts.add(key)

    def statobjs(self) -> Iterator[Any]:
        yield self.runner.file
        yield self.cache/self.index_filename

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        "Yield augmented records from CSV rows"
        index: dict[str, dict[str, str]] = self.cache.read_json(self.index_filename)
        todo: set[str] = set(index)

        def readrecords(it: Iterable[Iterable[str]]) -> Iterator[dict[str, str]]:
            headers = tuple(next(it))
            for values in it:
                row = dict(zip(headers, values))
                rowkey = self.rowkey(row.values())
                row['row_key'] = rowkey
                if rowkey in index:
                    row['artifacts_json'] = json.dumps(index[rowkey])
                    todo.discard(rowkey)
                yield row

        with self.runner.file.open() as file:
            yield readrecords(csv.reader(file))
            for key in todo:
                self.logger.warning(f'Unassociated artifacts {key=}')

    def rowkey(self, values: Iterable[str]) -> str:
        "Values hash key from CSV row for artifact index"
        raw = ''.join(''.join(values).split())
        clean = strs.clean_filename(raw, stem=True, fail=True) 
        return clean.translate(self.rowkey_trans)

    def build_index(self) -> dict[str, dict[str, str]]:
        """
        Build and save mapping of {rowkey: {cachekey: URL}}.
        """
        raise NotImplementedError

    def write_index_items(self, items: Iterable[tuple[str, str, str]]) -> dict[str, dict[str, str]]:
        """
        Converts an iterable of items (rowkey, cachekey, URL) into a sorted
        mapping of {rowkey: {cachekey: URL}}. Writes JSON to the index file,
        and returns the dict result.
        """
        index: dict[str, dict[str, str]] = defaultdict(dict)
        for rowkey, cachekey, url in sorted(items):
            index[rowkey][cachekey] = url
        self.cache.write_json(self.index_filename, index, indent=2)
        return dict(index)

class Runner:

    def __init__(self, scraper: Scraper) -> None:
        self.scraper = scraper

    @property
    def file(self) -> Path:
        return self.scraper.cache/f'{self.scraper.state.lower()}.csv'

    @functools.cached_property
    def module(self):
        return import_module(f'warn.scrapers.{self.scraper.state.lower()}')

    def scrape(self) -> None:
        mod = self.module
        scraper = self.scraper
        patches = {}
        restore = {}
        if hasattr(mod, 'scrape_state'):
            patches['scrape_state'] = self.patched_scrape_state
            restore['scrape_state'] = mod.scrape_state
        patches['print'] = scraper.logger.info
        restore['print'] = print
        try:
            for name, value in patches.items():
                scraper.logger.debug(f'Patching {name}')
                setattr(mod, name, value)
            mod.scrape(scraper.cache.dir, scraper.cache.dir.parent)
        finally:
            for name, value in restore.items():
                scraper.logger.debug(f'Restoring {name}')
                setattr(mod, name, value)

    def patched_scrape_state(
        self,
        state_postal: StateCode,
        search_url: str,
        output_csv: Path,
        stop_year: int,
        cache_dir: Path = ...,
        use_cache: bool = ...,
        verify: bool = ...,
    ) -> Path:
        site = jobcenter_site_class()(self.scraper, search_url, stop_year)
        site.patched_scrape_state()
        return self.file

@functools.cache
def jobcenter_site_class():
    import time

    from warn.platforms.job_center.site import Site as BaseSite

    class JobCenterSite(BaseSite):
        headers: ClassVar = [
            'employer',
            'notice_date',
            'number_of_employees_affected',
            'warn_type',
            'city',
            'zip',
            'lwib_area',
            'address',
            'record_number',
            'detail_page_url']

        @override
        def __init__(self, scraper: Scraper, url: str, stop_year: int) -> None:
            self.scraper = scraper
            self.request_delay = max(0.5, scraper.request_delay)
            self.stop_year = stop_year
            super().__init__(scraper.state, url, scraper.cache.dir, scraper.ssl_verify)

        def patched_scrape_state(self) -> None:
            from warn.platforms.job_center import utils as jcutils
            scraper = self.scraper
            no_cache_years, yearly_dates = self._get_datestring_ranges()
            ssl_verify = scraper.ssl_verify
            raw_csv = scraper.cache/f'{scraper.state.lower()}_raw.csv'
            scraper.logger.debug(f'patched_scrape_state {ssl_verify=} {yearly_dates=} {no_cache_years=} {raw_csv=}')
            scraper.cache.mkpdir(raw_csv)
            scraper.cache.delete(raw_csv)
            with raw_csv.open('w', newline='') as fp:
                writer = csv.writer(fp)
                writer.writerow(self.headers)
            jcutils._scrape_years(
                self, raw_csv, self.headers, no_cache_years, use_cache=False, verify=ssl_verify)
            jcutils._scrape_years(
                self, raw_csv, self.headers, yearly_dates, use_cache=True, verify=ssl_verify)
            scraper.cache.delete(scraper.runner.file)
            jcutils._dedupe(raw_csv, scraper.runner.file)

        @override
        def _get_page(self, url: str, params=None, use_cache=True) -> str:
            'Override to check status, use scraper session, add delay, cache record files'
            scraper = self.scraper
            cachekey = self.cache.key_from_url(url, params)
            use_cache = use_cache or Path(cachekey).parent.name == 'records'
            if use_cache and scraper.cache.exists(cachekey):
                return scraper.cache.read(cachekey)
            if scraper.metrics['request_count']:
                time.sleep(self.request_delay)
            scraper.logger.debug(f'Request {url=}')
            scraper.metrics['request_count'] += 1
            rep = scraper.session.get(url, params=params, verify=scraper.ssl_verify)
            rep.raise_for_status()
            text = rep.text
            scraper.metrics['request_bytes'] += len(text)
            scraper.cache.write(cachekey, text)
            return text

        def _get_datestring_ranges(self) -> tuple[list[str], list[str]]:
            now = utils.now(tz=self.scraper.tz)
            yearly_dates = [
                (f'{year}-01-01', f'{year}-12-31')
                for year in range(self.stop_year, now.year + 1)]
            no_cache_years = [yearly_dates.pop()]
            if yearly_dates and now.month <= 6:
                no_cache_years.append(yearly_dates.pop())
            yearly_dates.reverse()
            return no_cache_years, yearly_dates

    return JobCenterSite

def hashstat(it: Iterable[Path|str|Buffer|dom.PageElement]) -> dict[str, str|int|None]:
    h = hashlib.sha1()
    size = 0
    for obj in it:
        if isinstance(obj, Path):
            try:
                with obj.open('rb') as file:
                    hashlib.file_digest(file, lambda: h)
                size += obj.stat().st_size
            except FileNotFoundError:
                pass
            continue
        if isinstance(obj, str):
            buf = obj.encode()
        elif callable(getattr(obj, 'get_text', None)):
            # BeautifulSoup element, use text
            buf = obj.get_text().encode()
        else:
            buf = obj
        if buf:
            h.update(buf)
            size += len(buf)
    hash = h.hexdigest() if size else None
    return dict(hash=hash, size=size)
