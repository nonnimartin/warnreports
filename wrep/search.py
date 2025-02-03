from __future__ import annotations

import re
from typing import Any, Iterable, Iterator, Sequence

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.operations import IndexModel

from . import orm, settings, utils
from .models import *
from .utils import BaseCommand, FuncCommand

__all__ = ['filters', 'retrieve', 'retrieve404', 'search', 'search_result', 'NotFoundError']

type MongoDB = AsyncIOMotorDatabase

logger = utils.get_logger('search')

class MongoSearch(FilterModel[DM]):
    minmax_fields: ClassVar[Sequence[str]] = ()
    MINMAX_OPERS: ClassVar[dict[str, str]] = dict(min='$gte', max='$lte')

    def get_filters(self) -> Iterable[dict[str, Any]]:
        yield from self.get_minmax_filters(*self.minmax_fields)

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

class MongoReportsFilter(ReportsFilter, MongoSearch[ReportData]):
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

class MongoStatesFilter(StatesFilter, MongoSearch[StateDetail]):
    minmax_fields: ClassVar = ('reports_count', 'last_reported')

    def get_filters(self):
        if self.id:
            yield {'id': {'$in': sorted(set(map(str.upper, self.id)))}}
        yield from super().get_filters()

class MongoCompaniesFilter(CompaniesFilter, MongoSearch[CompanyDetail]):
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

class MongoNaicsFilter(NaicsFilter, MongoSearch[NaicsDetail]):
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

class MongoArtifactsFilter(ArtifactsFilter, MongoSearch[ArtifactDetail]):

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

class NotFoundError(Exception):
    pass

filters: dict[type[DataModel], type[MongoSearch]] = {
    ReportData: MongoReportsFilter,
    StateDetail: MongoStatesFilter,
    CompanyDetail: MongoCompaniesFilter,
    NaicsDetail: MongoNaicsFilter,
    ArtifactDetail: MongoArtifactsFilter}

async def search_result(
    model: type[DM],
    params: dict[str, Any]|None = None,
    limit: Limit|None = None,
    offset: Offset = 0,
    dbname: str|None = None,
) -> tuple[list[DM], int]:
    filt = filters[model](**params or {})
    db = get_mongo_database(dbname)
    coll = db.get_collection(collections_map[model])
    filts = tuple(filt.get_filters())
    q = {'$and': filts} if filts else {}
    total = await coll.count_documents(q)
    if limit == 0:
        objs = []
    else:
        cur = coll.find(q)
        orders = list(filt.get_ordering())
        if ('_id', 1) not in orders and ('_id', -1) not in orders:
            orders.append(('_id', 1))
        if orders:
            cur = cur.sort(orders)
        if offset:
            cur = cur.skip(offset)
        if limit:
            cur = cur.limit(limit)
        objs = [model.model_validate(obj) async for obj in cur]
    return objs, total

async def search(
    model: type[DM],
    params: dict[str, Any]|None = None,
    limit: Limit|None = None,
    offset: Offset = 0
) -> list[DM]:
    return (await search_result(model, params, limit, offset))[0]

async def retrieve(model: type[DM], **params) -> DM:
    results, total = await search_result(model, params, 1)
    if total:
        return results[0]
    raise NotFoundError

async def retrieve404(model: type[DM], **params) -> DM:
    try:
        return await retrieve(model, **params)
    except NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

_mongo_client = AsyncIOMotorClient(settings.SEARCH_MONGODB_URL, uuidRepresentation='standard')
_mongo_database_default = _mongo_client.get_database(settings.SEARCH_MONGODB_DBNAME)

def get_mongo_database(dbname: str|None = None) -> MongoDB:
    if dbname:
        return _mongo_client.get_database(dbname)
    return _mongo_database_default

class CollectionDefn:

    def __init__(self, orm_model: type[orm.MapReduceBase], indexes: Iterable[dict]) -> None:
        self.orm_model = orm_model
        self.data_model: type[DataModel] = orm_model.data_model
        self.indexes = list(map(IndexModel, indexes))

