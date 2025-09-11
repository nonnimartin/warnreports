from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import (Any, AsyncGenerator, AsyncIterable, Callable, ClassVar, Literal,
                    Mapping, Self, override)
from uuid import UUID, uuid5

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pydantic import NonNegativeInt

from .. import Stage, settings, utils
from ..models import *
from ..utils import EitherIterable
from .mongo import (AbstractMongoCollection, MongoClient, MongoCollection,
                    MongoFilterModel, Search)

__all__ = [
    'ExtractionBackend',
    'PipelineLogBackend',
    'SearchIndexBackend',
    'StageBackend',
    'TranslationBackend']

type Doc = dict[str, Any]
type UpdateCounts = tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt]

logger = utils.get_logger('backends.etl')

default_client = MongoClient(
    url=settings.ETL_MONGODB_URL,
    control_dbname=settings.ETL_MONGODB_CONTROL_DBNAME,
    dbname_key='etl.dbname',
    dbname_ttl=settings.ETL_MONGODB_DBNAME_TTL,
    dbname_default=settings.ETL_MONGODB_DBNAME)

collections: dict[str, MongoCollection] = dict(
    extractions=MongoCollection(
        name='extractions',
        client=default_client,
        data_model=Extraction,
        indexes=[
            {'state': 1},
            {'i': 1}]),
    translations=MongoCollection(
        name='translations',
        client=default_client,
        data_model=Translation,
        indexes=[
            {'values_id': 1},
            {'state': 1}]),
    pipelinelogs=MongoCollection(
        name='pipelinelogs',
        client=default_client,
        data_model=PipelineLog,
        indexes=[
            {'stages': 1},
            {'states': 1},
            {'start': -1},
            {'end': -1},
            {'elapsed': -1}]))

class ContextMixin:
    context: Doc

    def __init__(self, *, context: Doc|None) -> None:
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
    async def update(self, source: EitherIterable[PipelineLog]) -> UpdateCounts: ...

    @abstractmethod
    async def prune(self, maxage: utils.Delta, *, dryrun: bool = False) -> NonNegativeInt: ...

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if hasattr(cls, 'engine'):
            cls.registry[cls.engine] = cls

class StageBackend(ContextMixin):
    registry: ClassVar[dict[str, dict[Stage, type[StageBackend]]]] = {}
    stage: ClassVar[Stage]
    engine: ClassVar[str]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if hasattr(cls, 'engine') and hasattr(cls, 'stage'):
            cls.registry.setdefault(cls.engine, {})[cls.stage] = cls

class ETBase[DM: (Extraction, Translation)](StageBackend):

    @abstractmethod
    @asynccontextmanager
    async def reader(self, filter: FilterModel[DM]|Any, /, *, limit: Limit|None = None, offset: Offset = 0) -> AsyncGenerator[AsyncIterable[DM]]: ...

    @abstractmethod
    async def stat(self, filter: FilterModel[DM]|Any) -> dict: ...

    @abstractmethod
    async def clean(self, filter: FilterModel[DM]|Any) -> NonNegativeInt: ...

    @abstractmethod
    async def update(self, source: EitherIterable[DM|Doc]) -> UpdateCounts: ...

class ExtractionBackend(ETBase[Extraction]):
    stage: ClassVar = Stage.Extract

class TranslationBackend(ETBase[Translation]):
    stage: ClassVar = Stage.Translate

class SearchIndexBackend(StageBackend):
    stage: ClassVar = Stage.Index
    collections: ClassVar[Mapping[str, search.AbstractMappedCollection]]

    @abstractmethod
    async def stat(self, name: str, filter: FilterModel[DataModel]|Any) -> dict: ...

    @abstractmethod
    async def clean(self, name: str, filter: FilterModel[DataModel]|Any) -> NonNegativeInt: ...

    @abstractmethod
    async def update(self, name: str, source: EitherIterable[DataModel]) -> UpdateCounts: ...

