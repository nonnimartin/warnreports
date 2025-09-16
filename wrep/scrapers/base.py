from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from importlib import import_module
from itertools import chain
from pathlib import Path
from types import ModuleType
from typing import Any, AsyncGenerator, ClassVar, Generator, Iterable, Iterator

import requests
import requests.models
from requests.adapters import HTTPAdapter, Retry
from requests.exceptions import HTTPError
from starlette.datastructures import URL

from .. import Stage, settings, utils
from ..models import ScraperOpts, StateCode, ValidStateCode
from ..ref.tz import zoneinfos
from ..tools import files, strs

__all__ = ['Scraper']

class Scraper:
    'Scraper base class'
    state: ClassVar[StateCode]
    base_url: ClassVar[str|None] = None
    user_agent: ClassVar[str] = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0'
    request_delay: ClassVar[float] = 0.0
    ssl_verify: ClassVar[bool] = True
    retry: ClassVar[dict] = dict(total=10, backoff_factor=0.5, backoff_max=20.0)
    maxconns: ClassVar[int] = 10

    def __init__(self, *, opts: ScraperOpts|dict|None = None) -> None:
        self.opts = ScraperOpts.model_validate(opts or {})
        self.cache = files.FileCache(settings.BUILD_DIR/Stage.Scrape/self.state.lower())
        self.extract_cache = files.FileCache(settings.BUILD_DIR/Stage.Extract/self.state.lower())
        self.artifacts = files.ArtifactStore(
            settings.ARTIFACTS_DIR/self.state.lower(),
            self.cache.dir)
        self.metrics = defaultdict(int)
        self.logger = logging.getLogger(f'{__name__}.{self.state}')
        self.tz = zoneinfos[self.state]
        self.session = self.Session(self)
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
        await self.runner.scrape()

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

    async def fetch(self, key: str|Path|None, url: str|URL, **kw) -> str:
        key = key or strs.clean_filename(Path(URL(str(url)).path).name, fail=True)
        rep = await self.session.arequest('GET', url, **kw)
        try:
            text = rep.content.decode()
        except UnicodeDecodeError:
            text = rep.text
        self.cache.write(key, text)
        return text

    async def download(self, key: str|Path|None, url: str|URL, *, encoding: str|None = None, missing_only: bool = False, **kw) -> requests.Response|None:
        # Adapted from: https://github.com/biglocalnews/warn-scraper/blob/main/warn/cache.py
        key = key or strs.clean_filename(Path(URL(str(url)).path).name, fail=True)
        dest = self.cache/key
        if missing_only and dest.exists():
            await asyncio.sleep(0)
            return
        self.logger.debug(f'Downloading {url} to {dest}')
        dest.parent.mkdir(parents=True, exist_ok=True)
        with await self.session.arequest('GET', url, stream=True, **kw) as rep:
            if not rep.ok:
                self.logger.warning(f'Download failed status={rep.status_code} url={rep.url}')
                return rep
            rep.encoding = encoding or rep.encoding or 'utf-8'
            with dest.open('wb') as f:
                async for chunk in rep.aiter_content(chunk_size=8192):
                    f.write(chunk)
        await asyncio.sleep(0)
        return rep

    def absurl(self, url: str|URL) -> str:
        return strs.absurl(self.base_url, url)

    def get_patches(self) -> dict[str, Any]:
        'Get patches to warn scraper module'
        return {}

    def __init_subclass__(cls) -> None:
        cls.retry = Scraper.retry | cls.retry
        try:
            cls.state = ValidStateCode(cls.__name__)
        except ValueError:
            pass

    class Session(requests.Session):

        def __init__(self, scraper: Scraper) -> None:
            super().__init__()
            self.scraper = scraper
            self.logger = scraper.logger
            self.metrics = scraper.metrics
            self.mount('https://', HTTPAdapter(
                pool_maxsize=scraper.maxconns,
                max_retries=Retry(**scraper.retry)))
            self.headers['User-Agent'] = scraper.user_agent
            self.verify = scraper.ssl_verify

        def send(self, request: requests.models.PreparedRequest, **kwargs) -> requests.Response:
            self.logger.debug(f'{request.method} {request.url}')
            self.metrics['request_count'] += 1
            rep = super().send(request, **kwargs)
            if kwargs.get('stream', self.stream):
                rep.__class__ = self.StreamingResponse
                rep.metrics = self.metrics
            else:
                self.metrics['request_bytes'] += len(rep.content)
            return rep

        def request(self, method: str, url: str, *, check: bool = True, **kw) -> requests.Response:
            url = self.scraper.absurl(url)
            try:
                rep = super().request(method, url, **kw)
                if check:
                    rep.raise_for_status()
            except Exception as err:
                if isinstance(err, HTTPError) and err.response is not None:
                    status = err.response.status_code
                else:
                    status = None
                self.logger.error(f'Failed to get {url=} {status=}')
                raise
            return rep

        async def arequest(self, method: str, url: str, *, check: bool = True, **kw) -> Scraper.Session.StreamingResponse:
            delay = kw.pop('delay', self.metrics['request_count'] and self.scraper.request_delay)
            if delay:
                await asyncio.sleep(delay)
            rep = self.request(method, url, check=check, **kw)
            if not kw.get('stream', self.stream):
                await asyncio.sleep(0.0)
            return rep

        class StreamingResponse(requests.Response):
            metrics: dict

            def iter_content(self, chunk_size: int = 8192) -> Generator[bytes]:
                for chunk in super().iter_content(chunk_size):
                    self.metrics['request_bytes'] += len(chunk)
                    yield chunk

            async def aiter_content(self, chunk_size: int = 8192) -> AsyncGenerator[bytes]:
                for chunk in self.iter_content(chunk_size):
                    yield chunk
                    await asyncio.sleep(0)

        # Allow for patching reequests
        def Session(self):
            return self

        session = Session

