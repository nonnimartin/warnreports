from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, AsyncIterable, Callable, Iterable

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
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

logger = utils.get_logger('backends.etl')
mongo_client = AsyncIOMotorClient(settings.ETL_MONGODB_URL, uuidRepresentation='standard')

class ReaderMixin:

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[dict[str, Any]]]: ...

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

class ExtractionBackend(StageBackend, ReaderMixin):

    @abstractmethod
    async def update(self, source: Iterable[dict[str, str]]) -> int: ...

class TranslationBackend(StageBackend, ReaderMixin):
    
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
        IndexModel({'runner.id': 'hashed'}),
        IndexModel({'jobseq': 1}),
        IndexModel({'stage': 'hashed'}),
        IndexModel({'state': 'hashed'}),
        IndexModel({'start': -1}),
        IndexModel({'elapsed': -1}),
    ]

class MongoETBase(StageBackend):
    mongo = mongo_client.get_database(settings.ETL_MONGODB_DBNAME)
    collection_name: str
    ordering = []
    clean_keys = []

    @property
    def collection(self):
        return self.mongo.get_collection(self.collection_name)

    async def clean(self) -> None:
        await self.collection.delete_many(self.get_filter())

    @asynccontextmanager
    async def reader(self):
        it = self.collection.find(self.get_filter()).sort(self.ordering)
        yield (self.clean_doc(doc) async for doc in it)

    async def stat(self):
        async with self.reader() as reader:
            return await docs_stat(reader)

    def get_filter(self) -> dict[str, Any]:
        return {}

    def clean_doc(self, doc: dict) -> dict:
        for key in self.clean_keys:
            doc.pop(key, None)
        return doc

    def get_filter(self) -> dict[str, Any]:
        return dict(state=self.state)

class MongoExtraction(MongoETBase, ExtractionBackend):
    collection_name = 'extractions'
    ordering = ['_i']
    clean_keys = ['_id', '_i', 'state']

    async def update(self, source):
        await self.clean()
        await self.collection.create_indexes(self.indexes)
        it = utils.CountingIter(source)
        docs = (
            dict(state=self.state, _i=i) | doc
            for i, doc in enumerate(it))
        await self.collection.insert_many(docs)
        return it.count

    indexes = [
        IndexModel({'state': 'hashed'}),
        IndexModel({'_i': 1}),
    ]

class MongoTranslation(MongoETBase, TranslationBackend):
    collection_name = 'translations'
    ordering = ['id']
    clean_keys = ['_id', 'row']

    async def run(self, translator, source):
        await self.collection.create_indexes(self.indexes)
        count = 0
        async for row in source:
            count += 1
            entry = translator.entry(row)
            entry.update(state=self.state, row=row)
            await self.collection.replace_one(dict(id=entry['id']), entry, True)
        return count

    indexes = [
        IndexModel({'id': 'hashed'}),
        IndexModel({'id': 1}),
        IndexModel({'state': 'hashed'}),
    ]

class MongoSearchIndex(SearchIndexBackend):
    mongo = search.mongo

    async def clean(self) -> None:
        for name in search.search_indexes:
            coll = self.mongo.get_collection(name)
            if name == 'naics':
                coro = coll.drop()
            else:
                coro = coll.delete_many(dict(state=self.state))
            await coro

    async def stat(self):
        it = self.mongo.reports.find(dict(state=self.state)).sort('id')
        return await docs_stat(it)

    async def update_reports(self, source):
        def get_filter(inst: ReportData):
            return dict(_id=inst.id)
        return await self.update_collection('reports', source, get_filter)

    async def update_states(self, source):
        def get_filter(inst: StateDetail):
            return dict(state=inst.state)
        return await self.update_collection('states', source, get_filter)

    async def update_companies(self, source):
        def get_filter(inst: CompanyDetail):
            return dict(state=inst.state, company=inst.company)
        return await self.update_collection('companies', source, get_filter)

    async def update_naics(self, source):
        def get_filter(inst: NaicsDetail):
            return dict(id=inst.id)
        return await self.update_collection('naics', source, get_filter)

    async def update_collection(self, name: str, source: Iterable[DM], get_filter: Callable[[DM], dict[str, Any]]) -> tuple[int, int, int]:
        coll = self.mongo.get_collection(name)
        indexes = search.search_indexes[name]
        await coll.create_indexes(indexes)
        return await update_collection(coll, source, get_filter)

async def update_collection(coll: AsyncIOMotorCollection, source: Iterable[DM], get_filter: Callable[[DM], dict[str, Any]]) -> tuple[int, int, int]:
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

async def docs_stat(it: AsyncIterable[dict[str, Any]]):
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