class MongoContextMixin(ContextMixin):
    engine: ClassVar[Literal['mongo']] = 'mongo'
    client: MongoClient

    def __init__(self, *, context: Doc|None, client: MongoClient) -> None:
        super().__init__(context=context)
        self.client = client

    async def db(self) -> AsyncIOMotorDatabase:
        return await self.client.get_context_database(self.context)

    def reloop(self) -> Self:
        'Create a copy with a new AsyncIOMotorClient object for a separate thread/event loop'
        return type(self)(context=self.context, client=self.client.reloop())

class MongoContextCollectionMixin[DM: DataModel](MongoContextMixin):
    collection: ClassVar[MongoCollection]

    def __init__(self, *, context: Doc|None = None, client: MongoClient|None = None) -> None:
        client = client or self.collection.client
        self._indexes_created = False
        super().__init__(context=context, client=client)

    def search(self, filter: MongoFilterModel[DM]|Any, limit: Limit|None = None, offset: Offset = 0) -> Search[DM]:
        return Search(
            filter=self.filter_class.model_validate(filter),
            limit=limit,
            offset=offset,
            context=self.context,
            client=self.client)

    @property
    def model(self) -> type[DM]:
        return self.collection.data_model

    @property
    def filter_class(self) -> type[MongoFilterModel[DM]]:
        return self.collection.filter_class

    async def get_collection(self) -> AsyncIOMotorCollection:
        return (await self.db()).get_collection(self.collection.name)

    async def create_indexes(self) -> None:
        if not self._indexes_created:
            coll = await self.get_collection()
            await coll.create_indexes(self.collection.indexes)
            self._indexes_created = True

    def reloop(self) -> Self:
        inst = super().reloop()
        inst._indexes_created = self._indexes_created
        return inst

class MongoPipelineLog(PipelineLogBackend, MongoContextCollectionMixin[PipelineLog]):
    collection: ClassVar = collections['pipelinelogs']

    async def save(self, log: PipelineLog) -> None:
        doc = log.model_dump(by_alias=True)
        await self.create_indexes()
        coll = await self.get_collection()
        await coll.replace_one({'_id': doc['_id']}, doc, True)

    async def fetch(self, id: UUID) -> PipelineLog:
        res = self.search(dict(id=[id]), limit=1)
        try:
            return await anext(res.objs())
        except StopAsyncIteration:
            raise ValueError(f'Not found {id=}')

    async def fetch_latest(self) -> PipelineLog:
        res = self.search(dict(order='-start'), limit=1)
        try:
            return await anext(res.objs())
        except StopAsyncIteration:
            raise ValueError(f'No entries found')

    async def update(self, source: EitherIterable[PipelineLog]) -> UpdateCounts:
        it = (x.model_dump(by_alias=True) async for x in utils.as_aiter(source))
        await self.create_indexes()
        return await update_collection(await self.get_collection(), it)

    async def prune(self, maxage: utils.Delta, *, dryrun: bool = False) -> NonNegativeInt:
        age = utils.deltaparse(maxage, default_unit='days')
        expiry = utils.utcnow() - age
        filt = {'start': {'$lt': expiry}}
        coll = await self.get_collection()
        if dryrun:
            return await coll.count_documents(filt)
        res = await coll.delete_many(filt)
        return res.deleted_count

class MongoETBase[DM: (Extraction, Translation)](ETBase[DM], MongoContextCollectionMixin[DM]):
    'Common base class for MongoExraction & MongoTranslation'

    @asynccontextmanager
    async def reader(self, filter: MongoFilterModel[DM]|Any, /) -> AsyncGenerator[AsyncIterable[DM]]:
        yield self.search(filter).objs()

    async def stat(self, filter: MongoFilterModel[DM]|Any) -> Doc:
        it = self.search(filter).objs()
        it = (x.model_dump(by_alias=True) async for x in it)
        it = utils.amap(self.clean_stat_doc, it)
        return await docs_stat(it)

    async def clean(self, filter: MongoFilterModel[DM]|Any) -> NonNegativeInt:
        q = self.search(filter, limit=0).q
        coll = await self.get_collection()
        res = await coll.delete_many(q)
        return res.deleted_count

    async def update(self, source: EitherIterable[DM|Any]) -> UpdateCounts:
        await self.create_indexes()
        coll = await self.get_collection()
        it = utils.amap(self.model.model_validate, source)
        it = utils.amap(reversed, utils.aenumerate(it))
        it = utils.astarmap(self.get_save_doc, it)
        return await update_collection(coll, it, self.get_replace_filter)

    def get_save_doc(self, inst: DM, i: NonNegativeInt) -> Doc:
        return inst.model_dump(by_alias=True, exclude_unset=True, exclude_none=True)

    def get_replace_filter(self, doc: Doc) -> Doc:
        return {'_id': doc['_id']}

    def clean_stat_doc(self, doc: Doc) -> Doc:
        for field in self.model.stat_exclude_fields:
            doc.pop(field, None)
        return doc

