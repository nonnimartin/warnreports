from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import (Any, AsyncGenerator, AsyncIterable, Callable, ClassVar,
                    Mapping, override)
from uuid import UUID, uuid5

from motor.motor_asyncio import AsyncIOMotorCollection

from .. import Stage, settings, utils
from ..models import *
from ..utils import EitherIterable
from .mongo import (AbstractMongoCollection, MongoClient, MongoCollection,
                    Search, filters)

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
        data_model=Extraction,
        indexes=[
            {'state': 1},
            {'_i': 1}]),
    translations=MongoCollection(
        client=client,
        name='translations',
        data_model=Translation,
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

class ReaderMixin[T]:

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[T]]: ...

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

class ExtractionBackend(StageBackend, ReaderMixin[Extraction]):
    stage = Stage.Extract

    @abstractmethod
    async def update(self, source: EitherIterable[Extraction|Doc]) -> tuple[int, int, int]: ...

class TranslationBackend(StageBackend, ReaderMixin[Translation]):
    stage = Stage.Translate

    @abstractmethod
    async def update(self, source: EitherIterable[Translation|Doc]) -> tuple[int, int, int]: ...

class SearchIndexBackend(StageBackend):
    stage = Stage.Index
    collections: ClassVar[Mapping[str, search.AbstractMappedCollection]]

    @abstractmethod
    async def update(self, name: str, source: EitherIterable[DataModel]) -> tuple[int, int, int]: ...

class MongoContextMixin(ContextMixin):
    engine = 'mongo'
    client: ClassVar[MongoClient]

    async def db(self):
        return await self.client.get_context_database(self.context)

class MongoContextCollectionMixin[DM: DataModel](MongoContextMixin):
    collection: ClassVar[MongoCollection]
    _indexes_created = False

    @property
    def model(self) -> type[DM]:
        return self.collection.data_model

    @property
    def client(self) -> MongoClient:
        return self.collection.client

    @property
    def filter_class(self) -> type[FilterModel[DM]]:
        return filters[self.model]

    async def get_collection(self):
        return (await self.db()).get_collection(self.collection.name)

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
        await coll.replace_one({'_id': doc['_id']}, doc, True)

    async def fetch(self, id):
        res = Search(self.filter_class(id=[id]), 1, context=self.context)
        if await res.count():
            return await anext(res.objs())
        raise ValueError(f'Not found {id=}')

    async def fetch_latest(self):
        async for log in await self.findall(limit=1):
            return log
        raise ValueError(f'No entries found')

    async def findall(self, limit: Limit|None = None, offset: Offset = 0):
        filter = self.filter_class()
        res = Search(filter, limit=limit, offset=offset, context=self.context)
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

class MongoETBase[DM: (Extraction, Translation)](StageBackend, MongoContextCollectionMixin[DM]):
    'Common base class for MongoExraction & MongoTranslation'

    @asynccontextmanager
    async def reader(self):
        coll = await self.get_collection()
        ordering = self.filter_class.default_ordering
        it = coll.find(self.get_select_filter()).sort(ordering)
        yield utils.amap(self.model.model_validate, it)

    async def stat(self):
        async with self.reader() as reader:
            it = utils.amap(self.model.as_doc, reader)
            it = utils.amap(self.clean_stat_doc, it)
            return await docs_stat(it)

    async def clean(self) -> None:
        coll = await self.get_collection()
        await coll.delete_many(self.get_clean_filter())

    async def update(self, source):
        await self.create_indexes()
        coll = await self.get_collection()
        it = utils.amap(self.model.model_validate, source)
        it = utils.amap(reversed, utils.aenumerate(it))
        it = utils.astarmap(self.get_save_doc, it)
        return await update_collection(coll, it, self.get_replace_filter)

    def get_save_doc(self, inst: DM, i: int) -> Doc:
        return inst.as_doc(exclude_unset=True)

    def get_select_filter(self) -> Doc:
        return dict(state=self.state)

    def get_clean_filter(self) -> Doc:
        return self.get_select_filter()

    def get_replace_filter(self, doc: Doc) -> Doc:
        return {'_id': doc['_id']}

    def clean_stat_doc(self, doc: Doc) -> Doc:
        for field in self.model.stat_exclude_fields:
            doc.pop(field, None)
        return doc

class MongoExtraction(MongoETBase[Extraction], ExtractionBackend):
    NS: ClassVar[UUID] = uuid5(settings.NAMESPACE, 'extractions')
    collection = collections['extractions']

    @override
    async def update(self, source):
        await self.clean()
        return await super().update(source)

    @override
    def get_save_doc(self, inst, i) -> Doc:
        inst.i = i
        inst.state = self.state
        inst.id = uuid5(self.NS, f'{inst.state}:seq:{int(i)}')
        return super().get_save_doc(inst, i)


class MongoTranslation(MongoETBase[Translation], TranslationBackend):
    collection = collections['translations']

    @override
    def get_replace_filter(self, doc: Doc) -> Doc:
        return {
            '$or': [
                super().get_replace_filter(doc),
                {'values_id': doc['values_id']}]}

from .. import search


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

