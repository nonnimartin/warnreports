from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import (Any, AsyncGenerator, AsyncIterable, Callable, ClassVar,
                    Mapping)
from uuid import UUID, uuid5

from motor.motor_asyncio import AsyncIOMotorCollection

from .. import Stage, search, settings, utils
from ..models import *
from ..utils import EitherIterable
from .mongo import (AbstractMongoCollection, MongoClient, MongoCollection,
                    MongoQueryFilter, Search, filters)

__all__ = [
    'ExtractionBackend',
    'PipelineLogBackend',
    'SearchIndexBackend',
    'StageBackend',
    'TranslationBackend']

type Doc = dict[str, Any]
logger = utils.get_logger('backends.etl')
client = MongoClient(
    url=settings.ETL_MONGODB_URL,
    control_dbname=settings.ETL_MONGODB_CONTROL_DBNAME,
    dbname_key='etl.dbname',
    dbname_ttl=settings.ETL_MONGODB_DBNAME_TTL,
    dbname_default=settings.ETL_MONGODB_DBNAME)

collections: dict[str, MongoCollection] = dict(
    extractions=MongoCollection(
        client=client,
        name='extractions',
        indexes=[
            {'state': 1},
            {'_i': 1}]),
    translations=MongoCollection(
        client=client,
        name='translations',
        indexes=[
            {'id': 1},
            {'values_id': 1},
            {'state': 1}]),
    pipelinelogs=MongoCollection(
        client=client,
        name='pipelinelogs',
        data_model=PipelineLog,
        indexes=[
            {'stages': 1},
            {'states': 1},
            {'start': -1},
            {'end': -1},
            {'elapsed': -1}]))

class ReaderMixin:

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[Doc]]: ...

class ContextMixin:

    def __init__(self, context: Doc|None = None) -> None:
        if context is None:
            context = {}
        self.context = context

class PipelineLogBackend(ContextMixin):
    registry: ClassVar[dict[str, type[PipelineLogBackend]]] = {}
    engine: ClassVar[str]

    @abstractmethod
    async def save(self, log: PipelineLog) -> None: ...

    @abstractmethod
    async def fetch(self, id: UUID) -> PipelineLog: ...

    @abstractmethod
    async def fetch_latest(self) -> PipelineLog: ...

    @abstractmethod
    async def findall(self, limit: Limit|None = None, offset: Offset = 0) -> AsyncIterable[PipelineLog]: ...

    @abstractmethod
    async def update(self, source: EitherIterable[PipelineLog]) -> tuple[int, int, int]: ...

    @abstractmethod
    async def prune(self, maxage: utils.Delta) -> int: ...

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if hasattr(cls, 'engine'):
            cls.registry[cls.engine] = cls

class StageBackend(ContextMixin):
    registry: ClassVar[dict[str, dict[Stage, type[StageBackend]]]] = {}
    stage: ClassVar[Stage]
    engine: ClassVar[str]

    def __init__(self, state: StateCode, context: Doc|None = None) -> None:
        super().__init__(context)
        self.state = state.upper()

    @abstractmethod
    async def clean(self) -> None: ...

    async def stat(self) -> dict:
        return {}

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if hasattr(cls, 'engine') and hasattr(cls, 'stage'):
            cls.registry.setdefault(cls.engine, {})[cls.stage] = cls

class ExtractionBackend(StageBackend, ReaderMixin):
    stage = Stage.Extract

    @abstractmethod
    async def update(self, source: EitherIterable[Doc]) -> tuple[int, int, int]: ...

class TranslationBackend(StageBackend, ReaderMixin):
    stage = Stage.Translate

    @abstractmethod
    async def update(self, source: EitherIterable[Doc]) -> tuple[int, int, int]: ...

class SearchIndexBackend(StageBackend):
    stage = Stage.Index
    collections: ClassVar[Mapping[str, search.AbstractMappedCollection]]

    @abstractmethod
    async def update(self, name: str, source: EitherIterable[DataModel]) -> tuple[int, int, int]: ...

class MongoContextMixin(ContextMixin):
    engine = 'mongo'
    client: ClassVar[MongoClient]
    _db = None

    async def db(self):
        if self._db is None:
            self._db = await self.client.get_database(self.context.get(self.client.dbname_key))
            self.context[self.client.dbname_key] = self._db.name
        return self._db

class MongoContextCollectionMixin[DM: DataModel](MongoContextMixin):
    collection: ClassVar[MongoCollection]
    _coll = None
    _indexes_created = False

    @property
    def model(self) -> type[DM]|None:
        return self.collection.data_model

    @property
    def client(self) -> MongoClient:
        return self.collection.client

    async def get_collection(self):
        if self._coll is None:
            self._coll = (await self.db()).get_collection(self.collection.name)
        return self._coll

    async def create_indexes(self) -> None:
        if not self._indexes_created:
            coll = await self.get_collection()
            await coll.create_indexes(self.collection.indexes)
            self._indexes_created = True