class MongoExtraction(MongoETBase[Extraction], ExtractionBackend):
    NS: ClassVar[UUID] = uuid5(settings.NAMESPACE, 'extractions')
    collection: ClassVar = collections['extractions']

    @override
    def get_save_doc(self, inst: Extraction, i: NonNegativeInt) -> Doc:
        if not inst.id:
            inst.i = i
            inst.id = self.get_seq_id(inst.state, i)
        return super().get_save_doc(inst, i)

    def clean_stat_doc(self, doc: Doc) -> Doc:
        super().clean_stat_doc(doc['data'])
        return doc

    @classmethod
    def get_seq_id(cls, state: StateCode, i: NonNegativeInt) -> UUID:
        return uuid5(cls.NS, f'{state.upper()}:seq:{int(i)}')

class MongoTranslation(MongoETBase[Translation], TranslationBackend):
    collection: ClassVar = collections['translations']

    @override
    def get_replace_filter(self, doc: Doc) -> Doc:
        return {
            '$or': [
                super().get_replace_filter(doc),
                {'values_id': doc['values_id']}]}

class MongoExtractionFilter(ExtractionFilter, MongoFilterModel[Extraction]):
    collection: ClassVar = collections['extractions']

class MongoTranslationFilter(TranslationFilter, MongoFilterModel[Translation]):
    collection: ClassVar = collections['translations']

class MongoPipelineLogFilter(PipelineLogFilter, MongoFilterModel[PipelineLog]):
    collection: ClassVar = collections['pipelinelogs']

from .. import search


class MongoSearchIndex(SearchIndexBackend, MongoContextMixin):
    collections: ClassVar[Mapping[str, AbstractMongoCollection]] = search.mapped_collections

    def __init__(self, *, context: Doc|None = None, client: MongoClient|None = None) -> None:
        super().__init__(context=context, client=client or search.default_client)

    async def clean(self, name, filter: MongoFilterModel[DataModel]|Any) -> NonNegativeInt:
        collection = self.collections[name]
        filter = collection.filter_class.model_validate(filter)
        q = Search(filter=filter, limit=0, context=self.context, client=self.client).q
        coll = (await self.db()).get_collection(collection.name)
        res = await coll.delete_many(q)
        return res.deleted_count

    async def stat(self, name, filter: MongoFilterModel[DataModel]|Any) -> Doc:
        collection = self.collections[name]
        filter = collection.filter_class.model_validate(filter)
        srch = Search(filter=filter, context=self.context, client=self.client)
        return await docs_stat(await srch.docs())

    async def update(self, name, source: EitherIterable[DataModel]) -> UpdateCounts:
        collection = self.collections[name]
        coll = (await self.db()).get_collection(collection.name)
        await coll.create_indexes(collection.indexes)
        it = utils.as_aiter(source)
        it = (x.model_dump(by_alias=True) async for x in it)
        key = 'id' if name in ('states', 'naics') else '_id'
        return await update_collection(coll, it, lambda doc: {key: doc[key]})

async def update_collection(coll: AsyncIOMotorCollection, it: EitherIterable[Doc], get_filter: Callable[[Doc], Doc]|None = None) -> UpdateCounts:
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
            # logger.debug(f'{coll.name} created {res.upserted_id}')
        elif res.modified_count:
            updated += 1
            # logger.debug(f'{coll.name} modified {doc.get('_id', filt.get('_id', filt))}')
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
