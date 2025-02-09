from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Iterable, Iterator, Sequence

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo.operations import IndexModel

from . import orm, settings, utils
from .backends.mongo import MongoClient
from .models import *

__all__ = ['filters', 'Search']

logger = utils.get_logger('search')

client = MongoClient(
    url=settings.SEARCH_MONGODB_URL,
    control_dbname=settings.SEARCH_MONGODB_CONTROL_DBNAME,
    dbname_key='search.dbname',
    dbname_ttl=settings.SEARCH_MONGODB_DBNAME_TTL,
    dbname_default=settings.SEARCH_MONGODB_DBNAME)

collection_defns: dict[str, CollectionDefn] = {}
collections_map: dict[type[DataModel], str] = {}
filters: dict[type[DataModel], type[MongoFilter|FilterModel]] = {}

class CollectionDefn:

    def __init__(self, name: str, orm_model: type[orm.MapReduceBase], indexes: Iterable[dict]) -> None:
        self.name = name
        self.orm_model = orm_model
        self.indexes = list(map(IndexModel, indexes))
        collection_defns[self.name] = self
        collections_map[self.data_model] = self.name

    @property
    def data_model(self) -> type[DataModel]:
        return self.orm_model.data_model

    @property
    def filter_class(self) -> type[MongoFilter]:
        return filters[self.data_model]

    async def stats(self, db: str|AsyncIOMotorDatabase|None = None) -> dict[str, str|int]:
        'Get collection stats'
        db = await client.get_database(db)
        stat = await db.command('collstats', self.name)
        return dict(name=self.name, count=stat['count'], size=stat['size'])

    async def init(self, db: str|AsyncIOMotorDatabase|None = None) -> None:
        'Init collection'
        db = await client.get_database(db)
        logger.info(f'Initializing {self.name}')
        await db.get_collection(self.name).create_indexes(self.indexes)

    async def clean(self, db: str|AsyncIOMotorDatabase|None = None) -> None:
        'Clean collection'
        db = await client.get_database(db)
        stat = await self.stats(db=db)
        logger.info(f'Cleaning {self.name} {stat=}')
        await db.get_collection(self.name).drop()

    async def build(self, db: str|AsyncIOMotorDatabase|None = None, lazy: bool = True) -> None:
        'Build collection'
        db = await client.get_database(db)
        await self.clean(db=db)
        await self.init(db=db)
        with orm.SessionLocal() as session:
            logger.info(f'Building {self.name}')
            it = self.orm_model.map_reduce_exec(session, lazy=lazy)
            it = map(self.data_model.as_doc, it)
            await db.get_collection(self.name).insert_many(it)
        stat = await self.stats(db=db)
        logger.info(f'Built {self.name} {stat=}')

CollectionDefn(
    name='reports',
    orm_model=orm.Report,
    indexes=[
        {'company': 'text'},
        {'company_id': 1},
        {'reported': 1},
        {'reported': -1},
        {'employees': 1},
        {'employees': -1},
        {'naics.code': 1},
        {'naics.id': 1},
        {'state': 1}])

CollectionDefn(
    name='companies',
    orm_model=orm.Company,
    indexes=[
        {'aliases': 'text'},
        {'name': 1},
        {'aliases': 1},
        {'states': 1},
        {'naics.code': 1},
        {'naics.id': 1},
        {'last_reported': 1},
        {'last_reported': -1},
        {'reports_count': 1},
        {'reports_count': -1},
        {'states_count': 1},
        {'states_count': -1},
        {'employees_sum': -1}])

CollectionDefn(
    name='naics',
    orm_model=orm.Naics,
    indexes=[
        {'id': 1},
        {'code': 1},
        {'title': 1},
        {'root': 1},
        {'parent': 1},
        {'depth': 1},
        {'states': 1},
        {'is_leaf': 1},
        {'companies_count': 1},
        {'last_reported': 1},
        {'last_reported': -1},
        {'reports_count': 1},
        {'reports_count': -1},
        {'states_count': 1},
        {'states_count': -1},
        {'employees_sum': -1}])

CollectionDefn(
    name='artifacts',
    orm_model=orm.Artifact,
    indexes=[
        {'name': 1},
        {'path': 1}])

CollectionDefn(
    name='states',
    orm_model=orm.StateStat,
    indexes=[
        {'id': 1},
        {'last_reported': -1},
        {'reports_count': -1}])


