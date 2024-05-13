from __future__ import annotations

import asyncio
import io
import json
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pathlib import Path
from typing import (Any, AsyncGenerator, AsyncIterable, Generic, Iterator,
                    TypeVar)

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.operations import IndexModel

from .. import utils
from ..scrapers import Scraper

__all__ = [
    'ExtractionBackend',
    'FileExtraction',
    'FileTranslation',
    'MongoExtraction',
    'MongoTranslation',
    'TranslationBackend']

T = TypeVar('T')
S = TypeVar('S', bound='Scraper|ExtractionBackend')

logger = utils.get_logger('backends.etl')

class DocWriter(ABC):

    @abstractmethod
    async def write(self, doc: dict[str, Any]) -> None: ...

class BackendMixin(Generic[T, S]):
    
    def __init__(self, source: S, dest: T):
        self.state = source.state.upper()
        self.scraper = source
        self.dest = dest

    @abstractmethod
    async def clean(self) -> None: ...

    async def stat(self) -> dict:
        return {}

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[dict[str, T]]]: ...

class ExtractionBackend(BackendMixin[str, Scraper], Generic[T]):

    def __init__(self, source: Scraper, dest: T):
        self.state = source.state.upper()
        self.scraper = source
        self.dest = dest

    @abstractmethod
    async def run(self) -> int: ...

class TranslationBackend(BackendMixin[Any, ExtractionBackend], Generic[T]):

    def __init__(self, source: ExtractionBackend, dest: T):
        self.state = source.state.upper()
        self.source = source
        self.dest = dest
    
    @abstractmethod
    @asynccontextmanager
    async def runctx(self) -> AsyncGenerator[tuple[AsyncIterable[dict[str, str]], DocWriter]]: ...

class MongoExtraction(ExtractionBackend[AsyncIOMotorCollection]):

    async def run(self):
        await self.dest.delete_many(dict(state=self.state))
        await self.dest.create_indexes([
            IndexModel({'state': 'hashed'}),
            IndexModel({'_i': 1})])
        with self.scraper.extract() as reader:
            it = utils.CountingIter(reader)
            docs = (dict(state=self.state, _i=i)|doc for i, doc in enumerate(it))
            await self.dest.insert_many(docs, ordered=False)
        return it.count

    async def clean(self) -> None:
        await self.dest.delete_many(dict(state=self.state))

    @asynccontextmanager
    async def reader(self):
        yield (
            self.clean_doc(doc) async for doc in
            self.dest.find(dict(state=self.state)).sort('_i'))

    def clean_doc(self, doc: dict):
        doc.pop('_i', None)
        doc.pop('_id', None)
        doc.pop('state', None)
        return doc

class FileExtraction(ExtractionBackend[Path]):

    async def run(self):
        with self.scraper.extract() as reader:
            it = utils.CountingIter(reader)
            self.dest.parent.mkdir(parents=True, exist_ok=True)
            with self.dest.open('w') as file:
                writer = LogdictWrapper(file)
                for record in it:
                    await writer.write(record)
        return it.count

    async def clean(self) -> None:
        self.dest.unlink(missing_ok=True)

    async def stat(self):
        files = [self.dest]
        return dict(
            hash=utils.hashfiles(files, missing_ok=True),
            size=sum(file.stat().st_size for file in files))

    @asynccontextmanager
    async def reader(self):
        with self.dest.open() as file:
            yield LogdictWrapper(file)

class MongoTranslation(TranslationBackend[AsyncIOMotorCollection], DocWriter):

    clean = MongoExtraction.clean

    async def write(self, entry: dict[str, Any]):
        await self.dest.replace_one(dict(id=entry['id']), entry, True)

    @asynccontextmanager
    async def runctx(self):
        await self.dest.create_indexes([
            IndexModel({'id': 'hashed'}),
            IndexModel({'state': 'hashed'})])
        async with self.source.reader() as reader:
            yield reader, self

    @asynccontextmanager
    async def reader(self):
        yield self.dest.find(dict(state=self.state))

class FileTranslation(TranslationBackend[Path]):

    clean = FileExtraction.clean
    reader = FileExtraction.reader
    stat = FileExtraction.stat

    @asynccontextmanager
    async def runctx(self):
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        async with self.source.reader() as reader:
            with self.dest.open('w') as file:
                yield reader, LogdictWrapper(file)

class LogdictWrapper(DocWriter):

    def __init__(self, file: io.TextIOWrapper):
        self.file = file

    def __iter__(self) -> Iterator[dict[str, Any]]:
        while True:
            line = self.file.readline()
            if not line:
                break
            yield json.loads(line)

    __aiter__ = utils.as_aiter

    async def write(self, entry: dict[str, Any]):
        json.dump(entry, self.file, default=utils.json_default)
        self.file.write('\n')