class AugmentArtifactsScraper(Scraper):
    """
    Scraper class with default functionality for augmenting CSV data with artifacts.
    Subclasses must implement `build_index()`
    """
    index_filename: ClassVar[str] = 'index.json'
    rowkey_trans: ClassVar[dict[int, None]] = dict.fromkeys(map(ord, '-_'))

    async def scrape(self) -> None:
        await super().scrape()
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

    async def scrape(self) -> None:
        scraper = self.scraper
        with self.patch() as mod:
            mod.scrape(scraper.cache.dir, scraper.cache.dir.parent)
        await asyncio.sleep(0)

    @contextmanager
    def patch(self) -> Generator[ModuleType]:
        scraper = self.scraper
        mod = import_module(f'warn.scrapers.{scraper.state.lower()}')
        patches = dict(print=scraper.logger.info)
        restore = dict(print=print)
        if getattr(mod, 'requests', None) is requests:
            patches.update(requests=scraper.session)
            restore.update(requests=requests)
        for name, value in scraper.get_patches().items():
            if hasattr(mod, name):
                patches[name] = value
                restore[name] = getattr(mod, name)
            else:
                scraper.logger.warning(
                    f'warn scraper has no attribute {name}, skipping runner patch')
        if 'utils' not in patches and (wutils := getattr(mod, 'utils', None)):
            patch = PatchUtils(scraper)
            if wutils is patch.delegate:
                patches.update(utils=patch)
                restore.update(utils=wutils)
        for name, value in patches.items():
            scraper.logger.debug(f'Patching {name}')
            setattr(mod, name, value)
        try:
            yield mod
        finally:
            for name, value in restore.items():
                scraper.logger.debug(f'Restoring {name}')
                setattr(mod, name, value)

