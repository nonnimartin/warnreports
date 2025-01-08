from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, AsyncIterable, Callable, Iterable

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.operations import IndexModel

from .. import search, settings, utils
from ..models import *
from ..utils import EitherIterable

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

type Doc = dict[str, Any]
logger = utils.get_logger('backends.etl')
mongo_client = AsyncIOMotorClient(settings.ETL_MONGODB_URL, uuidRepresentation='standard')

class ReaderMixin:

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[Doc]]: ...

class PipelineLogBackend:

    @abstractmethod
    async def save(self, runs: Iterable[dict]) -> None: ...

class StageBackend:

    def __init__(self, state: StateCode, **context):
        self.state = state.upper()
        self.context = context

    @abstractmethod
    async def clean(self) -> None: ...

    async def stat(self) -> dict:
        return {}

class ExtractionBackend(StageBackend, ReaderMixin):

    @abstractmethod
    async def update(self, source: EitherIterable[Doc]) -> tuple[int, int, int]: ...

class TranslationBackend(StageBackend, ReaderMixin):

    @abstractmethod
    async def update(self, source: EitherIterable[Doc]) -> tuple[int, int, int]: ...

class SearchIndexBackend(StageBackend):

    @abstractmethod
    async def update(self, name: str, source: EitherIterable[DataModel]) -> tuple[int, int, int]: ...

class MongoPipelineLog(PipelineLogBackend):
    mongo = mongo_client.get_database(settings.ETL_MONGODB_DBNAME)

    async def save(self, runs):
        coll = self.mongo.pipelines
        await coll.create_indexes(self.indexes)
        await coll.insert_many(runs)

    indexes = [
        IndexModel({'runner.id': 1}),
        IndexModel({'jobseq': 1}),
        IndexModel({'stage': 1}),
        IndexModel({'state': 1}),
        IndexModel({'start': -1}),
        IndexModel({'elapsed': -1}),
    ]

class MongoETBase(StageBackend):
    'Common base class for MongoExraction & MongoTranslation'
    mongo = mongo_client.get_database(settings.ETL_MONGODB_DBNAME)
    collection_name: str
    ordering = []
    clean_keys = []
    stat_clean_keys = []

    @property
    def collection(self):
        return self.mongo.get_collection(self.collection_name)

    async def clean(self) -> None:
        filt = self.get_filter()
        res = await self.collection.delete_many(filt)
        logger.debug(f'{filt=} {res=}')

    @asynccontextmanager
    async def reader(self):
        it = self.collection.find(self.get_filter()).sort(self.ordering)
        yield utils.amap(self.clean_doc, it)

    async def stat(self):
        async with self.reader() as reader:
            it = utils.amap(self.clean_stat_doc, reader)
            return await docs_stat(it)

    def clean_doc(self, doc: Doc) -> Doc:
        for key in self.clean_keys:
            doc.pop(key, None)
        return doc

    def clean_stat_doc(self, doc: Doc) -> Doc:
        for key in self.stat_clean_keys:
            doc.pop(key, None)
        return doc

    def get_filter(self) -> Doc:
        return dict(state=self.state)

class MongoExtraction(MongoETBase, ExtractionBackend):
    collection_name = 'extractions'
    ordering = ['_i']
    clean_keys = ['_id', '_i', 'state']
    stat_clean_keys = ['scrape_time']

    async def update(self, source):
        await self.clean()
        await self.collection.create_indexes(self.indexes)
        it = utils.aenumerate(source)
        it = (dict(state=self.state, _i=i) | doc async for i, doc in it)
        return await update_collection(self.collection, it, self.get_replace_filter)

    def get_replace_filter(self, doc: Doc) -> Doc:
        return dict(_i=doc['_i'], state=self.state)

    indexes = [
        IndexModel({'state': 1}),
        IndexModel({'_i': 1}),
    ]

class MongoTranslation(MongoETBase, TranslationBackend):
    collection_name = 'translations'
    ordering = ['id']
    clean_keys = ['_id', 'row']

    async def update(self, source):
        await self.collection.create_indexes(self.indexes)
        return await update_collection(self.collection, source, self.get_replace_filter)

    def get_replace_filter(self, entry: Doc) -> Doc:
        return {'$or': [{'id': entry['id']}, {'values_id': entry['values_id']}]}

    indexes = [
        IndexModel({'id': 1}),
        IndexModel({'values_id': 1}),
        IndexModel({'state': 1}),
    ]

class MongoSearchIndex(SearchIndexBackend):
    mongo = search.mongo
    collections = search.collections

    async def clean(self) -> None:
        for name in self.collections:
            coll = self.mongo.get_collection(name)
            if name == 'naics':
                coro = coll.drop()
            elif name == 'artifacts':
                coro = coll.delete_many(dict(path={'$regex': f'^{self.state.lower()}/'}))
            elif name == 'companies':
                coro = coll.delete_many({
                    '$and': [
                        {'states': self.state},
                        {'states': {'$size': 1}}]})
            elif name == 'states':
                coro = coll.delete_one(dict(id=self.state))
            else:
                coro = coll.delete_many(dict(state=self.state))
            await coro

    async def stat(self):
        it = self.mongo.reports.find(dict(state=self.state)).sort('id')
        return await docs_stat(it)

    async def update(self, name, source):
        coll = self.mongo.get_collection(name)
        await coll.create_indexes(self.collections[name].indexes)
        it = (inst.as_doc() async for inst in utils.as_aiter(source))
        key = 'id' if name in ('states', 'naics') else '_id'
        return await update_collection(coll, it, lambda doc: {key: doc[key]})

async def update_collection(coll: AsyncIOMotorCollection, it: EitherIterable[Doc], get_filter: Callable[[Doc], Doc]) -> tuple[int, int, int]:
    count, created, updated = 0, 0, 0
    async for doc in utils.as_aiter(it):
        filt = get_filter(doc)
        if '_id' not in filt:
            old = await coll.find_one(filt)
            if old:
                idfilt = dict(_id=old['_id'])
                filt |= idfilt
                doc = idfilt|doc
        res = await coll.replace_one(filt, doc, True)
        if res.upserted_id:
            created += 1
        elif res.modified_count:
            updated += 1
        count += 1
    return count, created, updated

async def docs_stat(it: AsyncIterable[Doc]) -> Doc:
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
