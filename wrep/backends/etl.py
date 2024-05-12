from __future__ import annotations

import io
import json
import asyncio
from pathlib import Path
from abc import abstractmethod, ABC
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, AsyncIterable, Generator, Generic, Iterable, Iterator, TypeVar

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
logger = utils.get_logger('backends.etl')

class ExtractionBackend(Generic[T]):

    def __init__(self, source: Scraper, dest: T):
        self.state = source.state.upper()
        self.scraper = source
        self.dest = dest

    @abstractmethod
    async def run(self) -> int: ...

    @abstractmethod
    async def clean(self) -> None: ...

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[dict[str, str]]]: ...

class TranslationBackend(Generic[T]):

    def __init__(self, source: ExtractionBackend, dest: T):
        self.state = source.state.upper()
        self.source = source
        self.dest = dest
    
    @abstractmethod
    async def clean(self) -> None: ...

    @abstractmethod
    @asynccontextmanager
    async def runctx(self) -> AsyncGenerator[tuple[AsyncIterable[dict[str, str]], DocWriter]]: ...

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[dict[str, Any]]]: ...

class MongoExtraction(ExtractionBackend[AsyncIOMotorCollection]):

    async def run(self):
        await self.dest.delete_many(dict(state=self.state))
        await self.dest.create_indexes([IndexModel({'state': 'hashed'})])
        with self.scraper.extract() as reader:
            it = utils.CountingIter(reader)
            docs = (dict(state=self.state)|doc for doc in it)
            await self.dest.insert_many(docs, ordered=False)
        return it.count

    async def clean(self) -> None:
        await self.dest.delete_many(dict(state=self.state))

    @asynccontextmanager
    async def reader(self):
        yield (
            self.clean_doc(doc) async for doc in
            self.dest.find(dict(state=self.state)))

    def clean_doc(self, doc: dict):
        doc.pop('_id', None)
        doc.pop('state', None)
        return doc

class DocWriter(ABC):

    @abstractmethod
    async def write(self, doc: dict[str, Any]) -> None: ...

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

    @asynccontextmanager
    async def reader(self):
        with self.dest.open() as file:
            yield LogdictWrapper(file)

class MongoTranslation(TranslationBackend[AsyncIOMotorCollection], DocWriter):

    async def clean(self) -> None:
        await self.dest.delete_many(dict(state=self.state))

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

    async def clean(self) -> None:
        self.dest.unlink(missing_ok=True)

    @asynccontextmanager
    async def runctx(self):
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        async with self.source.reader() as reader:
            with self.dest.open('w') as file:
                yield reader, LogdictWrapper(file)

    @asynccontextmanager
    async def reader(self):
        with self.dest.open() as file:
            yield LogdictWrapper(file)

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
