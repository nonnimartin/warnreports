from __future__ import annotations

import re
from abc import abstractmethod
from typing import Any, ClassVar, Iterable

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.operations import IndexModel

from . import settings, utils
from .models import *

__all__ = ['filters', 'mongo', 'retrieve', 'retrieve404', 'search', 'NotFoundError']

logger = utils.get_logger('search')


class MongoSearch(FilterModel[DM]):
    collection_name: ClassVar[str]

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
    def get_naics_filter(cls, naics: int, prefix: str = 'naics'):
        if prefix:
            prefix = prefix.removesuffix('.') + '.'
        return {
                '$or': [
                    {f'{prefix}code': {'$regex': cls.wc_startswith(str(naics))}},
                    {f'{prefix}id': naics}]}

class MongoReportsFilter(ReportsFilter, MongoSearch[ReportData]):
    collection_name: ClassVar = 'reports'

    def get_filters(self):
        if self.id:
            yield {'_id': self.id}
        if self.state:
            yield {'state': self.state.upper()}
        if self.company:
            yield {'company': {'$regex': self.wc_contains(self.company)}}
        if self.action:
            yield {'action': {'$regex': self.wc_contains(self.action)}}
        if self.location:
            yield {'location': {'$regex': self.wc_contains(self.location)}}
        if self.naics:
            yield self.get_naics_filter(self.naics)
        if self.text:
            yield {'$text': {'$search': self.text}}
        if self.reported_before:
            yield {'reported': {'$lt': self.reported_before}}
        if self.reported_after:
            yield {'reported': {'$gt': self.reported_after}}
        if self.starting_before:
            yield {'starting': {'$lt': self.starting_before}}
        if self.starting_after:
            yield {'starting': {'$gt': self.starting_after}}
        if self.employees_lt is not None:
            yield {'employees': {'$lt': self.employees_lt}}
        if self.employees_gt is not None:
            yield {'employees': {'$gt': self.employees_gt}}

class MongoStatesFilter(StatesFilter, MongoSearch[StateDetail]):
    collection_name: ClassVar = 'states'

    def get_filters(self):
        if self.id:
            yield {'id': self.id.upper()}
        if self.reports_count_lt is not None:
            yield {'reports_count': {'$lt': self.reports_count_lt}}
        if self.reports_count_gt is not None:
            yield {'reports_count': {'$gt': self.reports_count_gt}}
        if self.last_reported_before:
            yield {'last_reported': {'$lt': self.last_reported_before}}
        if self.last_reported_after:
            yield {'last_reported': {'$gt': self.last_reported_after}}

class MongoCompaniesFilter(CompaniesFilter, MongoSearch[CompanyDetail]):
    collection_name: ClassVar = 'companies'

    def get_filters(self):
        if self.id:
            yield {'_id': self.id}
        if self.name:
            yield {'name': {'$regex': self.wc_contains(self.name)}}
        if self.state:
            yield {'states': self.state.upper()}
        if self.naics:
            yield self.get_naics_filter(self.naics)
        if self.reports_count_lt is not None:
            yield {'reports_count': {'$lt': self.reports_count_lt}}
        if self.reports_count_gt is not None:
            yield {'reports_count': {'$gt': self.reports_count_gt}}
        if self.employees_sum_lt is not None:
            yield {'employees_sum': {'$lt': self.employees_sum_lt}}
        if self.employees_sum_gt is not None:
            yield {'employees_sum': {'$gt': self.employees_sum_gt}}
        if self.last_reported_before:
            yield {'last_reported': {'$lt': self.last_reported_before}}
        if self.last_reported_after:
            yield {'last_reported': {'$gt': self.last_reported_after}}

class MongoNaicsFilter(NaicsFilter, MongoSearch[NaicsDetail]):
    collection_name: ClassVar = 'naics'

    def get_filters(self):
        if self.id:
            yield {'id': self.id}
        if self.code is not None:
            yield {'code': self.code}
        if self.prefix:
            yield self.get_naics_filter(self.prefix, prefix='')
        if self.title:
            yield {'title': {'$regex': self.wc_contains(self.title)}}
        if self.reports_count_lt is not None:
            yield {'reports_count': {'$lt': self.reports_count_lt}}
        if self.reports_count_gt is not None:
            yield {'reports_count': {'$gt': self.reports_count_gt}}
        if self.companies_count_lt is not None:
            yield {'companies_count': {'$lt': self.companies_count_lt}}
        if self.companies_count_gt is not None:
            yield {'companies_count': {'$gt': self.companies_count_gt}}

