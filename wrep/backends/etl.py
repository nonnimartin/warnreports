from __future__ import annotations

import hashlib
import io
import json
from abc import abstractmethod
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

class DocWriter(Generic[T]):

    @abstractmethod
    async def write(self, doc: dict[str, T]) -> None: ...

class BackendMixin(Generic[T, S]):
    
    def __init__(self, source: S, dest: T):
        self.state = source.state.upper()
        self.source = source
        self.dest = dest

    @abstractmethod
    async def clean(self) -> None: ...

    async def stat(self) -> dict:
        return {}

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[dict[str, T]]]: ...

class ExtractionBackend(BackendMixin[T, Scraper]):

    @abstractmethod
    async def run(self) -> int: ...

class TranslationBackend(BackendMixin[T, ExtractionBackend]):
    
    @abstractmethod
    @asynccontextmanager
    async def runctx(self) -> AsyncGenerator[tuple[AsyncIterable[dict[str, str]], DocWriter[Any]]]: ...

class MongoMixin(BackendMixin[AsyncIOMotorCollection, S]):
    reader_sort = []
    clean_keys = []
    stat_sort = []

    async def clean(self) -> None:
        await self.dest.delete_many(dict(state=self.state))

    @asynccontextmanager
    async def reader(self):
        it = self.dest.find(dict(state=self.state))
        if self.reader_sort:
            it = it.sort(*self.reader_sort)
        yield (self.clean_doc(doc) async for doc in it)

    async def stat(self):
        h = hashlib.sha1()
        size, count = 0, 0
        filt = dict(state=self.state)
        it = self.dest.find(filt)
        if self.stat_sort:
            it = it.sort(*self.stat_sort)
        async for doc in it:
            buf = json.dumps(self.clean_doc(doc), default=str).encode()
            h.update(buf)
            size += len(buf)
            count += 1
        return dict(
            hash=h.hexdigest() if count else None,
            size=size,
            count=count)

    def clean_doc(self, doc: dict) -> dict:
        for key in self.clean_keys:
            doc.pop(key, None)
        return doc

class MongoExtraction(MongoMixin[Scraper], ExtractionBackend[AsyncIOMotorCollection]):
    reader_sort = ['_i']
    clean_keys = ['_id', '_i', 'state']

    async def run(self):
        await self.dest.delete_many(dict(state=self.state))
        await self.dest.create_indexes([
            IndexModel({'state': 'hashed'}),
            IndexModel({'_i': 1})])
        with self.source.extract() as reader:
            it = utils.CountingIter(reader)
            docs = (dict(state=self.state, _i=i)|doc for i, doc in enumerate(it))
            await self.dest.insert_many(docs, ordered=False)
        return it.count

class MongoTranslation(MongoMixin[ExtractionBackend], TranslationBackend[AsyncIOMotorCollection], DocWriter):
    stat_sort = ['id']
    clean_keys = ['_id', 'row']

    async def write(self, entry: dict[str, Any]):
        await self.dest.replace_one(dict(id=entry['id']), entry, True)

    @asynccontextmanager
    async def runctx(self):
        await self.dest.create_indexes([
            IndexModel({'id': 'hashed'}),
            IndexModel({'id': 1}),
            IndexModel({'state': 'hashed'})])
        async with self.source.reader() as reader:
            yield reader, self

class FileMixin(BackendMixin[Path, S]):

    async def clean(self) -> None:
        self.dest.unlink(missing_ok=True)

    async def stat(self):
        file = self.dest
        return dict(
            hash=utils.hashfile(file, missing_ok=True),
            size=file.stat().st_size if file.exists() else 0)

    @asynccontextmanager
    async def reader(self):
        with self.dest.open() as file:
            yield LogdictWrapper(file)

class FileExtraction(FileMixin[Scraper], ExtractionBackend[Path]):

    async def run(self):
        with self.source.extract() as reader:
            it = utils.CountingIter(reader)
            self.dest.parent.mkdir(parents=True, exist_ok=True)
            with self.dest.open('w') as file:
                writer = LogdictWrapper(file)
                for record in it:
                    await writer.write(record)
        return it.count

class FileTranslation(FileMixin[ExtractionBackend], TranslationBackend[Path]):

    @asynccontextmanager
    async def runctx(self):
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        async with self.source.reader() as reader:
            with self.dest.open('w') as file:
                yield reader, LogdictWrapper(file)

class LogdictWrapper(DocWriter[T]):

    def __init__(self, file: io.TextIOWrapper):
        self.file = file

    def __iter__(self) -> Iterator[dict[str, T]]:
        while True:
            line = self.file.readline()
            if not line:
                break
            yield json.loads(line)

    async def __aiter__(self):
        for x in self:
            yield x

    async def write(self, entry: dict[str, T]):
        json.dump(entry, self.file, default=utils.json_default)
        self.file.write('\n')
