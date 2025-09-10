from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from collections import defaultdict
from contextlib import contextmanager
from importlib import import_module
from itertools import chain
from pathlib import Path
from typing import Any, ClassVar, Generator, Iterable, Iterator, Self

import requests
from requests.adapters import HTTPAdapter, Retry
from requests.exceptions import HTTPError
from typing_extensions import Buffer

from .. import Stage, settings, utils
from ..models import ScraperOpts, StateCode
from ..tools import dom, files, strs

__all__ = ['Scraper', 'scrapers']

scrapers: dict[StateCode, type[Scraper]] = {}
'Scraper class registry'

class Scraper:
    'Scraper base class'
    state: ClassVar[StateCode]
    base_url: ClassVar[str|None] = None
    user_agent: ClassVar[str] = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0'
    request_delay: ClassVar[float] = 0.0
    ssl_verify: ClassVar[bool] = True
    retry: ClassVar[dict] = dict(total=3, backoff_factor=2)

    def __init__(self, *, opts: ScraperOpts|dict|None = None):
        self.opts = ScraperOpts.model_validate(opts or {})
        self.runner = Runner(self.state)
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

    async def clean(self) -> None:
        self.cache.delete(
            '*.csv',
            '*.xlsx',
            '*.pdf',
            '*.json',
            '*.html',
            '*/*.html',
            f'../{self.state.lower()}_raw.csv',
            glob=True)

    async def scrape(self) -> None:
        self.runner.scrape()

    async def stat(self) -> dict[str, Any]:
        return hashstat(self.statobjs())

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
        if len(name := cls.__name__.upper()) == 2:
            cls.state = name
            scrapers[cls.state] = cls

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

    def __init__(self, state: StateCode) -> None:
        self.state = state.upper()
        self.logger = utils.get_logger(f'scrapers.{self.state}')
        self.cache_dir = settings.BUILD_DIR/Stage.Scrape
        self.data_dir = self.cache_dir/self.state.lower()
        self.file = self.data_dir/f'{self.state.lower()}.csv'

    def scrape(self) -> None:
        mod = import_module(f'warn.scrapers.{self.state.lower()}')
        mod.scrape(self.data_dir, self.cache_dir)

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
