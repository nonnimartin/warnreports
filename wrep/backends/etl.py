from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import (Any, AsyncGenerator, AsyncIterable, Generic, Iterable,
                    TypeVar)

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.operations import IndexModel

from wrep.models import ReportData

from .. import utils
from ..models import *
from ..translators import Translator

__all__ = [
    'ExtractionBackend',
    'TranslationBackend',
    'IndexBackend',
    'StageBackend',
]

T = TypeVar('T')

logger = utils.get_logger('backends.etl')

class StageBackend:

    state: StateCode

    @abstractmethod
    async def clean(self) -> None: ...

    async def stat(self) -> dict:
        return {}

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[dict[str, Any]]]: ...

class ExtractionBackend(StageBackend, Generic[T]):

    def __init__(self, state: StateCode, dest: T):
        self.state = state.upper()
        self.dest = dest

    @abstractmethod
    async def update(self, source: Iterable[dict[str, str]]) -> int: ...

class TranslationBackend(StageBackend, Generic[T]):

    def __init__(self, state: StateCode, dest: T):
        self.state = state.upper()
        self.dest = dest
    
    @abstractmethod
    async def run(self, translator: Translator, source: AsyncIterable[dict[str, str]]) -> int: ...

class IndexBackend(StageBackend, Generic[T]):

    def __init__(self, state: StateCode, dest: T):
        self.state = state.upper()
        self.dest = dest

    @abstractmethod
    async def update(self, source: Iterable[ReportData]) -> tuple[int, int, int]: ...


__all__ += [
    'MongoExtraction',
    'MongoTranslation',
    'MongoIndex',
]

class MongoMixin(StageBackend):

    dest: AsyncIOMotorCollection
    reader_sort = []
    clean_keys = []
    stat_sort = []

    async def clean(self) -> None:
        await self.dest.delete_many(dict(state=self.state))

    @asynccontextmanager
    async def reader(self, *, order=None):
        it = self.dest.find(dict(state=self.state))
        if order is None:
            order = self.reader_sort
        if order:
            it = it.sort(order)
        yield (self.clean_doc(doc) async for doc in it)

    async def stat(self):
        h = hashlib.sha1()
        order = self.stat_sort or self.reader_sort
        size, count = 0, 0
        async with self.reader(order=order) as reader:
            async for doc in reader:
                buf = json.dumps(doc, default=str).encode()
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

class MongoExtraction(MongoMixin, ExtractionBackend):
    reader_sort = ['_i']
    clean_keys = ['_id', '_i', 'state']

    async def update(self, source):
        await self.clean()
        await self.dest.create_indexes(self.indexes)
        it = utils.CountingIter(source)
        docs = (
            dict(state=self.state, _i=i) | doc
            for i, doc in enumerate(it))
        await self.dest.insert_many(docs, ordered=False)
        return it.count

    indexes = [
        IndexModel({'state': 'hashed'}),
        IndexModel({'_i': 1}),
    ]

class MongoTranslation(MongoMixin, TranslationBackend):
    stat_sort = ['id']
    clean_keys = ['_id', 'row']

    async def run(self, translator, source):
        await self.dest.create_indexes(self.indexes)
        count = 0
        async for row in source:
            count += 1
            entry = translator.entry(row)
            entry.update(state=self.state, row=row)
            await self.dest.replace_one(dict(id=entry['id']), entry, True)
        return count

    indexes = [
        IndexModel({'id': 'hashed'}),
        IndexModel({'id': 1}),
        IndexModel({'state': 'hashed'}),
    ]

class MongoIndex(MongoMixin, IndexBackend):
    stat_sort = ['id']

    async def update(self, source):
        await self.dest.create_indexes(self.indexes)
        count, created, updated = 0, 0, 0
        for report in source:
            filt = dict(_id=report.id)
            res = await self.dest.replace_one(filt, report.as_doc(), True)
            if res.upserted_id:
                created += 1
            elif res.modified_count:
                updated += 1
            count += 1
        return count, created, updated

    indexes = [
        IndexModel({'company': 'text', 'location': 'text'}),
        IndexModel({'reported': 1}),
        IndexModel({'reported': -1}),
        IndexModel({'employees': 1}),
        IndexModel({'employees': -1}),
        IndexModel({'naics.code': 1}),
        IndexModel({'naics.id': 1}),
        IndexModel({'state': 'hashed'}),
    ]
