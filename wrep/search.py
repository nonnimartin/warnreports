from __future__ import annotations

import re
from abc import abstractmethod
from typing import Any, Iterable, Iterator

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.operations import IndexModel

from . import settings, utils
from . import orm
from .models import *
from .utils import BaseCommand, FuncCommand

__all__ = ['filters', 'mongo', 'retrieve', 'retrieve404', 'search', 'NotFoundError']

logger = utils.get_logger('search')


class MongoSearch(FilterModel[DM]):

    @abstractmethod
    def get_filters(self) -> Iterable[Any]:
        yield from ()

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
        for oper, suffix in zip(('$gte', '$lte'), ('min', 'max')):
            for field in fields:
                if (value := getattr(self, f'{field}_{suffix}')) is not None:
                    yield {field: {oper: value}}

class MongoReportsFilter(ReportsFilter, MongoSearch[ReportData]):

    def get_filters(self):
        if self.id:
            yield {'_id': self.id}
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
        yield from self.get_minmax_filters('reported', 'starting', 'employees')

class MongoStatesFilter(StatesFilter, MongoSearch[StateDetail]):

    def get_filters(self):
        if self.id:
            yield {'id': self.id.upper()}
        yield from self.get_minmax_filters('reports_count', 'last_reported')

class MongoCompaniesFilter(CompaniesFilter, MongoSearch[CompanyDetail]):

    def get_filters(self):
        if self.id is not None:
            yield {'_id': {'$in': self.id}}
        if self.name is not None:
            yield {'$or': [{'aliases': name} for name in self.name]}
        if self.state is not None:
            yield {'state': {'$in': self.state}}
        if self.naics is not None:
            yield self.get_naics_filter(self.naics)
        if self.text:
            yield {'$text': {'$search': self.text}}
        yield from self.get_minmax_filters('reports_count', 'employees_sum', 'last_reported')

class MongoNaicsFilter(NaicsFilter, MongoSearch[NaicsDetail]):

    def get_filters(self):
        if self.id:
            yield {'id': self.id}
        if self.code is not None:
            yield {'code': self.code}
        if self.prefix is not None:
            yield self.get_naics_filter(self.prefix, prefix='')
        if self.title:
            yield {'title': {'$regex': self.wc_contains(self.title)}}
        yield from self.get_minmax_filters('reports_count', 'employees_sum', 'companies_count')

class MongoArtifactsFilter(ArtifactsFilter, MongoSearch[ArtifactDetail]):

    def get_filters(self):
        if self.id:
            yield {'_id': self.id}
        for field in ('name', 'sha1'):
            value = getattr(self, field)
            if value:
                yield {field: value}

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
    with_total: bool = False,
) -> tuple[list[DM], int|None]:
    filt = filters[model](**params or {})
    coll = mongo.get_collection(collections_map[model])
    filts = tuple(filt.get_filters())
    q = {'$and': filts} if filts else {}
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
    total = await coll.count_documents(q) if with_total else None
    objs = [model.model_validate(obj) async for obj in cur]
    return objs, total

async def search_with_total(
    model: type[DM],
    params: dict[str, Any]|None = None,
    limit: Limit|None = None,
    offset: Offset = 0
) -> tuple[list[DM], int]:
    return await search_result(model, params, limit, offset, with_total=True)

async def search(
    model: type[DM],
    params: dict[str, Any]|None = None,
    limit: Limit|None = None,
    offset: Offset = 0
) -> list[DM]:
    return (await search_result(model, params, limit, offset))[0]

async def retrieve(model: type[DM], **params) -> DM:
    results = await search(model, params, 1)
    if results:
        return results[0]
    raise NotFoundError

async def retrieve404(model: type[DM], **params) -> DM:
    try:
        return await retrieve(model, **params)
    except NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

mongo_client = AsyncIOMotorClient(settings.MONGODB_URL, uuidRepresentation='standard')
mongo = mongo_client.get_database(settings.MONGODB_DBNAME)

class CollectionDefn:

    def __init__(self, orm_model: type[orm.MapReduceBase], indexes: Iterable[dict]) -> None:
        self.orm_model = orm_model
        self.data_model: type[DataModel] = orm_model.data_model
        self.indexes = list(map(IndexModel, indexes))

collections: dict[str, CollectionDefn] = dict(
    reports=CollectionDefn(orm.Report, [
        {'company': 'text'},
        {'company_id': 'hashed'},
        {'reported': 1},
        {'reported': -1},
        {'employees': 1},
        {'employees': -1},
        {'naics.code': 1},
        {'naics.id': 1},
        {'state': 'hashed'}]),
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
        {'employees_sum': -1}]),
    naics=CollectionDefn(orm.Naics, [
        {'id': 'hashed'},
        {'id': 1},
        {'code': 1},
        {'title': 1},
        {'root': 1},
        {'companies_count': 1},
        {'reports_count': 1},
        {'reports_count': -1},
        {'employees_sum': -1}]),
    artifacts=CollectionDefn(orm.Artifact, [
        {'name': 1}]),
    states=CollectionDefn(orm.StateStat, [
        {'id': 'hashed'},
        {'last_reported': -1},
        {'reports_count': -1}]))

collections_map: dict[type[DataModel], str] = {
    defn.data_model: name for name, defn in collections.items()}

async def search_stats(*names: str) -> dict[str, dict[str, int]]:
    'Get collection stats'
    names = names or collections
    stats = {}
    for name in names:
        stat = await mongo.command('collstats', name)
        stats[name] = dict(count=stat['count'], size=stat['size'])
    return stats

async def search_init(*names: str) -> None:
    'Init collections'
    names = names or collections
    defns = {name: collections[name] for name in names}
    for name, defn in defns.items():
        logger.info(f'Initializing {name}')
        await mongo.get_collection(name).create_indexes(defn.indexes)

async def search_clean(*names: str) -> None:
    'Clean collections'
    names = names or collections
    for name in names:
        stat = (await search_stats(name))[name]
        logger.info(f'Cleaning {name} {stat=}')
        await mongo.get_collection(name).drop()

async def search_build(*names: str) -> None:
    'Build collections'
    names = names or collections
    defns = {name: collections[name] for name in names}
    with orm.SessionLocal() as session:
        for name, defn in defns.items():
            await search_clean(name)
            await search_init(name)
            logger.info(f'Building {name}')
            it = defn.orm_model.map_reduce_exec(session)
            it = map(defn.data_model.as_doc, it)
            await mongo.get_collection(name).insert_many(it)
            stat = (await search_stats(name))[name]
            logger.info(f'Built {name} {stat=}')

class SubCommand(BaseCommand):

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument('names', nargs='*')

    async def run(self):
        res = await self.func(*self.opts.names)
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