collections: dict[str, CollectionDefn] = dict(
    reports=CollectionDefn(orm.Report, [
        {'company': 'text'},
        {'company_id': 1},
        {'reported': 1},
        {'reported': -1},
        {'employees': 1},
        {'employees': -1},
        {'naics.code': 1},
        {'naics.id': 1},
        {'state': 1}]),
    companies=CollectionDefn(orm.Company, [
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
        {'employees_sum': -1}]),
    naics=CollectionDefn(orm.Naics, [
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
        {'employees_sum': -1}]),
    artifacts=CollectionDefn(orm.Artifact, [
        {'name': 1},
        {'path': 1}]),
    states=CollectionDefn(orm.StateStat, [
        {'id': 1},
        {'last_reported': -1},
        {'reports_count': -1}]))

collections_map: dict[type[DataModel], str] = {
    defn.data_model: name for name, defn in collections.items()}

async def search_stats(*names: str, dbname: str|None = None) -> dict[str, dict[str, int]]:
    'Get collection stats'
    db = get_mongo_database(dbname)
    names = names or collections
    stats = {}
    for name in names:
        stat = await db.command('collstats', name)
        stats[name] = dict(count=stat['count'], size=stat['size'])
    return stats

async def search_init(*names: str, dbname: str|None = None) -> None:
    'Init collections'
    db = get_mongo_database(dbname)
    names = names or collections
    defns = {name: collections[name] for name in names}
    for name, defn in defns.items():
        logger.info(f'Initializing {name}')
        await db.get_collection(name).create_indexes(defn.indexes)

async def search_clean(*names: str, dbname: str|None = None) -> None:
    'Clean collections'
    db = get_mongo_database(dbname)
    names = names or collections
    for name in names:
        stat = (await search_stats(name, dbname=dbname))[name]
        logger.info(f'Cleaning {name} {stat=}')
        await db.get_collection(name).drop()

async def search_build(*names: str, dbname: str|None = None, lazy: bool = True) -> None:
    'Build collections'
    db = get_mongo_database(dbname)
    names = names or collections
    defns = {name: collections[name] for name in names}
    with orm.SessionLocal() as session:
        for name, defn in defns.items():
            await search_clean(name, dbname=dbname)
            await search_init(name, dbname=dbname)
            logger.info(f'Building {name}')
            it = defn.orm_model.map_reduce_exec(session, lazy=lazy)
            it = map(defn.data_model.as_doc, it)
            await db.get_collection(name).insert_many(it)
            stat = (await search_stats(name, dbname=dbname))[name]
            logger.info(f'Built {name} {stat=}')

class SubCommand(BaseCommand):

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg('--dbname', '-d',
            default=None,
            help=(
                f'Alternate mongo search db name, '
                f'default SEARCH_MONGODB_DBNAME ({settings.SEARCH_MONGODB_DBNAME})'))
        if cls is Command.commands['build']:
            arg('--eager', '-e',
                action='store_false',
                dest='lazy',
                help='Use eager loading of SQL result sets. Uses more memory.')
        arg('names',
            nargs='*',
            choices=collections,
            help='Collection names, default all')

    def setup(self, opts):
        super().setup(opts)
        self.funckw = {}
        if opts.dbname is not None:
            self.funckw.update(dbname=opts.dbname)
        if hasattr(opts, 'lazy'):
            self.funckw.update(lazy=opts.lazy)

    async def run(self):
        res = await self.func(*self.opts.names, **self.funckw)
        if res is not None:
            import json
            print(json.dumps(res, indent=2))

class Command(BaseCommand):
    'Search collection commands'
    commands = dict(
        stats=FuncCommand(search_stats, SubCommand),
        init=FuncCommand(search_init, SubCommand),
        build=FuncCommand(search_build, SubCommand),
        clean=FuncCommand(search_clean, SubCommand))

if __name__ == '__main__':
    Command.main()
