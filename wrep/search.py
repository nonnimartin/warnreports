from __future__ import annotations

import re
from abc import abstractmethod
from typing import Any, AsyncIterable, ClassVar, Generic, Iterable, TypeVar

from fastapi import HTTPException, status
from motor.motor_asyncio import (AsyncIOMotorClient, AsyncIOMotorCollection,
                                 AsyncIOMotorCursor)
from pymongo.operations import IndexModel

from . import settings, utils
from .models import *

__all__ = ['filters', 'mongo', 'retrieve', 'retrieve404', 'search', 'NotFoundError']

QS = TypeVar('QS')
ST = TypeVar('ST', bound='BaseSearch')
logger = utils.get_logger('search')


class BaseSearch(FilterModel[DM], Generic[QS, DM]):

    async def search(self, limit: Limit|None = None, offset: Offset = 0):
        qs = self.get_queryset()
        qs = self.filter_queryset(qs)
        qs = self.order_queryset(qs)
        qs = self.paginate_queryset(qs, limit, offset)
        return await self.queryset_to_list(qs)

    def get_filters(self) -> Iterable[Any]:
        yield from ()

    @abstractmethod
    def get_queryset(self) -> QS: ...

    @abstractmethod
    def filter_queryset(self, qs: QS) -> QS: ...

    @abstractmethod
    def order_queryset(self, qs: QS) -> QS: ...

    @abstractmethod
    def paginate_queryset(self, qs: QS, limit: Limit|None, offset: Offset) -> QS: ...

    async def iter_queryset(self, qs: QS) -> AsyncIterable[DM]:
        async for obj in qs:
            yield self.result_model.model_validate(obj)

    async def queryset_to_list(self, qs: QS) -> list[DM]:
        return [obj async for obj in self.iter_queryset(qs)]

class MongoSearch(BaseSearch[AsyncIOMotorCursor, DM]):
    collection_name: ClassVar[str]

    def get_queryset(self):
        return mongo.get_collection(self.collection_name)

    def filter_queryset(self, qs: AsyncIOMotorCollection):
        filters = tuple(self.get_filters())
        return qs.find({'$and': filters} if filters else {})

    def order_queryset(self, qs):
        orders = tuple(self.get_ordering())
        return qs.sort(orders) if orders else qs

    def paginate_queryset(self, qs, limit, offset):
        if offset:
            qs = qs.skip(offset)
        if limit:
            qs = qs.limit(limit)
        return qs

    @staticmethod
    def wc_contains(text: str, flags: re.RegexFlag = re.I) -> re.Pattern:
        return re.compile(f'.*{re.escape(text)}.*', flags)

    @staticmethod
    def wc_startswith(text: str, flags: re.RegexFlag = re.I) -> re.Pattern:
        return re.compile(f'^{re.escape(text)}.*', flags)

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
            yield {
                '$or': [
                    {'naics.code': {'$regex': self.wc_startswith(str(self.naics))}},
                    {'naics.id': self.naics}]}
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
        if self.state:
            yield {'state': self.state.upper()}
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
        if self.company:
            yield {'company': {'$regex': self.wc_contains(self.company)}}
        yield from MongoStatesFilter.get_filters(self)

class MongoNaicsFilter(NaicsFilter, MongoSearch[NaicsDetail]):
    collection_name: ClassVar = 'naics'

    def get_filters(self):
        if self.id:
            yield {'id': self.id}
        if self.code is not None:
            yield {'code': self.code}
        if self.prefix:
            yield {
                '$or': [
                    {'code': {'$regex': self.wc_startswith(str(self.prefix))}},
                    {'id': self.prefix}]}
        if self.title:
            yield {'title': {'$regex': self.wc_contains(self.title)}}
        if self.text:
            yield {
                '$or': [
                    {'code': {'$regex': self.wc_startswith(str(self.text))}},
                    {'title': {'$regex': self.wc_contains(self.text)}}]}
        if self.reports_count_lt is not None:
            yield {'reports_count': {'$lt': self.reports_count_lt}}
        if self.reports_count_gt is not None:
            yield {'reports_count': {'$gt': self.reports_count_gt}}

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

filters: dict[type[DataModel], type[BaseSearch]] = {
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
) -> list[DM]:
    return await filters[model](**params or {}).search(limit, offset)

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
        IndexModel({'company': 1}),
        IndexModel({'state': 'hashed'}),
        IndexModel({'last_reported': 1}),
        IndexModel({'last_reported': -1}),
        IndexModel({'reports_count': 1}),
        IndexModel({'reports_count': -1}),
    ],
    states=[
        IndexModel({'state': 'hashed'}),
        IndexModel({'last_reported': -1}),
        IndexModel({'reports_count': -1}),
    ],
    naics=[
        IndexModel({'id': 'hashed'}),
        IndexModel({'id': 1}),
        IndexModel({'code': 1}),
        IndexModel({'title': 1}),
        IndexModel({'reports_count': 1}),
        IndexModel({'reports_count': -1}),
    ],
    artifacts=[
        IndexModel({'name': 1}),
    ])

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