class MongoFilter:
    minmax_fields: ClassVar[Sequence[str]] = ()
    MINMAX_OPERS: ClassVar[dict[str, str]] = dict(min='$gte', max='$lte')

    def get_filters(self) -> Iterable[dict[str, Any]]:
        yield from self.get_minmax_filters(*self.minmax_fields)

    def get_query(self) -> dict[str, Any]:
        filts = tuple(self.get_filters())
        return {'$and': filts} if filts else {}

    @staticmethod
    def wc_contains(text: str, flags: re.RegexFlag = re.I) -> re.Pattern:
        return re.compile(f'.*{re.escape(text)}.*', flags)

    @staticmethod
    def wc_startswith(text: str, flags: re.RegexFlag = re.I) -> re.Pattern:
        return re.compile(f'^{re.escape(text)}.*', flags)

    @classmethod
    def get_naics_filter(cls, naics: list[int], prefix: str = 'naics'):
        if prefix:
            prefix = prefix.removesuffix('.') + '.'
        rxs = (
            {f'{prefix}code': {'$regex': cls.wc_startswith(str(code))}}
            for code in naics)
        return {'$or': [*rxs, {f'{prefix}id': {'$in': naics}}]}

    def get_minmax_filters(self, *fields: str) -> Iterator[dict[str, dict[str, int]]]:
        for field in fields:
            for suffix, oper in self.MINMAX_OPERS.items():
                if (value := getattr(self, f'{field}_{suffix}')) is not None:
                    yield {field: {oper: value}}

    def __init_subclass__(cls, **kw) -> None:
        super().__init_subclass__(**kw)
        for base in cls.__bases__:
            if issubclass(base, FilterModel):
                filters[base.result_model] = cls
                break

class MongoReportsFilter(ReportsFilter, MongoFilter):
    minmax_fields: ClassVar = ('reported', 'starting', 'employees')

    def get_filters(self):
        if self.id is not None:
            yield {'_id': {'$in': self.id}}
        if self.id_not:
            yield {'_id': {'$nin': self.id_not}}
        for field in ('state', 'company', 'company_id'):
            if (value := getattr(self, field)) is not None:
                yield {field: {'$in': value}}
        for field in ('action', 'location'):
            if (value := getattr(self, field)) is not None:
                yield {field: {'$regex': self.wc_contains(value)}}
        if self.naics is not None:
            yield self.get_naics_filter(self.naics)
        if self.text:
            yield {'$text': {'$search': self.text}}
        yield from super().get_filters()

class MongoStatesFilter(StatesFilter, MongoFilter):
    minmax_fields: ClassVar = ('reports_count', 'last_reported')

    def get_filters(self):
        if self.id:
            yield {'id': {'$in': sorted(set(map(str.upper, self.id)))}}
        yield from super().get_filters()

class MongoCompaniesFilter(CompaniesFilter, MongoFilter):
    minmax_fields: ClassVar = MongoStatesFilter.minmax_fields + ('states_count', 'employees_sum')

    def get_filters(self):
        if self.id is not None:
            yield {'_id': {'$in': self.id}}
        if self.name is not None:
            yield {'aliases': {'$in': self.name}}
        if self.state is not None:
            yield {'states': {'$in': self.state}}
        if self.naics is not None:
            yield self.get_naics_filter(self.naics)
        if self.text:
            yield {'$text': {'$search': self.text}}
        yield from super().get_filters()

class MongoNaicsFilter(NaicsFilter, MongoFilter):
    minmax_fields: ClassVar = MongoCompaniesFilter.minmax_fields + ('depth', 'companies_count')

    def get_filters(self):
        if self.id:
            yield {'id': {'$in': self.id}}
        if self.prefix is not None:
            yield self.get_naics_filter(self.prefix, prefix='')
        if self.title:
            yield {'title': {'$regex': self.wc_contains(self.title)}}
        if self.parent is not None:
            yield {'parent': {'$in': self.parent}}
        if self.root:
            yield {'root': {'$in': self.root}}
        if self.state is not None:
            yield {'states': {'$in': self.state}}
        if self.is_leaf is not None:
            yield {'is_leaf': self.is_leaf}
        if self.includes:
            incs = set()
            for code in self.includes:
                s = str(code)
                for i in range(2, min(6, len(s))):
                    incs.add(int(s[:i]))
                incs.add(code)
            yield {'id': {'$in': sorted(incs)}}
        yield from super().get_filters()

