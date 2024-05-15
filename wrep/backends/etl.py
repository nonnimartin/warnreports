from __future__ import annotations

import asyncio
import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import (Any, AsyncGenerator, AsyncIterable, Generic, Iterable,
                    TypeVar)

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.operations import IndexModel

from wrep.models import ReportData, StateDetail

from .. import search, utils
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
    async def update_reports(self, source: Iterable[ReportData]) -> tuple[int, int, int]: ...

    @abstractmethod
    async def update_states(self, detail: StateDetail) -> None: ...

    @abstractmethod
    async def update_companies(self, source: Iterable[CompanyDetail]) -> tuple[int, int, int]: ...

    @abstractmethod
    async def update_naics(self, source: Iterable[NaicsDetail]) -> tuple[int, int, int]: ...

__all__ += [
    'MongoExtraction',
    'MongoTranslation',
    'MongoSearchIndex',
]

class MongoMixin(StageBackend):

    dest: AsyncIOMotorDatabase
    reader_sort = []
    clean_keys = []
    stat_sort = []
    collname: str

    def getcoll(self, name: str|None = None):
        return self.dest.get_collection(name or self.collname)
    
    async def clean(self) -> None:
        await self.getcoll().delete_many(dict(state=self.state))

    @asynccontextmanager
    async def reader(self, *, order=None):
        it = self.getcoll().find(dict(state=self.state))
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

class MongoExtraction(MongoMixin, ExtractionBackend[AsyncIOMotorDatabase]):
    collname = 'extractions'
    reader_sort = ['_i']
    clean_keys = ['_id', '_i', 'state']

    async def update(self, source):
        coll = self.getcoll()
        await self.clean()
        await coll.create_indexes(self.indexes)
        it = utils.CountingIter(source)
        docs = (
            dict(state=self.state, _i=i) | doc
            for i, doc in enumerate(it))
        await coll.insert_many(docs, ordered=False)
        return it.count

    indexes = [
        IndexModel({'state': 'hashed'}),
        IndexModel({'_i': 1}),
    ]

class MongoTranslation(MongoMixin, TranslationBackend[AsyncIOMotorDatabase]):
    collname = 'translations'
    stat_sort = ['id']
    clean_keys = ['_id', 'row']

    async def run(self, translator, source):
        coll = self.getcoll()
        await coll.create_indexes(self.indexes)
        count = 0
        async for row in source:
            count += 1
            entry = translator.entry(row)
            entry.update(state=self.state, row=row)
            await coll.replace_one(dict(id=entry['id']), entry, True)
        return count

    indexes = [
        IndexModel({'id': 'hashed'}),
        IndexModel({'id': 1}),
        IndexModel({'state': 'hashed'}),
    ]

class MongoSearchIndex(MongoMixin, IndexBackend[AsyncIOMotorDatabase]):
    stat_sort = ['id']
    collname = 'reports'

    async def clean(self) -> None:
        filt = dict(state=self.state)
        for name in search.search_indexes:
            coll = self.getcoll(name)
            if name == 'naics':
                coro = coll.drop()
            else:
                coro = coll.delete_many(filt)
            await coro

    async def update_reports(self, source):
        coll = self.getcoll('reports')
        await coll.create_indexes(search.search_indexes['reports'])
        count, created, updated = 0, 0, 0
        for report in source:
            filt = dict(_id=report.id)
            res = await coll.replace_one(filt, report.as_doc(), True)
            if res.upserted_id:
                created += 1
            elif res.modified_count:
                updated += 1
            count += 1
        return count, created, updated

    async def update_states(self, detail: StateDetail) -> None:
        coll = self.getcoll('states')
        await coll.create_indexes(search.search_indexes['states'])
        filt = dict(state=self.state)
        await coll.replace_one(filt, detail.as_doc(), True)

    async def update_companies(self, source):
        coll = self.getcoll('companies')
        await coll.create_indexes(search.search_indexes['companies'])
        count, created, updated = 0, 0, 0
        for company in source:
            filt = dict(state=self.state, company=company.company)
            res = await coll.replace_one(filt, company.as_doc(), True)
            if res.upserted_id:
                created += 1
            elif res.modified_count:
                updated += 1
            count += 1
        return count, created, updated

    async def update_naics(self, source):
        coll = self.getcoll('naics')
        await coll.create_indexes(search.search_indexes['naics'])
        count, created, updated = 0, 0, 0
        for naics in source:
            filt = dict(id=naics.id)
            res = await coll.replace_one(filt, naics.as_doc(), True)
            if res.upserted_id:
                created += 1
            elif res.modified_count:
                updated += 1
            count += 1
        return count, created, updated

