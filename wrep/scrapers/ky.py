from __future__ import annotations

import asyncio
import csv
import dataclasses
import json
import uuid
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar, Generator, Iterable, Iterator

from .. import settings, utils
from ..backends import webdrivers
from ..tools import files, strs
from .base import Scraper

__all__ = ['KY']

class KY(Scraper):

    async def scrape(self) -> None:
        self.runner.scrape()
        index = self.load_index()
        if settings.SELENIUM_ENABLED:
            await ArtifactDownloader(self, index).run()
        for key in index.values():
            if self.cache.exists(key):
                self.artifacts.add(key)

    async def clean(self) -> None:
        await super().clean()
        self.cache.delete('download/*', glob=True)

    def statobjs(self) -> Iterator[Any]:
        yield self.runner.file
        yield self.cache/'artifacts.json'

    @contextmanager
    def extract(self) -> Generator[Iterator[dict[str, str]]]:
        index = self.load_index()
        def extend(row: dict) -> dict:
            if (key := index.get(url := row['Notice URL'])):
                if self.cache.exists(key):
                    row.update(artifacts_json=json.dumps({key: url}))
            return row
        with self.runner.file.open() as f:
            yield map(extend, csv.DictReader(f))

    def load_index(self) -> dict[str, str]:
        if self.cache.exists('artifacts.json'):
            return self.cache.read_json('artifacts.json')
        return {}

@dataclasses.dataclass
class ArtifactDownloader:
    scraper: KY
    index: dict[str, str]
    broken_links: ClassVar = {
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005grO4/Vc6tHw.pgfZltA4R7RPb6MS7UY060XBDCzz3WNj9vVg',
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005NnQa/qEmJQv7aNct3EcgWUyr2QdpPW4csItqqtY1R7UFUEoM',
        'https://kydev.my.salesforce.com/sfc/p/#t00000004X3h/a/8y000005NnQa/qEmJQv7aNct3EcgWUyr2QdpPW4csItqqtY1R7UFUEoM',
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/t0000000WdMn/g2M_onZ71eICyV5MHAmrcI9xj.DWop9fES47Qz6TOY0',
        'https://kydev.my.salesforce.com/sfc/p/#t00000004X3h/a/t0000000WdMn/g2M_onZ71eICyV5MHAmrcI9xj.DWop9fES47Qz6TOY0',
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000004t96n/5P7Er8jyZDBXBGs92hEZzvmN8hJRRiUjVC3V9bSY5Z0',
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005Lkhh/16ZxfoY4UYNVp8NSCL2i.Im.Q7k0xxjpNn_725NxzFQ',
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005AaYZ/nOhlGCeHWJakUVLtYFLpq2QXY.WDel0jlYO6gs7mer8',
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005Aajf/_s09zrUsBYJdgPCh.PqdjhGXOuSG1CnCX_R06f6cUpw',
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005Aabo/V_hfVFWEIfnIQH57FqfbR9BdouHsTK6yDVavS3W.yC4',
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000005Aaxr/KwrVbJWv9bt4iW0MMP6gybrw6S28RfEL_VJ2mbxlYXI',
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000004qHeU/0nnBdn1OOgCrcBTm_OtK6KFJkSq1YTPT7tRoYjrnotg',
        'https://kydev.my.salesforce.com/sfc/p/t00000004X3h/a/8y000004aMmU/2LSDXkaovRtmd5nUogcW..Erku6gsF1YNYPlI_KxcHY',
        'https://kydev.my.salesforce.com'}

    @property
    def logger(self) -> utils.logging.Logger:
        return self.scraper.logger

    async def run(self) -> None:
        with self.scraper.runner.file.open() as f:
            todos = deque(self.find_todos(csv.DictReader(f)))
        if todos:
            self.logger.info(f'Found {len(todos)} artifact urls to scrape')
        else:
            self.logger.info(f'No artifact urls to scrape')
            return
        self.scraper.cache.mkdir('records')
        num_workers = min(self.scraper.opts.selenium_max_procs, len(todos))
        self.logger.info(f'Creating {num_workers} selenium workers')
        try:
            async with asyncio.TaskGroup() as group:
                for i in range(num_workers):
                    name = f'worker-{i}'
                    coro = self.start_worker(todos, name)
                    group.create_task(coro, name=name)
        finally:
            self.save_index()

    def find_todos(self, rows: Iterable[dict[str, str]]) -> Iterator[tuple[str, str]]:
        for row in rows:
            url = row['Notice URL']
            recvd = row.get('Date Received')
            if not (url and recvd):
                continue
            if url in self.broken_links:
                self.logger.debug(f'Ignoring {url=}')
                continue
            if url in self.index:
                key = self.index[url]
                if self.scraper.cache.exists(key):
                    self.logger.debug(f'Skipping {key} already exists')
                    continue
            dateid = str(recvd).split()[0]
            urlid = uuid.uuid5(settings.NAMESPACE, url).hex[:6]
            prefix = strs.clean_filename(f'{dateid}-{urlid}')
            yield (url, prefix)

    async def start_worker(self, queue: deque[tuple[str, str]], name: str) -> None:
        cache = self.scraper.cache.subcache(f'download/{name}')
        cache.mkdir()
        prefs = {
            'download.default_directory': cache.path,
            'download.prompt_for_download': False,
            'download.directory_upgrade': True}
        async with webdrivers.selenium(prefs=prefs) as driver:
            helper = WorkerHelper(self, driver, cache)
            while queue:
                url, prefix = queue.popleft()
                cache.delete('*', glob=True)
                await helper.run(url, prefix)
        cache.nuke()

    def save_index(self) -> None:
        self.scraper.cache.write_json('artifacts.json', self.index, indent=2)

    def add_entry(self, url: str, key: str) -> None:
        self.index[url] = key
        self.save_index()

