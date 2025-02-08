from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, AsyncIterable, Callable

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.operations import IndexModel

from .. import search, settings, utils
from ..models import *
from ..utils import EitherIterable
from .mongo import MongoClient

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

client = MongoClient(
    url=settings.ETL_MONGODB_URL,
    control_dbname=settings.ETL_MONGODB_CONTROL_DBNAME,
    dbname_key='etl.dbname',
    dbname_ttl=settings.ETL_MONGODB_DBNAME_TTL,
    dbname_default=settings.ETL_MONGODB_DBNAME)

class ReaderMixin:

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[Doc]]: ...

class PipelineLogBackend:

    @abstractmethod
    async def save(self, doc: Doc) -> None: ...

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

    def __init__(self, **context):
        self.context = context
        self._indexes_created = False

    async def save(self, doc):
        db = await client.get_database(self.context.get('dbname'))
        coll = db.pipelinelogs
        if not self._indexes_created:
            await coll.create_indexes(self.indexes)
            self._indexes_created = True
        doc['_id'] = doc.pop('id')
        res = await coll.replace_one({'_id': doc['_id']}, doc, True)

    indexes = [
        IndexModel({'stages': 1}),
        IndexModel({'states': 1}),
        IndexModel({'start': -1}),
        IndexModel({'end': -1}),
        IndexModel({'elapsed': -1}),
    ]

class MongoETBase(StageBackend):
    'Common base class for MongoExraction & MongoTranslation'
    collection_name: str
    ordering = []
    clean_keys = []
    stat_clean_keys = []

    _db = None

    async def collection(self):
        if self._db is None:
            self._db = await client.get_database(self.context.get('dbname'))
        return self._db.get_collection(self.collection_name)

    async def clean(self) -> None:
        filt = self.get_filter()
        coll = await self.collection()
        res = await coll.delete_many(filt)
        logger.debug(f'{filt=} {res=}')

    @asynccontextmanager
    async def reader(self):
        coll = await self.collection()
        it = coll.find(self.get_filter()).sort(self.ordering)
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
        coll = await self.collection()
        await coll.create_indexes(self.indexes)
        it = utils.aenumerate(source)
        it = (dict(state=self.state, _i=i) | doc async for i, doc in it)
        return await update_collection(coll, it, self.get_replace_filter)

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
        coll = await self.collection()
        await coll.create_indexes(self.indexes)
        return await update_collection(coll, source, self.get_replace_filter)

    def get_replace_filter(self, entry: Doc) -> Doc:
        return {'$or': [{'id': entry['id']}, {'values_id': entry['values_id']}]}

    indexes = [
        IndexModel({'id': 1}),
        IndexModel({'values_id': 1}),
        IndexModel({'state': 1}),
    ]

class MongoSearchIndex(SearchIndexBackend):
    collections = search.collection_defns

    _db = None

    async def db(self):
        if self._db is None:
            self._db = await client.get_database(self.context.get('dbname'))
        return self._db

    async def clean(self) -> None:
        db = await self.db()
        for name in self.collections:
            coll = db.get_collection(name)
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
        it = (await self.db()).reports.find(dict(state=self.state)).sort('id')
        return await docs_stat(it)

    async def update(self, name, source):
        coll = (await self.db()).get_collection(name)
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

async def docs_stat(it: EitherIterable[Doc]) -> Doc:
    h = hashlib.sha1()
    size, count = 0, 0
    async for doc in utils.as_aiter(it):
        buf = json.dumps(doc, default=str).encode()
        h.update(buf)
        size += len(buf)
        count += 1
    return dict(
        hash=h.hexdigest() if count else None,
        size=size,
        count=count)