class PatchUtils:

    def __init__(self, scraper: Scraper) -> None:
        self.scraper = scraper
        self.logger = scraper.logger
        from warn import utils as wutils
        self.delegate = wutils

    def save_if_good_url(self, file: Path, url: str, **kwargs) -> tuple[bool, bytes]:
        file.parent.mkdir(parents=True, exist_ok=True)
        rep: requests.Response = self.get_url(url, check=False, **kwargs)
        if not rep.ok:
            self.logger.error(f'URL {url} fetch failed with {rep.status_code}')
            content = False
        else:
            with file.open('wb') as fp:
                fp.write(rep.content)
                content = rep.content
        return rep.ok, content

    def get_url(self, url: str, user_agent=None, session=None, **kw) -> requests.Response:
        return self.scraper.session.get(url, **kw)

    def __getattr__(self, name: str):
        return self.__dict__.setdefault(name, getattr(self.delegate, name))

class JobCenterSiteProxy:
    """
    Fix weaknesses in warn.platforms.job_center.site.Site
    """
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

    def __init__(self, scraper: Scraper, url: str, stop_year: int) -> None:
        self._clsinit()
        self.scraper = scraper
        self.request_delay = max(0.5, scraper.request_delay)
        self.stop_year = stop_year
        self.delegate = self.BaseSite(
            scraper.state,
            scraper.absurl(url),
            scraper.cache.dir,
            scraper.ssl_verify)
        for name in set(self.delegate.__dict__).difference(self.__dict__):
            setattr(self, name, getattr(self.delegate, name))

    async def run(self) -> None:
        scraper = self.scraper
        no_cache_years, yearly_dates = self._get_datestring_ranges()
        ssl_verify = scraper.ssl_verify
        raw_csv = scraper.cache/f'{scraper.state.lower()}_raw.csv'
        scraper.logger.debug(f'run {ssl_verify=} {yearly_dates=} {no_cache_years=} {raw_csv=}')
        scraper.cache.mkpdir(raw_csv)
        scraper.cache.delete(raw_csv)
        with raw_csv.open('w', newline='') as fp:
            writer = csv.writer(fp)
            writer.writerow(self.headers)
        for item in no_cache_years:
            self._jcutils._scrape_years(
                self, raw_csv, self.headers, [item], use_cache=False, verify=ssl_verify)
            await asyncio.sleep(0)
        for item in yearly_dates:
            self._jcutils._scrape_years(
                self, raw_csv, self.headers, [item], use_cache=True, verify=ssl_verify)
            await asyncio.sleep(0)
        scraper.cache.delete(scraper.runner.file)
        self._jcutils._dedupe(raw_csv, scraper.runner.file)

    def _get_page(self, url: str, params=None, use_cache=True) -> str:
        'Override to check status, use scraper session, add delay, cache record files'
        scraper = self.scraper
        cachekey = self.delegate.cache.key_from_url(url, params)
        use_cache = use_cache or Path(cachekey).parent.name == 'records'
        if use_cache and scraper.cache.exists(cachekey):
            return scraper.cache.read(cachekey)
        if scraper.metrics['request_count']:
            time.sleep(self.request_delay)
        scraper.logger.debug(f'Request {url=}')
        rep = scraper.session.get(url, params=params, verify=scraper.ssl_verify)
        text = rep.text
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

    @classmethod
    def _clsinit(cls):
        if 'BaseSite' in cls.__dict__:
            return
        from warn.platforms.job_center import utils as jcutils
        from warn.platforms.job_center.site import Site as BaseSite
        cls.BaseSite = BaseSite
        cls._jcutils = jcutils
        for name in set(BaseSite.__dict__).difference(cls.__dict__):
            setattr(cls, name, getattr(BaseSite, name))

def hashstat(it: Iterable[Any]) -> dict[str, str|int|None]:
    h = hashlib.sha1()
    geth = None
    size = 0
    for obj in it:
        if isinstance(obj, Path):
            geth = geth or (lambda: h)
            try:
                with obj.open('rb') as file:
                    hashlib.file_digest(file, geth)
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
