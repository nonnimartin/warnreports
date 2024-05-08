from __future__ import annotations

import re
from abc import abstractmethod
from typing import Any, ClassVar, Generic, Iterable, TypeVar

from motor.motor_asyncio import (AsyncIOMotorClient, AsyncIOMotorCollection,
                                 AsyncIOMotorCursor, AsyncIOMotorDatabase)
from pymongo.operations import IndexModel

from . import settings, utils
from .models import *

__all__ = ['filters', 'mongo', 'retrieve', 'search', 'NotFoundError']

QS = TypeVar('QS')
ST = TypeVar('ST', bound='BaseSearch')
DM = TypeVar('DM', bound=DataModel)
logger = utils.get_logger('search')


class BaseSearch(FilterModel, Generic[QS, DM]):

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

    async def queryset_to_list(self, qs: QS) -> list[DM]:
        return list(qs)

class MongoSearch(BaseSearch[AsyncIOMotorCursor, DM]):

    def filter_queryset(self, qs: AsyncIOMotorCollection):
        filters = list(self.get_filters())
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

    order_fieldmap: ClassVar[dict[str, orm.Field]] = {}

    def get_ordering(self):
        for field, dir_ in super().get_ordering():
            if field in self.order_fieldmap:
                ormfield = self.order_fieldmap[field]
                if dir_ == -1:
                    ormfield = ormfield.desc()
                yield ormfield

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

    @staticmethod
    def wc_contains(text: str) -> str:
        return f'%{text}%'

    @staticmethod
    def wc_startswith(text: str) -> str:
        return f'{text}%'

class MongoReportsFilter(ReportsFilter, MongoSearch[ReportData]):

    def get_queryset(self):
        return mongo.reports

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

class SqlReportsFilter(ReportsFilter, SqlSearch[ReportData]):

    order_fieldmap: ClassVar = {
        'reported': Report.reported,
        'starting': Report.starting,
        'employees': Report.employees,
        'state': Report.state.collate('NOCASE'),
        'company': Report.company.collate('NOCASE'),
        'action': Report.action.collate('NOCASE')}

    def get_queryset(self):
        return Report.select()

    def get_filters(self):
        if self.id:
            yield Report.id == self.id
        if self.state:
            yield Report.state == self.state
        if self.company:
            yield Report.company.ilike(self.wc_contains(self.company))
        if self.action:
            yield Report.action.ilike(self.wc_contains(self.action))
        if self.location:
            yield Report.location.ilike(self.wc_contains(self.location))
        if self.text:
            wc = self.wc_contains(self.text)
            yield Report.company.ilike(wc) | Report.location.ilike(wc)
        if self.reported_before:
            yield Report.reported < self.reported_before
        if self.reported_after:
            yield Report.reported > self.reported_after
        if self.starting_before:
            yield Report.starting < self.starting_before
        if self.starting_after:
            yield Report.starting > self.starting_after
        if self.employees_lt is not None:
            yield Report.employees < self.employees_lt
        if self.employees_gt is not None:
            yield Report.employees > self.employees_gt

class SqlCompaniesFilter(CompaniesFilter, SqlSearch[CompanyData]):
    order_fieldmap: ClassVar = SqlReportsFilter.order_fieldmap

    def get_queryset(self):
        group_by = [Report.company, Report.state]
        return Report.select().group_by(*group_by)

    def get_filters(self):
        yield from SqlReportsFilter(**self.model_dump()).get_filters()

class SqlStatesFilter(StatesFilter, SqlSearch[StateData]):
    order_fieldmap: ClassVar = SqlReportsFilter.order_fieldmap

    def get_queryset(self):
        return Report.select(Report.state).distinct()

    def get_filters(self):
        yield from SqlReportsFilter(**self.model_dump()).get_filters()

class SqlNaicsFilter(NaicsFilter, SqlSearch[NaicsData]):
    order_fieldmap: ClassVar = {
        'id': Naics.id,
        'code': Naics.code,
        'title': Naics.title.collate('NOCASE')}

    def get_queryset(self):
        return Naics.select()

    def get_filters(self):
        if self.id is not None:
            yield Naics.id == self.id
        if self.code is not None:
            yield Naics.id == self.code
        if self.prefix:
            wc = self.wc_startswith(str(self.prefix))
            logger.info(f'{wc=}')
            yield (Naics.id == self.prefix) | Naics.code.ilike(wc)
        if self.title:
            wc = self.wc_contains(self.title)
            yield Naics.title.ilike(wc)
        if self.text:
            wc1 = self.wc_startswith(str(self.text))
            wc2 = self.wc_contains(self.text)
            yield Naics.title.ilike(wc2) | Naics.code.ilike(wc1)

class NotFoundError(Exception):
    pass

filters: dict[type[DataModel], type[BaseSearch]] = {
    ReportData: SqlReportsFilter,
    CompanyData: SqlCompaniesFilter,
    StateData: SqlStatesFilter,
    NaicsData: SqlNaicsFilter}

if settings.SEARCH_BACKEND == 'mongo':
    filters[ReportData] = MongoReportsFilter

async def search(
    model: type[DM],
    params: dict[str, Any]|None = None,
    limit: Limit|None = None,
    offset: Offset = 0
) -> list[DM]:
    return await filters[model](**params or {}).search(limit, offset)

async def retrieve(model: type[DM], **params) -> DM|None:
    results = await search(model, params, 1)
    if results:
        return results[0]
    raise NotFoundError

mongo_client = AsyncIOMotorClient(settings.MONGODB_URL, uuidRepresentation='standard')
mongo = mongo_client.active

async def mongo_init(mongo: AsyncIOMotorDatabase = mongo) -> None:
    indexes = [
        IndexModel({'company': 'text', 'location': 'text'}),
        IndexModel({'reported': 1}),
        IndexModel({'reported': -1}),
        IndexModel({'employees': 1}),
        IndexModel({'employees': -1}),
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

    @classmethod
    def add_arguments(cls, parser) -> None:
        parser.add_argument('action', choices=actions)

    async def run(self):
        await actions[self.opts.action]()

if __name__ == '__main__':
    Command.main()