class MongoArtifactsFilter(ArtifactsFilter, MongoFilter):

    def get_filters(self):
        if self.id:
            yield {'_id': {'$in': self.id}}
        if self.state:
            it = (re.escape(x.lower()[:2]) for x in self.state)
            pat = '|'.join(filter(None, dict.fromkeys(it))) or '_'
            pat = f'^({pat})/.*'
            yield {'path': {'$regex': re.compile(pat)}}
        for field in ('name', 'sha1'):
            value = getattr(self, field)
            if value:
                yield {field: value}
        yield from super().get_filters()


class Search[DM: DataModel]:

    def __init__(
        self,
        model: type[DM],
        params: dict[str, Any]|None = None,
        limit: Limit|None = None,
        offset: Offset = 0,
        dbname: str|None = None
    ) -> None:        
        self.model = model
        self.dbname = dbname
        self.filter = filters[model](**params or {})
        self.q = self.filter.get_query()
        self.limit = limit
        self.offset = offset
        if limit == 0:
            self.orders = []
        else:
            self.orders = list(self.filter.get_ordering())
            if ('_id', 1) not in self.orders and ('_id', -1) not in self.orders:
                self.orders.append(('_id', 1))
        self._db = None

    @property
    def collection_name(self) -> str:
        return collections_map[self.model]

    async def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            self._db = await client.get_database(self.dbname)
        return self._db

    async def collection(self) -> AsyncIOMotorCollection:
        return (await self.db()).get_collection(self.collection_name)

    async def count(self) -> int:
        return await (await self.collection()).count_documents(self.q)

    async def tolist(self) -> list[DM]:
        return [obj async for obj in self.objs()]

    async def objs(self) -> AsyncIterator[DM]:
        async for doc in await self.docs():
            yield self.model.model_validate(doc)

    async def docs(self) -> AsyncIterator[dict[str, Any]]:
        if self.limit == 0:
            return utils.as_aiter(())
        cur = (await self.collection()).find(self.q)
        if self.orders:
            cur = cur.sort(self.orders)
        if self.offset:
            cur = cur.skip(self.offset)
        if self.limit is not None:
            cur = cur.limit(self.limit)
        return cur

class CollectionCmdBase(utils.BaseCommand):
    method: ClassVar[str]

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg('--dbname', '-d',
            default=None,
            help=f'Alternate mongo search db name')
        if cls.method == 'build':
            arg('--eager', '-e',
                action='store_false',
                dest='lazy',
                help='Use eager loading of SQL result sets. Uses more memory.')
        arg('names',
            nargs='*',
            choices=collection_defns,
            help='Collection names, default all')

    def setup(self, opts):
        self.funckw = {}
        if hasattr(opts, 'lazy'):
            self.funckw.update(lazy=opts.lazy)

    async def run(self):
        db = await client.get_database(self.opts.dbname)
        names = self.opts.names or collection_defns
        results: dict[str, Any] = {}
        for name in names:
            defn = collection_defns[name]
            res = await getattr(defn, self.method)(db=db, **self.funckw)
            if res is not None:
                results[name] = res
        if res:
            print(json.dumps(res, indent=2))

def CollectionCmd(method: str) -> type[CollectionCmdBase]:
    class Cmd(CollectionCmdBase): pass
    Cmd.method = method
    Cmd.description = getattr(CollectionDefn, method).__doc__
    return Cmd

class ControlGetCommand(utils.BaseCommand):
    'Get the search mongo DB name'

    async def run(self):
        doc = await client.get_doc()
        print(json.dumps(doc, indent=2, default=str))

class ControlSetCommand(utils.BaseCommand):
    'Set the search mongo DB name'

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg(
            '--ttl',
            type=utils.deltaopt('seconds'),
            default=None,
            help='Override the TTL')
        arg(
            'name',
            help='The database name')

    async def run(self):
        doc = await client.set_dbname(self.opts.name, ttl=self.opts.ttl)
        print(json.dumps(doc, indent=2, default=str))

class ControlCommand(utils.BaseCommand):
    'Mongo DB name control commands'
    commands = dict(
        get=ControlGetCommand,
        set=ControlSetCommand)

class Command(utils.BaseCommand):
    'Search collection commands'
    commands = dict(
        stats=CollectionCmd('stats'),
        init=CollectionCmd('init'),
        build=CollectionCmd('build'),
        clean=CollectionCmd('clean'),
        control=ControlCommand)