class MongoPipelineLog(PipelineLogBackend, MongoContextCollectionMixin[PipelineLog]):
    collection = collections['pipelinelogs']

    async def save(self, log):
        doc = log.as_doc()
        await self.create_indexes()
        coll = await self.get_collection()
        res = await coll.replace_one({'_id': doc['_id']}, doc, True)

    async def fetch(self, id):
        filter: FilterModel[PipelineLog] = filters[self.model](q={'_id': id})
        db = await self.db()
        res = Search(filter, 1, dbname=db.name)
        if await res.count():
            return await anext(res.objs())
        raise ValueError(f'Not found {id=}')

    async def fetch_latest(self):
        async for log in await self.findall(limit=1):
            return log
        raise ValueError(f'No entries found')

    async def findall(self, limit: Limit|None = None, offset: Offset = 0):
        filter: FilterModel[PipelineLog] = filters[self.model]()
        db = await self.db()
        res = Search(filter, limit=limit, offset=offset, dbname=db.name)
        return res.objs()

    async def update(self, source):
        it = (x.as_doc() async for x in utils.as_aiter(source))
        await self.create_indexes()
        return await update_collection(await self.get_collection(), it)

    async def prune(self, maxage: utils.Delta) -> int:
        age = utils.deltaparse(maxage, default_unit='days')
        expiry = utils.utcnow() - age
        filt = {'start': {'$lt': expiry}}
        coll = await self.get_collection()
        res = await coll.delete_many(filt)
        return res.deleted_count

class PipelineLogFilter(FilterModel[PipelineLog], MongoQueryFilter):
    result_model: ClassVar = PipelineLog
    collection: ClassVar = MongoPipelineLog.collection
    default_ordering: ClassVar = [('start', -1)]

class MongoETBase(StageBackend, MongoContextCollectionMixin):
    'Common base class for MongoExraction & MongoTranslation'
    ordering: ClassVar[list[str]] = []
    clean_keys: ClassVar[list[str]] = []
    stat_clean_keys: ClassVar[list[str]] = []
    lookup_id_key: ClassVar[str]

    async def clean(self) -> None:
        filt = self.get_filter()
        coll = await self.get_collection()
        res = await coll.delete_many(filt)
        logger.debug(f'{filt=} {res=}')

    @asynccontextmanager
    async def reader(self):
        coll = await self.get_collection()
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

    @classmethod
    async def doc_lookup(cls, id: str|UUID, context: Doc|None = None) -> tuple[StateCode, Doc]:
        filt = {cls.lookup_id_key: UUID(str(id))}
        self = cls('XX', context=context)
        coll = await self.get_collection()
        doc = await coll.find_one(filt)
        if not doc:
            raise ValueError(f'doc {id=} not found')
        self.state = doc['state']
        return doc['state'], self.clean_doc(doc)

class MongoExtraction(MongoETBase, ExtractionBackend):
    NS: ClassVar[UUID] = uuid5(settings.NAMESPACE, 'extractions')
    collection = collections['extractions']
    ordering = ['_i']
    clean_keys = ['_id', '_i', 'state']
    stat_clean_keys = ['scrape_time', 'NAICS Codes']
    lookup_id_key = '_id'

    async def update(self, source):
        await self.clean()
        await self.create_indexes()
        coll = await self.get_collection()
        it = utils.aenumerate(source)
        it = utils.amap(self._makedoc, it)
        return await update_collection(coll, it, self.get_replace_filter)

    def get_replace_filter(self, doc: Doc) -> Doc:
        return dict(_i=doc['_i'], state=self.state)

    def _makedoc(self, item: tuple[int, Doc]) -> Doc:
        i, doc = item
        return dict(
            state=self.state,
            _i=i,
            _id=self.state_seq_docid(self.state, i)) | doc

    @classmethod
    def state_seq_docid(cls, state: StateCode, i: int) -> UUID:
        return uuid5(cls.NS, f'{state}:seq:{int(i)}')

class MongoTranslation(MongoETBase, TranslationBackend):
    collection = collections['translations']
    ordering = ['id']
    clean_keys = ['_id', 'row']
    stat_clean_keys = ['row']
    lookup_id_key = 'id'

    async def update(self, source):
        await self.create_indexes()
        coll = await self.get_collection()
        return await update_collection(coll, source, self.get_replace_filter)

    def get_replace_filter(self, entry: Doc) -> Doc:
        return {'$or': [{'id': entry['id']}, {'values_id': entry['values_id']}]}

class MongoSearchIndex(SearchIndexBackend, MongoContextMixin):
    collections: ClassVar[Mapping[str, AbstractMongoCollection]] = search.mapped_collections
    client = search.client

    async def clean(self) -> None:
        db = await self.db()
        for name, collection in self.collections.items():
            coll = db.get_collection(collection.name)
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
        collection = self.collections['reports']
        coll = (await self.db()).get_collection(collection.name)
        it = coll.find(dict(state=self.state)).sort('id')
        return await docs_stat(it)

    async def update(self, name, source):
        collection = self.collections[name]
        coll = (await self.db()).get_collection(collection.name)
        await coll.create_indexes(collection.indexes)
        it = (inst.as_doc() async for inst in utils.as_aiter(source))
        key = 'id' if name in ('states', 'naics') else '_id'
        return await update_collection(coll, it, lambda doc: {key: doc[key]})

async def update_collection(coll: AsyncIOMotorCollection, it: EitherIterable[Doc], get_filter: Callable[[Doc], Doc]|None = None) -> tuple[int, int, int]:
    count, created, updated = 0, 0, 0
    async for doc in utils.as_aiter(it):
        if get_filter:
            filt = get_filter(doc)
        else:
            filt = {'_id': doc['_id']}
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
        count=count,
        size=size,
        hash=h.hexdigest() if count else None)