class MongoArtifactsFilter(ArtifactsFilter, MongoSearch[ArtifactDetail]):
    collection_name: ClassVar = 'artifacts'

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

async def search(
    model: type[DM],
    params: dict[str, Any]|None = None,
    limit: Limit|None = None,
    offset: Offset = 0
) -> tuple[list[DM], int]:
    filt = filters[model](**params or {})
    coll = mongo.get_collection(filt.collection_name)
    filts = tuple(filt.get_filters())
    q = {'$and': filts} if filts else {}
    cur = coll.find(q)
    orders = tuple(filt.get_ordering())
    if orders:
        cur = cur.sort(orders)
    if offset:
        cur = cur.skip(offset)
    if limit:
        cur = cur.limit(limit)
    total = await coll.count_documents(q)
    return await cur.to_list(None), total

async def retrieve(model: type[DM], **params) -> DM:
    results = (await search(model, params, 1))[0]
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

search_indexes = dict(
    reports=[
        IndexModel({'company': 'text', 'location': 'text'}),
        IndexModel({'reported': 1}),
        IndexModel({'reported': -1}),
        IndexModel({'employees': 1}),
        IndexModel({'employees': -1}),
        IndexModel({'naics.code': 1}),
        IndexModel({'naics.id': 1}),
        IndexModel({'state': 'hashed'}),
    ],
    companies=[
        IndexModel({'name': 1}),
        IndexModel({'states': 1}),
        IndexModel({'naics.code': 1}),
        IndexModel({'naics.id': 1}),
        IndexModel({'last_reported': 1}),
        IndexModel({'last_reported': -1}),
        IndexModel({'reports_count': 1}),
        IndexModel({'reports_count': -1}),
    ],
    states=[
        IndexModel({'id': 'hashed'}),
        IndexModel({'last_reported': -1}),
        IndexModel({'reports_count': -1}),
    ],
    naics=[
        IndexModel({'id': 'hashed'}),
        IndexModel({'id': 1}),
        IndexModel({'code': 1}),
        IndexModel({'title': 1}),
        IndexModel({'companies_count': 1}),
        IndexModel({'reports_count': 1}),
        IndexModel({'reports_count': -1}),
    ],
    artifacts=[
        IndexModel({'name': 1}),
    ])

async def search_stats() -> dict[str, dict[str, Any]]:
    stats = {}
    for name in search_indexes:
        stats[name] = await mongo.command('collstats', name)
    return stats

async def search_init() -> None:
    for name, indexes in search_indexes.items():
        await mongo.get_collection(name).create_indexes(indexes)

async def search_clean() -> None:
    for name in search_indexes:
        await mongo.get_collection(name).drop()

async def search_build() -> None:
    await search_clean()
    await search_init()
    it = map(ReportData.as_doc, ReportData.map_reduce())
    await mongo.reports.insert_many(it)
    it = map(StateDetail.model_validate, list(StateStat.select()))
    it = map(StateDetail.as_doc, it)
    await mongo.states.insert_many(it)
    it = map(CompanyDetail.as_doc, CompanyDetail.map_reduce())
    await mongo.companies.insert_many(it)
    it = map(NaicsDetail.as_doc, NaicsDetail.map_reduce())
    await mongo.naics.insert_many(it)
    it = map(ArtifactDetail.as_doc, ArtifactDetail.map_reduce())
    await mongo.artifacts.insert_many(it)

actions = dict(
    init=search_init,
    build=search_build,
    clean=search_clean)

class Command(utils.BaseCommand):

    @classmethod
    def add_arguments(cls, parser) -> None:
        parser.add_argument('action', choices=actions)

    async def run(self):
        await actions[self.opts.action]()

if __name__ == '__main__':
    Command.main()
