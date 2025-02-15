from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import (Any, AsyncGenerator, AsyncIterable, Callable, ClassVar,
                    Mapping)
from uuid import UUID, uuid5

import yaml
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.operations import IndexModel

from .. import Stage, search, settings, utils
from ..models import *
from ..utils import EitherIterable
from .mongo import ClientControlCommand, MongoClient

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

class ReaderMixin:

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[Doc]]: ...

class ContextMixin:

    def __init__(self, context: Doc|None = None):
        if context is None:
            context = {}
        self.context = context

class PipelineLogBackend(ContextMixin):
    registry: ClassVar[dict[str, type[PipelineLogBackend]]] = {}
    engine: ClassVar[str]

    @abstractmethod
    async def save(self, doc: Doc) -> None: ...

    def __init_subclass__(cls):
        super().__init_subclass__()
        if hasattr(cls, 'engine'):
            cls.registry[cls.engine] = cls

class StageBackend(ContextMixin):
    registry: ClassVar[dict[str, dict[Stage, type[StageBackend]]]] = {}
    stage: ClassVar[Stage]
    engine: ClassVar[str]

    def __init__(self, state: StateCode, context: Doc|None = None):
        super().__init__(context)
        self.state = state.upper()

    @abstractmethod
    async def clean(self) -> None: ...

    async def stat(self) -> dict:
        return {}

    def __init_subclass__(cls):
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
    collections: Mapping[str, search.AbstractCollectionDefn]

    @abstractmethod
    async def update(self, name: str, source: EitherIterable[DataModel]) -> tuple[int, int, int]: ...

class MongoContextMixin(ContextMixin):
    engine = 'mongo'
    mongo: ClassVar[MongoClient]
    _db = None

    async def db(self):
        if self._db is None:
            self._db = await self.mongo.get_database(self.context.get(self.mongo.dbname_key))
            self.context[self.mongo.dbname_key] = self._db.name
        return self._db

class MongoContextCollectionMixin(MongoContextMixin):
    collection_name: ClassVar[str]
    _coll = None

    async def collection(self):
        if self._coll is None:
            self._coll = (await self.db()).get_collection(self.collection_name)
        return self._coll

class MongoPipelineLog(PipelineLogBackend, MongoContextCollectionMixin):
    collection_name = 'pipelinelogs'
    mongo = client
    _indexes_created = False

    async def save(self, doc):
        coll = await self.collection()
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

class MongoETBase(StageBackend, MongoContextCollectionMixin):
    'Common base class for MongoExraction & MongoTranslation'
    ordering: ClassVar[list[str]] = []
    clean_keys: ClassVar[list[str]] = []
    stat_clean_keys: ClassVar[list[str]] = []
    lookup_id_key: ClassVar[str]
    mongo = client

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

    @classmethod
    async def doc_lookup(cls, id: str|UUID, context: Doc|None = None) -> tuple[StateCode, Doc]:
        filt = {cls.lookup_id_key: UUID(str(id))}
        self = cls('XX', context=context)
        coll = await self.collection()
        doc = await coll.find_one(filt)
        if not doc:
            raise ValueError(f'doc {id=} not found')
        self.state = doc['state']
        return doc['state'], self.clean_doc(doc)

class MongoExtraction(MongoETBase, ExtractionBackend):
    NS: ClassVar[UUID] = uuid5(settings.NAMESPACE, 'extractions')
    collection_name = 'extractions'
    ordering = ['_i']
    clean_keys = ['_id', '_i', 'state']
    stat_clean_keys = ['scrape_time']
    lookup_id_key = '_id'

    async def update(self, source):
        await self.clean()
        coll = await self.collection()
        await coll.create_indexes(self.indexes)
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

    indexes = [
        IndexModel({'state': 1}),
        IndexModel({'_i': 1}),
    ]

class MongoTranslation(MongoETBase, TranslationBackend):
    collection_name = 'translations'
    ordering = ['id']
    clean_keys = ['_id', 'row']
    lookup_id_key = 'id'

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

class MongoSearchIndex(SearchIndexBackend, MongoContextMixin):
    collections = search.collection_defns
    mongo = search.client

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
        count=count,
        size=size,
        hash=h.hexdigest() if count else None)


class OneBaseCommand(utils.BaseCommand):

    @classmethod
    def add_arguments(cls, parser: utils.AP):
        arg = parser.add_argument
        arg('--etl-dbname', '-b',
            default=None,
            help=f'Alternate mongo etl db name')
        arg('--yaml', action='store_true', help='Output yaml')

    def setup(self, opts):
        self.context = {client.dbname_key: opts.etl_dbname}

    def printobj(self, obj: Any) -> None:
        print(self.objtext(obj))

    def objtext(self, obj: Any) -> str:
        obj = self.jsondoc(obj)
        if self.opts.yaml:
            text = yaml.safe_dump(obj, sort_keys=False)
        else:
            text = json.dumps(obj, indent=2)
        return text

    @staticmethod
    def jsondoc(obj: Any) -> Any:
        return json.loads(json.dumps(obj, default=str))

class TroneCommand(OneBaseCommand):
    'Run translations for a single extraction doc, and print the result'

    @classmethod
    def add_arguments(cls, parser):
        super().add_arguments(parser)
        arg = parser.add_argument
        arg('id', type=UUID, help='The extraction doc id')

    async def run(self):
        from ..translators import translators
        state, doc = await MongoExtraction.doc_lookup(
            self.opts.id,
            context=self.context)
        it = translators[state]().entries(doc)
        it = utils.as_aiter(it)
        res = [x async for x in it]
        self.printobj(res)

class LdoneCommand(OneBaseCommand):
    'Run load operations for a single translation doc, and print the result'

    @classmethod
    def add_arguments(cls, parser):
        super().add_arguments(parser)
        arg = parser.add_argument
        arg('id', type=UUID, help='The translation doc id')

    async def run(self):
        from .. import orm
        from ..pipeline import Pipeline
        state, doc = await MongoTranslation.doc_lookup(
            self.opts.id,
            context=self.context)
        pipeline = Pipeline(state, context=self.context)
        with orm.SessionLocal() as session:
            pipeline.session = session
            pipeline.artifact_cache = {}
            report, save = pipeline.save(doc)
            if report is not None:
                report, = orm.Report.map_reduce([(report, report, None, None)])
                report = report.model_dump(mode='json')
            session.rollback()
        self.printobj(dict(save=save, report=report))

class Command(utils.BaseCommand):
    'Misc ETL pipeline commands'
    commands = dict(
        trone=TroneCommand,
        ldone=LdoneCommand,
        control=ClientControlCommand(client))
