from __future__ import annotations

import re
from abc import abstractmethod
from typing import Any, Generic, Iterable, TypeVar

from motor.motor_asyncio import (AsyncIOMotorClient, AsyncIOMotorCollection,
                                 AsyncIOMotorCursor, AsyncIOMotorDatabase)
from pymongo.operations import IndexModel

from . import settings, utils
from .models import *

QS = TypeVar('QS')
ST = TypeVar('ST', bound='BaseSearch')
DM = TypeVar('DM', bound=DataModel)
logger = utils.get_logger('search')


class BaseSearch(Generic[QS, DM]):

    async def search(self, limit: Limit|None = None, offset: Offset = 0):
        qs = self.get_queryset()
        qs = self.filter_queryset(qs)
        qs = self.order_queryset(qs)
        qs = self.paginate_queryset(qs, limit, offset)
        return await self.queryset_to_list(qs)

    @abstractmethod
    def get_filters(self) -> Iterable[Any]: ...

    @abstractmethod
    def get_queryset(self) -> QS: ...

    @abstractmethod
    def get_ordering(self) -> Iterable[Any]: ...

    @abstractmethod
    def filter_queryset(self, qs: QS) -> QS: ...

    @abstractmethod
    def order_queryset(self, qs: QS) -> QS: ...

    @abstractmethod
    def paginate_queryset(self, qs: QS, limit: Limit|None, offset: Offset) -> QS: ...

    @abstractmethod
    async def queryset_to_list(self, qs: QS) -> list[DM]: ...

class MongoSearch(BaseSearch[AsyncIOMotorCursor, DM]):

    def filter_queryset(self, qs: AsyncIOMotorCollection):
        filters = list(self.get_filters())
        logger.info(f'{filters=}')
        return qs.find({'$and': filters} if filters else {})

    def order_queryset(self, qs):
        orders = list(self.get_ordering())
        return qs.sort(orders) if orders else qs

    def paginate_queryset(self, qs, limit, offset):
        if offset:
            qs = qs.skip(offset)
        if limit:
            qs = qs.limit(limit)
        return qs

    async def queryset_to_list(self, qs):
        return await qs.to_list(None)

    @staticmethod
    def wc_contains(text: str, flags: re.RegexFlag = re.I) -> re.Pattern:
        return re.compile(f'.*{re.escape(text)}.*', flags)

    @staticmethod
    def wc_startswith(text: str, flags: re.RegexFlag = re.I) -> re.Pattern:
        return re.compile(f'^{re.escape(text)}.*', flags)

class SqlSearch(BaseSearch[orm.ModelSelect, DM]):

    def filter_queryset(self, qs):
        filters = list(self.get_filters())
        return qs.where(*filters) if filters else qs

    def order_queryset(self, qs):
        orders = list(self.get_ordering())
        return qs.order_by(*orders) if orders else qs

    def paginate_queryset(self, qs, limit, offset):
        if limit:
            qs = qs.limit(limit)
        if offset:
            qs = qs.offset(offset)
        return qs

    async def queryset_to_list(self, qs):
        return list(qs)

    @staticmethod
    def wc_contains(text: str) -> str:
        return f'%{text}%'

    @staticmethod
    def wc_startswith(text: str) -> str:
        return f'{text}%'

class MongoReportsFilter(ReportsFilter, MongoSearch[ReportData]):

    def get_queryset(self):
        return mongo.reports

    def get_ordering(self):
        yield ('reported', -1)
        yield ('state', 1)
        yield ('company', 1)

    def get_filters(self):
        if self.state:
            yield {'state': self.state.upper()}
        if self.company:
            yield {'company': {'$regex': self.wc_contains(self.company)}}
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

class SqlReportsFilter(ReportsFilter, SqlSearch[ReportData]):

    def get_queryset(self):
        return Report.select()

    def get_ordering(self):
        yield Report.reported.desc()
        yield Report.state.collate('NOCASE')
        yield Report.company.collate('NOCASE')

    def get_filters(self):
        if self.state:
            yield Report.state == self.state
        if self.company:
            yield Report.company.ilike(self.wc_contains(self.company))
        if self.location:
            yield Report.location.ilike(self.wc_contains(self.location))
        if self.text:
            wc = self.wc_contains(self.text)
            yield Report.company.ilike(wc) | Report.location.ilike(wc)
        if self.reported_before:
            yield Report.reported < self.reported_before
        if self.reported_after:
            yield Report.reported > self.reported_after

class SqlCompaniesFilter(CompaniesFilter, SqlSearch[CompanyData]):

    def get_queryset(self):
        return Report.select(Report.company, Report.state).distinct()

    def get_ordering(self):
        yield Report.company.collate('NOCASE')

    def get_filters(self):
        yield from SqlReportsFilter(**self.model_dump()).get_filters()

class SqlStatesFilter(StatesFilter, SqlSearch[StateData]):

    def get_queryset(self):
        return Report.select(Report.state).distinct()

    def get_ordering(self):
        yield Report.state

    def get_filters(self):
        yield from SqlReportsFilter(**self.model_dump()).get_filters()

filter_classes: dict[type[DataModel], type[BaseSearch]] = {}

if settings.SEARCH_BACKEND == 'mongo':
    filter_classes[ReportData] = MongoReportsFilter
else:
    filter_classes[ReportData] = SqlReportsFilter
filter_classes[CompanyData] = SqlCompaniesFilter
filter_classes[StateData] = SqlStatesFilter

async def search(
    model: type[DM],
    params: dict[str, Any]|None = None,
    limit: Limit|None = None,
    offset: Offset = 0
) -> list[DM]:
    return await filter_classes[model](**params or {}).search(limit, offset)

mongo_client = AsyncIOMotorClient(settings.MONGODB_URL, uuidRepresentation='standard')
mongo = mongo_client.active

async def mongo_init(mongo: AsyncIOMotorDatabase = mongo) -> None:
    indexes = [
        IndexModel({'company': 'text', 'location': 'text'}),
        IndexModel({'reported': 1}),
        IndexModel({'reported': -1}),
        IndexModel({'naics.code': 1}),
        IndexModel({'naics.id': 1}),
        IndexModel({'state': 'hashed'}),
    ]
    await mongo.reports.create_indexes(indexes)

async def mongo_clean(mongo: AsyncIOMotorDatabase = mongo) -> None:
    await mongo.reports.drop()

async def mongo_build(mongo: AsyncIOMotorDatabase = mongo) -> None:
    await mongo_clean(mongo)
    await mongo_init(mongo)
    docs = map(ReportData.as_doc, ReportData.map_reduce())
    await mongo.reports.insert_many(docs)

actions = dict(
    init=mongo_init,
    build=mongo_build,
    clean=mongo_clean)

class Command(utils.BaseCommand):

    methods = {
        # 'search': 'search',
    }

    @classmethod
    def add_arguments(cls, parser) -> None:
        parser.add_argument('action', choices=actions|cls.methods)

    async def run(self):
        if self.opts.action in self.methods:
            func = getattr(self, self.methods[self.opts.action])
        else:
            func = actions[self.opts.action]
        await func()

    async def search(self):
        ...

if __name__ == '__main__':
    Command.main()