@dataclasses.dataclass
class WorkerHelper:
    downloader: ArtifactDownloader
    driver: webdrivers.Chrome
    cache: files.FileCache

    @property
    def scraper(self) -> KY:
        return self.downloader.scraper

    @property
    def index(self) -> dict[str, str]:
        return self.downloader.index

    @property
    def logger(self) -> utils.logging.Logger:
        return self.downloader.logger

    def find_title(self) -> str:
        return self.get_title(self.driver.page_source)

    def find_fileinfos(self) -> list[webdrivers.WebElement]:
        return self.driver.find_elements('xpath',
            "//*[contains(text(), 'Word document') or "
            "contains(text(), 'Adobe PDF')]")

    def find_buttons(self) -> list[webdrivers.WebElement]:
        return self.driver.find_elements('css selector', 'button.downloadbutton')

    def find_downloads(self) -> list[Path]:
        files = list(self.cache.glob('*'))
        for file in files:
            if file.name.endswith('.crdownload'):
                return []
        return files

    async def run(self, url: str, prefix: str) -> None:
        self.driver.get(url)
        wait = utils.Wait(timeout=10)
        try:
            element = (await wait.until(self.find_fileinfos))[0]
            doc_type = element.get_attribute('innerHTML')
        except TimeoutError:
            self.logger.warning(f'No file info found at {url=}')
            return
        except Exception:
            self.logger.warning(f'Failed to fetch {url=}', exc_info=True)
            return
        wait = utils.Wait(timeout=5)
        try:
            title = await wait.until(self.find_title)
        except TimeoutError:
            if url in self.index:
                key = self.index[key]
                self.logger.warning(f'Using stored key {key} for {url=}')
            else:
                self.logger.warning(f'Skipping empty title for {url=}')
                return
        else:
            # Construct file name
            ext = self.get_extension(doc_type)
            name = strs.clean_filename(f'{prefix}-{title}.{ext}')
            key = f'records/{name}'
            # Save to index
            self.downloader.add_entry(url, key)
        await self.download(url, key)

    async def download(self, url: str, key: str) -> None:
        dest = self.scraper.cache/key
        if dest.exists():
            self.logger.debug(f'Skipping download {key} already downloaded')
            return
        wait = utils.Wait(timeout=5)
        try:
            button = (await wait.until(self.find_buttons))[0]
        except TimeoutError:
            self.logger.warning(f'No download button found for {key} {url=}')
            return
        self.logger.info(f'Clicking download button for {key}')
        wait = utils.Wait(timeout=5, ignored=[Exception], oper=id)
        try:
            await wait.until(button.click)
        except TimeoutError:
            self.logger.warning(f'Click to download failed for {url=}', exc_info=True)
            return
        wait = utils.Wait(timeout=10)
        try:
            downloads = await wait.until(self.find_downloads)
        except TimeoutError:
            self.logger.warning(f'Downloads did not complete for {key} {url=}')
            return
        if len(downloads) > 1:
            self.logger.warning(f'Multiple downloads found for {url=} {downloads}')
            return
        self.logger.info(f'Moving download to {key}')
        downloads.pop().rename(dest)

    @staticmethod
    def get_title(text: str) -> str:
        start_str = 'Page 1 of '
        start_index = text.find(start_str)
        if start_index == -1:
            return ''
        start_index += len(start_str)
        end_index = text.find('"', start_index)
        if end_index == -1:
            return ''
        filename = text[start_index:end_index].split(', ')[1]
        return filename

    @staticmethod
    def get_extension(file_type: str) -> str:
        if file_type == 'Adobe PDF':
            return 'pdf'
        return 'docx'
