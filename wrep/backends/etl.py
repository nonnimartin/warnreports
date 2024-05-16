from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import (Any, AsyncGenerator, AsyncIterable, Callable, Iterable,
                    TypeVar)

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.operations import IndexModel

from wrep.models import ReportData, StateDetail

from .. import search, settings, utils
from ..models import *
from ..translators import Translator

__all__ = [
    'ExtractionBackend',
    'MongoExtraction',
    'MongoPipelineLog',
    'MongoSearchIndex',
    'MongoTranslation',
    'PipelineLogBackend',
    'SearchIndexBackend',
    'StageBackend',
    'TranslationBackend',
]

T = TypeVar('T')

logger = utils.get_logger('backends.etl')
mongo_client = AsyncIOMotorClient(settings.ETL_MONGODB_URL, uuidRepresentation='standard')


class PipelineLogBackend:

    @abstractmethod
    async def save(self, runs: Iterable[dict]) -> None: ...

class StageBackend:

    def __init__(self, state: StateCode):
        self.state = state.upper()

    @abstractmethod
    async def clean(self) -> None: ...

    async def stat(self) -> dict:
        return {}

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[dict[str, Any]]]: ...

class ExtractionBackend(StageBackend):

    @abstractmethod
    async def update(self, source: Iterable[dict[str, str]]) -> int: ...

class TranslationBackend(StageBackend):
    
    @abstractmethod
    async def run(self, translator: Translator, source: AsyncIterable[dict[str, str]]) -> int: ...

class SearchIndexBackend(StageBackend):

    @abstractmethod
    async def update_reports(self, source: Iterable[ReportData]) -> tuple[int, int, int]: ...

    @abstractmethod
    async def update_states(self, detail: Iterable[StateDetail]) -> tuple[int, int, int]: ...

    @abstractmethod
    async def update_companies(self, source: Iterable[CompanyDetail]) -> tuple[int, int, int]: ...

    @abstractmethod
    async def update_naics(self, source: Iterable[NaicsDetail]) -> tuple[int, int, int]: ...


class MongoPipelineLog(PipelineLogBackend):

    mongo = mongo_client.get_database(settings.ETL_MONGODB_DBNAME)

    async def save(self, runs):
        coll = self.mongo.pipelines
        await coll.create_indexes(self.indexes)
        await coll.insert_many(runs)

    indexes = [
        IndexModel({'runner_id': 'hashed'}),
        IndexModel({'stage': 'hashed'}),
        IndexModel({'state': 'hashed'}),
        IndexModel({'start': -1}),
    ]

class MongoBackend(StageBackend):
    mongo = mongo_client.get_database(settings.ETL_MONGODB_DBNAME)
    collname: str|None = None
    reader_sort = []
    clean_keys = []
    stat_sort = []

    def getcoll(self, name: str|None = None):
        return self.mongo.get_collection(name or self.collname)
    
    async def clean(self, *, name: str|None = None) -> None:
        await self.getcoll(name).delete_many(dict(state=self.state))

    @asynccontextmanager
    async def reader(self, *, name: str|None = None, order: Any|None = None):
        it = self.getcoll(name).find(dict(state=self.state))
        if order is None:
            order = self.reader_sort
        if order:
            it = it.sort(order)
        yield (self.clean_doc(doc) async for doc in it)

    async def stat(self, *, name: str|None = None, order: Any|None = None):
        order = order or self.stat_sort or self.reader_sort
        async with self.reader(name=name, order=order) as reader:
            return await collstat(reader)

    def clean_doc(self, doc: dict) -> dict:
        for key in self.clean_keys:
            doc.pop(key, None)
        return doc

class MongoExtraction(MongoBackend, ExtractionBackend):
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
        await coll.insert_many(docs)
        return it.count

    indexes = [
        IndexModel({'state': 'hashed'}),
        IndexModel({'_i': 1}),
    ]

class MongoTranslation(MongoBackend, TranslationBackend):
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

class MongoSearchIndex(MongoBackend, SearchIndexBackend):
    mongo = search.mongo
    collname = 'reports'
    stat_sort = ['id']

    async def clean(self) -> None:
        for name in search.search_indexes:
            if name == 'naics':
                coro = self.getcoll(name).drop()
            else:
                coro = super().clean(name=name)
            await coro

    async def update_reports(self, source):
        def get_filter(inst: ReportData):
            return dict(_id=inst.id)
        return await self._update_collection('reports', source, get_filter)

    async def update_states(self, source):
        def get_filter(inst: StateDetail):
            return dict(state=inst.state)
        return await self._update_collection('states', source, get_filter)

    async def update_companies(self, source):
        def get_filter(inst: CompanyDetail):
            return dict(state=inst.state, company=inst.company)
        return await self._update_collection('companies', source, get_filter)

    async def update_naics(self, source):
        def get_filter(inst: NaicsDetail):
            return dict(id=inst.id)
        return await self._update_collection('naics', source, get_filter)

    async def _update_collection(self, name: str, source: Iterable[DM], get_filter: Callable[[DM], dict[str, Any]]) -> tuple[int, int, int]:
        coll = self.getcoll(name)
        indexes = search.search_indexes[name]
        await coll.create_indexes(indexes)
        count, created, updated = 0, 0, 0
        for inst in source:
            filt = get_filter(inst)
            res = await coll.replace_one(filt, inst.as_doc(), True)
            if res.upserted_id:
                created += 1
            elif res.modified_count:
                updated += 1
            count += 1
        return count, created, updated

async def collstat(it: AsyncIterable[dict[str, Any]]):
    h = hashlib.sha1()
    size, count = 0, 0
    async for doc in it:
        buf = json.dumps(doc, default=str).encode()
        h.update(buf)
        size += len(buf)
        count += 1
    return dict(
        hash=h.hexdigest() if count else None,
        size=size,
        count=count)
